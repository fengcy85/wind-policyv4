/* Wind Policy Watch — two-page, evidence-first policy viewer; untrusted data is always escaped. */
'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
const safeHref = value => {try{const raw=String(value||'').trim();if(!/^https?:\/\//i.test(raw))return '';const u=new URL(raw);return ['http:', 'https:'].includes(u.protocol)?u.href:'';}catch{return '';}};
const isoDay = val => {const s=String(val||'');if(!/^\d{4}-\d{2}-\d{2}$/.test(s))return '';const d=new Date(`${s}T00:00:00Z`);return Number.isFinite(d.getTime())&&d.toISOString().slice(0,10)===s?s:'';};
const isInactive = r => /失效|废止|已终止|inactive|repealed|revoked/i.test(String(r.validity_status||r.doc_type||'')+' '+String(r.title||'').slice(0,18));
function insideDays(value, days, now=new Date()){
  if(days==='all')return true;
  const date=isoDay(value);if(!date)return false;
  const china=new Date(now.getTime()+8*3600*1000).toISOString().slice(0,10);
  const age=Math.round((Date.parse(china+'T00:00:00Z')-Date.parse(date+'T00:00:00Z'))/86400000);
  return age>=0&&age<Number(days);
}
const has = (value, term) => String(value||'').toLocaleLowerCase().includes(term);
const isOkay = code => String(code||'').startsWith('ok_')||['found','no_wind_regulations'].includes(code);
function labelStatus(code){return ({ok_with_results:'已核实发现候选',ok_no_recent:'已检查暂无近期法规',ok_no_relevant:'暂无相关法规',
  partial_coverage:'目录覆盖不完整',needs_adapter:'待专站适配',search_adapter_required:'检索入口待适配',
  blocked:'访问受限',robots_denied:'robots 限制',robots_unavailable:'robots 无法核实',
  access_restricted:'访问受限',connection_error:'连接失败',timeout:'超时',http_error:'HTTP 异常',
  detail_error:'法规详情失败',partial_failure:'部分抓取失败',found:'发现候选',
  no_wind_regulations:'未发现风电法规',not_checked:'尚未检查',not_run:'尚未检查'})[code]||code||'状态未核实';}
function outlink(url, text, cls=''){const u=safeHref(url);return u?`<a class="${esc(cls)}" href="${esc(u)}" target="_blank" rel="noopener noreferrer">${esc(text)} <span aria-hidden="true">↗</span></a>`:'<span class="link-disabled">原文链接待核实</span>';}
function selectOptions(id, values, label){const node=$(id);if(!node)return;const old=node.value;
  node.innerHTML=`<option value="">${esc(label)}</option>`+[...new Set(values.filter(Boolean))].sort((a,b)=>String(a).localeCompare(String(b),'zh-CN')).map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');
  node.value=[...new Set(values)].includes(old)?old:'';
}
const ui={policies:[],sources:[],statuses:[],dimensions:[],crawl:{},ai:{},sort:'latest'};
function policyScore(r){const numeric=Number(r.importance_score);const verified=Number.isFinite(numeric)&&r.importance_score!==null&&r.importance_score!=='';
  return (verified?200+numeric:0) + Math.min(20,Number(r.design_relevance||0)*5) + Math.min(10,(r.dimensions||[]).length);}
function filteredPolicies(now=new Date()){
  const term=$('policySearch').value.trim().toLocaleLowerCase(), days=$('policyDays').value;
  const region=$('policyRegion').value, dim=$('policyDimension').value, validity=$('policyValidity').value;
  return ui.policies.filter(r=>{const inactive=isInactive(r), hay=[r.title,r.country,r.source_name,r.source_excerpt,r.impact_design,...(r.dimensions||[])].join(' ').toLocaleLowerCase();
    return (!term||hay.includes(term))&&insideDays(r.published_at,days,now)&&(!region||r.region===region)&&(!dim||(r.dimensions||[]).includes(dim))&&
      (validity==='all'||(validity==='inactive'?inactive:!inactive));
  }).sort((a,b)=>{if(ui.sort==='impact'){const n=policyScore(b)-policyScore(a);if(n)return n;}
    return String(b.published_at||'').localeCompare(String(a.published_at||''))||String(a.title||'').localeCompare(String(b.title||''),'zh-CN');});
}
function policyCard(r){const tags=(r.dimensions||[]).slice(0,6).map(tag=>`<span class="tag">${esc(tag)}</span>`).join('')||'<span class="tag tag-muted">维度待核实</span>';
  const official=r.date_evidence?`title="${esc(r.date_evidence)}"`:'';
  const score=Number.isFinite(r.importance_score)?`<span class="tiny-label">已核验评分 ${esc(r.importance_score)}</span>`:'';
  const excerpt=r.source_excerpt||'原文内容尚未提取成功，请从官网核验。';
  const notice=(r.analysis_method||'规则辅助初筛·待人工核验');
  return `<article class="policy-card">
    <div class="policy-meta"><span class="policy-date" ${official}>${esc(isoDay(r.published_at)||'发布日期待核实')}</span><span class="meta-sep"></span><span>${esc(r.country||r.region||'地区待核实')}</span><span class="policy-type">${esc(r.doc_type||'法规候选')}</span>${isInactive(r)?'<span class="invalid-pill">已标注失效</span>':''}${score}</div>
    <h3 class="policy-title">${outlink(r.url,r.title||'原文标题待核实','title-link')}</h3>
    <div class="tag-row">${tags}</div>
    <div class="evidence-grid"><div class="evidence-box"><span class="field-label"><span class="field-icon">“</span> 法规原文节选</span><p>${esc(excerpt)}</p></div>
      <div class="impact-box"><span class="field-label"><span class="field-icon">↗</span> 产品设计影响分析</span><p>${esc(r.impact_design||'产品适用性待核实')}</p>
      <span class="analysis-note">${esc(notice)}</span></div></div>
    <div class="policy-bottom"><div><span>来源 · ${esc(r.source_name||'官方来源待核对')}</span><span class="meta-sep"></span><span>${esc(r.validity_status||'法律效力待核验')}</span></div>${outlink(r.url,'查看原文','source-link')}</div>
    <details class="deep-details"><summary>查看业务影响与核验说明</summary><p><strong>商业模式影响：</strong>${esc(r.impact_business||'未确认，需人工核对适用主体、采购与项目场景。')}</p><p><strong>核验状态：</strong>${esc(r.verification_status||'待人工核验')}</p><p><strong>后续建议：</strong>${esc(r.next_step||'核对官方全文和现行效力。')}</p>${r.ai_application_note?`<p><strong>AI 适用性提醒：</strong>${esc(r.ai_application_note)}</p>`:''}</details>
  </article>`;
}
function renderPolicies(){const rows=filteredPolicies();$('policyList').innerHTML=rows.slice(0,300).map(policyCard).join('');
  $('policyEmpty').classList.toggle('hidden',rows.length!==0);
  $('policySummary').textContent=`当前显示 ${rows.length} 条 · 候选库 ${ui.policies.length} 条（保留发布日期与可追溯原文证据）`+(rows.length>300?' · 仅展示前 300 条，请缩小筛选范围':'');
  $('policyCount').textContent=ui.policies.length;
  [['policySortLatest','latest'],['policySortImpact','impact']].forEach(([id,sort])=>{$(id).classList.toggle('active',ui.sort===sort);$(id).setAttribute('aria-pressed',String(ui.sort===sort));});
}
function statusRows(){const byId=new Map(ui.statuses.map(s=>[s.id,s]));return ui.sources.map(s=>({source:s,status:byId.get(s.id)||{status:'not_checked',message:'尚未运行'}}));}
function sourceViewRows(){const region=$('sourceRegion').value,term=$('sourceSearch').value.trim().toLocaleLowerCase(),state=$('sourceStatusFilter').value;
  return statusRows().filter(({source,status})=>{const hay=[source.name,source.country,source.url,source.region,status.message,status.status].join(' ').toLocaleLowerCase();const code=status.status||'not_checked';
    return (!term||hay.includes(term))&&(!region||source.region===region)&&(!state||(state==='ok'?isOkay(code):state==='problem'?!isOkay(code)&&code!=='not_checked':code==='not_checked'));
  });
}
function renderSources(){const all=statusRows(), visible=sourceViewRows(),checked=all.filter(({status})=>!['not_checked','not_run'].includes(status.status));
  const problems=all.filter(({status})=>!isOkay(status.status)&&!['not_checked','not_run'].includes(status.status));
  $('sourceTotal').textContent=ui.sources.length;$('cnSourceCount').textContent=ui.sources.filter(s=>s.region==='国内').length;
  $('intlSourceCount').textContent=ui.sources.filter(s=>s.region!=='国内').length;
  $('checkedSourceCount').textContent=checked.length;$('sourceProblemCount').textContent=problems.length;
  $('sourceInitializedCount').textContent=ui.crawl.initialized_source_count??checked.filter(({status})=>status.initialized===true).length;
  $('sourcesSummary').textContent=`已配置 ${ui.sources.length} 个来源 · 本轮/历史状态 ${checked.length} 个已轮询 · ${problems.length} 个异常或待适配`;
  $('policySourceGrid').innerHTML=visible.map(({source,status})=>{const code=status.status||'not_checked';const attempts=(status.attempts||[]).filter(x=>x.status==='failed').slice(0,2).map(x=>x.error||'').filter(Boolean);
    const msg=[status.message||status.status_message||'尚无检测详情',...attempts].join(' · ').slice(0,390);
    return `<article class="source-card"><div class="source-card-head"><strong>${outlink(source.url,source.name||'未知来源')}</strong><span class="source-status ${isOkay(code)?'ok':code==='not_checked'?'idle':'warn'}">${esc(labelStatus(code))}</span></div>
      <small>${esc(source.region||'')} · ${esc(source.country||'')} · ${esc(source.organization_type||source.strategy||'')}</small>
      <p>${esc(msg)}</p><small>候选 ${Number(status.found_count||status.accepted||0)} · 链接 ${Number(status.candidate_links||status.links_discovered||0)} · ${esc(status.checked_at?status.checked_at.slice(0,10):'尚未轮询')}</small></article>`;}).join('');
  $('sourceEmpty').classList.toggle('hidden',visible.length>0);
}
function renderDimensions(){$('dimensionsGrid').innerHTML=ui.dimensions.map((d,i)=>`<div class="dimension-item"><span>${String(i+1).padStart(2,'0')}</span><div><strong>${esc(d.name||'法规维度')}</strong><small>${esc(d.description||d.scope||'用于初步分类')}</small></div></div>`).join('');}
async function loadJSON(file,fallback){try{const r=await fetch(`./data/${file}?v=${Date.now()}`,{cache:'no-store'});return r.ok?await r.json():fallback;}catch{return fallback;}}
async function loadAll(){const [policies,registry,statuses,dimensions,crawl,ai,meta]=await Promise.all([
  loadJSON('policies_display.json',[]),loadJSON('policy_source_registry.json',[]),loadJSON('policy_source_status.json',[]),
  loadJSON('regulatory_dimensions.json',[]),loadJSON('policy_crawl_state.json',{}),loadJSON('policy_ai.json',{}),loadJSON('policy_meta.json',{})
]);
  ui.policies=Array.isArray(policies)?policies:[];ui.sources=Array.isArray(registry)?registry:[];ui.statuses=Array.isArray(statuses)?statuses:[];
  ui.dimensions=Array.isArray(dimensions)?dimensions:[];ui.crawl=crawl&&typeof crawl==='object'?crawl:{};ui.ai=ai&&typeof ai==='object'?ai:{};
  selectOptions('policyDimension',ui.dimensions.map(d=>d.name).concat(ui.policies.flatMap(p=>p.dimensions||[])),'全部法规维度');
  const updated=ui.crawl.last_run||meta.last_run_at;
  const when=updated&&!Number.isNaN(Date.parse(updated))?new Date(updated).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})+'（北京时间）':'尚无完整抓取记录';
  $('policyUpdatedAt').textContent=`上次法规采集：${when} · 首次回溯30天，之后重试与增量检查`;
  const n=Object.values(ui.ai.analyses||{}).filter(x=>x.status==='completed').length;
  $('policyAIState').textContent=ui.ai.mode==='optional-ai'?`AI辅助分析已配置 · 缓存 ${n} 条`:'规则辅助初筛 · 尚未配置 AI API';
  renderPolicies();renderSources();renderDimensions();
}
function ready(){['policySearch','policyDays','policyRegion','policyDimension','policyValidity'].forEach(id=>$(id).addEventListener(id==='policySearch'?'input':'change',renderPolicies));
  ['sourceSearch','sourceRegion','sourceStatusFilter'].forEach(id=>$(id).addEventListener(id==='sourceSearch'?'input':'change',renderSources));
  $('policySortLatest').addEventListener('click',()=>{ui.sort='latest';renderPolicies();});
  $('policySortImpact').addEventListener('click',()=>{ui.sort='impact';renderPolicies();});
  loadAll();
}
if(typeof document!=='undefined'){if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ready);else ready();}
if(typeof module!=='undefined')module.exports={esc,safeHref,isoDay,insideDays,isInactive,labelStatus,policyScore};
