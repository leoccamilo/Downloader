from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from openpyxl import load_workbook
import audit_exports
import audit_workflow


class AuditExportTests(unittest.TestCase):
    def test_split_preserves_all_rows_columns_and_order_with_repeated_headers(self):
        frame = pd.DataFrame({'label': ['001', '002', '003', '004', '005'], 'value': [1, 2, None, 4, 5]})
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'result.xlsx'
            with patch.object(audit_exports, 'MAX_EXCEL_ROWS', 4), redirect_stdout(StringIO()):
                audit_exports.write_audit_excel(frame, target, index=False)
            book = load_workbook(target, read_only=True, data_only=True)
            rows = []
            self.assertEqual(book.sheetnames, ['Sheet1_1', 'Sheet1_2'])
            for sheet in book:
                content = list(sheet.values)
                self.assertEqual(content[0], ('label', 'value'))
                self.assertLessEqual(len(content), 4)
                rows.extend(content[1:])
            book.close()
            self.assertEqual([row[0] for row in rows], frame['label'].tolist())
            self.assertEqual([row[1] for row in rows], [1, 2, None, 4, 5])

    def test_boundary_keeps_original_single_sheet_and_no_index(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'result.xlsx'
            with patch.object(audit_exports, 'MAX_EXCEL_ROWS', 4):
                audit_exports.write_audit_excel(pd.DataFrame({'a': [1, 2, 3]}), target, index=None)
            book = load_workbook(target, read_only=True)
            self.assertEqual(book.sheetnames, ['Sheet1'])
            self.assertEqual(list(book.active.values), [('a',), (1,), (2,), (3,)])
            book.close()

    def test_new_sites_rebuild_is_idempotent_and_removes_old_duplicates(self):
        path = Path(next(item['path'] for item in audit_workflow.AUDITS if item['id'] == 'new-sites'))
        document = json.loads(path.read_text(encoding='utf-8'))
        code = ''.join(document['cells'][7]['source'])
        end = ''.join(document['cells'][9]['source'])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'Sites_Novos_46.xlsx'
            lte = pd.DataFrame([dict(Ano=2026, Semana=46, Regional='N', UF='AM', eNB='node', CELL='cell')]*2)
            nr = pd.DataFrame([dict(Ano=2026, Semana=46, Regional='N', UF='AM', gNB='node', nRCellDUId='cell')]*2)
            with pd.ExcelWriter(source) as writer:
                lte.to_excel(writer, sheet_name='Setores Novos LTE', index=False)
                nr.to_excel(writer, sheet_name='Setores Novos NR', index=False)
            # Only the two workbook locations change in the validation code.
            import ast
            class Paths(ast.NodeTransformer):
                def visit_Constant(self, node):
                    if isinstance(node.value, str):
                        value = node.value.replace('\\', '/')
                        if value.endswith('Sites Novos/*.xlsx'):
                            return ast.copy_location(ast.Constant(str(root / '*.xlsx')), node)
                        if 'Historico_' in value and value.endswith('.xlsx'):
                            return ast.copy_location(ast.Constant(str(root / 'history/result.xlsx')), node)
                    return node
            (root / 'history').mkdir()
            tree = ast.fix_missing_locations(Paths().visit(ast.parse(code)))
            for _ in range(2):
                with redirect_stdout(StringIO()):
                    namespace = {}
                    exec(compile(tree, str(path), 'exec'), namespace)
                    exec(end, namespace)
                for frame in pd.read_excel(root / 'history/result.xlsx', sheet_name=None).values():
                    self.assertEqual(len(frame), 1)
                    self.assertEqual(int(frame.duplicated().sum()), 0)


if __name__ == '__main__':
    unittest.main()
