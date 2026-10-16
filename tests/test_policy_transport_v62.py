"""V6.2 synthetic regression tests. Never evidence of live website availability."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from threading import Lock
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

import requests
import policy_scrape as crawler
from policy_transport import DomainThrottle, classify_error
from policy_network_probe import compare_reports, probe_one

SOURCES=crawler.read(crawler.SOURCES, [])
DIMS=crawler.read(crawler.DIMS, [])
SRC=next(src for src in SOURCES if src['name']=='北京市发展和改革委员会')
HOST=urlsplit(SRC['url']).hostname
NOW=date.today()
FRESH=(NOW-timedelta(days=1)).isoformat()
OLD=(NOW-timedelta(days=45)).isoformat()
CUTOFF=NOW-timedelta(days=29)


def table(when=FRESH, older=OLD, next_html='', undated=False):
    d2='即将发布' if undated else older
    return f'<main><table><tr><td><a href="https://{HOST}/doc/wind-new.html">关于风电并网和设备认证的新通知</a></td><td>{when}</td></tr><tr><td><a href="https://{HOST}/doc/wind-old.html">关于风电并网和设备标准的旧通知</a></td><td>{d2}</td></tr></table>{next_html}</main>'


class TransportRegressions(unittest.TestCase):
    def test_http_errors_stay_separate(self):
        for status,code in ((403,'http_403'),(404,'http_404'),(412,'http_412'),(429,'http_429'),(503,'http_5xx')):
            with self.subTest(status=status):
                resp=requests.Response();resp.status_code=status
                error=requests.HTTPError('initial request failed',response=resp)
                self.assertEqual(classify_error(error)[:2],(code,status))

    def test_timeout_ssl_and_dns_are_distinct(self):
        self.assertEqual(classify_error(requests.Timeout('server timed out'))[0],'timeout')
        self.assertEqual(classify_error(requests.exceptions.SSLError('SSL handshake failed'))[0],'tls_error')
        self.assertEqual(classify_error(requests.ConnectionError('Name resolution failed'))[0],'dns_error')
        self.assertEqual(classify_error(requests.ConnectionError('Network is unreachable'))[0],'connection_error')

    def test_denied_requests_not_browser_bypassed(self):
        for status in (403,404,412):
            with self.subTest(status=status):
                def raise_http(_):
                    resp=requests.Response();resp.status_code=status
                    raise requests.HTTPError(f'HTTP {status}',response=resp)
                with patch.object(crawler,'fetch',side_effect=raise_http),\
                    patch.object(crawler,'BROWSER_ENABLED',True),\
                    patch.object(crawler,'browser_fetch') as browser:
                    trace=[]
                    self.assertIsNone(crawler._try_entry(SRC['url'],'',True,trace))
                    browser.assert_not_called()
                    self.assertEqual(trace[0]['http_status'],status)

    def test_timeout_not_rendered_or_disguised(self):
        with patch.object(crawler,'fetch',side_effect=requests.Timeout('Read timed out')),\
             patch.object(crawler,'BROWSER_ENABLED',True),\
             patch.object(crawler,'browser_fetch') as browser:
            attempts=[]
            self.assertIsNone(crawler._try_entry(SRC['url'],'',True,attempts))
            browser.assert_not_called()
            self.assertEqual(attempts[0]['error_code'],'timeout')
            self.assertEqual(crawler._result_status(attempts,{},0,False,False,False,False,False,False)[0],'timeout')

    def test_host_gate_limits_parallel_active_requests(self):
        gate=DomainThrottle(concurrency=1,spacing_seconds=0.0)
        lock=Lock();inside=0;peak=0
        def work(n):
            nonlocal inside,peak
            with gate.lease('https://www.example.gov.cn/list?page='+str(n)):
                with lock:
                    inside+=1;peak=max(peak,inside)
                time.sleep(.012)
                with lock:inside-=1
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(work,range(20)))
        self.assertEqual(peak,1)

    def test_different_domains_have_distinct_gates(self):
        gate=DomainThrottle(concurrency=1,spacing_seconds=0.0)
        with gate.lease('https://a.example.gov.cn/one'):
            with gate.lease('https://b.example.gov.cn/two'):
                self.assertTrue(True)


class ListingRegressions(unittest.TestCase):
    def scrape_with(self,pages,alternate=None):
        def fake_fetch(url):
            if url in pages:
                value=pages[url]
                if isinstance(value,Exception):raise value
                return value,url,'html'
            if url.startswith(f'https://{HOST}/doc/'):
                raise requests.HTTPError('HTTP 403 Forbidden')
            raise requests.HTTPError('HTTP 404 Not Found')
        with patch.object(crawler,'fetch',side_effect=fake_fetch),patch.object(crawler,'BROWSER_ENABLED',False):
            ctx=patch.object(crawler,'adapter_urls',return_value=alternate) if alternate else None
            if ctx:
                with ctx:return crawler.scrape_one(SRC,DIMS,CUTOFF,{})
            return crawler.scrape_one(SRC,DIMS,CUTOFF,{})

    def test_a_real_next_selector_is_respected(self):
        src_adapter=crawler.load_adapter(SRC)
        parsed=crawler._listing_page(table(next_html='<a title="下一页" href="/page-2.html">→</a>'),SRC['url'],src_adapter)
        self.assertTrue(parsed['selector_matched'])
        self.assertEqual(parsed['next_urls'],[f'https://{HOST}/page-2.html'])

    def test_missing_second_page_blocks_cursor(self):
        page2=f'https://{HOST}/page-2.html'
        pages={SRC['url']:table(next_html='<a title="下一页" href="/page-2.html">NEXT</a>'),
               page2:requests.Timeout('connect timeout')}
        _,_,status=self.scrape_with(pages)
        self.assertFalse(status['listing_coverage_complete'])
        cp=crawler.advance_checkpoint(crawler.make_checkpoint(SRC,{},NOW),status,NOW)
        self.assertFalse(cp['initialized'])
        self.assertTrue(any(a.get('error_code')=='timeout' for a in status['attempts']))

    def test_second_page_success_can_prove_boundary(self):
        pages={SRC['url']:table(when=FRESH,older=(NOW-timedelta(days=4)).isoformat(),next_html='<a title="下一页" href="/page-2.html">NEXT</a>'),
               f'https://{HOST}/page-2.html':table(when=(NOW-timedelta(days=15)).isoformat(),older=OLD)}
        _,_,status=self.scrape_with(pages)
        self.assertTrue(status['listing_coverage_complete'])
        self.assertEqual(status['listing_pages'],2)
        self.assertEqual(status['listing_rows_total'],4)
        self.assertEqual(status['detail_retry_count'],2)

    def test_js_only_next_stays_unverified_without_browser(self):
        html=table(next_html='<a class="next" href="javascript:void(0)">下一页</a>')
        _,_,status=self.scrape_with({SRC['url']:html})
        self.assertFalse(status['listing_coverage_complete'])
        self.assertEqual(status['status'],'partial_coverage')

    def test_non_topical_undated_row_prevents_false_success(self):
        doc=f'<tr><td><a href="https://{HOST}/doc/unrelated.html">关于农村农业规划与民生发展的公告</a></td><td>发布日期尚未确定</td></tr>'
        html=table().replace('</table>',doc+'</table>')
        _,_,status=self.scrape_with({SRC['url']:html})
        self.assertFalse(status['listing_coverage_complete'])
        self.assertEqual(status['listing_rows_total'],3)
        self.assertEqual(status['listing_rows_with_date'],2)

    def test_date_in_title_does_not_fake_publication(self):
        html=f'<main><ul><li><a href="https://{HOST}/doc/titled.html">2026-09-02风力发电项目会议纪要和政策汇编</a></li></ul></main>'
        parsed=crawler._listing_page(html,SRC['url'],crawler.load_adapter(SRC))
        self.assertEqual(parsed['dated_rows'],0)
        self.assertEqual(parsed['eligible_rows'],1)

    def test_future_date_cannot_certify_coverage(self):
        future=(NOW+timedelta(days=2)).isoformat()
        _,_,status=self.scrape_with({SRC['url']:table(when=future,older=OLD)})
        self.assertFalse(status['listing_coverage_complete'])

    def test_backup_listing_does_not_mix_with_wrong_first_page(self):
        primary='https://'+HOST+'/wrong'
        secondary='https://'+HOST+'/proper'
        first=table(undated=True)
        second=table()
        _,_,status=self.scrape_with({primary:first,secondary:second},[primary,secondary])
        self.assertTrue(status['listing_coverage_complete'])
        self.assertEqual(status['listing_rows_total'],2)
        self.assertEqual(status['listing_rows_with_date'],2)
        self.assertTrue(any(x['url']==primary for x in status['attempts']))

    def test_browser_js_pagination_can_exhaust_real_pages(self):
        first=table(when=FRESH,older=(NOW-timedelta(days=4)).isoformat(),
                    next_html='<a href="javascript:nextPage()">下一页</a>')
        last=table(when=(NOW-timedelta(days=16)).isoformat(),older=OLD)
        with patch.object(crawler,'fetch',side_effect=lambda url:(first,url,'html') if url==SRC['url'] else (_ for _ in ()).throw(requests.HTTPError('HTTP 403'))),\
             patch.object(crawler,'BROWSER_ENABLED',True),\
             patch('policy_public_ui.public_js_pages',return_value=([(first,SRC['url']),(last,SRC['url'])],True)):
            _,_,status=crawler.scrape_one(SRC,DIMS,CUTOFF,{})
        self.assertTrue(status['listing_coverage_complete'])
        self.assertEqual(status['listing_pages'],2)

    def test_js_pagination_unknown_end_fails(self):
        first=table(when=FRESH,older=(NOW-timedelta(days=4)).isoformat(),
                    next_html='<a href="javascript:nextPage()">下一页</a>')
        with patch.object(crawler,'fetch',side_effect=lambda url:(first,url,'html') if url==SRC['url'] else (_ for _ in ()).throw(requests.HTTPError('HTTP 403'))),\
             patch.object(crawler,'BROWSER_ENABLED',True),\
             patch('policy_public_ui.public_js_pages',return_value=([(first,SRC['url'])],False)):
            _,_,status=crawler.scrape_one(SRC,DIMS,CUTOFF,{})
        self.assertFalse(status['listing_coverage_complete'])

    def test_old_initialized_checkpoint_invalidation(self):
        source=SRC.copy()
        old={'source_id':source['id'],'first_seen_on':'2026-10-13',
             'initial_window_start':'2026-09-14','initialized':True,'last_verified_date':'2026-10-15'}
        cp=crawler.make_checkpoint(source,old,NOW)
        self.assertFalse(cp['initialized'])
        self.assertEqual(cp['initial_window_start'],'2026-09-14')
        self.assertIsNone(cp['last_verified_date'])
        old['coverage_proof_version']=2;old['source_url']='https://previous.example.gov.cn/old'
        self.assertFalse(crawler.make_checkpoint(source,old,NOW)['initialized'])


class ProbeRegressions(unittest.TestCase):
    def test_probe_comparison_never_claims_missing_side_success(self):
        a={'region':'github', 'probes':[{'host':'one.cn','reachable':False,'http_status':403,'error_code':'http_403'},
                                       {'host':'only.github','reachable':True,'http_status':200,'error_code':''}]}
        b={'region':'authorized-cn', 'probes':[{'host':'one.cn','reachable':True,'http_status':200,'error_code':''}]}
        result=compare_reports(a,b)
        rows={r['host']:r for r in result['results']}
        self.assertEqual(rows['one.cn']['result'],'only_authorized-cn_reachable')
        self.assertEqual(rows['only.github']['result'],'missing_one_side')

    def test_status_probe_getter_without_real_network(self):
        class FakeResponse:
            status_code=412
            url='https://example.gov.cn/source'
            def __enter__(self):return self
            def __exit__(self,*exc):return False
        with patch('policy_network_probe.requests.get',return_value=FakeResponse()):
            result=probe_one({'id':'test','name':'test','url':'https://example.gov.cn/source'},gate=DomainThrottle(1,0))
        self.assertFalse(result['reachable'])
        self.assertEqual(result['error_code'],'http_412')
        self.assertEqual(result['http_status'],412)


if __name__=='__main__':unittest.main()
