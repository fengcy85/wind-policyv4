"""Normal public browser pagination (clicks only visible Next controls).

Never attempts a login, stealth fingerprint, captcha bypass, private API, or
manually forged cookies. Failure leaves the chronological cursor unverified.
"""
from __future__ import annotations

import hashlib
from urllib.parse import urlsplit

from policy_transport import DOMAIN_GATE


def public_js_pages(url, profile, max_pages=8):
    """Return (rendered_pages, exhausted), each page as (html, final_url).

    exhausted=True is only emitted after a genuine clickable Next control was
    followed to the last page, or an explicit single-page indicator is visible.
    """
    from playwright.sync_api import sync_playwright
    max_pages=max(1,min(int(max_pages),20))
    pages=[];exhausted=False;clicked=0
    next_selectors=[s for s in profile.get('next_selectors',[]) if ':contains(' not in s]
    next_selectors += ['a[rel="next"]','a[title*="下一页"]','button[aria-label*="Next"]',
                       'a:has-text("下一页")','button:has-text("下一页")',
                       'a:has-text("Next")','button:has-text("Next")']
    with DOMAIN_GATE.lease(url),sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
        try:
            page=browser.new_page(locale='zh-CN',user_agent='WindPolicyMonitor/6.2 (public policy indexing)')
            response=page.goto(url,wait_until='domcontentloaded',timeout=25000)
            if response is None or response.status>=400:
                raise ValueError('public UI HTTP '+str(response.status if response else 'unknown'))
            page.wait_for_timeout(850)
            # Search only when the adapter explicitly declares a public UI search.
            if profile.get('needs_browser_ui') and profile.get('ui_search_term'):
                for css in ('input[placeholder*="检索"]','input[placeholder*="搜索"]',
                            'input[placeholder*="关键词"]','input[type=search]'):
                    try:
                        box=page.locator(css).first
                        if box.count() and box.is_visible():
                            box.fill(profile['ui_search_term'],timeout=1500)
                            box.press('Enter',timeout=1500)
                            page.wait_for_timeout(900)
                            break
                    except Exception:
                        continue
            fingerprints=set()
            for _ in range(max_pages):
                markup=page.content()
                signature=hashlib.sha256(markup.encode('utf-8')).hexdigest()
                if signature in fingerprints:break
                fingerprints.add(signature)
                pages.append((markup,page.url))
                next_button=None
                for selector in next_selectors:
                    try:
                        nodes=page.locator(selector)
                        for j in range(min(nodes.count(),5)):
                            node=nodes.nth(j)
                            if not node.is_visible() or not node.is_enabled():continue
                            if node.get_attribute('aria-disabled')=='true':continue
                            classes=(node.get_attribute('class') or '').lower()
                            if 'disabled' in classes:continue
                            next_button=node;break
                        if next_button:break
                    except Exception:continue
                if next_button is None:
                    # More than one distinct page and the next control is gone;
                    # or only one page with a literal finite-page counter.
                    exhausted=clicked>0 or bool(__import__('re').search(
                        r'共\s*1\s*页|Page\s*1\s*of\s*1',page.locator('body').inner_text(),__import__('re').I))
                    break
                # Limit reached with a live Next control => NOT exhausted.
                if len(pages)>=max_pages:break
                next_button.click(timeout=5000)
                clicked+=1
                page.wait_for_timeout(850)
        finally:
            browser.close()
    return pages,exhausted
