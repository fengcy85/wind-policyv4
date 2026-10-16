"""Province-first wind-policy discovery (no UI changes).

Official publications and professional-media hints are deliberately different
kinds of evidence.  This module never manufactures a government source URL,
publication date, cursor, law, or successful network probe.
"""
from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

PROVINCES = (
    '北京', '天津', '河北', '山西', '内蒙古', '辽宁', '吉林', '黑龙江',
    '上海', '江苏', '浙江', '安徽', '福建', '江西', '山东', '河南',
    '湖北', '湖南', '广东', '广西', '海南', '重庆', '四川', '贵州',
    '云南', '西藏', '陕西', '甘肃', '青海', '宁夏', '新疆',
)
ALIASES = {
    '北京': ('北京市',), '天津': ('天津市',), '河北': ('河北省',),
    '山西': ('山西省',), '内蒙古': ('内蒙古自治区',),
    '辽宁': ('辽宁省',), '吉林': ('吉林省',), '黑龙江': ('黑龙江省',),
    '上海': ('上海市',), '江苏': ('江苏省',), '浙江': ('浙江省',),
    '安徽': ('安徽省',), '福建': ('福建省',), '江西': ('江西省',),
    '山东': ('山东省',), '河南': ('河南省',), '湖北': ('湖北省',),
    '湖南': ('湖南省',), '广东': ('广东省',),
    '广西': ('广西壮族自治区', '广西省'), '海南': ('海南省',),
    '重庆': ('重庆市',), '四川': ('四川省',), '贵州': ('贵州省',),
    '云南': ('云南省',), '西藏': ('西藏自治区',),
    '陕西': ('陕西省',), '甘肃': ('甘肃省',), '青海': ('青海省',),
    '宁夏': ('宁夏回族自治区',),
    '新疆': ('新疆维吾尔自治区',),
}
MEDIA_SOURCE_ID = 'cn_5555c1d4376e'
BJX_DIRECTORY = 'https://fd.bjx.com.cn/zc/'
BJX_ARTICLE = re.compile(r'^https?://news\.bjx\.com\.cn/html/20\d{6}/\d+\.shtml(?:\?.*)?$', re.I)
DATE_PATTERN = re.compile(r'(?<!\d)(20[12]\d)[-./年](0?[1-9]|1[0-2])[-./月](0?[1-9]|[12]\d|3[01])日?(?!\d)')
WIND_WORDS = re.compile(r'风电|风力发电|风机|风光|风[、，和与/]光|海风|海上风|陆上风|风能|风场|风力机|风光大基地')
RENEWABLE = re.compile(r'新能源|可再生能源|绿电|绿色电力|电力市场|上网电价|机制电价|直连|能源项目|清洁能源|并网|电力现货|储能|消纳')
POLICY = re.compile(r'政策|法规|条例|规章|规范性|管理办法|办法|实施方案|细则|标准|通知|公示|公告|规定|意见|规划|竞价|竞争性配置|竞配|指标|核准|申报|清单|改革')
OUT_OF_SCOPE = re.compile(r'招聘|展会|大会直播|上市|股价|中标供应商|采购招标|人物访谈|财报|企业业绩')
OFFICIAL_HOST = re.compile(r'(?:^|\.)gov\.cn$|(?:^|\.)nea\.gov\.cn$', re.I)


def province_of(value):
    value = str(value or '').strip()
    for short, variants in ALIASES.items():
        if value == short or value in variants:
            return short
    return ''


def provinces_in_title(value):
    """Only use the headline to assign region; one headline may refer to many."""
    text = str(value or '')
    matched = [short for short, aliases in ALIASES.items()
               if short in text or any(alias in text for alias in aliases)]
    return matched


def province_from_title(value):
    matched = provinces_in_title(value)
    return matched[0] if len(matched) == 1 else ''


def plausible_wind_policy(title, text=''):
    """Cheap prefilter; never a legal-validity assessment.

    General renewable-electricity policies often affect wind farms even when
    the title does not contain the two characters 风电.  The body must establish
    the wind relationship for a generalized title.
    """
    title = str(title or '')
    text = str(text or '')
    if OUT_OF_SCOPE.search(title) and not POLICY.search(title):
        return False
    if WIND_WORDS.search(title):
        return bool(POLICY.search(title) or RENEWABLE.search(title) or POLICY.search(text))
    return bool(RENEWABLE.search(title) and POLICY.search(title) and WIND_WORDS.search(text))


def _day(text):
    m = DATE_PATTERN.search(str(text or ''))
    if not m:
        return ''
    try:
        return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
    except ValueError:
        return ''


def _outside_link_date(anchor):
    """A date after an article link, not a yyyy-mm-dd in the headline."""
    # The BJX listing's item wrapper contains the article anchor and its date.
    container = anchor.find_parent(['li', 'tr', 'article']) or anchor.parent
    if container is not None:
        clone = BeautifulSoup(str(container), 'html.parser')
        for link in clone.select('a'):
            link.decompose()
        candidate = _day(clone.get_text(' ', strip=True))
        if candidate:
            return candidate
    for node in list(anchor.next_siblings)[:4]:
        text = node.get_text(' ', strip=True) if hasattr(node, 'get_text') else str(node)
        if len(text) < 130 and (candidate := _day(text)):
            return candidate
    return ''


def parse_bjx_policy_directory(html, url):
    """Site-specific policy directory: restricted article URL + adjacent date.

    This is NOT a general-purpose link parser; unrelated menus, commercial ads,
    social links, pagination and other BJX channels are excluded explicitly.
    Pagination is read from the real '下一页' anchor; never guess /2/ URLs.
    """
    soup = BeautifulSoup(html, 'html.parser')
    rows = []
    seen = set()
    for anchor in soup.select('a[href]'):
        raw = anchor.get('href') or ''
        target = urljoin(url, raw)
        if not BJX_ARTICLE.fullmatch(target) or target in seen:
            continue
        title = ' '.join(anchor.get_text(' ', strip=True).split())
        if not 7 <= len(title) <= 190:
            continue
        # A dated link in a media site is a discovery candidate, not a law.
        published = _outside_link_date(anchor)
        seen.add(target)
        score = 9 if WIND_WORDS.search(title) else (5 if RENEWABLE.search(title) and POLICY.search(title) else 0)
        rows.append({'title': title, 'url': target, 'date': published,
                     'rank': score, 'discovery_type': 'media_hint'})
    next_urls = []
    for anchor in soup.select('a[href]'):
        title = ' '.join(anchor.get_text(' ', strip=True).split())
        if title not in ('下一页', '下页', 'Next', 'next') and anchor.get('rel') != ['next']:
            continue
        path = urljoin(url, anchor.get('href') or '')
        if (urlsplit(path).hostname == 'fd.bjx.com.cn' and
            re.fullmatch(r'/zc/(?:\d+/)?', urlsplit(path).path) and
            path.rstrip('/') != url.rstrip('/') and path not in next_urls):
            next_urls.append(path)
    dates = [x['date'] for x in rows if x['date']]
    # The category page is long and may be sorted by issue date; those dates
    # must be consecutive for a boundary proof. We never infer a single page
    # from merely finding one page of results.
    dated = sum(bool(r['date']) for r in rows)
    return {'links': rows,
            'selector_matched': bool(rows),
            'selectors': ['bjx_policy_article_url+adjacent_row_date'] if rows else [],
            'oldest_date': min(dates) if dates else '',
            'newest_date': max(dates) if dates else '',
            'dated_rows': dated,
            'eligible_rows': len(rows),
            'undated_policy_rows': len(rows)-dated,
            'next_urls': next_urls[:1],
            'js_pagination': False,
            'explicit_single_page': False,
            'anchor_total': len(soup.select('a[href]')),
            'chronological': all(a >= b for a,b in zip(dates, dates[1:])),
            'future_dates': sum(d > date.today().isoformat() for d in dates),
            'explicit_pagination': bool(next_urls)}


def official_link_candidates(html, article_url):
    """Only identify explicit official outbound links; never invent or crawl one."""
    soup = BeautifulSoup(html, 'html.parser')
    links = []
    for node in soup.select('article a[href],.article a[href],.article-content a[href],#content a[href],a[href]'):
        target = urljoin(article_url, node.get('href') or '')
        host = (urlsplit(target).hostname or '').lower()
        if (urlsplit(target).scheme in ('https', 'http') and OFFICIAL_HOST.search(host)
                and target not in links):
            links.append(target)
    return links[:12]


def _is_official_source(src):
    if src.get('source_type') == '政策线索' or src['id'] == MEDIA_SOURCE_ID:
        return False
    host = (urlsplit(src.get('url', '')).hostname or '').lower()
    return bool(OFFICIAL_HOST.search(host))


def build_contract(sources):
    """Document all provinces and their *configured* official channels.

    Contract presence is not a successful HTTP probe or proof of coverage.
    """
    groups = defaultdict(lambda: {'official': [], 'media': []})
    for src in sources:
        name = src.get('name','')
        province = province_of(src.get('province'))
        if src['id'] == MEDIA_SOURCE_ID:
            for p in PROVINCES:
                groups[p]['media'].append(src['id'])
        elif province:
            if _is_official_source(src):
                groups[province]['official'].append(src['id'])
    result = []
    for province in PROVINCES:
        refs = groups[province]
        official = sorted(refs['official'], key=lambda sid: (
            0 if any(s['id']==sid and ('能源局' in s['name'] or '发改' in s['name'] or '发展和改革' in s['name']) for s in sources) else 1,
            sid))
        result.append({'province': province, 'official_source_ids': official,
                       'media_source_ids': refs['media'],
                       'monitoring_contract': '官方目录+风电政策媒体线索；媒体不能作为法规原文',
                       'contract_configured': bool(official and refs['media']),
                       'source_count': len(official),
                       'live_verified': False})
    return result


def build_province_report(sources, statuses, policies):
    """Grounded monitor health per province, distinct from legal coverage."""
    by_id = {x['id']:x for x in statuses if isinstance(x, dict) and x.get('id')}
    contract = build_contract(sources)
    rows=[]
    for item in contract:
        p = item['province']; refs=item['official_source_ids']
        all_statuses = [by_id[x] for x in refs if x in by_id]
        # Do not rebrand a historical crawl as today's successful coverage.
        # A single verified catalogue is not proof that all provincial agencies
        # have been checked, hence there is no state called 'province_complete'.
        now = datetime.now(timezone.utc)
        def recent(st):
            if st.get('not_refreshed_in_this_run') or not st.get('checked_at'):return False
            try:return now-datetime.fromisoformat(st['checked_at'].replace('Z','+00:00'))<=timedelta(hours=36)
            except (TypeError,ValueError):return False
        observed = [st for st in all_statuses if recent(st)]
        verified = sum(bool(x.get('listing_coverage_complete')) for x in observed)
        readable = sum(x.get('status') in ('ok_with_results','ok_no_recent','partial_coverage')
                       and x.get('listing_rows_total',0)>0 for x in observed)
        errors = [(x['name'],x['status'],x.get('message','')) for x in all_statuses
                  if x.get('status') not in ('ok_with_results','ok_no_recent')]
        matched_official = [x for x in policies if province_of(x.get('province'))==p and
                            x.get('source_id') in refs]
        matched_media = [x for x in policies if province_of(x.get('province'))==p and
                          x.get('source_id')==MEDIA_SOURCE_ID]
        if verified:
            state='official_listing_verified'  # At least one channel, NOT entire province.
        elif matched_official:
            state='official_policy_discovered_without_complete_coverage'
        elif matched_media:
            state='media_clues_only'
        elif readable:
            state='official_listing_readable_but_unproven'
        else:
            state='pending_or_blocked'
        rows.append({**item, 'status':state, 'official_sources_scanned':len(observed),
                     'official_sources_with_saved_history':len(all_statuses),
                     'verified_official_catalogues':verified,
                     'readable_official_catalogues':readable,
                     'official_policy_records':len(matched_official),
                     'media_clues':len(matched_media),
                     'issues': [{'name':a,'status':b,'reason':c} for a,b,c in errors]})
    return {'generated_at':datetime.now(timezone.utc).isoformat(),
            'warning':'某省至少一个目录已核验不代表全省所有发文机关均已覆盖；媒体线索不是官方法规',
            'province_count':len(PROVINCES),'provinces':rows}


def export_province_report(root, data_dir=None, diagnostics_dir=None, statuses=None, policies=None):
    root=Path(root);data=Path(data_dir) if data_dir is not None else root/'site'/'data'
    data.mkdir(parents=True,exist_ok=True)
    sources=json.loads((root/'policy_sources.json').read_text(encoding='utf-8'))
    if statuses is None:statuses=json.loads((data/'policy_source_status.json').read_text(encoding='utf-8'))
    if policies is None:policies=json.loads((data/'policies.json').read_text(encoding='utf-8'))
    report=build_province_report(sources,statuses,policies)
    (data/'provincial_monitoring_status.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    diag=Path(diagnostics_dir) if diagnostics_dir is not None else root/'diagnostics'
    diag.mkdir(parents=True,exist_ok=True)
    with (diag/'province_coverage.csv').open('w',encoding='utf-8-sig',newline='') as f:
        keys=('province','status','source_count','official_sources_scanned','verified_official_catalogues',
              'readable_official_catalogues','official_policy_records','media_clues')
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader()
        for r in report['provinces']:w.writerow({k:r.get(k,'') for k in keys})
    (diag/'province_coverage.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


if __name__ == '__main__':
    print('Provinces:',len(export_province_report(Path(__file__).resolve().parent)['provinces']))
