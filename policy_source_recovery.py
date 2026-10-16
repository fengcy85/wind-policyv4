"""Write one auditable per-site recovery plan from configured policies + last runs.

No successful HTTP result or DOM verification is inferred from a configuration.
This is an operational aid and never changes the website frontend.
"""
from __future__ import annotations
import csv
import json
from pathlib import Path
from urllib.parse import urlsplit
from datetime import datetime, timezone
from policy_provincial import build_contract,MEDIA_SOURCE_ID,province_of,OFFICIAL_HOST

ROOT=Path(__file__).resolve().parent


def _read(path, fallback):
    try:return json.loads(Path(path).read_text(encoding='utf-8'))
    except (ValueError,OSError):return fallback


def operator_action(source, status):
    code=status.get('status','not_tested')
    errs=[a.get('error_code') for a in status.get('attempts',[]) if a.get('method')=='http' and a.get('status')=='failed']
    if any(x=='http_404' for x in errs) or (code=='http_error' and '404' in status.get('message','')):
        return '404：逐一核对已配置的官方备用目录；需有实际发布条目才替换主入口。无法找到则转北极星媒体发现，保留原机关未核验。'
    if any(x=='http_403' for x in errs) or (code=='blocked' and '403' in status.get('message','')):
        return '403：核对官网允许访问的公开栏目；在已获授权的境内机器与GitHub分别探测；不绕过访问限制，使用官方公开备选和北极星线索。'
    if any(x=='http_412' for x in errs) or (code=='blocked' and '412' in status.get('message','')):
        return '412：请求前提不满足；停止频繁重试，检查官网公开访问条件或改官方公报、公开镜像。媒体仅作线索。'
    if code=='blocked':return '受限：遵循对方访问规则，降低频率，检查官网公开栏目，媒体仅用于补漏。'
    if code in ('timeout','connection_error'):
        return '连接/TLS/DNS/超时：记录原始错误和最终地址，做GitHub与获准境内服务器对照；若境内畅通则迁移执行端而不是网页；不要关闭TLS证书验证。'
    if code=='needs_adapter':return 'HTML200但未识别列表：留存真实页面结构，核对是否搜索/iframe/JS数据；对该站设置真正列表DOM、逐行日期和翻页机制。'
    if code=='partial_coverage':return '能取得部分候选但日期或分页不完整：单独排查日期所在节点、真实下一页和时间边界；不得推进目录游标；详情列入重试队列。'
    if code in ('ok_with_results','ok_no_recent'):
        return '本轮目录覆盖通过：检查发现数、详情待补和发布日期证据；按日增量继续。通过一个栏目不代表全省完整覆盖。'
    if code in ('not_scheduled','not_tested'):return '尚未由该运行环境抓取：优先对政策主管部门真站执行，完成实际DOM、发布日期、翻页和附件验收。'
    return '运行异常：根据attempts区分请求失败与解析失败；保留官方备用目录+媒体线索，不视为该省已覆盖。'


def make_plan(sources, statuses):
    statuses_by_id={s['id']:s for s in statuses if isinstance(s,dict) and s.get('id')}
    contracts=build_contract(sources)
    priority_by_id={sid:rank+1 for row in contracts for rank,sid in enumerate(row['official_source_ids'])}
    rows=[]
    for src in sources:
        if src.get('region')!='中国':continue
        status=statuses_by_id.get(src['id'],{})
        url=src['url']
        is_media=src['id']==MEDIA_SOURCE_ID or src.get('source_type')=='政策线索'
        official=bool(OFFICIAL_HOST.search((urlsplit(url).hostname or '').lower())) and not is_media
        latest_probe=status.get('checked_at')
        attempts=[a for a in status.get('attempts',[]) if a.get('method') in ('http','browser','public_ui_search')]
        probes_main=[a for a in attempts if a.get('url')==url]
        attempted_url=next((a.get('url') for a in attempts), '')
        rows.append({
          '省份':province_of(src.get('province')) or ('全国补充' if is_media else '全国'),
          '来源名称':src['name'],'来源ID':src['id'],
          '角色':'媒体政策线索（需核对官方原文）' if is_media else ('官方发布机关' if official else '其他公开来源'),
          '来源优先级':priority_by_id.get(src['id'],'补充'),
          '官方/媒体入口':url,
          '备用入口':'; '.join(src.get('entry_urls',[url])[1:]),
          '已观察的线上状态':status.get('status','not_tested'),
          '上次检查时间UTC':latest_probe or '',
          '核验基于现行入口':bool(probes_main),
          '检测入口与当前配置一致':(attempted_url==url if attempted_url else False),
          'URL真实访问检测通过':bool(any(a.get('status')=='read' and a.get('method')=='http' for a in probes_main)),
          '本轮识别日期目录行':int(status.get('listing_rows_with_date') or 0),
          '真实DOM选择器已核验':bool(status.get('adapter_live_verified',False)),
          '目录时间段已核验':bool(status.get('listing_coverage_complete')),
          '已识别政策条目数':int(status.get('found_count') or 0),
          '失败类型':' / '.join(dict.fromkeys(a.get('error_code','') for a in attempts if a.get('status')=='failed')),
          '处置方法':operator_action(src,status),
          '核验备注':'网页目录是否公开可访问与采集规则能否成功执行是两个不同的验收指标。'
        })
    return {'generated_at':datetime.now(timezone.utc).isoformat(),
            'warning':'对历史状态/旧URL不推断新URL成功；未测试站点不是已抓取成功；媒体不能证明官方法规原文。',
            'configured_source_count':len(sources),
            'provincial_source_rows':len(rows),
            'province_count':len(contracts),
            'province_contracts':contracts,'source_rows':rows}


def export_plan(root=ROOT):
    root=Path(root);s=_read(root/'policy_sources.json',[])
    statuses=_read(root/'site/data/policy_source_status.json',[])
    plan=make_plan(s,statuses)
    folder=root/'diagnostics';folder.mkdir(exist_ok=True)
    (folder/'provincial_source_recovery.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    rows=plan['source_rows']
    with (folder/'provincial_source_recovery.csv').open('w',newline='',encoding='utf-8-sig') as f:
        if rows:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    # Static contract is configuration only; generated separately from run status.
    (folder/'province_source_contracts.json').write_text(json.dumps(plan['province_contracts'],ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return plan

if __name__=='__main__':
    report=export_plan()
    print('Configured',report['configured_source_count'],'sources; 31 provinces;',report['provincial_source_rows'],'Chinese channels; no live success assumed')
