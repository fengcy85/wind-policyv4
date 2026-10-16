"""Offline contract/DOM/edge tests; NOT evidence of successful live HTTP."""
import json
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import policy_scrape as crawler
from policy_provincial import (
    BJX_DIRECTORY, MEDIA_SOURCE_ID, PROVINCES, province_of, province_from_title,
    parse_bjx_policy_directory, official_link_candidates, plausible_wind_policy,
    build_contract, build_province_report,
)
from policy_structured_discovery import discover_repeating_rows

ROOT=Path(__file__).resolve().parents[1]
SOURCES=json.loads((ROOT/'policy_sources.json').read_text(encoding='utf-8'))
DIMS=json.loads((ROOT/'regulatory_dimensions.json').read_text(encoding='utf-8'))
MEDIA=next(s for s in SOURCES if s['id']==MEDIA_SOURCE_ID)


def mock_news_article(title='江苏出台海上风电退役管理规定'):
    return f'''<html><head><meta name="pubdate" content="{date.today().isoformat()}"/></head>
    <body><h1>{title}</h1><div class="article-content">
    第一条 省发展改革部门发布本通知，海上风电项目须依照规定实施管理，应当落实并网验收和安全管理责任。
    本文介绍江苏省有关风力发电机组建设和退役更新等管理办法的适用对象，以及新能源项目开发、电网接入和认证要求。
    如有未明确事项，应以主管部门正式文件原文为准。
    <a href="https://www.jiangsu.gov.cn/art/2026/10/12/art_222_123.html">政府原文链接</a>
    </div></body></html>'''


class ProvinceRebuild(unittest.TestCase):
    def test_source_contract_31_provinces_and_media(self):
        contract=build_contract(SOURCES)
        self.assertEqual([x['province'] for x in contract],list(PROVINCES))
        self.assertEqual(len(set(s['id'] for s in SOURCES)),len(SOURCES))
        self.assertEqual(len(set(s['url'] for s in SOURCES)),len(SOURCES))
        for row in contract:
            self.assertTrue(row['official_source_ids'],row['province'])
            self.assertEqual(row['media_source_ids'],[MEDIA_SOURCE_ID])
            self.assertFalse(row['live_verified'])
            self.assertTrue(row['contract_configured'])
            for sid in row['official_source_ids']:
                self.assertEqual(next(s for s in SOURCES if s['id']==sid)['region'],'中国')

    def test_aliases_and_headline_region(self):
        self.assertEqual(province_of('内蒙古自治区'),'内蒙古')
        self.assertEqual(province_of('新疆维吾尔自治区'),'新疆')
        self.assertEqual(province_of('广西'),'广西')
        self.assertEqual(province_from_title('江苏省发布海上风电规范性通知'),'江苏')
        self.assertEqual(province_from_title('江苏与浙江联合出台风电通知'),'')
        self.assertEqual(province_from_title('国家能源局风电管理办法'),'')

    def test_media_parser_rejects_nav_headline_date_and_foreign_channels(self):
        page=f'''<html><nav><a href="/">政策</a></nav><ul>
          <li><a href="https://news.bjx.com.cn/html/20261015/1500101.shtml">江苏省风电项目政策清单发布</a><span>2026-10-15</span></li>
          <li><a href="https://news.bjx.com.cn/html/20261012/1500102.shtml">天津新能源上网电价政策公布</a><time datetime="2026-10-12">2026-10-12</time></li>
          <li><a href="https://news.bjx.com.cn/html/20261009/1500103.shtml">山东风电并网管理规定征求意见</a><span>2026-10-09</span></li>
          <li><a href="https://news.bjx.com.cn/html/20261008/1500104.shtml">2026-10-08新疆风电政策新变化</a></li>
          <li><a href="https://news.bjx.com.cn/html/20261008/1500103.shtml">企业项目新闻</a><span>2026-10-08</span></li>
          </ul><a href="/zc/2/">下一页</a>
          <a href="https://news.bjx.com.cn/special/2026">风电产业新闻专区</a></html>'''
        got=parse_bjx_policy_directory(page,BJX_DIRECTORY)
        self.assertEqual(got['eligible_rows'],4)
        self.assertEqual(got['dated_rows'],3)
        self.assertEqual(got['undated_policy_rows'],1)
        self.assertFalse(got['explicit_single_page'])
        self.assertTrue(got['selector_matched'])
        self.assertEqual(got['next_urls'],['https://fd.bjx.com.cn/zc/2/'])
        self.assertEqual(got['links'][0]['date'],'2026-10-15')
        self.assertEqual(got['links'][-1]['date'],'')

    def test_media_missing_and_malformed_links(self):
        got=parse_bjx_policy_directory('''<html><a href="/zc/2/">下一页</a>
        <a href="https://evil.invalid/html/20261012/9999.shtml">江苏风电通知</a>
        <li><a href="https://news.bjx.com.cn/html/20261012/12345.shtml">广东出台风电相关规定</a><em>2026-02-31</em></li></html>''',BJX_DIRECTORY)
        self.assertEqual(got['eligible_rows'],1)
        self.assertEqual(got['dated_rows'],0)
        self.assertFalse(got['chronological'] is False)
        self.assertTrue(got['next_urls'])

    def test_gov_outbound_links_are_clues_not_verified_statutes(self):
        body=mock_news_article()
        urls=official_link_candidates(body,'https://news.bjx.com.cn/html/20261013/1515993.shtml')
        self.assertEqual(len(urls),1)
        self.assertIn('www.jiangsu.gov.cn',urls[0])
        self.assertNotIn('news.bjx.com.cn',urls[0])

    def test_relevance_generalized_policy_checks_body(self):
        self.assertTrue(plausible_wind_policy('天津新能源上网电价政策', '根据规定风电和光伏参加竞价'))
        self.assertFalse(plausible_wind_policy('天津新能源上网电价政策', '只有光伏项目参与竞价'))
        self.assertTrue(plausible_wind_policy('江苏海上风电退役办法'))
        self.assertFalse(plausible_wind_policy('招聘岗位和展会介绍'))

    def test_structural_discovery_recognizes_4_dated_rows_and_ignores_navigation(self):
        nav='<nav>'+''.join('<a href="/nav/%s">主管部门政策资源介绍</a>'%i for i in range(9))+'</nav>'
        rows='<main><ul class="publist">'+''.join(
            f'<li><a href="/article/{i}.html">关于加强风电项目并网运行管理的通知第{i}号</a><span>2026-10-{15-i:02d}</span></li>'
            for i in range(5))+'</ul></main>'
        html='<html>'+nav+rows+'</html>';base='https://fgw.example.gov.cn/policy/'
        found=discover_repeating_rows(html,base,parse_date=crawler.parse_date,
            normalize_url=crawler.normalize_url,
            allowed_link=lambda origin,candidate:crawler.same_site(origin,candidate))
        self.assertEqual(found['confidence'],'repeated_dated_rows')
        self.assertEqual(found['rows'],5)
        self.assertEqual(found['dated_rows'],5)
        self.assertTrue(all('/article/' in x['href'] for x in found['anchors']))

    def test_title_date_does_not_certify_complete_listing(self):
        base='https://gov.example.gov.cn/zc/'
        html='<main><ul>'+''.join(
            '<li><a href="/a/%s">2026-10-0%s风电政策发布说明</a></li>'%(i,i)
            for i in range(1,5))+'</ul></main>'
        src=next(s for s in SOURCES if s['id']=='cn_24e54ba38a1a')
        parsed=crawler._listing_page(html,base,crawler.load_adapter(src))
        self.assertEqual(parsed['dated_rows'],0)
        self.assertNotEqual(parsed['eligible_rows'],0)

    def test_media_article_carries_province_and_is_never_official_evidence(self):
        candidate={'title':'江苏出台海上风电退役管理规定','date':date.today().isoformat(),
                   'url':'https://news.bjx.com.cn/html/20261013/1515993.shtml','rank':9}
        obj,reason=crawler.make_record(MEDIA,candidate,mock_news_article(),candidate['url'],'html',
                                       DIMS,date.today()-timedelta(days=30),{})
        self.assertEqual(reason,'')
        self.assertEqual(obj['province'],'江苏')
        self.assertEqual(obj['discovery_channel'],'professional_media')
        self.assertFalse(obj['article_evidence_available'])
        self.assertIn('待官方原文核验',obj['verification_status'])
        self.assertEqual(len(obj['linked_official_urls']),1)
        self.assertNotEqual(obj['url'],obj['linked_official_urls'][0])

    def test_status_media_clue_does_not_claim_official_coverage(self):
        policy={'source_id':MEDIA_SOURCE_ID,'title':'云南发布风电竞配细则','province':'云南'}
        got=build_province_report(SOURCES,[],[policy])
        row=next(x for x in got['provinces'] if x['province']=='云南')
        self.assertEqual(row['status'],'media_clues_only')
        self.assertEqual(row['verified_official_catalogues'],0)
        self.assertEqual(row['media_clues'],1)

    def test_site_specific_media_follows_two_real_page_links_no_guessed_url(self):
        new=date.today().isoformat();yesterday=(date.today()-timedelta(days=1)).isoformat()
        old=(date.today()-timedelta(days=45)).isoformat()
        older=(date.today()-timedelta(days=60)).isoformat()
        def directory(items, nextpage=''):
            links=''.join('<li><a href="https://news.bjx.com.cn/html/20261015/%s.shtml">%s</a><span>%s</span></li>'%(n,t,d) for n,t,d in items)
            return '<main><ul>'+links+'</ul>'+('<a href="/zc/2/">下一页</a>' if nextpage else '')+'</main>'
        first=directory([('123456','江苏风电项目并网管理通知',new),
                         ('123457','天津新能源上网电价政策通知',yesterday),
                         ('123458','山东风电建设管理办法',old)],'2')
        second=directory([('123459','河北风电项目配置管理办法',older)])
        def fake_fetch(url):
            if url==BJX_DIRECTORY:return first,url,'html'
            if url=='https://fd.bjx.com.cn/zc/2/':return second,url,'html'
            return mock_news_article('江苏风电项目并网管理通知'),url,'html'
        with patch.object(crawler,'fetch',side_effect=fake_fetch), patch.object(crawler,'BROWSER_ENABLED',False):
            items,reviews,status=crawler.scrape_one(MEDIA,DIMS,date.today()-timedelta(days=30),{})
        self.assertEqual(status['listing_pages'],2)
        self.assertEqual(status['candidate_dated_links'],4)
        self.assertTrue(status['listing_coverage_complete'])
        self.assertTrue(all(x['source_id']==MEDIA_SOURCE_ID for x in items))
        self.assertTrue(all(x['discovery_channel']=='professional_media' for x in items))


if __name__=='__main__':unittest.main()
