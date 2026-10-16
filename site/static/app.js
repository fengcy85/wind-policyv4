/* Wind Policy Watch — industry news, using the existing 16 public news sources. */
'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safeHref = value => {try{const raw=String(value||'').trim();if(!/^https?:\/\//i.test(raw))return '';const u=new URL(raw);return ['http:','https:'].includes(u.protocol)?u.href:'';}catch{return '';}};
const link = (url,title,cls='') => {const u=safeHref(url);return u?`<a class="${esc(cls)}" href="${esc(u)}" rel="noopener noreferrer" target="_blank">${esc(title)} <span aria-hidden="true">↗</span></a>`:`<span>${esc(title)}</span>`;};
const day = v => /^\d{4}-\d{2}-\d{2}$/.test(String(v||''))?String(v):'';
const isRecent = (d,days,now=new Date()) => {if(days==='all')return true;if(!day(d))return false;
  const current=new Date(now.getTime()+8*3600000).toISOString().slice(0,10);
  const delta=Math.round((Date.parse(current+'T00:00:00Z')-Date.parse(day(d)+'T00:00:00Z'))/86400000);
  return delta>=0&&delta<Number(days);};
const news={items:[],focus:[],statuses:[],sources:[],meta:{},sort:'latest'};
async function fetchJSON(name,fallback){try{const response=await fetch(`./data/${name}?v=${Date.now()}`,{cache:'no-store'});return response.ok?await response.json():fallback;}catch{return fallback;}}
function selectOptions(id, values,label){const node=$(id),chosen=node.value;const filtered=[...new Set(values.filter(Boolean))];
  node.innerHTML=`<option value="">${esc(label)}</option>`+filtered.sort((a,b)=>String(a).localeCompare(String(b),'zh-CN')).map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');
  node.value=filtered.includes(chosen)?chosen:'';
}
function itemCard(r, compact=false){const tags=(r.tags||[]).slice(0,4).map(tag=>`<span class="tag">${esc(tag)}</span>`).join('');
  const headline=r.translated_title||r.title||'暂无标题';const subtitle=r.translated_title&&r.title&&r.title!==r.translated_title?`<p class="news-english">${esc(r.title)}</p>`:'';
  const score=Number(r.strategic_score||0);
  const text=String(r.excerpt||'').replace(/\s+/g,' ').trim();
  const blocked=/verification successful|security service|cloudflare|access denied|javascript required|latest news|privacy policy|cookie consent/i.test(text);
  const excerpt=!compact&&!blocked&&text.length>40?`<p class="news-excerpt">${esc(text.slice(0,185))}${text.length>185?'…':''}</p>`:'';
  return `<article class="news-card"><div class="news-card-top"><span class="news-date">${esc(day(r.published_at)||'发布日期待核实')}</span><span>${esc(r.country||'地区待核实')}</span><span>${esc(r.source_name||'来源待核实')}</span></div>
    <h3>${link(r.url,headline,'title-link')}</h3>${subtitle}${excerpt}<div class="news-card-foot"><div class="tag-row">${tags}</div>${link(r.url,'查看资讯原文','source-link')}</div></article>`;
}
function filtered(){const q=$('searchInput').value.trim().toLocaleLowerCase(),tag=$('tagFilter').value,country=$('countryFilter').value,source=$('sourceFilter').value,days=$('daysFilter').value;
  return news.items.filter(n=>{const hay=[n.title,n.translated_title,n.source_name,n.country,...(n.tags||[])].join(' ').toLocaleLowerCase();
    return (!q||hay.includes(q))&&(!tag||(n.tags||[]).includes(tag))&&(!country||n.country===country)&&(!source||n.source_name===source)&&isRecent(n.published_at,days);}).sort((a,b)=>{
      if(news.sort==='score'){const rank=Number(b.strategic_score||0)-Number(a.strategic_score||0);if(rank)return rank;}
      return (b.published_at||'').localeCompare(a.published_at||'')||String(a.title||'').localeCompare(String(b.title||''));
    });
}
function render(){const items=filtered();$('newsList').innerHTML=items.slice(0,120).map(n=>itemCard(n)).join('');
  $('emptyState').classList.toggle('hidden',items.length>0);
  $('resultInfo').textContent=`当前 ${items.length} 条 · 行业监测历史库 ${news.items.length} 条`+(items.length>120?' · 展示前120条，可收窄筛选':'');
  $('newsSortLatest').classList.toggle('active',news.sort==='latest');$('newsSortScore').classList.toggle('active',news.sort==='score');
  $('newsSortLatest').setAttribute('aria-pressed',String(news.sort==='latest'));$('newsSortScore').setAttribute('aria-pressed',String(news.sort==='score'));
}
function renderFocus(){const unique=new Set(),rows=news.focus.filter(n=>{
  if(!safeHref(n.url)||unique.has(n.url))return false;unique.add(n.url);return true;
});
  $('focusList').innerHTML=rows.slice(0,8).map(n=>itemCard(n,true)).join('');
  $('focusInfo').textContent=`${rows.length} 条本周重点 · 招标、市场机制、竞对与并网动态`;
  $('focusEmpty').classList.toggle('hidden',rows.length>0);
}
function renderSources(){const rows=news.statuses;let ok=0,bad=0;const cards=rows.map(s=>{const success=s.status==='success',quiet=s.status==='no_news';if(success)ok++;if(!success&&!quiet)bad++;
   const attempted=(s.attempts||[]).filter(x=>x.ok===false).slice(0,2).map(x=>x.error||'').filter(Boolean);
   const details=[s.error||'',...attempted].filter(Boolean).join(' · ').slice(0,320);
   return `<article class="source-card"><div class="source-card-head"><strong>${esc(s.name||s.id||'来源')}</strong><span class="source-status ${success?'ok':quiet?'idle':'warn'}">${esc(success?'正常':quiet?'本轮无新增':s.status||'异常')}</span></div>
     <small>${esc(s.country||'')} · ${esc(s.role||'行业来源')}</small><p>${esc(details||`本轮保留 ${Number(s.found_count||0)} 条候选。`)}</p></article>`;});
  $('sourceGrid').innerHTML=cards.join('');$('newsSourceSummary').textContent=`配置 ${rows.length} 个新闻来源 · 本轮成功 ${ok} 个 · 异常 ${bad} 个`;
  $('successCount').textContent=ok;$('errorCount').textContent=bad;
}
async function init(){const [items,focus,meta,statuses]=await Promise.all([
  fetchJSON('news.json',[]),fetchJSON('weekly_focus.json',{}),fetchJSON('meta.json',{}),fetchJSON('source_status.json',[])]);
  news.items=Array.isArray(items)?items:[];news.focus=Array.isArray(focus.items)?focus.items:[];news.meta=meta||{};
  news.statuses=Array.isArray(statuses)?statuses:[];
  selectOptions('tagFilter',news.items.flatMap(n=>n.tags||[]),'全部行业标签');
  selectOptions('countryFilter',news.items.map(n=>n.country),'所有国家/地区');
  selectOptions('sourceFilter',news.items.map(n=>n.source_name),'所有资讯来源');
  $('totalCount').textContent=news.items.length;$('weekCount').textContent=news.items.filter(n=>isRecent(n.published_at,'7')).length;
  const when=meta.finished_at||meta.started_at;
  $('lastRun').textContent=when&&!Number.isNaN(Date.parse(when))?`上次行业采集：${new Date(when).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}（北京时间）`:'尚无完整行业采集记录';
  render();renderFocus();renderSources();
}
function ready(){['searchInput','tagFilter','countryFilter','sourceFilter','daysFilter'].forEach(id=>$(id).addEventListener(id==='searchInput'?'input':'change',render));
  $('newsSortLatest').addEventListener('click',()=>{news.sort='latest';render();});
  $('newsSortScore').addEventListener('click',()=>{news.sort='score';render();});
  init();
}
if(typeof document!=='undefined'){if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',ready);else ready();}
if(typeof module!=='undefined')module.exports={esc,safeHref,isRecent};
