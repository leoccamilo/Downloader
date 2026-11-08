"""Behavior checks for optional exports, failure isolation and orchestration."""

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch

import server_downloader as server
import weekly_workflow as workflow


class WeeklyWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        notebooks = self.root / "notebooks"
        references = self.root / "references"
        notebooks.mkdir()
        references.mkdir()
        for name in ("cellref.xlsx", "SCIENCE.xlsx"):
            (references / name).touch()
        (self.root / "input.xml").write_text("<root/>")
        self.config = {"notebook_dir": str(notebooks), "reference_dir": str(references),
                       "input_files": [str(self.root / "input.xml")],
                       "output_dir": str(self.root / "output"),
                       "enriched_dir": str(self.root / "enriched"),
                       "history_dir": str(self.root / "history"),
                       "vivo_dir": str(self.root / "vivo"), "run_date": "2026-11-09",
                       "create_weekly": False, "transfer_vivo": False}
        for name in workflow.NOTEBOOKS:
            self.write_notebook(name, "pass")
        self.write_notebook(workflow.NOTEBOOKS[1],
                            "from pathlib import Path\nPath('C:/Dumps/LTE_Total/raw.txt').write_text('fresh')")
        self.write_notebook(workflow.NOTEBOOKS[2],
                            "from pathlib import Path\nsemana_atual = 1\n"
                            "Path('C:/Camilo/' + 'report_' + str(semana_atual) + '.txt').write_text('report')")
        self.write_notebook(workflow.NOTEBOOKS[4],
                            "from pathlib import Path\nPath('C:/Vivo Reports/LTE/LTE MOs/report.csv').write_text('vivo')")

    def write_notebook(self, name, code):
        path = Path(self.config["notebook_dir"]) / name
        path.write_text(json.dumps({"cells": [{"cell_type": "code", "source": code.splitlines(True)}]}), encoding="utf-8")

    def run_workflow(self):
        with redirect_stdout(StringIO()):
            workflow.run_workflow(self.config)

    def test_export_options_are_independent_and_latest_is_always_saved(self):
        originals = {p: p.read_bytes() for p in Path(self.config["notebook_dir"]).iterdir()}
        for history, vivo in ((False, False), (True, False), (False, True), (True, True)):
            with self.subTest(history=history, vivo=vivo):
                scope = self.root / f"{history}_{vivo}"
                self.config.update(create_weekly=history, transfer_vivo=vivo)
                for key, folder in (("output_dir", "output"), ("enriched_dir", "enriched"),
                                    ("history_dir", "history"), ("vivo_dir", "vivo")):
                    self.config[key] = str(scope / folder)
                self.run_workflow()
                self.assertEqual((scope / "enriched/report.txt").read_text(), "report")
                self.assertEqual((scope / "history/report_46.txt").exists(), history)
                self.assertEqual((scope / "vivo/LTE/LTE MOs/report.csv").exists(), vivo)
                self.assertFalse((scope / "enriched/report_46.txt").exists())
        for path, content in originals.items():
            self.assertEqual(path.read_bytes(), content)

    def test_notebook_failure_preserves_existing_outputs_and_history(self):
        for key in ("output_dir", "history_dir", "vivo_dir", "enriched_dir"):
            directory = Path(self.config[key])
            directory.mkdir()
            (directory / "existing.txt").write_text("old")
        self.config.update(create_weekly=True, transfer_vivo=True)
        self.write_notebook(workflow.NOTEBOOKS[-1], "raise RuntimeError('test processing failure')")
        with self.assertRaisesRegex(RuntimeError, "cell 0.*test processing failure"):
            self.run_workflow()
        for key in ("output_dir", "history_dir", "vivo_dir", "enriched_dir"):
            self.assertEqual(list(Path(self.config[key]).iterdir()), [Path(self.config[key]) / "existing.txt"])
            self.assertEqual((Path(self.config[key]) / "existing.txt").read_text(), "old")
        manifest = json.loads(next(self.root.glob(".weekly_runs/*/manifest.json")).read_text())
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["exports"], [])

    def test_scope_without_tdd_still_produces_the_fdd_inventory(self):
        self.write_notebook(workflow.NOTEBOOKS[2],
                            "from pathlib import Path\nPath('C:/Camilo/EUtranCellFDD.csv').write_text("
                            "'UF,eNB,CELL,administrativeState\\nAM,TABC1_AM,VABC11,UNLOCKED\\n')")
        self.write_notebook(workflow.NOTEBOOKS[3],
                            "tdd_fdd.to_csv('C:/Camilo/EUtranCell_TDD_FDD.txt', sep='\\t', index=False)")
        self.run_workflow()
        import pandas as pd
        inventory = pd.read_csv(Path(self.config["enriched_dir"]) / "EUtranCell_TDD_FDD.txt", sep="\t")
        self.assertEqual(inventory["CELL"].tolist(), ["VABC11"])
        self.assertEqual(inventory["Tipo"].tolist(), ["FDD"])
        self.assertEqual(inventory["Regional"].tolist(), ["N"])

    def test_reports_do_not_save_the_previous_mo_frame(self):
        self.write_notebook(workflow.NOTEBOOKS[1],
                            "import pandas as pd\n"
                            "df3 = pd.DataFrame({'MO':['PreviousMO']})\n"
                            "df2 = pd.DataFrame({'MO':['SignalingRadioBearer']})\n"
                            "df3.to_csv('C:/Dumps/LTE_Total/SignalingRadioBearer.txt', index=False)\n"
                            "df2 = pd.DataFrame({'MO':['CarrierAggregationFunction']})\n"
                            "df3.to_csv('C:/Dumps/LTE_Total/CarrierAggregationFunction.txt', index=False)")
        self.run_workflow()
        import pandas as pd
        for mo in ("SignalingRadioBearer", "CarrierAggregationFunction"):
            frame = pd.read_csv(Path(self.config["output_dir"]) / (mo + ".txt"))
            self.assertEqual(frame["MO"].tolist(), [mo])

    def test_arrow_ids_can_be_joined_to_reference_strings(self):
        self.write_notebook(workflow.NOTEBOOKS[1],
                            "import pandas as pd\nimport pyarrow as pa\n"
                            "cell = pd.Series(['VABC11'], dtype=pd.ArrowDtype(pa.string()))\n"
                            "uf = pd.Series(['AM'], dtype=object)\n"
                            "site = cell.str[1:4] + '_' + uf\n"
                            "pd.DataFrame({'Site':site}).to_csv('C:/Dumps/LTE_Total/site.txt', index=False)")
        self.run_workflow()
        import pandas as pd
        frame = pd.read_csv(Path(self.config["output_dir"]) / "site.txt")
        self.assertEqual(frame["Site"].tolist(), ["ABC_AM"])

    def test_single_enm_id_variant_survives_sparse_column_cleanup(self):
        self.write_notebook(workflow.NOTEBOOKS[0],
                            "import pandas as pd\n"
                            "pd.DataFrame({'eUtranFreqRelationId':['LTE_1']}).to_parquet("
                            "'C:/Dumps/todos_enms/EUtranFreqRelation_sample_part00000.parquet')")
        self.write_notebook(workflow.NOTEBOOKS[1],
                            "import pandas as pd\n"
                            "df = pd.read_parquet('C:/Dumps/todos_enms/EUtranFreqRelation_sample_part00000.parquet')\n"
                            "df = df.convert_dtypes(dtype_backend='pyarrow')\n"
                            "df = df.dropna(thresh=1, axis='columns')\n"
                            "df['ID'] = df['EUtranFreqRelationId'].fillna('') + df['eUtranFreqRelationId'].fillna('')\n"
                            "df[['ID']].to_csv('C:/Dumps/LTE_Total/relations.txt', index=False)")
        self.run_workflow()
        import pandas as pd
        frame = pd.read_csv(Path(self.config["output_dir"]) / "relations.txt")
        self.assertEqual(frame["ID"].tolist(), ["LTE_1"])

    def test_dump_cannot_erase_references_or_output(self):
        for key in ("reference_dir", "output_dir", "enriched_dir", "notebook_dir", "history_dir"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "protected folder"):
                workflow.preflight(dict(self.config, dump_output_dir=self.config[key]))

    def test_vivo_destination_is_not_required_or_protected_when_disabled(self):
        self.config.update(transfer_vivo=False, vivo_dir="")
        workflow.preflight(self.config)
        # A saved optional destination must not restrict a Claro run when the
        # corresponding export is disabled.
        self.config.update(vivo_dir=str(self.root / "unused_vivo"),
                           dump_output_dir=str(self.root / "unused_vivo"))
        workflow.preflight(self.config)
        with self.assertRaisesRegex(ValueError, "protected folder"):
            workflow.preflight(dict(self.config, transfer_vivo=True))

    def test_failed_preflight_does_not_start_dump(self):
        with patch.object(server, "_run_step", return_value=(["missing references\n"], 1)), \
                patch.object(server, "_stream_checked_script") as run:
            output = "".join(server.stream_weekly_workflow(dict(self.config, dump_config={"output_dir": "unused"})))
        run.assert_not_called()
        self.assertIn("PIPELINE FAILED.", output)
        self.assertNotIn("PIPELINE COMPLETED.", output)

    def test_dump_failure_stops_notebooks(self):
        def fail_dump(*args):
            yield "ERROR ENM: failed\n"
            return 1

        with patch.object(server, "_run_step", return_value=(["REQUIRED_MOS=[]\n"], 0)), \
                patch.object(server, "_stream_checked_script", side_effect=fail_dump) as run:
            output = "".join(server.stream_weekly_workflow(dict(self.config, dump_config={"output_dir": "unused"})))
        self.assertEqual(run.call_count, 1)
        self.assertIn("PIPELINE FAILED.", output)
        self.assertNotIn("PIPELINE COMPLETED.", output)

    def test_concurrent_jobs_are_rejected_and_lock_is_released(self):
        with server.app.test_request_context():
            response = server._workflow_response(iter(["running\n"]))
            rejected = server._workflow_response(iter(["other\n"]))
            self.assertEqual(rejected.status_code, 409)
            self.assertEqual(response.get_data(as_text=True), "running\n")
            self.assertFalse(server._workflow_lock.locked())

    def test_disconnection_before_streaming_releases_the_job_lock(self):
        with server.app.test_request_context():
            response = server._workflow_response(iter(["not started\n"]))
            response.close()
            self.assertFalse(server._workflow_lock.locked())

    def test_closing_stream_terminates_its_subprocess(self):
        script = self.root / "long_running.py"
        script.write_text("import time\nprint('ready', flush=True)\ntime.sleep(120)\n")
        processes = []
        actual_popen = server.subprocess.Popen

        def start_process(*args, **kwargs):
            process = actual_popen(*args, **kwargs)
            processes.append(process)
            return process

        with patch.object(server.subprocess, "Popen", side_effect=start_process):
            stream = server._stream_checked_script(sys.executable, str(script), [])
            self.assertEqual(next(stream).strip(), "ready")
            stream.close()
        self.assertIsNotNone(processes[0].poll())


if __name__ == "__main__":
    unittest.main()
