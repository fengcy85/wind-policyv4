"""Polite shared transport primitives for public policy sites.

No credential/captcha bypass. A denial is evidence, not a signal to disguise the
crawler. One gate per hostname coordinates parallel source workers and browser
fallbacks. Network probing reuses the same error taxonomy.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
import re
import threading
import time
from urllib.parse import urlsplit

import requests


class DomainThrottle:
    def __init__(self, concurrency=1, spacing_seconds=0.6):
        self.concurrency = max(1, min(int(concurrency), 4))
        self.spacing_seconds = max(0.0, float(spacing_seconds))
        self._lock = threading.Lock()
        self._semaphores = {}
        self._next_at = {}

    @contextmanager
    def lease(self, url):
        host = (urlsplit(url).hostname or '').lower()
        if not host:
            raise ValueError('missing host')
        with self._lock:
            gate = self._semaphores.setdefault(host, threading.BoundedSemaphore(self.concurrency))
        gate.acquire()
        try:
            with self._lock:
                now = time.monotonic()
                due = max(now, self._next_at.get(host, 0.0))
                self._next_at[host] = due + self.spacing_seconds
            if due > now:
                time.sleep(due - now)
            yield
        finally:
            gate.release()


DOMAIN_GATE = DomainThrottle(
    os.getenv('POLICY_PER_HOST_CONCURRENCY', '1'),
    os.getenv('POLICY_PER_HOST_DELAY', '0.6'),
)


def classify_error(error):
    """Return a stable, UI-independent category, status code and operator hint.

    The *first* HTTP response is never hidden by a later browser failure.
    Supports both real requests exceptions and legacy synthetic exceptions.
    """
    response = getattr(error, 'response', None)
    status = getattr(response, 'status_code', None)
    msg = str(error or '')
    if status is None:
        match = re.search(r'(?<!\d)(403|404|412|429|500|502|503|504)(?!\d)', msg)
        if match:
            status = int(match.group(1))
    if status == 403:
        return 'http_403', 403, '服务器拒绝访问；保持原有身份，交由站点管理员或合规网络环境核实'
    if status == 404:
        return 'http_404', 404, '入口不存在或已迁移；仅尝试配置中已有的官方备用入口'
    if status == 412:
        return 'http_412', 412, '站点请求前置条件未满足；停止本轮重试并保留现场证据'
    if status == 429:
        return 'http_429', 429, '服务器要求降低请求频率；尊重 Retry-After 并留待后续重试'
    if status is not None and status >= 500:
        return 'http_5xx', status, '服务器临时故障；有限重试后延期补查'
    low = msg.lower()
    if isinstance(error, requests.exceptions.Timeout) or re.search(r'timed?\s*out|timeout', low):
        return 'timeout', None, '请求超时；有限重试，并核对境内外访问差异'
    if isinstance(error, requests.exceptions.SSLError) or re.search(r'ssl|tls|handshake|certificate', low):
        return 'tls_error', None, 'TLS 握手或证书异常；不禁用证书校验'
    if re.search(r'name\s*resolution|dns|no\s*such\s*host|getaddrinfo|name\s*or\s*service', low):
        return 'dns_error', None, 'DNS 解析失败；检查出口 DNS 与网络环境'
    if isinstance(error, requests.exceptions.ConnectionError) or re.search(r'connect|unreachable|network|refused', low):
        return 'connection_error', None, '网络连接或路由失败；检查执行端可达性'
    return 'other_error', status, '未分类读取异常；留存首个报错并核查页面格式'


def primary_failure(attempts):
    """Prefer original HTTP failures to later browser/render errors."""
    failures = [x for x in attempts if x.get('status') == 'failed']
    originals = [x for x in failures if x.get('method') == 'http']
    # If several official fallbacks were tried, last primary indicates which
    # alternative failed, while the full evidence remains in attempts.
    return (originals or failures or [{}])[0]
