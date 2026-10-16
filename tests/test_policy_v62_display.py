"""V6.2: stable data shape and optional public-evidence AI analysis (offline fixtures)."""
from __future__ import annotations
import csv
import hashlib
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import build_site_data as builder
import policy_ai_enrich as ai


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding='utf-8')


class BuildDisplayData(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.data = self.root / 'site' / 'data'
        self.data.mkdir(parents=True)
        self.today = (date.today() - timedelta(days=2)).isoformat()
        self.source = {'id': 'src', 'region': '中国', 'country': '中国', 'name': '新能源主管部门'}
        write_json(self.root / 'policy_sources.json', [self.source])
        write_json(self.root / 'regulatory_dimensions.json', [{'name': '并网技术规范', 'description': '风电并网'}])
        self.good = {'id': 'p-1', 'source_id': 'src', 'title': '风电机组并网技术规范通知',
                     'url': 'https://example.gov.cn/reg/12', 'published_at': self.today,
                     'source_region': '国内', 'country': '中国·中国·北京市',
                     'evidence': '第一条 风电机组应当提供并网技术文件以及相应检测资料，适用范围以发布文件为准。',
                     'dimensions': ['并网技术规范'], 'product_impact': '核查风机并网测试与控制策略，不代表义务已确认。'}

    def test_legacy_record_converts_with_quote_and_product_impact(self):
        write_json(self.data / 'policies.json', [self.good])
        result = builder.build(self.root)
        self.assertEqual(len(result), 1)
        row = result[0]
        self.assertEqual(row['published_at'], self.today)
        self.assertEqual(row['region'], '国内')
        self.assertEqual(row['country'], '北京市')
        self.assertEqual(row['dimensions'], ['并网技术规范'])
        self.assertIn('并网技术文件', row['source_excerpt'])
        self.assertIn('核查风机并网测试', row['impact_design'])
        self.assertIn('规则辅助', row['analysis_method'])
        csv_text = (self.data / 'policies.csv').read_text(encoding='utf-8-sig')
        self.assertIn('产品设计影响分析', csv_text)
        self.assertIn('https://example.gov.cn/reg/12', csv_text)
        # Building a stable display projection must not erase original records.
        self.assertEqual(json.loads((self.data / 'policies.json').read_text())[0]['id'], 'p-1')

    def test_undated_future_and_unrelated_not_passed_as_recent_laws(self):
        future = (date.today() + timedelta(days=3)).isoformat()
        raw = [dict(self.good, id='a', url='https://example.gov.cn/undated', published_at='', issued_at=self.today),
               dict(self.good, id='b', url='https://example.gov.cn/future', published_at=future),
               dict(self.good, id='c', url='https://example.gov.cn/unrelated',
                    title='关于做好经济社会发展工作的通知', evidence='本年度有序推进公共行政服务各项工作计划的制度措施。'),
               dict(self.good, id='d', url='javascript:alert(1)')]
        write_json(self.data / 'policies.json', raw)
        self.assertEqual(builder.build(self.root), [])

    def test_dedupe_prefers_cited_evidence_over_empty_stub(self):
        stub = dict(self.good, source_excerpt='', evidence='', dimensions=[])
        write_json(self.data / 'policies.json', [stub, self.good])
        rows = builder.build(self.root)
        self.assertEqual(len(rows), 1)
        self.assertIn('并网技术文件', rows[0]['source_excerpt'])

    def test_unverified_ai_cache_not_accepted(self):
        source = self.good
        write_json(self.data / 'policies.json', [source])
        write_json(self.data / 'policy_ai.json', {'analyses': {source['url']: {
            'status': 'completed', 'content_hash': 'wrong-old-evidence', 'result': {
                'product_design_impact': 'AI claims impossible consequences', 'dimensions': ['奇怪的标签']}}}})
        rows = builder.build(self.root)
        self.assertNotIn('AI claims impossible consequences', rows[0]['impact_design'])
        self.assertEqual(rows[0]['dimensions'], ['并网技术规范'])
        self.assertIn('规则辅助', rows[0]['analysis_method'])

    def test_verified_ai_cache_only_adds_analysis_and_allowed_tags(self):
        source = self.good
        e = builder.pick_excerpt(source)
        content_hash = hashlib.sha256((source['title']+'\n'+source['published_at']+'\n'+e).encode()).hexdigest()
        write_json(self.data / 'policies.json', [source])
        write_json(self.data / 'policy_ai.json', {'analyses': {source['url']: {
            'status': 'completed', 'content_hash': content_hash, 'result': {
                'product_design_impact': '建议核实电气控制软件的保护及故障穿越能力，不代表已有法律义务。',
                'dimensions': ['并网技术规范'], 'application_note': '须由法务和产品团队核查适用性。'}}}})
        rows = builder.build(self.root)
        self.assertIn('电气控制软件', rows[0]['impact_design'])
        self.assertIn('AI辅助', rows[0]['analysis_method'])
        self.assertEqual(rows[0]['source_excerpt'], e)


    def test_migrate_previous_source_ids_without_claiming_new_crawl(self):
        write_json(self.data / 'policies.json', [self.good])
        write_json(self.root / 'legacy_policy_source_aliases.json', {'old-src': 'src'})
        write_json(self.data / 'policy_source_status.json', [
            {'id': 'old-src', 'status': 'blocked', 'checked_at': '2026-10-11T00:00:00Z', 'message': '访问受限'},
            {'id': 'another-agency', 'status': 'ok_no_recent', 'message': 'not the same source'}])
        builder.build(self.root)
        statuses = builder.read(self.data / 'policy_source_status.json', [])
        self.assertEqual(len(statuses), 1)
        self.assertEqual(statuses[0]['id'], 'src')
        self.assertIn('上一版检测', statuses[0]['message'])
        self.assertEqual(statuses[0]['historical_source_id'], 'old-src')
        self.assertEqual(statuses[0]['status'], 'blocked')


class AIParsing(unittest.TestCase):
    def test_reject_unknown_tags_or_unusable_text(self):
        good = {'relevance': 'direct', 'dimensions': ['并网技术规范'],
                'product_design_impact': '建议核对风电机组并网软件以及测试报告内容是否需要调整。',
                'application_note': '具体适用范围仍需核对官方文件原文。'}
        self.assertEqual(ai.validate_result(good, {'并网技术规范'}), good)
        with self.assertRaises(ValueError):
            ai.validate_result(dict(good, dimensions=['不存在的维度']), {'并网技术规范'})
        with self.assertRaises(ValueError):
            ai.validate_result(dict(good, product_design_impact='已被证实'), {'并网技术规范'})

    def test_api_payload_is_evidence_limited_and_not_browser_search(self):
        captured = {}
        class Fake:
            def raise_for_status(self):
                pass
            def json(self):
                return {'output': [{'type': 'message', 'content': [{'type': 'output_text',
                    'text': json.dumps({'relevance': 'direct', 'dimensions': ['并网技术规范'],
                       'product_design_impact': '建议核对风机并网及电网保护软件的设计输入和测试资料。',
                       'application_note': '须核验文件适用国家和法律效力。'}, ensure_ascii=False)}]}]}
        def mocked_post(url, **kwargs):
            captured.update({'url': url, **kwargs})
            return Fake()
        output = ai.analyze({'title': '风电并网通知', 'published_at': date.today().isoformat(),
                             'url': 'https://example.gov.cn/law', 'source_excerpt': '第一条 风电机组并网应当开展例行测试，需提交标准测试报告。'},
                            ['并网技术规范'], 'fake-key', post=mocked_post)
        self.assertEqual(output['relevance'], 'direct')
        self.assertEqual(captured['url'], 'https://api.openai.com/v1/responses')
        self.assertIn('第一条', captured['json']['input'])
        self.assertFalse(captured['json']['store'])
        self.assertEqual(captured['json']['text']['format']['type'], 'json_schema')
        self.assertEqual(captured['headers']['Authorization'], 'Bearer fake-key')

    def test_no_key_makes_zero_network_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / 'site/data/policies.json', [])
            write_json(root / 'regulatory_dimensions.json', [])
            def offline(*a, **k):
                raise AssertionError('no network allowed without key')
            state = ai.run(root=root, key='', post=offline)
            self.assertEqual(state['mode'], 'rule-based-no-api-key')
            self.assertEqual(state['completed_this_run'], 0)


if __name__ == '__main__':
    unittest.main()
