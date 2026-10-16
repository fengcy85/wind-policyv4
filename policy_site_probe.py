"""Safe, independent, source-by-source listing probe for official wind policy directories.

Probes only explicitly configured *public* entry URLs; never guesses an API,
ignores refusal/robot rules, impersonates browsers, or claims one page proves
coverage. No site/data state is touched, so running the probe cannot advance a
production cursor. Run the full collector separately to verify pagination.
"""
from __future__ import annotations
import argparse
import csv
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from adapters.registry import load_adapter
from policy_provincial import PROVINCES, MEDIA_SOURCE_ID, build_contract, province_of
from policy_scrape import _listing_page, _try_entry, adapter_urls, allowed_detail_link

ROOT = Path(__file__).resolve().parent


def choose_sources(sources, province='', source_id='', province_first=False, limit=0):
    selected = [x for x in sources if x.get('region') == '中国']
    if source_id:
        selected = [x for x in sources if x.get('id') == source_id]
    elif province:
        selected = [x for x in selected if province_of(x.get('province')) == province]
    elif province_first:
        by_id = {x['id']: x for x in selected}
        contracts = build_contract(sources)
        selected = [by_id[x['official_source_ids'][0]] for x in contracts if x['official_source_ids']]
        selected += [by_id[MEDIA_SOURCE_ID]] if MEDIA_SOURCE_ID in by_id else []
    return selected[:limit] if limit else selected


def probe_one(source):
    """Read entry pages and explain failures; no detail fetch or full pagination.

    The response is never called a complete time-window coverage result.
    """
    a = load_adapter(source)
    at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    rows = []
    for url in adapter_urls(source):
        attempts = []
        fetched = _try_entry(url, source.get('adapter') or source['id'], False, attempts)
        result = {'url': url, 'http_readable': False, 'http_attempts': attempts,
                  'dated_rows': 0, 'eligible_rows': 0, 'missing_dates': 0,
                  'next_url': '', 'date_sorted_desc': False,
                  'live_dom_verified': False, 'time_window_coverage_verified': False,
                  'sample_headlines': [], 'dom_samples': []}
        if fetched is not None:
            html, final, kind = fetched
            if kind == 'html' and allowed_detail_link(url, final, a):
                listing = _listing_page(html, final, a)
                result.update(http_readable=True, final_url=final,
                    dated_rows=listing['dated_rows'], eligible_rows=listing['eligible_rows'],
                    missing_dates=listing['undated_policy_rows'],
                    next_url=(listing['next_urls'][0] if listing['next_urls'] else ''),
                    date_sorted_desc=listing['chronological'],
                    live_dom_verified=bool(listing['selector_matched'] and listing['dated_rows']),
                    sample_headlines=[{'title':r['title'],'date':r['date'],'url':r['url']}
                                      for r in listing['links'][:6]],
                    dom_samples=listing.get('dom_samples',[])[:6],
                    html_title=listing.get('page_title',''),
                    pagination_is_dynamic=listing['js_pagination'],
                    selector_matches=listing['selectors'][:5])
            elif kind == 'pdf':
                result.update(http_readable=True, failure_class='pdf_is_not_a_catalogue')
            else:
                result['failure_class']='rejected_redirect_or_unsupported_markup'
        if not result['http_readable']:
            result['failure_class'] = result.get('failure_class') or next(
                (a.get('error_code','unknown') for a in attempts if a.get('status')=='failed'),
                'unknown')
        elif not result['live_dom_verified']:
            result['failure_class']='no_dated_official_list_rows'
        else:
            result['failure_class']='requires_pagination_and_detail_validation'
        rows.append(result)
        # Only the first identified valid directory is needed for a quick probe;
        # subsequent entries are *alternatives*, not silently unified archives.
        if result['live_dom_verified']:
            break
    return {'source_id':source['id'],'name':source['name'],'province':province_of(source.get('province')),
            'category':source.get('source_type',''), 'checked_at':at,
            'candidate_entries':len(rows), 'verified_listing_entry':any(r['live_dom_verified'] for r in rows),
            'full_coverage_verified':False, 'entries':rows}


def write_reports(records, json_path):
    target = Path(json_path)
    target.parent.mkdir(parents=True,exist_ok=True)
    report = {'generated_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
              'warning':'该工具只核验公开目录第一页真实HTML及日期，不探测所有分页，不认定覆盖完整，不更新游标。',
              'probed_sources':len(records),
              'http_and_dom_readable':sum(bool(s['verified_listing_entry']) for s in records),
              'full_coverage_verified':False, 'sources':records}
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    flat=[]
    for record in records:
        entries=record['entries']
        entry=next((x for x in entries if x['live_dom_verified']),entries[0] if entries else {})
        flat.append({'省份':record['province'],'来源':record['name'],'来源ID':record['source_id'],
                     '入口':entry.get('url',''),'入口HTTP可读':entry.get('http_readable',False),
                     '真实日期目录已识别':record['verified_listing_entry'],
                     '日期行数':entry.get('dated_rows',0),'全部候选行数':entry.get('eligible_rows',0),
                     '缺日期行数':entry.get('missing_dates',0),
                     '第一页下一页':entry.get('next_url',''),
                     '完整时间区间已核验':False,
                     '诊断结果':entry.get('failure_class','no_configured_entry')})
    with target.with_suffix('.csv').open('w',encoding='utf-8-sig',newline='') as output:
        if flat:
            writer=csv.DictWriter(output,fieldnames=list(flat[0]))
            writer.writeheader();writer.writerows(flat)
    return report


def main(argv=None):
    ap=argparse.ArgumentParser(description='Independent per-site listing checks; does not modify production data')
    group=ap.add_mutually_exclusive_group()
    group.add_argument('--province',choices=PROVINCES)
    group.add_argument('--source-id')
    group.add_argument('--province-first',action='store_true')
    ap.add_argument('--limit',type=int,default=0)
    ap.add_argument('--workers',type=int,default=3)
    ap.add_argument('--output',default='diagnostics/site_probe_latest.json')
    opts=ap.parse_args(argv)
    sources=json.loads((ROOT/'policy_sources.json').read_text(encoding='utf-8'))
    selected=choose_sources(sources,opts.province,opts.source_id,opts.province_first,opts.limit)
    if not selected:
        ap.error('No matching source; use exact source ID or 31-provincial name')
    results=[]
    with ThreadPoolExecutor(max_workers=max(1,min(4,opts.workers))) as pool:
        jobs={pool.submit(probe_one,s):s for s in selected}
        for fut in as_completed(jobs):
            try:results.append(fut.result())
            except Exception as exc:
                s=jobs[fut]
                results.append({'source_id':s['id'],'name':s['name'],
                    'province':province_of(s.get('province')),'checked_at':datetime.now(timezone.utc).isoformat(),
                    'category':s.get('source_type',''),'candidate_entries':0,
                    'verified_listing_entry':False,'full_coverage_verified':False,
                    'entries':[{'url':s.get('url',''),'failure_class':type(exc).__name__+': '+str(exc)[:160]}]})
    results.sort(key=lambda r:next((i for i,s in enumerate(selected) if s['id']==r['source_id']),0))
    report=write_reports(results,ROOT/opts.output)
    print(f"Probed {report['probed_sources']} entries; HTTP+dated DOM readable {report['http_and_dom_readable']}; time-window coverage not asserted.")
    print('Report:',opts.output)

if __name__=='__main__':
    main()
