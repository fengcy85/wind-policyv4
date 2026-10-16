"""Wind Monitor V7 province-first: independent site adapters, checkpoints and daily retries.

No CAPTCHA solving, login bypass, access-control circumvention, invented evidence or
speculative legal scores. A successfully fetched home page is not a verified crawl.
"""
from __future__ import annotations
import argparse
import copy
import concurrent.futures as futures
import csv
import hashlib
import io
import json
import logging
import os
import re
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from adapters.registry import load_adapter
from policy_transport import DOMAIN_GATE, classify_error, primary_failure
from policy_provincial import (MEDIA_SOURCE_ID, province_from_title,
    plausible_wind_policy, parse_bjx_policy_directory, official_link_candidates,
    export_province_report, province_of, RENEWABLE, POLICY)
from policy_structured_discovery import discover_repeating_rows

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'site' / 'data'
DATA.mkdir(parents=True, exist_ok=True)
SOURCES = ROOT / 'policy_sources.json'
DIMS = ROOT / 'regulatory_dimensions.json'
SCORES = ROOT / 'reviewed_policy_scores.json'
POLICIES = DATA / 'policies.json'
STATUSES = DATA / 'policy_source_status.json'
CANDIDATES = DATA / 'policy_candidates_review.json'
STATE = DATA / 'policy_crawl_state.json'
CHECKPOINTS = DATA / 'policy_source_checkpoints.json'
DETAIL_QUEUE = DATA / 'policy_detail_retry_queue.json'
MAX_DETAILS = max(1, min(int(os.getenv('POLICY_DETAILS_PER_SOURCE','24')),90))
MAX_LIST_PAGES = max(1, min(int(os.getenv('POLICY_LIST_PAGES','8')),30))
MAX_WORKERS = max(1,min(int(os.getenv('POLICY_WORKERS','4')),8))
TIMEOUT = max(3.0,min(float(os.getenv('POLICY_REQUEST_TIMEOUT','14')),35.0))
BROWSER_ENABLED = os.getenv('POLICY_BROWSER_FALLBACK','1') == '1'
LOG = logging.getLogger('policy-v7')
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
_thread = threading.local()

WIND = re.compile(r'风(?:力)?电|风光|风[、，和与/]光|风场|海风|风力发电|风机|风力发电机组|风电机组|wind[ -]?(?:power|energy|farm|turbine|generation)|offshore wind|onshore wind|e[oó]lica|éolien|eolico|r[uü]zgar|điện gió|ветр',re.I)
NORM = re.compile(r'法规|政策|条例|办法|规定|规范|规章|法律|通知|公告|公示|申报|竞配|竞价|项目清单|指标|核准|批复|细则|意见|指南|规划|标准|认证|政府采购|招投标|招标|并网|电价|环评|管制|细则|条款|准入|grid code|policy|regulat|standard|act\b|decree|law\b|tender|resolution|directive',re.I)
BUSINESS = re.compile(r'风电|可再生能源|新能源|电力|电网|输电|并网|型式认证|电气设备|制造业|发电机|本地化|原产地|外资|贸易|海洋工程|关税|招标|采购|能源|供应链|投资|environmental|electricity|renewable|energy|power|grid|market access|local content|manufactur|certific|supply chain',re.I)
EXCLUDE = re.compile(r'^(首页|更多|点击|返回|上一页|下一页|信息公开|政府信息公开|政策解读|通知公告|联系我们|关于我们|动态|更多信息|免责声明)$',re.I)
DATE = re.compile(r'(?<!\d)(20[1-3]\d)[-./年](0?[1-9]|1[0-2])[-./月](0?[1-9]|[12]\d|3[01])日?(?!\d)')
CLAUSE = re.compile(r'(第[一二三四五六七八九十百零〇0-9]+条|Article\s+\d{1,3}[A-Za-z]?|第[一二三四五六七八九十百0-9]+款)',re.I)
ISSUE = re.compile(r'(征求意见|征求公众意见|草案|公开征求|consultation|draft)',re.I)
EXPIRED = re.compile(r'(失效|废止|已废止|被替代|repealed|revoked|expired)',re.I)
SKIPFILE = re.compile(r'\.(?:png|jpg|jpeg|gif|webp|svg|css|js|zip|rar|doc|docx|xls|xlsx|mp4|ico)(?:$|\?)',re.I)
PDF = re.compile(r'\.pdf(?:$|\?)',re.I)
RECOMMENDED = re.compile(r'推荐性|GB/T|guideline|voluntary',re.I)

# Dimension term groups correspond exactly to the 18 dimension names in original xlsx.
TERMS = [
 ['市场准入','外资','投资限制','准入许可','foreign investment','market access'],
 ['本地化','原产地','本地制造','国产化','local content','localization'],
 ['风机设计','风力发电机组','技术标准','认证','IEC 61400','型式试验','产品标准','testing'],
 ['电网建设','输电','升压站','接入容量','送出','grid connection','transmission'],
 ['并网','低电压穿越','高电压穿越','故障穿越','无功','频率响应','grid code','lvrt'],
 ['电价','新能源开发','可再生能源规划','绿证','ppa','cfd','feed-in tariff','market mechanism'],
 ['招标','投标','采购','供应商资格','bidding','tender','procurement'],
 ['关税','贸易救济','税收','反补贴','反倾销','tariff','tax','anti-dumping'],
 ['大件运输','超限','道路运输','港口吊装','物流','运输许可','logistics'],
 ['环评','生态保护','土地','噪声','鸟类','海域使用','environmental impact','permit'],
 ['航空','雷达','国防','净空','障碍灯','radar','aviation'],
 ['台风','雷击','防腐','沙尘','耐低温','极端风','环境适应','climate condition'],
 ['网络安全','数据安全','scada','数据出境','cybersecurity'],
 ['安全生产','职业安全','消防','施工安全','劳动保护','occupational safety'],
 ['海上风电','海底电缆','海上风机','海洋工程','offshore wind'],
 ['绿色金融','项目融资','担保','贷款','finance','bank guarantee'],
 ['运维','质保','退役','回收','维修','operation and maintenance','decommissioning'],
 ['碳足迹','ESG','供应链','碳排放','碳核算','绿色采购','carbon footprint'],
]
DESIGN_DIMS={2,4,8,10,11,12,13,14,16}
BUSINESS_DIMS={0,1,3,5,6,7,8,9,14,15,16,17}
ADAPTERS={
 'gov_search':['https://www.gov.cn/zhengce/zhengceku/','https://www.gov.cn/zhengce/zuixin/'],
 'gov_document_library':['https://www.gov.cn/zhengce/zhengceku/','https://www.gov.cn/zhengce/zuixin/'],
 'iea_policy_search':['https://www.iea.org/search/policies?q=wind'],
 'samr_standard_search':['https://std.samr.gov.cn/gb/gbQuery.National','https://std.samr.gov.cn/gb/search/gbAdvancedSearch?type=std'],
 'samr_fulltext_search':['https://openstd.samr.gov.cn/bzgk/std/std_list','https://openstd.samr.gov.cn/bzgk/gb/std_list'],
 'nmg_drc_iframe':[],
 'nmg_energy_iframe':[],
}

def read(path,default):
 try:return json.loads(Path(path).read_text(encoding='utf-8'))
 except (OSError,ValueError):return default

def save(path,data):
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
 tmp=p.with_suffix(p.suffix+'.tmp')
 tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 tmp.replace(p)

def clean(x):return re.sub(r'\s+',' ',str(x or '')).strip()
def clock():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def normalize_url(url):
 try:
  p=urlsplit(url)
  if p.scheme not in ('https','http') or not p.hostname or p.username or p.password:return ''
  if p.hostname.lower() in ('localhost','127.0.0.1','0.0.0.0') or p.hostname.endswith('.local'):return ''
  return urlunsplit((p.scheme,p.netloc,p.path or '/',p.query,''))
 except ValueError:return ''
def same_site(a,b):
 x=(urlsplit(a).hostname or '').removeprefix('www.').lower()
 y=(urlsplit(b).hostname or '').removeprefix('www.').lower()
 return bool(x and y and (x==y or x.endswith('.'+y) or y.endswith('.'+x) or
   (x.endswith('.gov.cn') and y=='gov.cn') or (y.endswith('.gov.cn') and x=='gov.cn')))

def allowed_detail_link(entry, candidate, adapter):
 """Permit same-government site, or a source-declared exact public mirror host.

 Not a general suffix/redirect exception; user supplied explicit mirrors only.
 """
 if same_site(entry,candidate):return True
 try: host=(urlsplit(candidate).hostname or '').lower()
 except ValueError:return False
 return bool(host and host in set(adapter.config.get('allowed_detail_hosts') or []))

def session():
 if not hasattr(_thread,'s'):
  s=requests.Session()
  s.headers.update({'User-Agent':'WindPolicyMonitor/6.2 (public policy indexing; contact repository maintainer)',
     'Accept':'text/html,application/xhtml+xml,application/pdf,*/*;q=0.2',
     'Accept-Language':'zh-CN,zh;q=0.9,en;q=0.7'})
  # Retry only transient errors. In particular 403/404/412 are never retried.
  retry=Retry(total=1,connect=1,read=1,status=1,backoff_factor=1,
              status_forcelist=[429,500,502,503,504],
              allowed_methods=frozenset(['GET']),
              respect_retry_after_header=True,raise_on_status=False)
  s.mount('https://',HTTPAdapter(max_retries=retry,pool_connections=8,pool_maxsize=8))
  s.mount('http://',HTTPAdapter(max_retries=retry,pool_connections=8,pool_maxsize=8))
  _thread.s=s
 return _thread.s

def fetch(url):
 # Global host gate covers all threads and per-source entry/detail requests.
 with DOMAIN_GATE.lease(url):
  r=session().get(url,timeout=(min(TIMEOUT,9),TIMEOUT),allow_redirects=True)
  r.raise_for_status()
  if not normalize_url(r.url):raise ValueError('invalid final URL')
  if len(r.content)>7_000_000:raise ValueError('response too large')
  ct=r.headers.get('Content-Type','').lower()
  if 'pdf' in ct or PDF.search(r.url):
   from pypdf import PdfReader
   pdf=PdfReader(io.BytesIO(r.content),strict=False)
   body='\n'.join(p.extract_text() or '' for p in pdf.pages[:20])
   if len(body)<120:raise ValueError('PDF lacks extractable text; needs manual/OCR review')
   return clean(body)[:30000],r.url,'pdf'
  if 'html' not in ct and 'text' not in ct and not r.content.lstrip().startswith(b'<'):
   raise ValueError('unsupported document type: '+ct[:70])
  if not r.encoding or r.encoding.lower() in ('iso-8859-1','ascii'):
   r.encoding=r.apparent_encoding or 'utf-8'
  return r.text,r.url,'html'

def browser_fetch(url, adapter=""):
 """Render public page normally; no anti-bot bypass / stealth or authenticated access."""
 from playwright.sync_api import sync_playwright
 with DOMAIN_GATE.lease(url), sync_playwright() as p:
  browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
  try:
   page=browser.new_page(locale='zh-CN',user_agent='WindPolicyMonitor/6.1 (public compliance monitoring)')
   response=page.goto(url,wait_until='domcontentloaded',timeout=30000)
   page.wait_for_timeout(1500)
   # Seven named portal adapters. Use only public UI, not guessed or private APIs.
   configurations={
    'gov_search':{'term':'风电','inputs':('input[name=q]','input[placeholder*=政策]','input[placeholder*=关键词]','input[type=search]'),'buttons':('button:has-text("搜索")','button:has-text("检索")')},
    'gov_document_library':{'term':'风力发电','inputs':('input[placeholder*=政策]','input[name=q]','input[placeholder*=关键词]','input[type=search]'),'buttons':('button:has-text("检索")','button:has-text("搜索")')},
    'samr_standard_search':{'term':'风力发电机组','inputs':('input[placeholder*=标准]','input[placeholder*=编号]','input[type=search]'),'buttons':('button:has-text("查询")','button:has-text("检索")')},
    'samr_fulltext_search':{'term':'风力发电机组','inputs':('input[placeholder*=标准号]','input[placeholder*=标准名称]','input[placeholder*=检索]'),'buttons':('button:has-text("在结果中筛选")','button:has-text("检索")')},
    'nmg_drc_iframe':{'term':'风电','inputs':('input[placeholder*=关键词]','input[placeholder*=搜索]'),'buttons':('button:has-text("搜索")',)},
    'nmg_energy_iframe':{'term':'风电','inputs':('input[placeholder*=关键词]','input[placeholder*=搜索]'),'buttons':('button:has-text("搜索")',)},
   }
   # Generic official public-search UI for any configured source; do not guess APIs.
   if re.fullmatch(r'(?:cn|intl)_[a-f0-9]{12}',str(adapter)):
    try:
     from importlib import import_module
     profile=import_module('adapters.sites.'+adapter).PROFILE
     if profile.get('needs_browser_ui'):
      configurations[adapter]={'term':profile.get('ui_search_term') or '风电',
       'inputs':('input[placeholder*=检索]','input[placeholder*=搜索]',
                 'input[placeholder*=关键词]','input[type=search]',
                 'input[placeholder*=政策]','input[placeholder*=标准]'),
       'buttons':('button:has-text(搜索)','button:has-text(检索)',
                  'button:has-text(查询)','input[type=submit]')}
    except (ImportError,AttributeError):pass
   if adapter=='iea_policy_search':
    # The public IEA wind policy index already encodes q=wind in its URL.
    try:page.locator('a[href*="/policies/"]').first.wait_for(timeout=2500)
    except Exception:pass
   elif adapter in configurations:
    opts=configurations[adapter]
    opts['inputs']+=('input[type=text]',)
    for selector in opts['inputs']:
     try:
      node=page.locator(selector).first
      if node.count() and node.is_visible(timeout=400):
       node.fill(opts['term'],timeout=1500)
       clicked=False
       for button in opts['buttons']:
        try:
         b=page.locator(button).first
         if b.count() and b.is_visible(timeout=400):
          b.click(timeout=1300);clicked=True;break
        except Exception:continue
       if not clicked:node.press('Enter',timeout=1300)
       page.wait_for_timeout(1200)
       break
     except Exception:continue
   status=response.status if response else None
   if status and status>=400:raise ValueError('browser HTTP '+str(status))
   return page.content(),page.url,'html'
  finally:browser.close()

def parse_date(x):
 raw=str(x or '')
 # Chinese official lists commonly abbreviate 2026-10-08 as 26-10-08.
 # Only accept the unambiguous YY-MM-DD sequence, years 2020--2039.
 short=re.search(r'(?<![\d/])(2[0-9]|3[0-9])[-./](0?[1-9]|1[0-2])[-./](0?[1-9]|[12]\d|3[01])(?!\d)',raw)
 if short:
  try:return date(2000+int(short.group(1)),int(short.group(2)),int(short.group(3))).isoformat()
  except ValueError:return ''
 # Official foreign portals may use dd/mm/yyyy, dd-mm-yyyy or month-name formats.
 # Demand a full day+month+year to avoid deriving fictional dates from year-only text.
 slash=re.search(r'(?<!\d)([0-3]?\d)[./-]([01]?\d)[./-](20[1-3]\d)(?!\d)',raw)
 if slash:
  try:return date(int(slash.group(3)),int(slash.group(2)),int(slash.group(1))).isoformat()
  except ValueError:return ''
 month_names={name:i for i,names in enumerate(('jan january','feb february','mar march','apr april','may','jun june','jul july','aug august','sep september','oct october','nov november','dec december'),1) for name in names.split()}
 month_re='(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
 month_first=re.search(r'(?<!\w)('+month_re+r')\s+([0-3]?\d),?\s+(20[1-3]\d)\b',raw,re.I)
 day_first=re.search(r'(?<!\w)([0-3]?\d)\s+('+month_re+r')\s+(20[1-3]\d)\b',raw,re.I)
 picked=month_first or day_first
 if picked:
  parts=picked.groups()
  mth=parts[0] if month_first else parts[1]
  day=parts[1] if month_first else parts[0]
  year=parts[-1]
  try:return date(int(year),month_names[mth[:3].lower()],int(day)).isoformat()
  except (ValueError,KeyError):return ''
 m=DATE.search(raw)
 if m:
  try:return date(int(m.group(1)),int(m.group(2)),int(m.group(3))).isoformat()
  except ValueError:return ''
 m=re.search(r'(?<!\d)(20[1-3]\d)-(\d\d)-(\d\d)T',str(x or ''))
 return parse_date('-'.join(m.groups())) if m else ''

def publication_date(html,text=''):
 soup=BeautifulSoup(html,'html.parser') if html.lstrip().startswith('<') else None
 hints=[]
 if soup:
  for tag in soup.select('meta[property="article:published_time"],meta[name="pubdate"],meta[name="publishdate"],meta[name="date"],time[datetime],.pubtime,.pubDate,.publish_time,.date,.time')[:16]:
   hints.append(tag.get('content') or tag.get('datetime') or tag.get_text(' ',strip=True))
  for node in soup.find_all(string=re.compile(r'发布(?:日期|时间)|发布日期|Publication Date|Published on',re.I),limit=8):
   hints.append(clean(node.parent.get_text(' ',strip=True))[:150])
 hints.append(text[:350])
 for t in hints:
  d=parse_date(t)
  if d:return d
 return ''

def extract_detail(body,kind,selectors=None):
 if kind=='pdf':return '',clean(body)
 soup=BeautifulSoup(body,'html.parser')
 for tag in soup(['script','style','nav','footer','header','aside','form']):tag.decompose()
 h=soup.find('h1')
 title=clean(h.get_text(' ',strip=True)) if h else ''
 options=[]
 for sel in dict.fromkeys(list(selectors or [])+['article','#UCAP-CONTENT','.TRS_Editor','#zoom','.article-content','.article','#content','.wenzhang','.content','main']):
  for node in soup.select(sel)[:4]:
   t=clean(node.get_text(' ',strip=True))
   if len(t)>120:options.append((len(t),t))
 viable=[(l,t) for l,t in options if l<22000]
 txt=max(viable,key=lambda x:x[0])[1] if viable else clean((soup.body or soup).get_text(' ',strip=True))
 return title,txt[:30000]

def parse_listing(html,base):
 soup=BeautifulSoup(html,'html.parser');links=[];seen=set()
 for a in soup.select('a[href]'):
  t=clean(a.get_text(' ',strip=True)) or clean(a.get('title'))
  if not 7<=len(t)<=190 or EXCLUDE.fullmatch(t):continue
  if not (NORM.search(t) or WIND.search(t) or BUSINESS.search(t)):continue
  u=normalize_url(urljoin(base,a.get('href','')))
  if not u or u in seen or not same_site(base,u) or u==normalize_url(base) or SKIPFILE.search(u):continue
  seen.add(u)
  parent=a.find_parent(['li','tr']) or a.parent
  local=clean(parent.get_text(' ',strip=True))[:350] if parent else ''
  d=parse_date(local)
  score=6*bool(WIND.search(t))+3*bool(NORM.search(t))+int(bool(BUSINESS.search(t)))
  links.append({'title':t,'url':u,'date':d,'rank':score})
 links.sort(key=lambda x:(x['date'],x['rank']),reverse=True)
 return links

def find_next_pages(html,url):
 soup=BeautifulSoup(html,'html.parser');out=[]
 for a in soup.select('a[href]'):
  t=clean(a.get_text(' ',strip=True))
  if t in ('下一页','下页','Next','next','2','3') or a.get('rel')==['next']:
   u=normalize_url(urljoin(url,a.get('href','')))
   if u and same_site(url,u) and u!=url and u not in out:out.append(u)
 return out[:max(0,MAX_LIST_PAGES-1)]

def get_dim_refs(text,dims):
 t=clean(text).lower();score=[]
 for i,(d,terms) in enumerate(zip(dims,TERMS)):
  hits=[k for k in terms if k.lower() in t]
  if hits:score.append((i,min(3,len(hits)),d['name'],hits))
 score.sort(key=lambda x:x[1],reverse=True)
 return score[:5]

def clause_slices(text):
 # Limit to passages containing actual requirement; never fabricate clause numbers.
 sentences=re.split(r'(?<=[。；;\.!?])\s*|\n+',text)
 candidates=[]
 for sentence in sentences:
  sentence=clean(sentence)
  if len(sentence)<35 or len(sentence)>2300:continue
  if (WIND.search(sentence) or BUSINESS.search(sentence)) and (NORM.search(sentence) or re.search(r'应当|必须|不得|要求|实施|适用于| shall | must ',sentence,re.I)):
   candidates.append(sentence)
 if not candidates and len(text)>=130:candidates=[clean(text[:600])]
 return candidates[:4]

def importance(scores,evidence):
 if not isinstance(scores,dict):return {'status':'证据不足，待条款级评分','D':None,'B':None,'C':None,'A':None,'U':None,'score':None,'priority':None,'reason':'缺少经核实的企业适用范围、法律后果及最迟行动日期'}
 values={k:scores.get(k) for k in 'DBCAU'}
 if not all(type(v)==int and 0<=v<=5 for v in values.values()) or not clean(scores.get('evidence')):
  return {'status':'证据不足，待条款级评分',**{k:(v if type(v)==int and 0<=v<=5 else None) for k,v in values.items()},'score':None,'priority':None,'reason':'缺少经核实的五维分数或出处'}
 v=6*values['D']+5*values['B']+4*values['C']+3*values['A']+2*values['U']
 level='P0' if v>=85 else 'P1' if v>=70 else 'P2' if v>=50 else 'P3' if v>=30 else 'P4'
 # Key-block override requires four separate verified boolean fields and cited evidence.
 override=all(scores.get(k) is True for k in ('key_block_verified','business_applies_verified','within_90_days_verified','legal_effect_verified'))
 return {'status':'人工核验评分','score':v,'priority':'P0' if override else level,'base_priority':level,'override':override,**values,'reason':clean(scores['evidence'])[:300]}

# These business-response paths are possible operational checks, never asserted legal duties.
# Every final impact must be traced to the quoted clause and a verified affected entity.
IMPACT_PATHS=[
 ('核对整机及关键零部件的市场认证、许可和技术文件', '核实销售主体、当地代理及准入许可对订单交付的限制', '国际销售、法务与合规、认证与测试'),
 ('核对本地制造零件的技术一致性、质量保证及追溯要求', '核实本地采购比例、建厂、产地证明及投标报价假设', '制造与本地化、供应链与采购、国际销售'),
 ('比对机组设计载荷、部件标准、型式试验报告和认证文件', '复核认证周期、第三方检测费用及客户准入要求', '产品研发、认证与测试、国际销售'),
 ('确认并网配套设备、线路接口及投运条件是否影响交付', '核对电网建设节点对销售回款、施工与交付计划的影响', '电气与控制、项目开发、项目交付'),
 ('复核故障穿越、无功、频率响应及控制软件是否需适配', '核对并网测试责任、接入确认、认证时间及合同里程碑', '电气与控制、认证与测试、国际销售'),
 ('确认是否存在机组效率、计量或调度相关技术条件', '核查绿证、电价、PPA、招标收益测算对客户采购的间接影响', '市场战略、国际销售、项目开发'),
 ('核对投标技术规范、质保测试证明及适用认证要求', '核查供应商资格、评标条件、价格及交付承诺', '国际销售、市场战略、法务与合规'),
 ('确认出口产品编码、材料原产地及认证文件一致性', '核查关税、税率、贸易救济对到岸成本及价格策略的影响', '国际销售、供应链与采购、财务与融资'),
 ('核对风机叶片、塔筒及运输包装的尺寸重量边界', '核查超限运输许可、港口与道路路线、保险及交期', '物流与交付、产品研发、项目开发'),
 ('核对噪声、叶片生态影响和环境监测的设计接口', '核实环评、用地海域和环境许可对项目选址及交付节点的影响', '产品研发、项目开发、法务与合规'),
 ('核查塔高、航标灯、雷达兼容及工程布置需求', '核实航空净空、雷达审批是否限制可销售机型或项目选址', '产品研发、电气与控制、项目开发'),
 ('检查极端风、低温、沙尘、防腐及雷击设计假设', '核查特殊环境型产品定位、成本和质保风险', '产品研发、认证与测试、市场战略'),
 ('复核SCADA、远程运维、数据存储及接口安全控制', '核查数据本地化、网络准入、服务部署及客户合同要求', '电气与控制、运维服务、法务与合规'),
 ('复核安全联锁、施工检修措施及设备技术文件', '核查施工、运维责任划分、人员培训及保险合同', '产品研发、运维服务、法务与合规'),
 ('复核海上机组防腐、海缆接口和船机施工适配', '核查海域使用、施工船期和海上运维服务的交付模式', '产品研发、项目开发、物流与交付'),
 ('确认绿色融资是否要求技术认证或产品信息披露', '核查银行担保、融资条件和项目现金流对客户采购的影响', '财务与融资、国际销售、市场战略'),
 ('复核运维手册、备件、质保周期及退役回收设计', '核查长期运维合同、备件本地化和退役成本承担', '运维服务、产品研发、国际销售'),
 ('复核碳足迹、物料追溯、供应链披露和LCA文档', '核查绿色采购、供应商披露及产品碳足迹对招投标的影响', '供应链与采购、法务与合规、国际销售')
]

def analyze_impact(matched,snippets):
 """Make an evidence-linked, transparently conditional impact chain."""
 lead=matched[0]; idx=lead[0]
 technical,commercial,teams=IMPACT_PATHS[idx]
 passage=snippets[0]['excerpt'] if snippets else ''
 quoted=clean(passage)[:200]
 requirement='官方正文节选：'+quoted
 design='根据“'+quoted[:85]+'…”的文本线索，产品设计核查路径：'+technical+'。是否直接约束整机制造商，待确认。'
 business='根据同一原文线索，商业模式核查路径：'+commercial+'。市场准入或成本后果不能仅凭关键词认定。'
 chain='已获取的条款线索 → 适用主体／实际义务待官方全文核定 → '+technical+'；'+commercial+' → 内部部门开展符合性差距核验。'
 return {'impact_design':design,'impact_business':business,'impact_chain':chain,'impact_evidence':requirement,'affected_entities':'制造商／项目业主／开发商／供应商的直接法律身份待核验','affected_scope':'具体风机类型、陆上/海上、现有/新项目和国家适用范围待核实','consequence':'未从可核实的条款中确认证书、禁售、罚款或并网阻断等具体法律后果','responsible_teams':teams,'uncertainty':'以上为基于关键词定位到原文后的核查路线，不是完成的法律适用性判断。'}

def classify_document(title,text):
 q=title[:150]+' '+text[:600]
 if EXPIRED.search(q):return '历史版本／失效'
 if ISSUE.search(q):return '政策观察／征求意见'
 if RECOMMENDED.search(title) and ('标准' in title or 'GB/T' in title):return '标准（强制性待核验）'
 return '待核验法规候选'

def review_record(src,title,url,reason):
 return {'source_id':src['id'],'source_name':src['name'],'title':title,'url':url,'reason':reason,'checked_at':clock()}

def make_record(src,candidate,html,final,kind,dims,cutoff,manual):
 title,txt=extract_detail(html,kind,load_adapter(src).body_selectors)
 title=title if 7<=len(title)<190 and (WIND.search(title) or NORM.search(title)) else candidate['title']
 pub=publication_date(html,txt) or candidate.get('date','')
 if not pub:return None,'未能证实发布日期（避免把旧法规当近30天）'
 if pub<cutoff.isoformat():return None,'发布日期早于回溯起点'
 if pub>date.today().isoformat():return None,'发布日期晚于运行当天，需人工核验'
 if len(txt)<130:return None,'无法提取法规正文／PDF内容'
 evidence=clause_slices(txt)
 matched=get_dim_refs(' '.join(evidence)+ ' '+title,dims)
 if not matched:return None,'无任何18维度的条款证据'
 # Allow cross-sector regulations, but demand relevant business linkage and substantive policy content.
 if not (WIND.search(txt+' '+title) or (BUSINESS.search(' '.join(evidence)) and NORM.search(txt[:2000]))):
  return None,'尚不能建立风电业务相关影响链条'
 if not (NORM.search(title) or NORM.search(' '.join(evidence))):return None,'无法核实政策规范信号'
 if not evidence:return None,'条款原文证据不足'
 dims_names=[x[2] for x in matched];i=matched[0][0]
 snippets=[]
 for passage in evidence:
  anchor=CLAUSE.search(passage)
  snippets.append({'clause':anchor.group(1) if anchor else '条款编号待核对','excerpt':passage[:380]})
 uid='p_'+hashlib.sha256(final.encode()).hexdigest()[:18]
 anchor=clean(evidence[0])[:180]
 impacts=analyze_impact(matched,snippets)
 if src.get('source_type')=='政策线索':
  # NEVER describe a media excerpt as 'official original' or verified law.
  impacts.update({
   'impact_evidence': '行业媒体报道节选（非官方政策原文）：'+clean(snippets[0]['excerpt'])[:180],
   'impact_design': '仅依据媒体报道发现可能影响风机设计的政策线索；需核对主管机关官方原文后才能分析条款义务。',
   'impact_business': '仅依据媒体报道发现可能影响项目开发的政策线索；具体价格、准入与执行时间以官方原文为准。',
   'impact_chain': '行业媒体线索 → 查找原发布机构与官方文件 → 核对适用范围和效力 → 再判断企业影响。',
   'uncertainty': '没有完成官方政策原文核验；媒体内容不能单独证明法规条款及企业法律义务。',
  })
 scores=manual.get(uid,{})
 # Clause-level scores are accepted only if each clause has separately reviewed evidence.
 reviews=(scores.get('clauses') if isinstance(scores,dict) else {}) or {}
 clause_scores=[]
 for num,clause in enumerate(snippets):
  entry=reviews.get(str(num+1)) or reviews.get(clause['clause']) if isinstance(reviews,dict) else None
  clause_scores.append({'clause':clause['clause'],'excerpt':clause['excerpt'],'importance':importance(entry,[clause])})
 scored=[z['importance'] for z in clause_scores if z['importance']['score'] is not None]
 if scored:
  representative=max(scored,key=lambda x:(-int(x['priority'][1]),x['score'],x['C'],x['U'],x['D'],x['B']))
 else:representative=importance(scores if not reviews and len(snippets)==1 else None,snippets)
 return {
  'id':uid,'title':title,'url':final,'source_id':src['id'],'source_name':src['name'],
  'region':src['region'],'country':src['country'],'province':(province_from_title(title) if src['id']==MEDIA_SOURCE_ID else province_of(src.get('province')) or src.get('province','')),
  'discovery_channel':('professional_media' if src['id']==MEDIA_SOURCE_ID else 'official_site'),
  'linked_official_urls':(official_link_candidates(html,final) if src['id']==MEDIA_SOURCE_ID and kind=='html' else []),
  'published_at':pub,'discovered_at':clock(),
  'doc_type':('行业政策线索（待官方原文核验）' if src.get('source_type')=='政策线索' else classify_document(title,txt)),
  'dimensions':dims_names,'primary_dimension':dims_names[0],
  'source_excerpt':snippets[0]['excerpt'][:340],'clauses':snippets,
  **impacts,'next_step':'核实法律效力、适用主体、条款编号、生效时间、企业目标市场和认证周期后制定应对措施。',
  'importance':representative,'clause_scoring':clause_scores,
  'verification_status':('媒体线索，待官方原文核验；非官方法规原文' if src.get('source_type')=='政策线索' else '待人工复核原文和适用范围'),
  'article_evidence_available':src.get('source_type')!='政策线索',
  'content_hash':hashlib.sha256((title+'\n'+pub+'\n'+'\n'.join(z['excerpt'] for z in snippets)).encode('utf-8')).hexdigest(),
 },''

def listing_only_lead(src,candidate,cutoff,reason='详情未能读取'):
 """Title+publication date evidence is enough to signal a new wind rule.

 This is never represented as a verified law or completed detail crawl. It can be
 replaced by the same URL's full-text record after the next successful visit.
 """
 title=clean(candidate.get('title'))
 published=candidate.get('date') or ''
 url=normalize_url(candidate.get('url') or '')
 # A trusted wind-policy *media category* is a discovery channel even if
 # a general renewable/tariff policy does not spell out 风电 in its heading.
 # Keep such an item as a lead only: never infer its wind applicability without
 # the official publication, and never present it as an authenticated law.
 is_media=src.get('source_type')=='政策线索'
 if is_media:
  in_scope=bool((WIND.search(title) and (NORM.search(title) or RENEWABLE.search(title))) or
                (RENEWABLE.search(title) and POLICY.search(title)))
 else:
  in_scope=bool(WIND.search(title) and NORM.search(title))
 if (not url or not published or published<cutoff.isoformat() or
     published>date.today().isoformat() or not in_scope):
  return None
 excerpt=('政策发布线索：'+title+'。公开目录标注发布日期：'+published+
          '；详细条文未取得，禁止据此认定法律效力、适用义务或产品技术要求。')
 return {'id':'p_'+hashlib.sha256(url.encode()).hexdigest()[:18],
  'title':title,'url':url,'source_id':src['id'],'source_name':src['name'],
  'region':src['region'],'country':src['country'],'province':(province_from_title(title) if src['id']==MEDIA_SOURCE_ID else province_of(src.get('province')) or src.get('province','')),
  'discovery_channel':('professional_media' if src['id']==MEDIA_SOURCE_ID else 'official_site'),
  'linked_official_urls':[],
  'published_at':published,'date_evidence':'来源公开列表日期',
  'discovered_at':clock(),'doc_type':('行业媒体政策发布线索（待核对官方原文）' if
      src.get('source_type')=='政策线索' else '官方政策发布线索（待核验正文）'),
  'source_excerpt':excerpt,'clauses':[],'dimensions':[],
  'impact_design':'只确认公开目录标题及发布日期；没有完整法规条文，不能判断产品设计义务。',
  'impact_business':'只确认公开目录标题及发布日期；应核对政策原文与适用范围。',
  'verification_status':('行业媒体政策线索：'+reason+'；风电适用性与法规效力均待官方原文核验' if
       is_media else '官方目录级线索：'+reason+'；尚未取得完整法规正文'),
  'article_evidence_available':False,'importance':importance(None,[]),
  'next_step':'访问主管机关政策详情，核对法规全文、法律效力及企业适用范围。',
  'content_hash':hashlib.sha256((title+'\n'+published+'\n'+excerpt).encode('utf-8')).hexdigest()}

def adapter_urls(source):
 """Exactly the configured official entries for this site-specific module."""
 adapter=load_adapter(source)
 raw=adapter.entry_urls()
 # Never invent a domain-wide search URL or mistake the homepage for a verified list.
 return list(dict.fromkeys(u for x in raw if (u:=normalize_url(x))))[:5]

def extract_iframes(html,url):
 soup=BeautifulSoup(html,'html.parser');out=[]
 for frm in soup.select('iframe[src],frame[src]'):
  u=normalize_url(urljoin(url,frm.get('src','')))
  if u and same_site(url,u) and u not in out:out.append(u)
 return out[:3]

def _listing_page(html,base,adapter):
 """Read dated document rows separately from wind relevance and page controls.

 A successful HTTP response or arbitrary links never certify a date interval.
 Only the listing's row dates (including unrelated document titles) support a
 chronological boundary; topic filtering happens later for detail downloads.
 """
 if adapter.id == MEDIA_SOURCE_ID:
  return parse_bjx_policy_directory(html,base)
 soup=BeautifulSoup(html,'html.parser')
 anchors=[];selector_hits=[]
 for selector in adapter.list_selectors:
  try: matches=soup.select(selector.replace(':contains(',':-soup-contains('))
  except Exception:continue
  for element in matches:
   a=element if element.name=='a' else element.find('a',href=True)
   if a and a.get('href') and a not in anchors:anchors.append(a)
  if matches:selector_hits.append(selector)
 # A conservative structural detector finds the actual repeated dated rows
 # when a province changes CMS templates. It never fabricates HTTP success or
 # pagination. This complements, rather than replaces, per-site profiles.
 structure=discover_repeating_rows(html,base,parse_date=parse_date,
       normalize_url=normalize_url,allowed_link=lambda a,b:allowed_detail_link(a,b,adapter))
 if structure['confidence']=='repeated_dated_rows' and structure['dated_rows']>=3:
  # A generic selector such as 'ul li a' may include hundreds of menus and
  # footers: favour the cohesive dated document cluster when clearly present.
  if not anchors or len(anchors)>int(structure['rows']*1.5):
   anchors=structure['anchors']
   selector_hits=['runtime_repeated_dated_rows']
 if not anchors:
  anchors=soup.select('main a[href],article a[href],.main a[href],a[href]')
  # A generic fallback only discovers leads, not a verified date interval.
  selector_hits=[]
 links=[];seen=set();dated=0;total=0;undated=0;dates=[];future=0
 trace=[]
 for a in anchors:
  if a.find_parent(['nav','header','footer','aside','menu']):continue
  if any(re.search(r'(?:navbar|navigation|breadcrumb|footer|side-menu|top-menu|sitemap|menu)',
        (' '.join(q.get('class') or [])+' '+str(q.get('id') or '')).lower())
        for q in list(a.parents)[:5]):continue
  title=clean(a.get_text(' ',strip=True)) or clean(a.get('title'))
  if not 7<=len(title)<=190 or EXCLUDE.fullmatch(title):continue
  href=clean(a.get('href'))
  if not href or href.lower().startswith(('#','javascript:','mailto:','tel:')):continue
  url=normalize_url(urljoin(base,href))
  if not url or url in seen or url==normalize_url(base) or not allowed_detail_link(base,url,adapter) or SKIPFILE.search(url):continue
  seen.add(url)
  parent=a.find_parent(['li','tr','article']) or a.parent
  row_text=clean(parent.get_text(' ',strip=True))[:550] if parent else title
  date_hint=[]
  for selector in adapter.date_selectors:
   try:
    date_hint.extend(clean(n.get('datetime') or n.get('content') or n.get_text(' ',strip=True))
                     for n in (parent or a).select(selector)[:2])
   except Exception:continue
  # Dedicated date column wins over dates occurring inside article titles.
  published=next((d for val in date_hint if (d:=parse_date(val))), '')
  if not published:
   # A date in the article's *title* is not evidence of publication. Accept
   # only a separate date field/text sibling within the same document row.
   if parent:
    independent=BeautifulSoup(str(parent),'html.parser')
    for link_node in independent.select('a'):
     link_node.decompose()
    independent_text=clean(independent.get_text(' ',strip=True))
    published=parse_date(independent_text) or ''
  if not published:
   # Policy rows with nested heading + independent date may be recognized by
   # repeated-column structural analysis, without using dates in headlines.
   published=structure.get('date_by_url',{}).get(url,'')
  if not published:
   # Some portals place a date in an immediate sibling after the title link.
   # Never look beyond the row into a wrapper containing multiple entries.
   for sibling in list(a.next_siblings)[:3]:
    txt=clean(sibling.get_text(' ',strip=True)) if hasattr(sibling,'get_text') else clean(sibling)
    if len(txt)>100:continue
    if (published:=parse_date(txt)):break
  total+=1
  if published:
   dated+=1;dates.append(published)
   if published>date.today().isoformat():future+=1
  else:undated+=1
  rank=6*bool(WIND.search(title))+3*bool(NORM.search(title))+bool(BUSINESS.search(title))
  links.append({'title':title,'url':url,'date':published,'rank':rank})
  if len(trace)<9:
   trace.append({'title':title[:110],'url':url[:240],'date':published,
     'row_tag':(parent.name if parent else ''),
     'row_class':(' '.join(parent.get('class') or [])[:95] if parent else ''),
     'date_field_match':bool(date_hint)})

 # An ordered official list is a prerequisite for using a date threshold to
 # omit older pages. Keep DOM order separate from detail prioritization.
 chronological=all(left>=right for left,right in zip(dates,dates[1:]))
 next_urls=[];js_page=False;explicit_pagination=False
 selected_next=[]
 for selector in adapter.config.get('next_selectors',[]):
  try:selected_next.extend(soup.select(selector.replace(':contains(',':-soup-contains(')))
  except Exception:continue
 for a in soup.select('a[href],button[onclick],button[data-page],a[onclick]'):
  label=clean(a.get_text(' ',strip=True)).lower()
  title=clean(a.get('title') or a.get('aria-label')).lower()
  rel=a.get('rel') or []
  cls=' '.join(a.get('class') or []).lower()
  # No blind numbered page 2/3 guesses. It must be a known next control.
  is_next=('next' in rel or '下一页' in label or '下一頁' in label or
           label in ('next','›','»','下页') or '下一页' in title or 'next' in title or
           bool(re.search(r'(^|[ -])next([ -]|$)',cls)))
  if a in selected_next:is_next=True
  if not is_next or 'disabled' in cls or a.get('aria-disabled')=='true':continue
  explicit_pagination=True
  raw=clean(a.get('href') or '')
  if not raw or raw.lower().startswith(('javascript:','#')):
   js_page=True;continue
  target=normalize_url(urljoin(base,raw))
  if target and target!=normalize_url(base) and same_site(base,target) and target not in next_urls:
   next_urls.append(target)
  else:js_page=True
 # CSS control matching a button does not establish a fetchable next URL.
 for node in selected_next:
  if node.name not in ('a','button'):continue
  if node.name=='button' and node.get('disabled') is None and node.get('aria-disabled')!='true':
   js_page=True
 text=soup.get_text(' ',strip=True)
 single=bool(re.search(r'(?:共\s*1\s*页|第\s*1\s*页\s*(?:，|/|共)\s*1\s*页|Page\s*1\s*of\s*1)',text,re.I))
 match=re.search(r'Page\s+(\d+)\s+of\s+(\d+)|第\s*(\d+)\s*页\s*[，/共]\s*(\d+)\s*页',text,re.I)
 if match:
  current,total_pages=(int(x) for x in (match.group(1),match.group(2))) if match.group(1) else (int(match.group(3)),int(match.group(4)))
  if current<total_pages and not next_urls:js_page=True
  if current==total_pages:single=(current==1)
 # A JS-only paginated directory is never treated as exhausted.
 if soup.select('[onclick*="nextPage"],[onclick*="goPage"],button[aria-label*=Next],a.next[href^="javascript:"]') and not next_urls:
  js_page=True
 return {'links':links,'selector_matched':bool(selector_hits and links),
         'selectors':selector_hits,'oldest_date':min(dates) if dates else '',
         'newest_date':max(dates) if dates else '',
         'dated_rows':dated,'eligible_rows':total,'undated_policy_rows':undated,
         'next_urls':next_urls[:1], 'js_pagination':js_page,
         'explicit_single_page':single,'anchor_total':len(anchors),
         'chronological':chronological,'future_dates':future,
         'explicit_pagination':explicit_pagination,
         'row_structure_evidence':structure['evidence'],
         'row_structure_confidence':structure['confidence'],
         'dom_samples':trace,'page_title':clean(soup.title.get_text(' ',strip=True))[:130] if soup.title else ''}

def _try_entry(url, legacy_adapter, should_render, attempts):
 """HTTP first; preserve exact error/status and never render to bypass denial.

 HTTP 404: only caller-supplied alternate public official entry may be tried.
 HTTP 403/412: stop the request, retain evidence for authorized operator.
 Timeouts and 5xx: bounded requests retries, no unbounded browser escalation.
 """
 try:
  html,actual,kind=fetch(url)
  attempts.append({'url':url,'method':'http','status':'read','redirect':actual})
  return html,actual,kind
 except Exception as exc:
  code,http_code,hint=classify_error(exc)
  attempts.append({'url':url,'method':'http','status':'failed','error_code':code,
                   'http_status':http_code,'operator_hint':hint,
                   'error':type(exc).__name__+': '+clean(str(exc))[:200]})
  if (not BROWSER_ENABLED or not should_render or
      code in ('http_403','http_404','http_412','http_429','timeout','dns_error','connection_error','tls_error')):
   return None
  try:
   html,actual,kind=browser_fetch(url,legacy_adapter)
   attempts.append({'url':url,'method':'browser','status':'read','redirect':actual})
   return html,actual,kind
  except Exception as be:
   code2,http2,hint2=classify_error(be)
   attempts.append({'url':url,'method':'browser','status':'failed','error_code':code2,
                    'http_status':http2,'operator_hint':hint2,
                    'error':type(be).__name__+': '+clean(str(be))[:200]})
   return None

def attachment_urls(html,base):
 """Public PDFs linked from an official detail page, not external mirrors."""
 soup=BeautifulSoup(html,'html.parser');result=[]
 for a in soup.select('a[href]'):
  href=a.get('href','');label=clean(a.get_text(' ',strip=True))
  if not (PDF.search(href) or (re.search(r'附件|下载|全文|pdf|原文',label,re.I) and
      re.search(r'\.pdf(?:$|\?)|downfile\.jsp|/download/pdf',href,re.I))):continue
  url=normalize_url(urljoin(base,href))
  if url and same_site(base,url) and url not in result:result.append(url)
 return result[:2]


def _result_status(attempts, found, detail_pending, limit_hit, listing_complete,
                   any_listing, any_parsed, has_undated, has_incomplete_pagination):
 if not any(a.get('status')=='read' for a in attempts):
  primary=primary_failure(attempts);code=primary.get('error_code')
  if code is None:
   code=classify_error(Exception(primary.get('error','')))[0]
  if code=='http_404':return 'http_error','官方入口返回 HTTP 404：已失效或迁移；须核对网址及备用入口'
  if code=='http_412':return 'blocked','官方返回 HTTP 412：请求前置条件不满足；不自动绕过'
  if code=='http_403':return 'blocked','官方返回 HTTP 403：访问被拒绝；需核查执行地及官方访问条件'
  if code=='http_429':return 'blocked','官方返回 HTTP 429：限流；应降低频率并尊重重试时间'
  if code=='timeout':return 'timeout','官方来源请求超时；有限重试后保留状态，待跨网络复核'
  if code in ('dns_error','connection_error','tls_error'):
   return 'connection_error',{'dns_error':'DNS 解析失败','tls_error':'TLS 握手失败',
     'connection_error':'官方来源网络不可达'}[code]+'；待境内外执行端比对'
  return 'error','官方来源读取失败；见详细异常证据，后续补查'
 if listing_complete:
  if detail_pending:
   return 'partial_coverage','官方目录日期和分页覆盖已核验，但部分详情待独立重试（目录游标可推进）'
  if found:return 'ok_with_results','官方目录覆盖已核验，发现带来源证据的法规或待核验线索'
  return 'ok_no_recent','该来源本次日期区间目录已核验，暂无符合收录条件的条目'
 if not any_listing or not any_parsed:return 'needs_adapter','专站列表选择器或公开查询未提取到带日期的有效目录'
 if limit_hit:return 'partial_coverage','目录翻页上限已到；尚不能证明完整覆盖'
 if has_incomplete_pagination:return 'partial_coverage','下一页失败、动态翻页或日期顺序异常；目录游标不推进'
 if has_undated:return 'partial_coverage','官方目录候选存在缺失发布日期或未来日期；不可证明覆盖完整'
 if found:return 'partial_coverage','取得部分法规线索，但目录时间窗尚未完全核验'
 return 'partial_coverage','已读取目录但缺少真实的时间窗口结束证据'

def scrape_one(src,dims,cutoff,manual,retry_candidates=None):
 """Audit a source, separately recording listing coverage and detail retries.

 A failed detail download does not invalidate *proven* listing coverage: its URL
 survives in the durable retry queue. JS-only or failed pagination is never
 silently assumed to have reached the time boundary.
 """
 adapter=load_adapter(src)
 at=clock();attempts=[];found={};reviews=[];links_by_url={};pending=[]
 dom_samples=[]
 any_listing=False;any_parsed=False;selector_used=False
 rows_with_date=0;rows_total=0;future_dates=0;oldest_dates=[]
 incomplete_pages=False;date_ordered=True;listing_boundary=False
 explicit_end=False;limit_hit=False;pages_count=0;reliable_entry=False
 visited=set();previous_oldest=None;entry_failure=False
 for start_url in adapter_urls(src):
  if reliable_entry:break
  # Every alternate address represents a separate chronological archive. Do
  # not combine its dates, pagination proof, or failed pages with another one.
  # We retain all attempted URLs and detail candidates for diagnostics.
  any_listing=False;any_parsed=False;selector_used=False
  rows_with_date=0;rows_total=0;future_dates=0;oldest_dates=[]
  incomplete_pages=False;date_ordered=True;listing_boundary=False
  explicit_end=False;limit_hit=False;pages_count=0;previous_oldest=None
  entry_failure=False
  queue=[start_url];read_any=False;entry_links=0
  while queue and pages_count<MAX_LIST_PAGES:
   page_url=queue.pop(0)
   if page_url in visited:
    incomplete_pages=True;continue
   visited.add(page_url)
   fetched=_try_entry(page_url,src.get('adapter') or src['id'],page_url==start_url,attempts)
   if fetched is None:
    entry_failure=True
    # A missing page in a chain destroys continuity, even if later pages load.
    if page_url!=start_url:incomplete_pages=True
    continue
   html,actual,kind=fetched
   if not allowed_detail_link(page_url,actual,adapter):
    incomplete_pages=True
    attempts.append({'url':page_url,'method':'validation','status':'failed',
                     'error_code':'redirect_rejected','error':'官方域名之外的跳转未获授权'})
    continue
   read_any=True
   if kind=='pdf':
    # Individual PDF documents are not complete chronological directories.
    continue
   page=_listing_page(html,actual,adapter)
   if (BROWSER_ENABLED and page_url==start_url and
       (not page['selector_matched'] or page['dated_rows']==0) and
       (adapter.config['needs_browser_ui'] or re.search(r'__NEXT_DATA__|__NUXT__|webpack|vue(?:\.runtime)?\.js|data-reactroot',html,re.I))):
    # A public browser may render HTML/normal search UI, not bypass HTTP denial.
    try:
     rendered,render_url,render_kind=browser_fetch(page_url,src.get('adapter') or src['id'])
     attempts.append({'url':page_url,'method':'public_ui_search','status':'read','redirect':render_url})
     if render_kind=='html' and allowed_detail_link(page_url,render_url,adapter):
      trial=_listing_page(rendered,render_url,adapter)
      if ((trial['dated_rows'],int(trial['selector_matched'])) >
          (page['dated_rows'],int(page['selector_matched']))):
       page=trial;html=rendered
    except Exception as exc:
     code,http_code,hint=classify_error(exc)
     attempts.append({'url':page_url,'method':'public_ui_search','status':'failed',
                      'error_code':code,'http_status':http_code,'operator_hint':hint,
                      'error':type(exc).__name__+': '+clean(str(exc))[:180]})
   if adapter.config['allow_iframe']:
    for framed_url in extract_iframes(html,actual):
     framed=_try_entry(framed_url,src.get('adapter',''),False,attempts)
     if not framed or framed[2]!='html' or not same_site(framed_url,framed[1]):continue
     sub=_listing_page(framed[0],framed[1],adapter)
     if sub['eligible_rows']:
      page['links'].extend(sub['links'])
      page['dated_rows']+=sub['dated_rows'];page['eligible_rows']+=sub['eligible_rows']
      page['undated_policy_rows']+=sub['undated_policy_rows']
      page['future_dates']+=sub['future_dates']
      page['chronological']=page['chronological'] and sub['chronological']
      page['selector_matched']=page['selector_matched'] or sub['selector_matched']
      page['next_urls']+=sub['next_urls']
      page['js_pagination']=page['js_pagination'] or sub['js_pagination']
      if sub['oldest_date']:
       page['oldest_date']=min(filter(None,(page['oldest_date'],sub['oldest_date'])))
   # Public JavaScript-only page controls can be clicked in normal Chromium.
   # If controls cannot be exhausted or prove a date boundary, keep pending.
   additional_pages=0
   if page['js_pagination'] and not page['next_urls'] and BROWSER_ENABLED and pages_count+1<MAX_LIST_PAGES:
    try:
     from policy_public_ui import public_js_pages
     rendered_pages,ui_exhausted=public_js_pages(page_url,adapter.config,MAX_LIST_PAGES-pages_count)
     if rendered_pages:
      first=_listing_page(rendered_pages[0][0],rendered_pages[0][1],adapter)
      if first['dated_rows']>page['dated_rows'] and first['selector_matched']:
       page=first
      older=page['oldest_date']
      for extra_html,extra_url in rendered_pages[1:]:
       extra=_listing_page(extra_html,extra_url,adapter)
       if older and extra['newest_date'] and extra['newest_date']>older:
        page['chronological']=False
       if extra['oldest_date']:
        older=extra['oldest_date']
        page['oldest_date']=min(filter(None,(page['oldest_date'],extra['oldest_date'])))
       if extra['newest_date']:
        page['newest_date']=max(filter(None,(page['newest_date'],extra['newest_date'])))
       page['links'].extend(extra['links'])
       page['dated_rows']+=extra['dated_rows'];page['eligible_rows']+=extra['eligible_rows']
       page['undated_policy_rows']+=extra['undated_policy_rows']
       page['future_dates']+=extra['future_dates']
       page['selector_matched']=page['selector_matched'] and extra['selector_matched']
       page['chronological']=page['chronological'] and extra['chronological']
       additional_pages+=1
      if ui_exhausted:
       page['js_pagination']=False
       page['js_pagination_exhausted']=True
     attempts.append({'url':page_url,'method':'public_ui_pagination',
                      'status':'read','pages':len(rendered_pages),'exhausted':ui_exhausted})
    except Exception as exc:
     code,http_code,hint=classify_error(exc)
     attempts.append({'url':page_url,'method':'public_ui_pagination',
                      'status':'failed','error_code':code,'http_status':http_code,
                      'error':type(exc).__name__+': '+clean(str(exc))[:150]})
   if len(dom_samples)<12:
    for row in page.get('dom_samples',[]):
     if len(dom_samples)<12:
      dom_samples.append({'catalogue_url':page_url,**row})
   pages_count+=1+additional_pages
   any_listing=any_listing or bool(page['selector_matched'] and page['eligible_rows'])
   any_parsed=any_parsed or page['eligible_rows']>0
   selector_used=selector_used or page['selector_matched']
   rows_with_date+=page['dated_rows'];rows_total+=page['eligible_rows']
   future_dates+=page['future_dates']
   date_ordered=date_ordered and page['chronological']
   if page['newest_date'] and previous_oldest and page['newest_date']>previous_oldest:
    date_ordered=False
   if page['oldest_date']:
    oldest_dates.append(page['oldest_date'])
    previous_oldest=page['oldest_date']
   explicit_end=explicit_end or page['explicit_single_page'] or page.get('js_pagination_exhausted',False)
   for candidate in page['links']:
    entry_links+=1  # Entry viability is local; global candidate URL dedup is separate.
    if candidate['url'] not in links_by_url or (candidate['date'] and not links_by_url[candidate['url']]['date']):
     links_by_url[candidate['url']]=candidate
   next_urls=[u for u in page['next_urls'] if u not in visited and u not in queue]
   if page['js_pagination']:
    incomplete_pages=True
   crossed=bool(page['oldest_date'] and page['oldest_date']<cutoff.isoformat())
   if crossed and (not page['next_urls'] or pages_count>1 or page['explicit_single_page']):
    # Need an additional page if a next link exists on the first page.
    # Across pages, dated rows must be in monotone descending order.
    listing_boundary=True
    queue.clear()
    break
   queue.extend(next_urls[:1])
   if page['next_urls'] and not next_urls and not crossed:
    incomplete_pages=True
  if queue:limit_hit=True
  if read_any and entry_links and any_listing:
   reliable_entry=True
   # A homepage with incidental dated links isn't an archive.
   if (urlsplit(start_url).path or '/')=='/' and adapter.strategy not in ('legal_database','iea_public_policy_index'):
    reliable_entry=False
   if adapter.strategy=='official_index_fallback' and re.search(r'\.s?html?$',urlsplit(start_url).path,re.I):
    reliable_entry=False
   if reliable_entry:
    # Only accept this alternative as final when its *own* complete listing
    # proof is sufficient; otherwise try the next explicitly configured URL.
    this_listing_proven=bool(selector_used and rows_total and
      rows_with_date==rows_total and not future_dates and date_ordered and
      not incomplete_pages and not limit_hit and
      (listing_boundary or explicit_end) and adapter.strategy!='document_entry_only')
    if this_listing_proven:break
    reliable_entry=False
 # Even a known 404 page cannot be overridden by a successful unrelated portal;
 # only an actual configured, dated document index is accepted.
 all_rows_dated=bool(rows_total and rows_with_date==rows_total and not future_dates)
 if entry_failure and not reliable_entry:incomplete_pages=True
 listing_complete=bool(reliable_entry and selector_used and all_rows_dated and date_ordered
    and not incomplete_pages and not limit_hit and
    (listing_boundary or explicit_end) and adapter.strategy!='document_entry_only')
 if listing_complete and not listing_boundary and pages_count==1:
  # A trivial document home without finite-pagination evidence cannot certify.
  official_path=urlsplit(adapter.config['official_url']).path
  if not official_path or official_path=='/':listing_complete=False
 # Source-specific selectors are still hypotheses until deployed/live-tested;
 # status carries a separate audit flag, never fabricating live validation.
 candidates=[]
 for v in retry_candidates or []:
  if isinstance(v,dict) and normalize_url(v.get('url','')) and v.get('date'):
   candidates.append({**v,'_retry':True})
 # A policy/energy topic filter reduces costly details; listing date verification
 # above included all document rows independently of the topic filter.
 # A general '通知' alone is not a reason to download 32 unrelated policies.
 # Broad electricity/new-energy titles are kept because the *body* may say 风电.
 # The media directory is wind-specific, but news still needs policy relevance.
 def topic_signal(row):
  title=row['title']
  if WIND.search(title):return bool(NORM.search(title) or RENEWABLE.search(title))
  if src['region']=='中国':return bool(RENEWABLE.search(title) and POLICY.search(title))
  return row['rank']>0 and bool(BUSINESS.search(title))
 candidates.extend(x for x in links_by_url.values() if topic_signal(x))
 unique={}
 for c in candidates:
  url=c['url'];unique[url]=dict(c,**{'_retry':bool(c.get('_retry') or unique.get(url,{}).get('_retry'))})
 selected=sorted(unique.values(),key=lambda x:(bool(x.get('_retry')),x['rank'],x['date']),reverse=True)
 details_errors=0;detail_limit_hit=False;details_attempted=0
 def enqueue(candidate,why):
  if any(v['url']==candidate['url'] for v in pending):return
  pending.append({'url':candidate['url'],'title':candidate['title'],'date':candidate.get('date',''),
                  'rank':candidate.get('rank',0),'last_error':why,'last_failed_at':clock()})
 for candidate in selected:
  if candidate['date'] and candidate['date']<cutoff.isoformat() and not candidate.get('_retry'):continue
  if details_attempted>=MAX_DETAILS:
   detail_limit_hit=True
   enqueue(candidate,'详情下载预算耗尽');continue
  details_attempted+=1
  # Prior-window retries must not be discarded just because the daily cutoff moved.
  candidate_cutoff=(min(cutoff,date.fromisoformat(candidate['date'])) if
                    candidate.get('_retry') and candidate.get('date') else cutoff)
  fetched=_try_entry(candidate['url'],src.get('adapter',''),False,attempts)
  if fetched is None:
   details_errors+=1;enqueue(candidate,'详情访问失败')
   lead=listing_only_lead(src,candidate,candidate_cutoff,'详情请求失败')
   if lead:found[lead['id']]=lead
   if len(reviews)<30:reviews.append(review_record(src,candidate['title'],candidate['url'],'详情访问失败'))
   continue
  html,final,kind=fetched
  if not allowed_detail_link(candidate['url'],final,adapter):
   details_errors+=1;enqueue(candidate,'非授权官方域名跳转')
   if len(reviews)<30:reviews.append(review_record(src,candidate['title'],final,'跨域详情跳转'))
   continue
  obj,reason=make_record(src,candidate,html,final,kind,dims,candidate_cutoff,manual)
  if not obj and kind=='html':
   for pdf_url in attachment_urls(html,final):
    result=_try_entry(pdf_url,src.get('adapter',''),False,attempts)
    if result is None:
     details_errors+=1;enqueue(candidate,'正文附件 PDF 读取失败');continue
    pdf_text,pdf_final,pdf_kind=result
    if pdf_kind!='pdf' or not allowed_detail_link(final,pdf_final,adapter):continue
    obj,reason=make_record(src,candidate,pdf_text,pdf_final,pdf_kind,dims,candidate_cutoff,manual)
    if obj:break
  if obj:found[obj['id']]=obj
  else:
   lead=listing_only_lead(src,candidate,candidate_cutoff,reason or '条款证据不足')
   if lead:found[lead['id']]=lead
   if reason and len(reviews)<30:reviews.append(review_record(src,candidate['title'],final,reason))
  if obj and pending:
   pending[:]=[x for x in pending if x['url']!=candidate['url']]
 # Never mark a missing listing complete merely because all its details worked.
 status,message=_result_status(attempts,found,len(pending),limit_hit,listing_complete,
                               any_listing,any_parsed,not all_rows_dated,
                               incomplete_pages or not date_ordered)
 record={'id':src['id'],'name':src['name'],'status':status,'checked_at':at,
         'found_count':len(found),'candidate_links':len(links_by_url),
         'candidate_dated_links':sum(bool(x['date']) for x in links_by_url.values()),
         'listing_rows_with_date':rows_with_date,'listing_rows_total':rows_total,
         'listing_pages':pages_count,'oldest_listing_date':min(oldest_dates) if oldest_dates else '',
         'explicit_end_of_list':explicit_end,'chronological_order_verified':date_ordered,
         'detail_errors':details_errors,'detail_limit_hit':detail_limit_hit,
         'detail_retry_count':len(pending),'retry_candidates':pending,
         'listing_coverage_complete':listing_complete,
         'coverage_complete':listing_complete and not pending,
         'coverage_evidence':('已读取官方目录行、日期和时间边界' if listing_complete else '目录日期或翻页边界未获完整证明'),
         'message':message,'attempts':attempts,'window_start':cutoff.isoformat(),
         'window_end':date.today().isoformat(),'adapter':src['id'],
         'adapter_strategy':adapter.strategy,
         'adapter_live_verified':adapter.config['selectors_live_verified'],
         'dom_samples_for_diagnosis':dom_samples,'source_kind':src.get('source_type','')}
 return list(found.values()),reviews,record

def export_csv(rows,filename,headers):
 with open(DATA/filename,'w',newline='',encoding='utf-8-sig') as f:
  w=csv.writer(f);w.writerow(headers)
  for r in rows:w.writerow([r.get(k,'') if not isinstance(r.get(k),list) else '、'.join(map(str,r[k])) for k in headers])


def make_checkpoint(source, previous, today):
 """Per-source fixed bootstrap start prevents silent loss after days of failures."""
 prev=copy.deepcopy(previous) if isinstance(previous,dict) else {}
 prev.setdefault('source_id',source['id'])
 prev.setdefault('first_seen_on',today.isoformat())
 prev.setdefault('initial_window_start',(date.fromisoformat(prev['first_seen_on'])-timedelta(days=29)).isoformat())
 prev.setdefault('initialized',False)
 # V6.1 could self-certify with an unresolved next-page link. Invalidate only
 # its unproven cursors; preserve first_seen_on and all old legal records.
 if prev.get('initialized') and prev.get('coverage_proof_version')!=2:
  prev['initialized']=False;prev['last_verified_date']=None;prev['last_verified_at']=None
  prev['migration_note']='旧游标缺少 V6.2 严格分页证据，需要重新核验'
 if prev.get('source_url') and prev['source_url']!=source['url']:
  prev['initialized']=False;prev['last_verified_date']=None;prev['last_verified_at']=None
  prev['migration_note']='目录入口已更新，原游标需复核'
 prev['source_url']=source['url']
 prev.setdefault('last_verified_date',None)
 prev.setdefault('last_verified_at',None)
 prev.setdefault('consecutive_failures',0)
 prev.setdefault('total_attempts',0)
 prev.setdefault('last_error','')
 return prev


def window_for(checkpoint,today,overlap_days=2):
 """Returns (phase, inclusive cutoff); keep original baseline for failed initializers."""
 if checkpoint['initialized'] and checkpoint.get('last_verified_date'):
  last=date.fromisoformat(checkpoint['last_verified_date'])
  return ('daily_increment', min(today,last-timedelta(days=overlap_days)))
 return ('initial_month',date.fromisoformat(checkpoint['initial_window_start']))


def advance_checkpoint(checkpoint,status,today):
 cp=copy.deepcopy(checkpoint);cp['total_attempts']+=1
 cp['last_attempt_at']=status.get('checked_at') or clock()
 cp['last_status']=status['status']
 if (status.get('listing_coverage_complete',status.get('coverage_complete')) and
     (status['status'].startswith('ok_') or status.get('detail_retry_count',0)>0)):
  cp['initialized']=True;cp['coverage_proof_version']=2;cp['last_verified_date']=today.isoformat()
  cp['last_verified_at']=clock();cp['consecutive_failures']=0;cp['last_error']=''
 else:
  cp['consecutive_failures']+=1;cp['last_error']=status.get('message','')
 return cp


def merge_legal_records(old,items,source_by_id):
 """Non-destructive URL dedup: same content stays; changed evidence updates in place."""
 by_url={};counts={'inserted':0,'updated':0,'unchanged':0}
 if isinstance(old,dict):
  old=next((old[k] for k in ('policies','items','records','articles') if isinstance(old.get(k),list)), [])
 for x in (old if isinstance(old,list) else []):
  if not isinstance(x,dict) or not x.get('url') or not x.get('title'):continue
  y=copy.deepcopy(x);source=source_by_id.get(y.get('source_id'),{})
  y.setdefault('country',source.get('country','待核实'))
  y.setdefault('region',source.get('region','待核实'))
  y.setdefault('source_name',source.get('name','历史来源'))
  y.setdefault('source_excerpt',y.get('excerpt',''))
  y.setdefault('dimensions',[]);y.setdefault('published_at','')
  y.setdefault('doc_type','历史记录／待核验')
  y.setdefault('impact_design','需依据法规条款重新开展产品影响分析')
  y.setdefault('impact_business','需依据法规条款重新开展商业模式影响分析')
  y.setdefault('importance',importance(None,[]))
  y.setdefault('verification_status','历史导入，待重新核验')
  by_url[normalize_url(y['url']) or y['url']]=y
 for new in items:
  key=normalize_url(new['url']) or new['url']
  if key in by_url:
   old=by_url[key]
   fields=('title','published_at','source_excerpt','dimensions','impact_design','impact_business')
   if any(old.get(k)!=new.get(k) for k in fields):
    # Preserve manually-reviewed scores until independent evidence review;
    # manual reviewed input is always re-applied by make_record.
    if old.get('importance',{}).get('status')=='人工核验评分' and new.get('importance',{}).get('score') is None:
     if old.get('source_excerpt')==new.get('source_excerpt'):
      new['importance']=old['importance'];new['clause_scoring']=old.get('clause_scoring',[])
     else:
      new['prior_importance_pending_recheck']=old['importance']
      new['importance']=importance(None,[])
      new['clause_scoring']=[]
    new['originally_discovered_at']=old.get('originally_discovered_at') or old.get('discovered_at')
    new['updated_at']=clock();counts['updated']+=1;by_url[key]=new
   else:counts['unchanged']+=1
  else:
   counts['inserted']+=1;new['originally_discovered_at']=new.get('discovered_at',clock());by_url[key]=new
 policies=sorted(by_url.values(),key=lambda x:(x.get('published_at') or '',x.get('discovered_at') or ''),reverse=True)
 return policies,counts


def main(argv=None):
 p=argparse.ArgumentParser(description='V7: dynamic source-specific adapters, initial 30 days per site then daily incremental')
 p.add_argument('--mode',choices=('auto',),default='auto',help='Daily automatic crawl')
 p.add_argument('--scope',choices=('all','provincial'),default='all',
                help='provincial: 31 provinces + national authorities + BJX; leave international data unchanged')
 p.add_argument('--offline-fixtures',action='store_true',help='Only for tests: no network')
 p.add_argument('--prepare',action='store_true',help='Write first-seen per-source checkpoints without network; used by Actions')
 a=p.parse_args(argv)
 if a.offline_fixtures:raise SystemExit('No fake network results are generated')
 sources=read(SOURCES,[]);dims=read(DIMS,[])
 if len(sources)<121 or len({s['id'] for s in sources})!=len(sources) or len(dims)!=18:
  raise SystemExit('Expected distinct source URLs with 18 regulatory dimensions')
 # Refuse silent fallback to a generic parser when even one individual module is absent.
 adapter_map={src['id']:load_adapter(src) for src in sources}
 if len(adapter_map)!=len(sources) or not all(a.is_site_specific() for a in adapter_map.values()):
  raise SystemExit('Missing a source-specific adapter module')
 today=date.today();manual=read(SCORES,{})
 saved=read(CHECKPOINTS,{})
 if not isinstance(saved,dict):saved={}
 previous_states=saved.get('sources',{}) if isinstance(saved.get('sources',{}),dict) else {}
 checkpoints={s['id']:make_checkpoint(s,previous_states.get(s['id']),today) for s in sources}
 if a.prepare:
  if (len(previous_states)!=len(checkpoints) or not CHECKPOINTS.exists() or
     any(previous_states.get(sid)!=cp for sid,cp in checkpoints.items())):
   save(CHECKPOINTS,{'version':1,'updated_at':clock(),'bootstrap_days':30,'daily_overlap_days':2,'sources':checkpoints})
  LOG.info('Prepared %s source-specific checkpoints without network',len(checkpoints))
  return checkpoints
 if len(previous_states)!=len(checkpoints) or not CHECKPOINTS.exists():
  # Journal the first-seen date before long-running work, not after all 121 calls.
  save(CHECKPOINTS,{'version':1,'updated_at':clock(),'bootstrap_days':30,'daily_overlap_days':2,'sources':checkpoints})
 jobs=[]
 for source in sources:
  if source.get('monitor_enabled') is False:continue
  if a.scope=='provincial' and source.get('region')!='中国':continue
  cp=checkpoints[source['id']]
  phase,cutoff=window_for(cp,today)
  jobs.append((source,phase,cutoff))
 # Operational priority: energy regulators + wind-policy media leads first,
 # then development commissions, provincial governments, and other departments.
 # This changes only execution order, not source identity or output/UI ordering.
 def _priority(job):
  source=job[0];name=source.get('name','')
  if source['id']==MEDIA_SOURCE_ID:return (0,0)
  if source.get('region')=='中国' and '能源局' in name:return (1,0)
  if source.get('region')=='中国' and any(z in name for z in ('发展改革','发改委','发展和改革')):return (2,0)
  if source.get('region')=='中国':return (3,0)
  return (4,0)
 jobs.sort(key=_priority)
 LOG.info('V7: %s per-site checkpoints; bootstrap=%s daily=%s workers=%s',len(sources),
          sum(x[1]=='initial_month' for x in jobs),sum(x[1]=='daily_increment' for x in jobs),MAX_WORKERS)
 prior_queues=read(DETAIL_QUEUE,{})
 if not isinstance(prior_queues,dict):prior_queues={}
 statuses=[];reviewed=[];items=[];next_queues={}
 with futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
  tasks={pool.submit(scrape_one,src,dims,cutoff,manual,*([prior_queues[src['id']]] if prior_queues.get(src['id']) else [])):(src,phase,cutoff) for src,phase,cutoff in jobs}
  for n,task in enumerate(futures.as_completed(tasks),1):
   src,phase,cutoff=tasks[task]
   try:docs,reviews,status=task.result()
   except Exception as exc:
    docs,reviews=[],[]
    status={'id':src['id'],'name':src['name'],'status':'error','checked_at':clock(),
            'found_count':0,'candidate_links':0,'message':'运行异常 '+type(exc).__name__+': '+str(exc)[:200],
            'attempts':[],'window_start':cutoff.isoformat(),'window_end':today.isoformat(),
            'coverage_complete':False,'adapter':src['id'],'adapter_strategy':adapter_map[src['id']].strategy}
   outstanding=status.pop('retry_candidates',None)
   if outstanding is None:outstanding=prior_queues.get(src['id'],[])
   if outstanding:next_queues[src['id']]=outstanding
   status['phase']=phase
   checkpoint=advance_checkpoint(checkpoints[src['id']],status,today)
   checkpoints[src['id']]=checkpoint
   status['initialized']=checkpoint['initialized']
   status['bootstrap_started_on']=checkpoint['first_seen_on']
   status['bootstrap_window_start']=checkpoint['initial_window_start']
   status['last_verified_date']=checkpoint.get('last_verified_date')
   status['consecutive_failures']=checkpoint['consecutive_failures']
   statuses.append(status);reviewed.extend(reviews);items.extend(docs)
   LOG.info('%s/%s [%s] [%s] %s +%s, verified=%s',n,len(sources),phase,status['status'],src['name'],len(docs),status.get('coverage_complete',False))
 assert len(statuses)==len(jobs) and len({s['id'] for s in statuses})==len(jobs)
 # Keep previously observed international source states in province-only jobs.
 # If never measured, say 'not_scheduled' instead of inventing a failure or success.
 prior_status_by_id={x['id']:x for x in read(STATUSES,[]) if isinstance(x,dict) and x.get('id')}
 scanned={x['id'] for x in statuses}
 for source in sources:
  if source['id'] in scanned:continue
  previous=prior_status_by_id.get(source['id'])
  if previous:
   statuses.append(dict(previous,not_refreshed_in_this_run=True))
  else:
   statuses.append({'id':source['id'],'name':source['name'],'status':'not_scheduled',
     'message':'本轮聚焦省级政策，未执行此来源采集；不代表网站失败',
     'checked_at':None,'coverage_complete':False,'listing_coverage_complete':False,
     'found_count':0,'candidate_links':0,'attempts':[],'not_refreshed_in_this_run':True})
 order={s['id']:i for i,s in enumerate(sources)}
 statuses.sort(key=lambda st:order[st['id']])
 records,changes=merge_legal_records(read(POLICIES,[]),items,{s['id']:s for s in sources})
 # Persist all legal records; do not truncate historical results to a hidden cap.
 save(POLICIES,records)
 save(STATUSES,statuses)
 save(CANDIDATES,reviewed[:3000])
 save(DETAIL_QUEUE,next_queues)
 save(CHECKPOINTS,{'version':1,'updated_at':clock(),'bootstrap_days':30,'daily_overlap_days':2,'sources':checkpoints})
 # Province diagnostics deliberately remain backend-only: the HTML/JS/CSS is unchanged.
 province_report=export_province_report(ROOT, DATA,
    (ROOT/'diagnostics' if DATA == ROOT/'site'/'data' else DATA/'diagnostics'),
    statuses=statuses,policies=records)
 LOG.info('Province coverage report: %d provinces, %d with any verified official directory',
          len(province_report['provinces']),
          sum(bool(p['verified_official_catalogues']) for p in province_report['provinces']))
 initialized_count=sum(cp['initialized'] for cp in checkpoints.values())
 counts={code:sum(st['status']==code for st in statuses) for code in sorted({st['status'] for st in statuses})}
 state={'version':'V7-province-first','scope':a.scope,'last_run':clock(),'configured_source_count':len(sources),'attempted_source_count':len(jobs),
        'initial_phase_count':sum(s.get('phase')=='initial_month' for s in statuses),
        'incremental_phase_count':sum(s.get('phase')=='daily_increment' for s in statuses),
        'initialized_source_count':initialized_count,'pending_initialization_count':len(sources)-initialized_count,
        'bootstrap_days':30,'daily_overlap_days':2,'detail_pending_source_count':len(next_queues),
  'detail_pending_count':sum(len(x) for x in next_queues.values()),
  'listing_verified_count':sum(bool(st.get('listing_coverage_complete',st.get('coverage_complete'))) for st in statuses),
  'status_counts':counts,'change_counts':changes}
 save(STATE,state)
 rows=[{'法规名称':x.get('title',''),'所属国家区域':x.get('country','')+' / '+x.get('province',''),
        '发布日期':x.get('published_at',''),'法规原文节选':x.get('source_excerpt',''),
        '法规维度标签':'、'.join(x.get('dimensions') or []),'产品设计影响':x.get('impact_design',''),
        '商业模式影响':x.get('impact_business',''),'重要度':(x.get('importance') or {}).get('priority') or '待条款评分',
        '法律状态':x.get('doc_type',''),'原文链接':x.get('url','')} for x in records]
 heads=['法规名称','所属国家区域','发布日期','法规原文节选','法规维度标签','产品设计影响','商业模式影响','重要度','法律状态','原文链接']
 export_csv(rows,'policies.csv',heads)
 acceptance=[]
 for src,st in zip(sources,statuses):
  attempts_errors=[a.get('error','') for a in st.get('attempts',[]) if a.get('status')=='failed']
  acceptance.append({'网站名称':src['name'],'当前状态':st['status'],
    '失败原因':st['message']+('；'+str(attempts_errors[:2]) if attempts_errors else ''),
    '需要怎么适配':str(st.get('adapter_strategy') or 'not_scheduled')+' / '+src['id']+'；核对本源列表日期、全文、附件和翻页',
    '修复后测试结果':('完整窗口覆盖可审计' if st.get('coverage_complete') else '未通过完整时间窗验收；仍需线上复测或适配'),
    '官方网站':src['url'],'专站适配器':st.get('adapter',src['id']),'策略':st.get('adapter_strategy','not_scheduled'),
    '阶段':st.get('phase','not_scheduled'),'初始化完成':st.get('initialized',False),'初始窗口起点':st.get('bootstrap_window_start',''),
    '本轮起点':st.get('window_start',''),'最后核验日期':st.get('last_verified_date') or '',
    '日期覆盖核验':st.get('coverage_complete',False),'目录覆盖单独核验':st.get('listing_coverage_complete',False),
    '详情补查队列数':st.get('detail_retry_count',0),'发布日期有效行数':st.get('listing_rows_with_date',0),
    '目录总行数':st.get('listing_rows_total',0),'详情错误数':st.get('detail_errors',0),
    '法规候选数':st.get('found_count',0),'连续失败次数':st.get('consecutive_failures',0),
    '检查时间UTC':st.get('checked_at'),'详细访问轨迹':json.dumps(st.get('attempts',[]),ensure_ascii=False)})
 export_csv(acceptance,'policy_site_acceptance.csv',list(acceptance[0]))
 save(DATA/'policy_site_acceptance.json',acceptance)
 LOG.info('Completed %s/%s, initialized %s/%s, inserted=%s updated=%s unchanged=%s; false successes prohibited',
          len(sources),len(sources),initialized_count,len(sources),changes['inserted'],changes['updated'],changes['unchanged'])
 return statuses

if __name__=='__main__':main()
