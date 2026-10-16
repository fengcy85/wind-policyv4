"""Non-invasive reachability probes for policy-source URLs.

Example:
  python policy_network_probe.py --region github-actions --limit 20 --output diagnostics/github.json
  python policy_network_probe.py --region authorized-cn-runner --all --output diagnostics/china.json
  python policy_network_probe.py --compare diagnostics/github.json diagnostics/china.json --output diagnostics/comparison.json

The region is an operator-supplied label; it is NOT inferred or authenticated.
No login, CAPTCHA solving, impersonated identities, or anti-bot evasion.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

import requests

from policy_transport import DomainThrottle, classify_error
from policy_provincial import build_contract,MEDIA_SOURCE_ID

ROOT=Path(__file__).resolve().parent


def representative_urls(sources, limit):
    """One URL per host, with a fair split across domestic/international."""
    groups={'中国':[], '海外/国际':[]}
    seen=set()
    for src in sources:
        host=(urlsplit(src['url']).hostname or '').lower()
        if host and host not in seen:
            seen.add(host)
            groups['中国' if src['region']=='中国' else '海外/国际'].append(src)
    if limit is None:
        return groups['中国']+groups['海外/国际']
    domestic=groups['中国'][:(limit+1)//2]
    foreign=groups['海外/国际'][:limit//2]
    rest=groups['中国'][len(domestic):]+groups['海外/国际'][len(foreign):]
    return (domestic+foreign+rest)[:limit]


def province_first_urls(sources,limit):
    """One configured high-priority government channel per province, plus BJX.

    A URL selected for probing is not claimed to have been verified accessible.
    """
    lookup={s['id']:s for s in sources}
    selected=[];hosts=set()
    def add(source):
        if not source:return
        host=(urlsplit(source.get('url','')).hostname or '').lower()
        if host and host not in hosts:
            selected.append(source);hosts.add(host)
    for item in build_contract(sources):
        if item['official_source_ids']:
            add(lookup.get(item['official_source_ids'][0]))
    add(lookup.get(MEDIA_SOURCE_ID))
    if limit is None or len(selected)<limit:
        for src in sources:
            if src.get('region')=='中国':add(src)
            if limit is not None and len(selected)>=limit:break
    return selected if limit is None else selected[:limit]

def probe_one(source, timeout=7, getter=None, gate=None):
    url=source['url'];host=urlsplit(url).hostname or ''
    getter=getter or requests.get
    gate=gate or DomainThrottle(1,0.5)
    record={'id':source['id'],'name':source['name'],'host':host,'url':url,
            'province':source.get('province',''),'reachable':False,'http_status':None,'redirect_url':'','error_code':'',
            'error':'','elapsed_ms':None}
    start=time.monotonic()
    try:
        with gate.lease(url):
            with getter(url,timeout=(min(timeout,5),timeout),stream=True,
                        allow_redirects=True,headers={'User-Agent':'WindPolicyMonitor/6.2 (public reachability check)'}) as response:
                record['http_status']=response.status_code
                record['redirect_url']=str(response.url)
                record['reachable']=response.status_code < 400
                if not record['reachable']:
                    code,_,hint=classify_error(Exception(f'HTTP {response.status_code}'))
                    record['error_code']=code;record['error']=hint
    except Exception as exc:
        code,http_status,hint=classify_error(exc)
        record['error_code']=code;record['http_status']=http_status
        record['error']=f'{hint} [{type(exc).__name__}: {str(exc)[:150]}]'
    record['elapsed_ms']=round((time.monotonic()-start)*1000)
    return record


def compare_reports(a,b):
    """Compare host evidence without assuming either runner's actual geography."""
    amap={r['host']:r for r in a.get('probes',[])}
    bmap={r['host']:r for r in b.get('probes',[])}
    rows=[]
    for host in sorted(set(amap)|set(bmap)):
        ar=amap.get(host);br=bmap.get(host)
        if ar is None or br is None:result='missing_one_side'
        elif ar['reachable'] and br['reachable']:result='both_reachable'
        elif ar['reachable'] and not br['reachable']:result='only_'+a['region']+'_reachable'
        elif not ar['reachable'] and br['reachable']:result='only_'+b['region']+'_reachable'
        else:result='both_failed'
        rows.append({'host':host,'result':result,
                     a.get('region','run_a'):{'status':ar.get('http_status') if ar else None,
                        'error':ar.get('error_code') if ar else 'not_tested'},
                     b.get('region','run_b'):{'status':br.get('http_status') if br else None,
                        'error':br.get('error_code') if br else 'not_tested'}})
    return {'compared_at':datetime.now(timezone.utc).isoformat(),
            'a_region_label':a.get('region'),'b_region_label':b.get('region'),
            'warning':'region labels are provided by runner operators; no IP geolocation proof',
            'hosts_compared':len(rows),'results':rows}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region',help='Operator-supplied runner location label')
    parser.add_argument('--all',action='store_true',help='All distinct hosts (default sample of 20)')
    parser.add_argument('--limit',type=int,default=20)
    parser.add_argument('--timeout',type=float,default=7)
    parser.add_argument('--workers',type=int,default=3)
    parser.add_argument('--provinces-first',action='store_true',help='Probe one official primary for each of 31 provinces and the BJX category')
    parser.add_argument('--compare',nargs=2,metavar=('RUN_A','RUN_B'))
    parser.add_argument('--output',required=True)
    args=parser.parse_args(argv)
    if args.compare:
        report=compare_reports(*(json.loads(Path(p).read_text()) for p in args.compare))
    else:
        if not args.region:parser.error('--region is required for a live probe')
        sources=json.loads((ROOT/'policy_sources.json').read_text())
        selection=(province_first_urls(sources,None if args.all else max(1,args.limit)) if args.provinces_first
                   else representative_urls(sources,None if args.all else max(1,args.limit)))
        gate=DomainThrottle(1,0.6)
        with ThreadPoolExecutor(max_workers=max(1,min(args.workers,5))) as pool:
            work={pool.submit(probe_one,src,args.timeout,None,gate):i for i,src in enumerate(selection)}
            items=sorted(((work[t],t.result()) for t in as_completed(work)),key=lambda x:x[0])
        probes=[record for _,record in items]
        report={'region':args.region,'observed_at':datetime.now(timezone.utc).isoformat(),
                'scope':{'sources':len(sources),'hosts_tested':len(probes),
                         'all_hosts':args.all},
                'warning':'Probe executed from this runner only; a China runner must be run separately',
                'probes':probes}
    target=Path(args.output);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(f'Saved {target} ({len(report.get("probes",report.get("results",[])))} hosts)')
    return report

if __name__=='__main__':main()
