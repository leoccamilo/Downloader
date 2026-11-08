"""Checks for shared references, portal inputs and safe physical refresh."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

import cellref_workflow as cellrefs
import server_downloader as server


class CellrefWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("scripts", "lte", "nr", "references", "parsed", "reports"):
            (self.root / name).mkdir()
        for name in (cellrefs.LTE_NOTEBOOK, cellrefs.NR_NOTEBOOK):
            (self.root / "scripts" / name).write_text(json.dumps({"cells": [{"cell_type": "code", "source": ["pass"]}]}))
        for name in ("4_MOs_Camilo.ipynb", "5_MOs_TDD.ipynb"):
            (self.root / "scripts" / name).write_text(json.dumps({"cells": [{"cell_type": "code", "source": ["pass"]}]}))
        for technology in ("lte", "nr"):
            frame = pd.DataFrame([{name: "x" for name in cellrefs.PORTAL_COLUMNS | {"SITUACAO_ERB"}}])
            frame.to_excel(self.root / technology / "portal_W45.xlsx", index=False, startrow=2)
        self.config = {"reference_dir": str(self.root / "references"), "notebook_dir": str(self.root / "scripts"),
                       "output_dir": str(self.root / "parsed"), "enriched_dir": str(self.root / "reports"),
                       "cellref": {"enabled": True, "scripts_dir": str(self.root / "scripts"),
                                   "lte_input_dir": str(self.root / "lte"), "nr_input_dir": str(self.root / "nr"),
                                   "parameter_dir": str(self.root / "reports"), "refresh_reports": True}}
        for name in ("EUtranCell_TDD_FDD.txt", "5G_GNBDUFunction.txt", "5G_NRCellDU.txt", "5G_NRSectorCarrier.txt"):
            (self.root / "reports" / name).write_text("UF\teNB\tTipo\nAM\tTABC1_AM\tFDD\n")
        (self.root / "parsed/EUtranCellFDD.txt").write_text("eNB\nTABC1_AM\n")
        (self.root / "parsed/ENodeBFunction.txt").write_text("eNB\nTABC1_AM\n")

    def test_portal_headers_and_separate_lte_nr_inputs(self):
        result = cellrefs.preflight_cellrefs(self.config)
        self.assertEqual(len(result["lte"]), 1)
        self.assertEqual(len(result["nr"]), 1)
        pd.DataFrame({"wrong": [1]}).to_excel(self.root / "nr/portal_W45.xlsx", index=False, startrow=2)
        with self.assertRaisesRegex(ValueError, "Invalid NR portal headers"):
            cellrefs.preflight_cellrefs(self.config)

    def test_mixed_portal_weeks_are_rejected(self):
        shutil.copy2(self.root / "lte/portal_W45.xlsx", self.root / "lte/portal_W44.xlsx")
        with self.assertRaisesRegex(ValueError, "different weeks"):
            cellrefs.preflight_cellrefs(self.config)

    def test_dump_cannot_erase_portal_downloads(self):
        import weekly_workflow
        for name in weekly_workflow.NOTEBOOKS:
            (self.root / "scripts" / name).write_text(json.dumps({"cells": [{"cell_type": "code", "source": ["pass"]}]}))
        (self.root / "references/cellref.xlsx").touch()
        config = dict(self.config, notebook_dir=str(self.root / "scripts"), dump_output_dir=str(self.root / "lte"))
        with self.assertRaisesRegex(ValueError, "protected folder"):
            weekly_workflow.preflight(config)

    def test_lte_and_nr_must_describe_the_same_week(self):
        (self.root / "nr/portal_W45.xlsx").rename(self.root / "nr/portal_W44.xlsx")
        with self.assertRaisesRegex(ValueError, "LTE and NR.*different weeks"):
            cellrefs.preflight_cellrefs(self.config)

    def test_science_fallback_prefers_host_over_remote_hotel_cell(self):
        path = self.root / "references/cellref.xlsx"
        pd.DataFrame({"eNB": ["TABC1_AM", "TABC1_AM"], "CELL": ["VXYZ11", "VABC11"],
                      "CLUSTER": ["Remote city", "Host city"], "BAIRRO": ["Remote", "Host"]}).to_excel(path, index=False)
        result = cellrefs.science_from_cellref(path)
        self.assertEqual(result.to_dict("records"), [{"SITE": "TABC1_AM", "MUNICÍPIO": "Host city", "BAIRRO": "Host"}])

    @unittest.skipUnless((Path.home() / "Novos_Audits/4_MOs_Camilo.ipynb").is_file(), "Configured external Camilo notebook is not installed")
    def test_real_camilo_notebook_preserves_remote_hotel_coordinates(self):
        import ast
        from weekly_workflow import execute_notebook
        source_path = Path.home() / "Novos_Audits/4_MOs_Camilo.ipynb"
        notebook = json.loads(source_path.read_text(encoding="utf-8"))
        source = next("".join(cell["source"]) for cell in notebook["cells"]
                      if cell["cell_type"] == "code" and "NIVEL 1 - por CELULA" in "".join(cell["source"]))
        usecols = next(ast.literal_eval(keyword.value) for node in ast.walk(ast.parse(source))
                       if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "read_csv"
                       for keyword in node.keywords if keyword.arg == "usecols")
        rows = []
        for cell in ("VREM11", "VHST11"):
            row = {key: 0 for key in usecols}
            row.update(UF="AM", eNB="THST1_AM", CELL=cell, cellId=1, earfcndl=1300)
            rows.append(row)
        pd.DataFrame(rows).to_csv(self.root / "parsed/EUtranCellFDD.txt", sep="\t", index=False)
        pd.DataFrame({"CN": [92, 92], "CLUSTER": ["Remote", "Host"], "BAIRRO": ["R", "H"],
                      "ENDERECO": ["Remote address", "Host address"], "eNB": ["THST1_AM"] * 2,
                      "CELL": ["VREM11", "VHST11"], "Longitude": [-60., -62.], "Latitude": [-1., -3.],
                      "Azimuth": [120, 10], "Height": [30, 40], "SiteType": ["Outdoor"] * 2,
                      "Site_Name": ["Remote site", "Host site"]}).to_excel(self.root / "references/cellref.xlsx", index=False)
        test_notebook = self.root / "scripts/4_MOs_Camilo.ipynb"
        test_notebook.write_text(json.dumps({"cells": [{"cell_type": "code", "source": source.splitlines(True)}]}), encoding="utf-8")
        roots = [("C:/Camilo/cellref.xlsx", self.root / "references/cellref.xlsx"),
                 ("C:/Dumps/LTE_Total", self.root / "parsed"), ("C:/Dumps/todos_enms", self.root / "raw"),
                 ("C:/Camilo", self.root / "reports")]
        with redirect_stdout(StringIO()):
            execute_notebook(test_notebook, roots, 45, [])
        result = pd.read_csv(self.root / "reports/EUtranCellFDD_45.txt", sep="\t").set_index("CELL")
        self.assertEqual(result.loc["VREM11", "Latitude"], -1.)
        self.assertEqual(result.loc["VHST11", "Latitude"], -3.)
        self.assertEqual(result.loc["VREM11", "Site_Name"], "Remote site")
        self.assertEqual(result["Origem_coord"].tolist(), ["celula", "celula"])

    def test_refresh_does_not_drop_existing_tdd_when_raw_mo_is_missing(self):
        inventory = self.root / "inventory.txt"
        inventory.write_text("eNB\tTipo\nTABC1_AM\tTDD\n")
        raw = self.root / "raw"
        raw.mkdir()
        with self.assertRaisesRegex(ValueError, "contains TDD"):
            cellrefs.prepare_refresh_inputs(self.root / "parsed", raw, inventory)

    def test_run_all_cache_preserves_tdd_for_later_refresh(self):
        raw = self.root / "source_raw"
        raw.mkdir()
        name = "EUtranCellTDD_sample_part00000.parquet"
        pd.DataFrame({"ManagedElement": ["TABC1_AM"], "cellId": [4]}).to_parquet(raw / name, index=False)
        cache = self.root / "run_45/refresh_inputs"
        cellrefs.cache_refresh_inputs(raw, cache)
        published = self.root / "parsed/.refresh_inputs"
        (published / "run_45").mkdir(parents=True)
        shutil.copy2(cache / "index.json", published / "current.json")
        shutil.copy2(cache / name, published / "run_45" / name)
        inventory = self.root / "inventory.txt"
        inventory.write_text("eNB\tTipo\nTABC1_AM\tTDD\n")
        target = self.root / "refresh_raw"
        target.mkdir()
        cellrefs.prepare_refresh_inputs(self.root / "parsed", target, inventory)
        self.assertEqual(pd.read_parquet(target / name)["cellId"].tolist(), [4])

    def test_refresh_failure_does_not_publish_new_references(self):
        reference = self.root / "references/cellref.xlsx"
        reference.write_bytes(b"previous workbook")
        with patch.object(cellrefs, "generate_cellrefs", return_value=self.root / "generated"), \
                patch.object(cellrefs, "refresh_physical_reports", side_effect=RuntimeError("refresh failed")), \
                patch.object(cellrefs, "publish_cellrefs") as publish, redirect_stdout(StringIO()):
            with self.assertRaisesRegex(RuntimeError, "refresh failed"):
                cellrefs.run_cellref_workflow(self.config)
        publish.assert_not_called()
        self.assertEqual(reference.read_bytes(), b"previous workbook")
        manifest = json.loads(next(self.root.glob(".cellref_runs/*/manifest.json")).read_text())
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["exports"], [])

    def test_site_list_refresh_uses_official_books_and_replaces_stale_cache(self):
        directory = self.root / "references"
        for name, site in (("cellref.xlsx", "TABC1_AM"), ("cellref_5g.xlsx", "SABC1_AM"),
                           ("CellRef_LTE_old.xlsx", "TOLD1_AM"), ("SCIENCE.xlsx", "TWRONG_AM")):
            pd.DataFrame({"UF": ["AM"], "MUNICIPIO": ["Manaus"], "eNB": [site]}).to_excel(directory / name, index=False)
        stale = [{"UF": "SP", "MUNICIPIO": "Old city", "SiteID": "TOLD1_SP", "Tech": "LTE"}] * 6
        server._save_site_list_txt(str(directory / "sites_list.txt"), stale)
        response = server.app.test_client().post("/api/load-site-list", json={"base_dir": str(directory), "refresh_from_references": True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row["SiteID"] for row in response.json["rows"]}, {"TABC1_AM", "SABC1_AM"})


if __name__ == "__main__":
    unittest.main()
