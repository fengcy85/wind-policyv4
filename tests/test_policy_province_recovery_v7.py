"""V7 province-first behavioral checks; all markup/network responses are fixtures."""
import json
import unittest
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch

import policy_scrape as crawler
from policy_provincial import MEDIA_SOURCE_ID,PROVINCES,build_contract,build_province_report
from policy_network_probe import province_first_urls
from policy_source_recovery import make_plan,operator_action

ROOT=Path(__file__).resolve().parents[1]
SOURCES=json.loads((ROOT/'policy_sources.json').read_text(encoding='utf-8'))
MEDIA=next(s for s in SOURCES if s['id']==MEDIA_SOURCE_ID)

class RecoveryV7(unittest.TestCase):
    def test_province_network_probe_one_region_each(self):
        selected=province_first_urls(SOURCES,32)
        self.assertEqual(len(selected),32)
        self.assertIn(MEDIA_SOURCE_ID,{x['id'] for x in selected})
        self.assertEqual({(x.get('province_canonical') or x.get('province')) for x in selected if x['id']!=MEDIA_SOURCE_ID},set(PROVINCES))

    def test_recovery_distinguishes_http_errors(self):
        source={'id':'x','url':'https://official.example.gov.cn/policy/','source_type':'政策法规'}
        for code,msg,token in [('http_404','invalid','404'),('http_403','forbidden','403'),
                               ('http_412','precondition','412')]:
            st={'status':'blocked','attempts':[{'method':'http','status':'failed','error_code':code}]}
            self.assertIn(token,operator_action(source,st))
        for s in ('timeout','connection_error'):
            self.assertIn('境内',operator_action(source,{'status':s,'attempts':[]}))

    def test_media_is_not_a_verified_agency(self):
        report=make_plan(SOURCES,[])
        self.assertEqual(report['province_count'],31)
        media=next(x for x in report['source_rows'] if x['来源ID']==MEDIA_SOURCE_ID)
        self.assertIn('媒体',media['角色'])
        self.assertFalse(media['目录时间段已核验'])
        self.assertFalse(media['URL真实访问检测通过'])
        self.assertTrue(any('能源局' in x['来源名称'] for x in report['source_rows'] if x['省份']=='吉林'))

    def test_media_blocked_detail_creates_lead_without_crash(self):
        candidate={'url':'https://news.bjx.com.cn/html/20261013/1515993.shtml',
                   'title':'江苏公布风电项目并网管理通知','date':date.today().isoformat(),'rank':10}
        lead=crawler.listing_only_lead(MEDIA,candidate,date.today()-timedelta(days=5),'HTTP 403')
        self.assertIsNotNone(lead)
        self.assertEqual(lead['discovery_channel'],'professional_media')
        self.assertEqual(lead['linked_official_urls'],[])
        self.assertFalse(lead['article_evidence_available'])
        self.assertEqual(lead['province'],'江苏')

    def test_nested_official_date_not_confused_with_document_title(self):
        url='https://fgw.sh.gov.cn/fgw_ny/index.html'
        # Shanghai official energy-list shape: date and document number are
        # siblings of the title inside a repeated wrapper, not inside the link.
        links=''.join(
            '<div class="policy-item"><h3><a href="/policy/%s.html">关于上海市风电项目管理方案第%s批</a></h3>'
            '<p>文号：沪发改能源〔2026〕%s号 发布日期：2026-10-%02d</p></div>' %(i,i,i,14-i)
            for i in range(4))
        source=next(s for s in SOURCES if s['id']=='cn_c3d9397ca287')
        page=crawler._listing_page('<main>'+links+'</main>',url,crawler.load_adapter(source))
        self.assertEqual(page['dated_rows'],4)
        self.assertEqual(page['eligible_rows'],4)
        self.assertEqual(page['row_structure_confidence'],'repeated_dated_rows')
        self.assertFalse(page['explicit_single_page'])

    def test_historical_status_not_reported_as_current(self):
        item=next(s for s in SOURCES if s.get('province_canonical')=='上海')
        statuses=[{'id':item['id'],'name':item['name'],'listing_coverage_complete':True,
                   'status':'ok_no_recent','checked_at':'2024-01-01T00:00:00+00:00'}]
        report=build_province_report(SOURCES,statuses,[])
        sh=next(x for x in report['provinces'] if x['province']=='上海')
        self.assertEqual(sh['verified_official_catalogues'],0)
        self.assertEqual(sh['official_sources_scanned'],0)
        self.assertEqual(sh['official_sources_with_saved_history'],1)

    def test_source_url_changed_old_error_must_not_claim_new_url_visited(self):
        s=next(x for x in SOURCES if x['id']=='cn_573ba3b6d161')
        old='https://xxgk.jl.gov.cn/zcbm/fgw_97953/xxgkmlqy/'
        status={'id':s['id'],'status':'blocked','attempts':[{'method':'http','url':old,'status':'failed','error_code':'http_403'}]}
        report=make_plan(SOURCES,[status]);row=next(x for x in report['source_rows'] if x['来源ID']==s['id'])
        self.assertFalse(row['核验基于现行入口'])
        self.assertFalse(row['检测入口与当前配置一致'])
        self.assertFalse(row['URL真实访问检测通过'])

if __name__=='__main__':unittest.main()
