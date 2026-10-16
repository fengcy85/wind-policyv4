"""Backend-only GitHub Actions quality gate report; no frontend changes."""
from __future__ import annotations
import json,os
from datetime import datetime,timezone
from pathlib import Path

BASE=Path(__file__).resolve().parent

def write_quality_summary(statuses,runner_label='GitHub Actions',state=None,started_at=None):
    total=len(statuses)
    fresh=[x for x in statuses if not x.get('not_refreshed_in_this_run') and x.get('checked_at')]
    listing_verified=sum(bool(row.get('listing_coverage_complete',row.get('coverage_complete'))) for row in fresh)
    full_verified=sum(bool(row.get('coverage_complete')) for row in fresh)
    blocked=sum(row['status']=='blocked' for row in statuses)
    network=sum(row['status'] in ('connection_error','timeout') for row in statuses)
    pending=sum(int(row.get('detail_retry_count') or 0) for row in fresh)
    state=state or {}
    last_run=state.get('last_run','')
    valid_new_run=bool(last_run and (not started_at or last_run>=started_at))
    lines=[f'## 风电法规抓取质量｜{runner_label}',
           '', '本轮新抓取数据：'+('已生成' if valid_new_run else '未能证明本轮成功写入（可能仍显示旧数据）'),
           '执行范围：'+str(state.get('scope','旧版未标注')),
           '',f'- 已配置来源：{total}；本轮已尝试：{len(fresh)}',f'- 目录时间窗完成核验：{listing_verified}',
           f'- 目录和详情均完成：{full_verified}',f'- 访问受限：{blocked}',
           f'- 连接/超时异常：{network}',f'- 独立详情待补：{pending}',
           '', '> 注意：HTTP 200、首页可见、或取得部分文章均不等于时间窗覆盖完成。',
           '', '| 站点 | 状态 | 目录覆盖 | 详情待补 | 解释 |', '|---|---|---|---|---|']
    for row in statuses:
        if not row.get('coverage_complete'):
            msg=str(row.get('message','')).replace('|','/').replace('\n',' ')[:95]
            lines.append(f"| {row.get('name','')} | {row.get('status','')} | "
                         f"{row.get('listing_coverage_complete',False)} | "
                         f"{row.get('detail_retry_count',0)} | {msg} |")
    return '\n'.join(lines)+'\n'

if __name__=='__main__':
    file=BASE/'site/data/policy_source_status.json'
    statuses=json.loads(file.read_text()) if file.exists() else []
    state_file=BASE/'site/data/policy_crawl_state.json'
    state=json.loads(state_file.read_text(encoding='utf-8')) if state_file.exists() else {}
    marker=BASE/'diagnostics/this_job_started_utc.txt'
    started_at=marker.read_text(encoding='utf-8').strip() if marker.exists() else None
    text=write_quality_summary(statuses,state=state,started_at=started_at)
    out=BASE/'diagnostics/last_run_quality.md'
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(text)
    path=os.getenv('GITHUB_STEP_SUMMARY')
    if path:
        with open(path,'a',encoding='utf-8') as f:f.write(text)
    print('Wrote',out,'with',len(statuses),'source records')
