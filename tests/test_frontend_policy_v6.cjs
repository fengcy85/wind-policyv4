/* DOM fixture covers original replaceChildren regression and actual policy card contract. */
'use strict';
const assert=require('assert'),fs=require('fs'),vm=require('vm'),path=require('path');
const root=path.resolve(__dirname,'..');
const sources=JSON.parse(fs.readFileSync(path.join(root,'policy_sources.json'),'utf8'));
const dims=JSON.parse(fs.readFileSync(path.join(root,'regulatory_dimensions.json'),'utf8'));
const base={
  id:'a',title:'关于风电机组并网技术规范的通知 <script>BAD</script>',country:'中国',region:'国内',
  source_name:'北京市发展和改革委员会',published_at:'2026-10-10',date_evidence:'官方页面日期',doc_type:'政策候选',
  source_excerpt:'第一条 风力发电机组应当提交并网检测资料。',dimensions:['并网技术规范'],
  url:'https://example.gov.cn/wind-policy',impact_design:'根据第一条需核对低电压穿越软件参数，未确认直接法律义务。',
  impact_business:'核实并网测试周期与交付节点。',importance_score:null,design_relevance:1,
  analysis_method:'规则辅助初筛·待人工核验'
};
const high={...base,id:'b',title:'风机认证规范新公告',published_at:'2026-10-11',url:'https://example.gov.cn/new',
  source_excerpt:'第一条 风电机组认证要求以官方附件为准。',design_relevance:0,dimensions:[],impact_design:'暂未确认'};
const fixtures={
  'policies_display.json':[base,high],
  'policy_source_registry.json':sources,
  'policy_source_status.json':sources.map((s,i)=>({id:s.id,status:i===0?'ok_with_results':'connection_error',found_count:i===0?1:0,initialized:i===0,checked_at:'2026-10-13T00:00:00Z'})),
  'regulatory_dimensions.json':dims,
  'policy_crawl_state.json':{last_run:'2026-10-13T00:00:00Z',initialized_source_count:1},
  'policy_ai.json':{mode:'rule-based-no-api-key',analyses:{}},
  'policy_meta.json':{}
};
const elements=new Map();
function fake(id){
 const handlers={};const classes=new Set();
 return {id,value:(id==='policyDays'?'all':id==='policyValidity'?'active':''),innerHTML:'',textContent:'',handlers,
   classList:{toggle(k,v){if(v)classes.add(k);else classes.delete(k);},contains(k){return classes.has(k)}},
   setAttribute(k,v){this[k]=v},addEventListener(k,cb){handlers[k]=cb},click(){handlers.click?.()},dispatch(k){handlers[k]?.()},
   getAttribute(k){return this[k]}};
}
const document={readyState:'complete',getElementById(id){if(!elements.has(id))elements.set(id,fake(id));return elements.get(id);}};
const fetch=async uri=>{const name=uri.split('/').pop().split('?')[0];return name in fixtures?{ok:true,json:async()=>fixtures[name]}:{ok:false};};
const exposed={exports:{}};
vm.runInNewContext(fs.readFileSync(path.join(root,'site/static/policy.js'),'utf8'),{document,fetch,Date,module:exposed,console,URL});
(async()=>{
 await new Promise(done=>setTimeout(done,35));
 const html=elements.get('policyList').innerHTML;
 for(const field of ['法规原文节选','第一条 风力发电机组应当提交并网检测资料','并网技术规范','产品设计影响分析','最新发布','查看原文']){
  assert(field==='最新发布'?fs.readFileSync(path.join(root,'site/index.html'),'utf8').includes(field):html.includes(field),`missing ${field}`);
 }
 assert(!html.includes('<script>BAD</script>'),'XSS must not be interpreted');
 assert(html.includes('&lt;script&gt;BAD&lt;/script&gt;'));
 assert.strictEqual(String(elements.get('sourceTotal').textContent),String(sources.length));
 assert.strictEqual(String(elements.get('sourceProblemCount').textContent),String(sources.length-1));
 assert.strictEqual(String(elements.get('sourceInitializedCount').textContent),'1');
 assert.strictEqual(String(elements.get('policyCount').textContent),'2');
 assert(elements.get('policySourceGrid').innerHTML.includes('Adilet'));
 assert(elements.get('policyUpdatedAt').textContent.includes('首次回溯30天'));
 assert(html.indexOf('风机认证规范新公告')<html.indexOf('风电机组并网技术规范'),'newest order');
 elements.get('policySortImpact').click();
 const impact=elements.get('policyList').innerHTML;
 assert(impact.indexOf('风电机组并网技术规范')<impact.indexOf('风机认证规范新公告'),'design relevance sort');
 elements.get('policySearch').value='xyz-no-match';elements.get('policySearch').dispatch('input');
 assert(elements.get('policyEmpty').classList.contains('hidden')===false,'filter should show empty state');
 assert.strictEqual(exposed.exports.safeHref('javascript:alert(1)'),'');
 assert.strictEqual(exposed.exports.isoDay('2026-02-30'),'');
 assert.strictEqual(exposed.exports.insideDays('2026-10-01','14',new Date('2026-10-13T00:00:00Z')),true);
 assert.strictEqual(exposed.exports.insideDays('2026-09-29','14',new Date('2026-10-13T00:00:00Z')),false);
 const index=fs.readFileSync(path.join(root,'site/index.html'),'utf8');
 const news=fs.readFileSync(path.join(root,'site/news.html'),'utf8');
 assert(index.includes('href="./news.html"')&&news.includes('href="./index.html"'));
 console.log(`FRONTEND POLICY PASS: ${sources.length} sources, two pages, quote/analysis, sorting, filters, safe links & XSS.`);
})().catch(err=>{console.error(err);process.exitCode=1;});
