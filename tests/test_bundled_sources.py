import ast
import hashlib
import json
from pathlib import Path
import tempfile
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import audit_workflow
import bundled_sources as bundled
import server_downloader as server
import weekly_workflow


class BundledSourcesTests(unittest.TestCase):
    def test_scripts_are_shipped_without_saved_notebook_outputs(self):
        manifest = json.loads((bundled.SCRIPT_ROOT / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(len(manifest['scripts']), 21)
        for entry in manifest['scripts']:
            path = bundled.SCRIPT_ROOT / entry['file']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry['sha256'])
            if path.suffix == '.ipynb':
                document = json.loads(path.read_text(encoding='utf-8'))
                for cell in document['cells']:
                    if cell['cell_type'] == 'code':
                        self.assertEqual(cell['outputs'], [])
                        self.assertIsNone(cell['execution_count'])
                for index, source in weekly_workflow.notebook_cells(path):
                    ast.parse(source, filename=f'{path.name}:{index}')
            else:
                ast.parse(path.read_text(encoding='utf-8-sig'))

    def test_preflight_and_audits_use_internal_sources(self):
        self.assertEqual(Path(weekly_workflow.DEFAULT_NOTEBOOK_DIR), bundled.WEEKLY_SCRIPTS)
        self.assertTrue(all(Path(item['path']).is_relative_to(bundled.AUDIT_SCRIPTS) for item in audit_workflow.AUDITS))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'cellref.xlsx').touch()
            mos = weekly_workflow.preflight(dict(reference_dir=directory, output_dir=str(root / 'output'), enriched_dir=str(root / 'reports')))
            self.assertIn('EUtranCellFDD', mos)
        self.assertTrue(all(item['embedded'] and Path(item['path']).name == item['path'] for item in audit_workflow.catalog()['audits']))

    def test_api_overrides_legacy_external_code_directories(self):
        seen = []
        def stream(config):
            seen.append(config)
            yield 'checked\n'
        with patch.object(server, 'stream_weekly_workflow', stream):
            response = server.app.test_client().post('/api/run-weekly-workflow', json=dict(
                input_dir='C:/Dumps/todos_enms', notebook_dir='C:/external', cellref={'scripts_dir': 'C:/external'}))
            self.assertEqual(response.status_code, 200)
            response.get_data()
            response.close()
        self.assertEqual(Path(seen[0]['notebook_dir']), bundled.WEEKLY_SCRIPTS)
        self.assertEqual(Path(seen[0]['cellref']['scripts_dir']), bundled.CELLREF_SCRIPTS)

    def test_builds_include_the_script_assets(self):
        root = bundled.SCRIPT_ROOT.parent
        for name in ['Downloader.spec', 'Downloader_debug.spec', 'Downloader_tmp.spec', 'build_nuitka.ps1']:
            source = (root / name).read_text(encoding='utf-8')
            self.assertIn('bundled_scripts', source)
            self.assertIn('bundled_sources.py', source)
            self.assertIn('audit_exports.py', source)

    def test_weekly_worker_preflight_works_from_an_isolated_app_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ['weekly_workflow.py', 'bundled_sources.py']:
                shutil.copy2(bundled.SCRIPT_ROOT.parent / name, root / name)
            shutil.copytree(bundled.SCRIPT_ROOT, root / 'bundled_scripts')
            (root / 'references').mkdir()
            (root / 'references/cellref.xlsx').touch()
            config = dict(reference_dir=str(root / 'references'), output_dir=str(root / 'output'), enriched_dir=str(root / 'reports'))
            (root / 'config.json').write_text(json.dumps(config))
            result = subprocess.run([sys.executable, str(root / 'weekly_workflow.py'), str(root / 'config.json'), '--check'],
                                    cwd=root, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PREFLIGHT OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
