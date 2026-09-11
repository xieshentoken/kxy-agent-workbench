"""Independent integration checks; no real model calls or private input data.
Run with the installed kxy Python: python acceptance/supervisor_checks.py.
"""
import io
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

TEST_ROOT = tempfile.TemporaryDirectory(prefix='kxy-supervisor-')
os.environ['KXY_DATA_ROOT'] = TEST_ROOT.name
os.environ.setdefault('LANGFLOW_CONFIG_DIR', str(Path(TEST_ROOT.name) / 'lfx'))
os.environ['DO_NOT_TRACK'] = 'true'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend import app as m
from fastapi.testclient import TestClient
from openpyxl import Workbook
from pypdf import PdfWriter


class IntegrationChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client_context = TestClient(m.app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)

    def run_workflow(self, workflow):
        response = self.client.post('/api/runs', json={'workflow': workflow})
        self.assertEqual(response.status_code, 200, response.text)
        identifier = response.json()['id']
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            result = self.client.get('/api/runs/' + identifier).json()
            if result['status'] in ('succeeded', 'failed', 'cancelled', 'interrupted'):
                return result
            time.sleep(.05)
        self.fail('Integration run did not terminate')

    def test_condition_preserves_input_on_both_paths(self):
        for expected, target in [('source', 'yes'), ('other', 'no')]:
            with self.subTest(target=target):
                flow = {'version': 'kxy.workflow.v1', 'nodes': [
                    {'id': 'input', 'type': 'text', 'data': {'text': 'KEEP_THIS_PAYLOAD'}},
                    {'id': 'condition', 'type': 'condition', 'data': {'field': 'status', 'operator': 'equals', 'expected': expected}},
                    {'id': 'yes', 'type': 'container', 'data': {}},
                    {'id': 'no', 'type': 'container', 'data': {}},
                ], 'edges': [
                    {'source': 'input', 'target': 'condition'},
                    {'source': 'condition', 'target': 'yes', 'sourceHandle': 'true'},
                    {'source': 'condition', 'target': 'no', 'sourceHandle': 'false'},
                ]}
                result = self.run_workflow(flow)
                self.assertEqual(result['status'], 'succeeded', result.get('error'))
                outputs = {item['node_id']: item for item in result['nodes']}
                self.assertIn('KEEP_THIS_PAYLOAD', json.dumps(outputs[target]['output']))
                self.assertEqual(outputs['no' if target == 'yes' else 'yes']['status'], 'skipped')

    def test_missing_condition_field_fails_run(self):
        result = self.run_workflow({'nodes': [
            {'id': 'input', 'type': 'text', 'data': {'text': 'known'}},
            {'id': 'condition', 'type': 'condition', 'data': {'field': 'missing', 'operator': 'equals', 'expected': 'x'}},
            {'id': 'output', 'type': 'container', 'data': {}},
        ], 'edges': [{'source': 'input', 'target': 'condition'}, {'source': 'condition', 'target': 'output', 'sourceHandle': 'false'}]})
        self.assertEqual(result['status'], 'failed', result)

    def test_empty_pdf_does_not_become_parsed_from_page_labels(self):
        writer = PdfWriter(); writer.add_blank_page(width=200, height=200)
        data = io.BytesIO(); writer.write(data)
        response = self.client.post('/api/files', files={'file': ('blank.pdf', data.getvalue())})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(response.json()['status'], ('parsed', 'parsed-truncated'))

    def test_xlsx_preserves_zero_false_and_row_locations(self):
        book = Workbook(); sheet = book.active; sheet.title = 'Numbers'
        sheet.append(['amount', 'checked']); sheet.append([0, False])
        data = io.BytesIO(); book.save(data)
        response = self.client.post('/api/files', files={'file': ('zero.xlsx', data.getvalue())})
        self.assertEqual(response.status_code, 200)
        text = response.json()['preview']
        self.assertIn('0', text)
        self.assertIn('False', text)
        self.assertTrue('row' in text.lower() or '行' in text or 'A2' in text, text)

    def test_skill_frontmatter_is_metadata(self):
        import zipfile
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('example/SKILL.md', '---\nname: revenue-method\ndescription: Compare revenue with source references.\n---\n\n# Different heading\nRead references/method.md.\n')
            archive.writestr('example/references/method.md', 'Do not infer missing margins.\n')
        response = self.client.post('/api/skills/import-zip', files={'file': ('method.zip', data.getvalue())})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['name'], 'revenue-method')
        self.assertEqual(response.json()['description'], 'Compare revenue with source references.')

    def test_rejects_bad_workflow_version_and_handles(self):
        valid = {'version': 'kxy.workflow.v1', 'nodes': [
            {'id': 'a', 'type': 'text', 'data': {'text': 'a'}},
            {'id': 'b', 'type': 'container', 'data': {}},
        ], 'edges': [{'source': 'a', 'target': 'b'}]}
        for mutation in ['version', 'sourceHandle', 'targetHandle']:
            with self.subTest(mutation=mutation):
                flow = json.loads(json.dumps(valid))
                if mutation == 'version': flow['version'] = 'untrusted.future.version'
                else: flow['edges'][0][mutation] = 'nonexistent'
                result = self.client.post('/api/workflows/validate', json=flow)
                self.assertTrue(result.status_code == 422 or result.json().get('ok') is False, result.text)

    def test_production_origin_allowed_external_origin_blocked(self):
        good = self.client.put('/api/settings', json=m.DEFAULT_SETTINGS, headers={'origin': 'http://127.0.0.1:8710', 'host': '127.0.0.1:8710'})
        self.assertEqual(good.status_code, 200, good.text)
        bad = self.client.put('/api/settings', json=m.DEFAULT_SETTINGS, headers={'origin': 'https://unrelated.invalid', 'host': '127.0.0.1:8710'})
        self.assertEqual(bad.status_code, 403, bad.text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
