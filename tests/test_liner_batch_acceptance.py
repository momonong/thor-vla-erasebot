"""Host-owned acceptance for a real offline Thor development task; no model calls."""
import importlib
import io
import json
import shutil
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stdout
from pathlib import Path

from erasebot.selection import InputError

FIXTURES = Path('fixtures/liner-evaluation')


class BatchAcceptance(unittest.TestCase):
    def setUp(self):
        try:
            self.module = importlib.import_module('tools.liner_batch')
        except ImportError:
            self.fail('Missing required tools.liner_batch implementation')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for source in FIXTURES.glob('*.json'):
            shutil.copyfile(source, self.root / source.name)

    def manifest(self, names, **overrides):
        entries = []
        for name in names:
            obs = json.loads((self.root / (name + '.json')).read_text())
            entries.append(dict(case_id=obs['case_id'], material='A', method='fixed_script',
                                target='target.json', observation=name + '.json', **overrides))
        path = self.root / 'batch.json'
        path.write_text(json.dumps(dict(schema_version=1, entries=entries)))
        return path

    def test_six_original_cases_are_all_preserved_and_never_claim_robot_success(self):
        report = self.module.evaluate_batch(self.manifest(
            ['clear', 'partial', 'folded', 'unknown-fold', 'wrong-target', 'not-run']))
        self.assertEqual(Counter(x['status'] for x in report['cases']), {
            'criteria_met': 1, 'criteria_not_met': 2, 'insufficient_evidence': 1,
            'invalid_input': 1, 'not_run': 1})
        self.assertIs(report['robot_validated'], False)
        self.assertIs(report['source_references_verified'], False)
        self.assertEqual(report['mode'], 'offline')
        self.assertEqual(sum(g['total'] for g in report['groups']), 6)
        for group in report['groups']:
            self.assertIsNone(group['success_rate'])
        self.assertTrue(report['limitations'])

    def test_denominator_and_unrun_are_explicit(self):
        report = self.module.evaluate_batch(self.manifest(['clear', 'partial']))
        self.assertEqual(len(report['groups']), 1)
        group = report['groups'][0]
        self.assertEqual(group['attempted'], 2)
        self.assertEqual(group['success_rate'], 0.5)
        self.assertEqual(group['counts'], {'criteria_met':1, 'criteria_not_met':1,
            'insufficient_evidence':0, 'invalid_input':0, 'not_run':0})
        unrun = self.module.evaluate_batch(self.manifest(['not-run']))['groups'][0]
        self.assertEqual(unrun['attempted'], 0)
        self.assertIsNone(unrun['success_rate'])

    def test_invalid_case_alone_prevents_an_inflated_success_rate(self):
        report=self.module.evaluate_batch(self.manifest(['clear','wrong-target']))
        self.assertEqual(len(report['cases']),2)
        invalid_group=next(g for g in report['groups'] if g['counts']['invalid_input'])
        self.assertIsNone(invalid_group['success_rate'])

    def test_evidence_material_and_method_are_not_pooled(self):
        p=self.manifest(['clear']);d=json.loads(p.read_text());base=d['entries'][0]
        seen=json.loads((self.root/'clear.json').read_text());seen['evidence_kind']='offline_annotation'
        (self.root/'annotation.json').write_text(json.dumps(seen))
        d['entries'] += [dict(base, material='B'),dict(base, method='visual_feedback'),
                        dict(base, method='learned_policy', observation='annotation.json')]
        p.write_text(json.dumps(d));r=self.module.evaluate_batch(p)
        self.assertEqual(len(r['groups']),4)
        self.assertEqual({g['evidence_kind'] for g in r['groups']},{'synthetic_fixture','offline_annotation'})

    def test_duplicate_and_identity_mismatch_are_errors_not_silent_dedup(self):
        p=self.manifest(['clear']);d=json.loads(p.read_text());d['entries']*=2;p.write_text(json.dumps(d))
        with self.assertRaises(InputError):self.module.evaluate_batch(p)
        p=self.manifest(['clear']);d=json.loads(p.read_text());d['entries'][0]['case_id']='wrong';p.write_text(json.dumps(d))
        with self.assertRaises(InputError):self.module.evaluate_batch(p)

    def test_manifest_validation_and_paths_do_not_escape_scope(self):
        for text in ['{"schema_version":true,"entries":[]}', '{"schema_version":1,"schema_version":1,"entries":[]}', '{"schema_version":NaN,"entries":[]}']:
            p=self.root/'bad.json';p.write_text(text)
            with self.assertRaises(InputError):self.module.evaluate_batch(p)
        external=tempfile.TemporaryDirectory();self.addCleanup(external.cleanup)
        outside=Path(external.name)/'target.json'
        outside.write_bytes((self.root/'target.json').read_bytes())
        for target in [str(outside),'../'+outside.parent.name+'/target.json']:
            p=self.manifest(['clear']);d=json.loads(p.read_text());d['entries'][0]['target']=target;p.write_text(json.dumps(d))
            try:r=self.module.evaluate_batch(p)
            except InputError:continue
            self.assertEqual(r['cases'][0]['status'],'invalid_input')
            self.assertIsNone(r['groups'][0]['success_rate'])
        link=self.root/'linked.json';link.symlink_to(self.root/'clear.json')
        p=self.manifest(['clear']);d=json.loads(p.read_text());d['entries'][0]['observation']='linked.json';p.write_text(json.dumps(d))
        try:r=self.module.evaluate_batch(p)
        except InputError:return
        self.assertEqual(r['cases'][0]['status'],'invalid_input')

    def test_cli_and_markdown_are_reproducible_and_no_traceback(self):
        p=self.manifest(['clear','partial']);out=io.StringIO()
        with redirect_stdout(out):code=self.module.main(['--manifest',str(p)])
        self.assertEqual(code,1);self.assertEqual(len(json.loads(out.getvalue())['cases']),2)
        r=self.module.evaluate_batch(self.manifest(['not-run']));md=self.module.render_markdown(r)
        self.assertIsInstance(md,str);self.assertIn('not_run',md)
        self.assertTrue('unknown' in md.lower() or '未知' in md)
        self.assertNotIn('0%',md)
        out=io.StringIO()
        with redirect_stdout(out):code=self.module.main(['--manifest',str(self.root/'missing.json')])
        self.assertEqual(code,3);self.assertEqual(json.loads(out.getvalue())['status'],'invalid_input')

    def test_usage_delivery_exists(self):
        doc=Path('docs/development/batch-report.md')
        self.assertTrue(doc.is_file(),'Missing required usage and evidence-limit document')
        text=doc.read_text();self.assertIn('--manifest',text)
        self.assertTrue('未實機驗證' in text or '未完成實機驗證' in text or '不是實機' in text)


if __name__ == '__main__':
    unittest.main()
