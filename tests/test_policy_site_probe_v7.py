"""Pure fixtures: separate entry verification from time-window coverage."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch
from tempfile import TemporaryDirectory
import policy_site_probe as probe

ROOT=Path(__file__).resolve().parents[1]
SOURCES=json.loads((ROOT/'policy_sources.json').read_text(encoding='utf-8'))

def dated_page():
    return ('<html><title>法规目录</title><main><ul>' + ''.join(
        f'<li><a href="/art/2026/10/{d}/rule{d}.html">关于风电并网管理规范性通知第{d}条</a>'
        f'<span>2026-10-{d:02d}</span></li>' for d in (15,14,13,12)) +
        '</ul><a href="/zc/index_1.html">下一页</a></main></html>')

class SiteProbeFixtures(unittest.TestCase):
    def test_one_official_entry_has_real_dated_rows_but_not_full_coverage(self):
        src=next(s for s in SOURCES if s['id']=='cn_bcae52a0ff64')
        with patch('policy_site_probe._try_entry',return_value=(dated_page(),src['url'],'html')):
            result=probe.probe_one(src)
        self.assertTrue(result['verified_listing_entry'])
        self.assertFalse(result['full_coverage_verified'])
        self.assertEqual(result['entries'][0]['dated_rows'],4)
        self.assertTrue(result['entries'][0]['next_url'])

    def test_403_is_not_rebranded_as_dom_success(self):
        src=next(s for s in SOURCES if s['id']=='cn_5555c1d4376e')
        def failed(url, adapter, render, attempts):
            attempts.append({'status':'failed','error_code':'http_403','http_status':403})
            return None
        with patch('policy_site_probe._try_entry',side_effect=failed):
            result=probe.probe_one(src)
        self.assertFalse(result['verified_listing_entry'])
        self.assertEqual(result['entries'][0]['failure_class'],'http_403')

    def test_province_first_selects_31_official_plus_media(self):
        picked=probe.choose_sources(SOURCES,province_first=True)
        self.assertEqual(len(picked),32)
        self.assertEqual(len(set(x['id'] for x in picked)),32)
        self.assertEqual(picked[-1]['id'],'cn_5555c1d4376e')

    def test_reports_are_not_false_positive(self):
        with TemporaryDirectory() as d:
            output=Path(d)/'site_probe.json'
            report=probe.write_reports([{'source_id':'a','name':'省发改委','province':'吉林',
                'category':'政策法规','verified_listing_entry':False,
                'full_coverage_verified':False,'entries':[]}],output)
            self.assertFalse(report['full_coverage_verified'])
            self.assertEqual(report['http_and_dom_readable'],0)
            self.assertTrue(output.with_suffix('.csv').exists())

if __name__=='__main__':unittest.main()

class MediaDataHonesty(unittest.TestCase):
    def test_unverified_bjx_general_energy_policy_hint_is_visible_but_labeled(self):
        from build_site_data import normalize_policy
        from policy_scrape import listing_only_lead
        from datetime import date,timedelta
        src=next(s for s in SOURCES if s['id']=='cn_5555c1d4376e')
        candidate={'title':'天津启动新能源机制电价竞价政策','date':date.today().isoformat(),
                   'url':'https://news.bjx.com.cn/html/20261016/1519191.shtml'}
        raw=listing_only_lead(src,candidate,date.today()-timedelta(days=2),'文章详情读取失败')
        self.assertIsNotNone(raw)
        result=normalize_policy(raw,{src['id']:src},{})
        self.assertIsNotNone(result)
        self.assertIn('尚未核实',result['verification_status'])
        self.assertIn('媒体',result['doc_type'])

    def test_official_unrelated_notice_is_not_mislabeled_as_wind(self):
        from build_site_data import normalize_policy
        from datetime import date
        src=next(s for s in SOURCES if s['id']=='cn_bcae52a0ff64')
        article={'source_id':src['id'],'title':'天津市商业街餐饮市场新政策通知','url':'https://www.tj.gov.cn/content/12345',
                 'published_at':date.today().isoformat(),
                 'source_excerpt':'天津市商业街餐饮市场经营活动应严格按照规范开展，无关新能源电力市场事项。',
                 'region':'中国','country':'中国'}
        self.assertIsNone(normalize_policy(article,{src['id']:src},{}))
