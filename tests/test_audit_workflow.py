"""Audit routing, failure behavior and notebook execution contracts."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import audit_workflow as audits
import server_downloader as server


class AuditWorkflowTests(unittest.TestCase):
    def test_scell_candidate_requires_only_its_active_report(self):
        item = next(item for item in audits.AUDITS if item['id'] == 'scell-candidate')
        self.assertEqual(item['outputs'], ['Vivo Reports/LTE/LTE Mobilidade/Audit_sCellCandidate.xlsx'])
        # The priority export is inside a multiline string, not executable code.
        import ast
        exports = []
        for _, source in audits.notebook_cells(item['path']):
            for node in ast.walk(ast.parse(source)):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'to_excel':
                    exports.append(ast.unparse(node))
        self.assertFalse(any('scellpriority_Higa' in call for call in exports))

    def test_output_mapping_keeps_directory_separator_for_notebook_concatenation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notebook = root / 'audit.ipynb'
            notebook.write_text(json.dumps({'cells': [{'cell_type': 'code', 'source': [
                "from pathlib import Path\nfolder = 'C:/Vivo Reports/Sites Novos/'\n",
                "Path(folder + 'report.xlsx').write_text('updated')\n"]}]}))
            item = dict(id='fixture', path=str(notebook), outputs=['Vivo Reports/Sites Novos/report.xlsx'])
            def mapped(path):
                return root / str(path).replace('\\', '/').replace('C:/', '')
            with redirect_stdout(StringIO()):
                audit_workflow_result = audits.execute_audit(item, 46, output_mapper=mapped)
            self.assertEqual(mapped(Path('C:/Vivo Reports/Sites Novos/report.xlsx')).read_text(), 'updated')

    def test_planning_includes_nearest_before_it(self):
        items = audits.selected_audits(['nrpci-planning'])
        self.assertEqual([item['id'] for item in items], ['nearest-nrpci', 'nrpci-planning'])
        with patch.object(audits, 'check_audit', return_value=[]) as check, \
             patch.object(audits, 'execute_audit', return_value=[]) as execute, redirect_stdout(StringIO()):
            audits.run_audits(['nrpci-planning'])
            self.assertEqual(execute.call_count, 2)
            self.assertIn(audits.resolved_files(items[0], 'outputs', 46)[0], check.call_args_list[1].args[2])

    def test_python_script_gets_its_own_arguments_and_restores_process_state(self):
        import sys
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'audit.py'
            output = Path(directory) / 'result.txt'
            source = ("from __future__ import annotations\nimport argparse\nfrom pathlib import Path\n"
                      "parser = argparse.ArgumentParser()\nparser.add_argument('--value', default='original')\n"
                      f"Path({str(output)!r}).write_text(parser.parse_args().value)\n")
            path.write_text(source)
            original_argv, original_path = sys.argv, sys.path[:]
            with redirect_stdout(StringIO()):
                audits.execute_audit(dict(id='script', path=str(path), outputs=[]), 46)
            self.assertEqual(output.read_text(), 'original')
            self.assertIs(sys.argv, original_argv)
            self.assertEqual(sys.path, original_path)
            self.assertEqual(path.read_text(), source)

    def test_python_script_nonzero_exit_is_reported_as_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'failure.py'
            path.write_text('raise SystemExit(2)')
            with redirect_stdout(StringIO()), self.assertRaisesRegex(RuntimeError, 'código 2'):
                audits.execute_audit(dict(id='script', path=str(path), outputs=[]), 46)

    def test_selection_uses_registered_order_and_rejects_unknown_notebooks(self):
        identifiers = [item['id'] for item in audits.AUDITS]
        self.assertEqual([item['id'] for item in audits.selected_audits(identifiers[::-1])], identifiers)
        for invalid in ([], None, ['../../other.ipynb'], 'capacity-state', [1]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                audits.selected_audits(invalid)

    def test_preflight_checks_whole_batch_before_writing_reports(self):
        items = audits.AUDITS[:2]
        with patch.object(audits, 'check_audit', side_effect=[[], ['Missing input']]), \
             patch.object(audits, 'execute_audit') as execute, redirect_stdout(StringIO()):
            with self.assertRaisesRegex(ValueError, 'Nenhum audit'):
                audits.run_audits([item['id'] for item in items])
            execute.assert_not_called()

    def test_runtime_failure_stops_later_audits(self):
        items = audits.AUDITS[:3]
        with patch.object(audits, 'check_audit', return_value=[]), \
             patch.object(audits, 'execute_audit', side_effect=[['report.xlsx'], RuntimeError('bad schema')]) as execute, \
             redirect_stdout(StringIO()) as log:
            with self.assertRaisesRegex(RuntimeError, 'bad schema'):
                audits.run_audits([item['id'] for item in items])
            self.assertEqual(execute.call_count, 2)
            events = [json.loads(line.split('=', 1)[1]) for line in log.getvalue().splitlines() if line.startswith('AUDIT_EVENT=')]
            self.assertEqual([event['status'] for event in events], ['completed', 'failed'])
            self.assertNotIn('AUDITS COMPLETED.', log.getvalue())

    def test_notebook_keeps_cell_state_and_original_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            notebook = root / 'audit.ipynb'
            output = root / 'result.txt'
            notebook.write_text(json.dumps({'cells': [
                {'cell_type': 'code', 'source': ['value = 40\n']},
                {'cell_type': 'markdown', 'source': ['Documentation']},
                {'cell_type': 'code', 'source': ['from pathlib import Path\n', f'Path({str(output)!r}).write_text(str(value + 2))\n']},
            ]}), encoding='utf-8')
            original = notebook.read_bytes()
            item = dict(id='fixture', path=str(notebook), outputs=[])
            with redirect_stdout(StringIO()):
                audits.execute_audit(item, 46)
            self.assertEqual(output.read_text(), '42')
            self.assertEqual(notebook.read_bytes(), original)

    def test_exception_reports_notebook_and_cell(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'broken.ipynb'
            path.write_text(json.dumps({'cells': [{'cell_type': 'code', 'source': ["raise ValueError('invalid input')"]}]}))
            with redirect_stdout(StringIO()), self.assertRaisesRegex(RuntimeError, 'broken.ipynb, célula 0: invalid input'):
                audits.execute_audit(dict(id='broken', path=str(path), outputs=[]), 46)

    def test_missing_report_is_a_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'empty.ipynb'
            path.write_text(json.dumps({'cells': []}))
            item = dict(id='empty', path=str(path), outputs=['Vivo Reports/report.xlsx'])
            with self.assertRaisesRegex(RuntimeError, 'Relatório não foi gerado'):
                audits.execute_audit(item, 46, lambda p: Path(directory) / p.name)

    def test_api_rejects_arbitrary_paths_and_busy_workflow(self):
        client = server.app.test_client()
        self.assertEqual(client.post('/api/run-audits', json={'audit_ids': ['C:/arbitrary.ipynb']}).status_code, 400)
        self.assertEqual(client.post('/api/run-audits', json=['unexpected']).status_code, 400)
        self.assertEqual(client.post('/api/run-audits', json={}).status_code, 400)
        server._workflow_lock.acquire()
        try:
            self.assertEqual(client.post('/api/run-audits', json={'audit_ids': [audits.AUDITS[0]['id']]}).status_code, 409)
        finally:
            server._workflow_lock.release()

    def test_old_report_does_not_count_as_a_successful_run(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'empty.ipynb'
            path.write_text(json.dumps({'cells': []}))
            (Path(directory) / 'report.xlsx').write_text('old result')
            item = dict(id='empty', path=str(path), outputs=['Vivo Reports/report.xlsx'])
            with self.assertRaisesRegex(RuntimeError, 'não foi atualizado'):
                audits.execute_audit(item, 46, lambda p: Path(directory) / p.name)

    def test_api_streams_exit_failure_and_releases_lock(self):
        client = server.app.test_client()
        def fake_script(*args):
            yield 'notebook failed\n'
            return 1
        with patch.object(server, '_stream_checked_script', fake_script):
            response = client.post('/api/run-audits', json={'audit_ids': [audits.AUDITS[0]['id']]})
            self.assertIn(b'AUDITS FAILED.', response.data)
            response.close()
        self.assertFalse(server._workflow_lock.locked())


if __name__ == '__main__':
    unittest.main()
