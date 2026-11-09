from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest

import weekly_workflow as workflow
from xml_to_txt import parse_ericsson_xmls


XML = '''<root xmlns:g="genericNrm.xsd" xmlns:e="EricssonSpecificAttributes.xsd">
<g:MeContext id="TABC1_AM"><g:ManagedElement id="1">
<g:VsDataContainer id="FDD1"><g:attributes><g:vsDataType>vsDataEUtranCellFDD</g:vsDataType>
<e:vsDataEUtranCellFDD><e:cellId>001</e:cellId><e:label>NA</e:label></e:vsDataEUtranCellFDD>
</g:attributes></g:VsDataContainer></g:ManagedElement></g:MeContext></root>'''


class DirectWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        for name in ['raw', 'processed', 'reports', 'references', 'notebooks']:
            (self.root / name).mkdir()
        (self.root / 'raw/source.xml').write_text(XML)
        (self.root / 'raw/mos_downloader.txt').write_text('Keep the command list')
        (self.root / 'references/cellref.xlsx').touch()
        (self.root / 'references/cellref_5g.xlsx').touch()
        self.config = dict(raw_txt_dir=str(self.root / 'raw'), input_dir=str(self.root / 'raw'),
                           output_dir=str(self.root / 'processed'), enriched_dir=str(self.root / 'reports'),
                           reference_dir=str(self.root / 'references'), notebook_dir=str(self.root / 'notebooks'),
                           create_weekly=True, transfer_vivo=True, history_dir=str(self.root / 'reports'),
                           vivo_dir=str(self.root / 'vivo'), run_date='2026-11-09')
        for name in workflow.NOTEBOOKS:
            self.notebook(name, 'pass')
        self.notebook(workflow.NOTEBOOKS[2], "from pathlib import Path\nPath('C:/Camilo/EUtranCell_TDD_FDD.csv').write_text('inventory')")

    def notebook(self, name, source):
        (self.root / 'notebooks' / name).write_text(json.dumps({'cells': [dict(cell_type='code', source=source.splitlines(True))]}))

    def test_direct_xml_to_txt_and_report_notebooks_share_original_paths(self):
        source = '''import glob, pandas as pd
from pathlib import Path
base_path = r'C:/Dumps/todos_enms'
files = glob.glob(fr'{base_path}\\EUtranCellFDD_*_part*.parquet')
frame = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
assert frame.loc[0, 'cellId'] == '001'
assert frame.loc[0, 'label'] == 'NA'
frame.to_csv('C:/Dumps/LTE_Total/EUtranCellFDD.txt', sep='\\t', index=False)
semana_atual = 1
frame.to_csv('C:/Camilo/report_' + str(semana_atual) + '.txt', sep='\\t', index=False)
'''
        self.notebook(workflow.NOTEBOOKS[1], source)
        with redirect_stdout(StringIO()):
            workflow.run_workflow(self.config)
        self.assertTrue((self.root / 'raw/EUtranCellFDD.txt').is_file())
        self.assertTrue((self.root / 'processed/EUtranCellFDD.txt').is_file())
        self.assertTrue((self.root / 'reports/report_46.txt').is_file())
        self.assertEqual((self.root / 'raw/mos_downloader.txt').read_text(), 'Keep the command list')
        self.assertEqual(json.loads((self.root / 'raw/downloader_manifest.json').read_text())['status'], 'completed')
        self.assertFalse(list(self.root.rglob('*.parquet')))
        self.assertFalse(list(self.root.rglob('.weekly_runs')))
        self.assertFalse(list(self.root.rglob('.cellref_runs')))
        self.assertFalse(list(self.root.rglob('dump_*.xml')))
        self.assertEqual((self.root / 'vivo/MoB_IMP/EUtranCell_TDD_FDD.csv').read_text(), 'inventory')
        self.assertTrue((self.root / 'vivo/MoB_IMP/cellref.xlsx').exists())
        self.assertTrue((self.root / 'vivo/MoB_IMP/cellref_5g.xlsx').exists())

    def test_parser_failure_does_not_clean_unrelated_txt_or_run_reports(self):
        (self.root / 'raw/source.xml').write_text('<broken>')
        self.notebook(workflow.NOTEBOOKS[1], "raise AssertionError('reports must not start')")
        with redirect_stdout(StringIO()), self.assertRaisesRegex(RuntimeError, 'XML parsing failed'):
            workflow.run_workflow(self.config)
        self.assertTrue((self.root / 'raw/mos_downloader.txt').is_file())
        self.assertEqual(json.loads((self.root / 'raw/downloader_manifest.json').read_text())['status'], 'failed')

    def test_disabled_exports_do_not_write_to_vivo_or_history(self):
        self.config.update(create_weekly=False, transfer_vivo=False)
        self.notebook(workflow.NOTEBOOKS[1],
                      "from pathlib import Path\nPath('C:/Camilo/report_46.txt').write_text('report')\n"
                      "Path('C:/Vivo Reports/LTE/LTE MOs/test.txt').write_text('vivo')")
        with redirect_stdout(StringIO()):
            workflow.run_workflow(self.config)
        self.assertEqual((self.root / 'reports/report.txt').read_text(), 'report')
        self.assertFalse((self.root / 'reports/report_46.txt').exists())
        self.assertFalse((self.root / 'vivo').exists())

    def test_raw_and_processed_folders_cannot_overlap(self):
        self.config['output_dir'] = self.config['raw_txt_dir']
        with self.assertRaisesRegex(ValueError, 'separada'):
            workflow.run_workflow(self.config)

    def test_targeted_recovery_keeps_other_mos_and_command_files(self):
        raw = self.root / 'raw'
        (raw / 'OtherMO.txt').write_text('preserve this MO')
        xml = XML.replace('vsDataEUtranCellFDD', 'vsDataGNBCUUPFunction')
        (raw / 'target.xml').write_text(xml)
        with redirect_stdout(StringIO()):
            written = parse_ericsson_xmls(str(raw), str(raw), selected_mos={'GNBCUUPFunction'}, strict=True)
        self.assertEqual(written, {'GNBCUUPFunction': 1})
        self.assertEqual((raw / 'OtherMO.txt').read_text(), 'preserve this MO')
        self.assertEqual((raw / 'mos_downloader.txt').read_text(), 'Keep the command list')
        self.assertFalse((raw / 'EUtranCellFDD.txt').exists())

    def test_mob_import_replaces_old_references_and_inventory(self):
        config = self.config
        references = self.root / 'references'
        reports = self.root / 'reports'
        (references / 'cellref.xlsx').write_bytes(b'new LTE')
        (references / 'cellref_5g.xlsx').write_bytes(b'new NR')
        (reports / 'EUtranCell_TDD_FDD.csv').write_text('new inventory')
        workflow.publish_mob_imports(config, reports)
        target = self.root / 'vivo/MoB_IMP'
        for name in ['cellref.xlsx', 'cellref_5g.xlsx']:
            self.assertEqual((target / name).read_bytes(), (references / name).read_bytes())
        (references / 'cellref.xlsx').write_bytes(b'next LTE')
        workflow.publish_mob_imports(config, reports)
        self.assertEqual((target / 'cellref.xlsx').read_bytes(), b'next LTE')
        self.assertEqual((target / 'EUtranCell_TDD_FDD.csv').read_text(), 'new inventory')
        self.assertEqual((self.root / 'vivo/LTE/LTE MOs/EUtranCell_TDD_FDD.csv').read_bytes(),
                         (reports / 'EUtranCell_TDD_FDD.csv').read_bytes())

    def test_missing_mob_source_does_not_publish_a_partial_set(self):
        with self.assertRaisesRegex(ValueError, 'MoB_IMP'):
            workflow.publish_mob_imports(self.config, self.root / 'reports')
        self.assertFalse((self.root / 'vivo/MoB_IMP').exists())


if __name__ == '__main__':
    unittest.main()
