"""Detect repeated dated policy rows in public government HTML.

This is a *discovery* aid for 30+ unrelated CMS layouts, NOT a claim that a
portal has been live verified. Every run retains raw counted rows, dates and
pagination evidence, and never derives a publication date from a headline.
"""
from __future__ import annotations
from collections import defaultdict
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin

NAV = re.compile(r'nav|breadcrumb|footer|side|header|search|menu|friendlink|related|hot|bottom|topbar|index-bar',re.I)
ARTICLE_TITLE = re.compile(r'^[\s\S]{7,190}$')


def clean(x):return re.sub(r'\s+',' ',str(x or '')).strip()


def row_for(link):
    for p in list(link.parents)[:5]:
        if p.name in ('li','tr','article'):
            return p
        classes=' '.join(p.get('class') or [])
        if p.name in ('div','section','p') and re.search(r'(?:^|\b|[-_])(item|record|list-item|info-item|news-item|policy-item)(?:$|\b|[-_])',classes,re.I):
            return p
    return link.parent


def row_date(row, parse_date):
    if row is None:return ''
    # Meta/date dedicated markers win when present.
    for n in row.select('time[datetime],span[class*=date],span[class*=time],td[class*=date],em[class*=time],.pubdate,.pub-date')[:5]:
        date=parse_date(n.get('datetime') or n.get_text(' ',strip=True))
        if date:return date
    stripped=BeautifulSoup(str(row),'html.parser')
    for a in stripped.select('a'):a.decompose()
    text=clean(stripped.get_text(' ',strip=True))
    # Reject giant wrappers whose unrelated dates cannot be attributed to one article.
    if len(text)>300:return ''
    return parse_date(text)


def _extend_date_wrapper(anchor, initial, parse_date):
    """Associate dates separated from headline by nested <div>/<p> wrappers.

    Requiring a single article anchor and a small container prevents borrowing a
    publication date from an adjacent unrelated list row or a whole web page.
    """
    if row_date(initial,parse_date):return initial
    for node in list(anchor.parents)[:6]:
        if node.name in ('html','body','main','nav','header','footer','aside','menu'):
            break
        if len(node.select('a[href]'))>2:break
        if len(clean(node.get_text(' ',strip=True)))>550:break
        if row_date(node,parse_date):return node
    return initial


def _valid_nonnav(a):
    for p in list(a.parents)[:6]:
        if p.name in ('nav','header','footer','aside','menu'):return False
        attrs=' '.join(p.get('class') or [])+' '+str(p.get('id') or '')
        if NAV.search(attrs):return False
    return True


def _signature(row):
    if row is None:return ''
    parent=row.parent
    # Template rows share tag+class and, normally, container attributes.
    return (row.name,tuple(sorted(row.get('class') or [])[:3]),
            parent.name if parent else '',tuple(sorted((parent.get('class') or [])[:3])) if parent else ())


def discover_repeating_rows(html, base, *, parse_date, normalize_url, allowed_link,
                            min_group=3):
    soup=BeautifulSoup(html,'html.parser')
    groups=defaultdict(list)
    for a in soup.select('a[href]'):
        if not _valid_nonnav(a):continue
        title=clean(a.get_text(' ',strip=True)) or clean(a.get('title'))
        if not ARTICLE_TITLE.fullmatch(title) or re.fullmatch(r'(?i)更多|下一页|首页|政策解读|通知公告',title):continue
        raw=clean(a.get('href'))
        if not raw or raw.startswith(('#','javascript:','mailto:','tel:')):continue
        url=normalize_url(urljoin(base,raw))
        if not url or not allowed_link(base,url):continue
        row=row_for(a)
        if row is None:continue
        row=_extend_date_wrapper(a,row,parse_date)
        # The same row can contain >1 link (e.g. title plus download PDF).
        if len(row.select('a[href]'))>3:continue
        pub=row_date(row,parse_date)
        groups[_signature(row)].append((a,url,title,pub))
    scored=[]
    for signature,items in groups.items():
        # Dedupe identical links within the same template before coverage analysis.
        distinct={}
        for a,url,title,pub in items:
            if url not in distinct or (pub and not distinct[url][3]):
                distinct[url]=(a,url,title,pub)
        items=list(distinct.values())
        n=len(items);dated=sum(bool(x[3]) for x in items)
        if n<min_group or dated<min_group:continue
        ratio=dated/n
        # Structural evidence: repeated same row wrapper, several dates,
        # no navigation container, and near-complete row dates.
        confidence='repeated_dated_rows' if ratio >= .8 else 'partial_dated_rows'
        score=(int(ratio>=.8),dated,ratio,min(n,100))
        scored.append((score,signature,items,confidence))
    if not scored:
        return {'anchors':[], 'evidence':'no_repeated_dated_list', 'confidence':'none',
                'rows':0,'dated_rows':0,'signature':'','date_by_url':{}}
    scored.sort(key=lambda x:x[0],reverse=True)
    _,signature,items,confidence=scored[0]
    return {'anchors':[v[0] for v in items], 'evidence':'row_grouping',
            'confidence':confidence,'rows':len(items),
            'dated_rows':sum(bool(x[3]) for x in items),'signature':str(signature)[:200],
            'date_by_url':{x[1]:x[3] for x in items if x[3]}}
