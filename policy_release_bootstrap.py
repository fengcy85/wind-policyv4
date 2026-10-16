"""Initialize *new-install* V7 policy monitor state without falsifying live checks.

Use only when preparing a new standalone release; DO NOT run automatically in
GitHub Actions or on a live repository, where it would reset real checkpoints.
Historical policies/news are deliberately retained; historical *crawl statuses*
are archived as evidence rather than presented as fresh V7 results.
"""
from __future__ import annotations
import argparse
import csv
import json
from datetime import date, timedelta, datetime, timezone
from pathlib import Path


def read(path, default):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError,OSError):return default


def put(path, obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def bootstrap_release(root):
    root=Path(root); data=root/'site'/'data'; audit=root/'diagnostics'
    sources=read(root/'policy_sources.json',[])
    if not sources or not all(s.get('id') and s.get('url') for s in sources):
        raise ValueError('No valid source registry; refusing destructive initialization')
    old=read(data/'policy_source_status.json',[])
    old_cp=read(data/'policy_source_checkpoints.json',{})
    if isinstance(old,list) and old:
        put(audit/'pre_v7_status_archive.json',{
            'warning':'历史运行记录，不证明V7站点已访问；详见新版本真正的Actions报告。',
            'archived_at':datetime.now(timezone.utc).isoformat(),
            'historical_statuses':old})
    cp_sources=old_cp.get('sources',{}) if isinstance(old_cp,dict) else {}
    if cp_sources:
        put(audit/'pre_v7_checkpoint_archive.json',{
            'warning':'迁移前游标备份，不代表V7新URL和新列表结构已核验。',
            'checkpoint':old_cp})
    today=date.today(); checkpoints={}; pending=[]; acceptance=[]
    for source in sources:
        sid=source['id'];past=cp_sources.get(sid,{})
        first=past.get('first_seen_on',today.isoformat())
        try:firstday=date.fromisoformat(first)
        except (ValueError,TypeError):firstday=today;first=today.isoformat()
        if firstday>today:
            firstday=today;first=today.isoformat()
        window=(firstday-timedelta(days=29)).isoformat()
        checkpoints[sid]={
            'source_id':sid,'source_url':source['url'],'first_seen_on':first,
            'initial_window_start':window,'initialized':False,
            'last_verified_date':None,'last_verified_at':None,
            'coverage_proof_version':0,'consecutive_failures':0,'total_attempts':0,
            'last_error':'','migration_note':'V7按省重构：目录与适配器需重新完成实网核验。'}
        st={'id':sid,'name':source['name'],'status':'not_tested','checked_at':None,
            'message':'V7重构来源：尚未从本次GitHub运行环境完成真实HTTP、目录、日期和翻页检查。',
            'found_count':0,'candidate_links':0,'listing_rows_with_date':0,
            'listing_rows_total':0,'listing_pages':0,'listing_coverage_complete':False,
            'coverage_complete':False,'detail_retry_count':0,'attempts':[],
            'source_kind':source.get('source_type',''), 'phase':'initial_month',
            'initialized':False,'not_refreshed_in_this_run':True}
        pending.append(st)
        acceptance.append({'网站名称':source['name'],'当前状态':'not_tested',
            '失败原因':'尚未执行V7真实抓取；不是网络错误，也不是已核验成功。',
            '需要怎么适配':'读取真实官网/媒体政策列表，验证发布时间、翻页、正文及附件。',
            '修复后测试结果':'待本次GitHub Actions真实运行结果验收',
            '官方网站':source['url'],'专站适配器':sid,'策略':source.get('strategy',''),
            '阶段':'initial_month','初始化完成':False,'初始窗口起点':window,
            '本轮起点':window,'最后核验日期':'','日期覆盖核验':False,
            '发布日期有效行数':0,'目录总行数':0,'详情错误数':0,'法规候选数':0,
            '连续失败次数':0,'检查时间UTC':'','详细访问轨迹':'[]'})
    put(data/'policy_source_status.json',pending)
    put(data/'policy_source_checkpoints.json',{'version':1,
        'updated_at':datetime.now(timezone.utc).isoformat(),
        'bootstrap_days':30,'daily_overlap_days':2,'sources':checkpoints})
    put(data/'policy_site_acceptance.json',acceptance)
    with (data/'policy_site_acceptance.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(acceptance[0]));writer.writeheader();writer.writerows(acceptance)
    put(data/'policy_crawl_state.json',{
        'version':'V7-province-first','last_run':None,
        'note':'新交付包暂无V7真实抓取；历史V6状态已归档 diagnostics/',
        'configured_source_count':len(sources),'attempted_source_count':0,
        'initial_phase_count':0,'incremental_phase_count':0,
        'initialized_source_count':0,'pending_initialization_count':len(sources),
        'bootstrap_days':30,'daily_overlap_days':2,
        'status_counts':{'not_tested':len(sources)},
        'change_counts':{'inserted':0,'updated':0,'unchanged':0}})
    # The former policy_crawler wrote a different historical policy_meta file.
    # Prevent its old counters being mistaken for V7 current status by the UI.
    old_meta=read(data/'policy_meta.json',{})
    if old_meta:
        put(audit/'pre_v7_policy_meta_archive.json',old_meta)
    put(data/'policy_meta.json',{
        'last_run_at':None,'source_total':len(sources),'checked_source_count':0,
        'sources_with_http_response':0,'sources_with_candidate_evidence':0,
        'new_candidate_clauses':0,'total_candidate_clauses':0,
        'pending_review_clauses':0,'verified_and_scored_clauses':0,
        'source_status_count':{},
        'warning':'历史来源状态已归档，V7本轮真实监测状态请看 policy_crawl_state.json / policy_source_status.json。',
        'crawler_mode':'V7 province-first official directories and professional-media discovery'})
    return len(pending)

if __name__=='__main__':
    a=argparse.ArgumentParser(description='For freshly packaged releases ONLY; backs up then resets historical site statuses.')
    a.add_argument('--apply-new-install',action='store_true',required=True)
    a.add_argument('--root',default=str(Path(__file__).resolve().parent))
    opts=a.parse_args()
    print('Initialized',bootstrap_release(opts.root),'unverified V7 source states (historical data archived).')
