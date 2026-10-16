'use strict';
const assert=require('assert'),fs=require('fs'),vm=require('vm'),path=require('path');
const root=path.resolve(__dirname,'..');
const now=new Date();const today=new Date(now.getTime()+8*3600000).toISOString().slice(0,10);
const rows=[
 {title:'Wind turbine market rules',translated_title:'风电机组市场规则',published_at:today,source_name:'WindEurope',country:'欧洲',url:'https://windeurope.org/news/test',tags:['市场机制'],strategic_score:5},
 {title:'Big offshore wind tender',published_at:today,source_name:'WindEurope',country:'欧洲',url:'https://windeurope.org/news/other',tags:['招标采购'],strategic_score:30},
 {title:'Unsafe script',published_at:today,source_name:'Bad',country:'全球',url:'javascript:alert(1)',tags:['竞对资讯'],strategic_score:10}
];
const d={
 'news.json':rows,'weekly_focus.json':{items:rows.slice(0,2)},'meta.json':{finished_at:new Date().toISOString()},
 'source_status.json':[{status:'success',id:'wind',name:'WindEurope',country:'欧洲',found_count:2},{status:'error',id:'other',name:'Other',error:'timeout'}],
 'source_sources.json':[]
};
const map=new Map();function fake(id){const handlers={};const classes=new Set();return {value:id==='daysFilter'?'90':'',textContent:'',innerHTML:'',handlers,
 setAttribute(k,v){this[k]=v},addEventListener(k,cb){handlers[k]=cb},click(){handlers.click?.()},dispatch(k){handlers[k]?.()},classList:{toggle(k,v){v?classes.add(k):classes.delete(k)},contains(k){return classes.has(k)}}};}
const document={readyState:'complete',getElementById(id){if(!map.has(id))map.set(id,fake(id));return map.get(id)}};
const exposed={exports:{}};const fetch=async url=>{const filename=url.split('/').pop().split('?')[0];return filename in d?{ok:true,json:async()=>d[filename]}:{ok:false}};
vm.runInNewContext(fs.readFileSync(path.join(root,'site/static/app.js'),'utf8'),{document,Date,fetch,URL,module:exposed,console});
(async()=>{
 await new Promise(ok=>setTimeout(ok,35));
 assert.strictEqual(String(map.get('totalCount').textContent),'3');
 assert.strictEqual(String(map.get('successCount').textContent),'1');
 assert(map.get('newsList').innerHTML.includes('风电机组市场规则'));
 assert(!map.get('newsList').innerHTML.includes('href="javascript:alert(1)"'));
 map.get('newsSortScore').click();
 assert(map.get('newsList').innerHTML.indexOf('Big offshore wind tender')<map.get('newsList').innerHTML.indexOf('风电机组市场规则'));
 map.get('tagFilter').value='市场机制';map.get('tagFilter').dispatch('change');
 assert(map.get('resultInfo').textContent.includes('当前 1 条'));
 assert.strictEqual(exposed.exports.safeHref('data:text/html,evil'),'');
 console.log('FRONTEND NEWS PASS: data loading, weekly focus, real-time search, score sorting and URL sanitization.');
})().catch(err=>{console.error(err);process.exitCode=1});
