"""Operator switch: Vivo and Claro never share folders or Vivo-only jobs."""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import operator_profiles as op  # noqa: E402


class CheckRequestTests(unittest.TestCase):
    def test_missing_operator_means_vivo(self):
        self.assertEqual(op.normalize_operator(None), op.VIVO)
        self.assertEqual(op.normalize_operator(" CLARO "), op.CLARO)
        self.assertIsNone(op.normalize_operator("tim"))

    def test_vivo_dump_in_vivo_folders_is_allowed(self):
        payload = {"output_dir": "C:/Dumps/todos_enms", "enms": [{"id": "ENMBARA"}]}
        self.assertIsNone(op.check_request(op.VIVO, "/api/run-dump", payload))

    def test_claro_dump_in_claro_root_subfolder_is_allowed(self):
        payload = {"output_dir": "C:/Claro_Reports/Dumps"}
        self.assertIsNone(op.check_request(op.CLARO, "/api/run-dump", payload, "C:/Claro_Reports"))

    def test_claro_cannot_use_vivo_folders(self):
        error = op.check_request(op.CLARO, "/api/run-dump", {"output_dir": "C:\\Dumps\\todos_enms"})
        self.assertIn("Vivo folders", error)
        nested = {"input_dir": "C:/Claro_Reports/Dumps", "output_dir": "C:/Claro_Reports/Dumps",
                  "cellref_dir": "C:/Camilo", "customize_txts": False}
        self.assertIn("cellref_dir", op.check_request(op.CLARO, "/api/run-parser-pipeline", nested))

    def test_vivo_cannot_use_claro_root_even_when_renamed(self):
        payload = {"output_dir": "D:/PR/Reports/Dumps"}
        self.assertIsNone(op.check_request(op.VIVO, "/api/run-dump", payload))
        self.assertIn("Claro folders", op.check_request(op.VIVO, "/api/run-dump", payload, "D:/PR/Reports"))
        files = {"input_files": ["C:/MoB_Claro/PR_mob_W42.zip"], "output_dir": "C:/Dumps/todos_enms"}
        self.assertIn("input_files", op.check_request(op.VIVO, "/api/run-parser-pipeline", files))

    def test_folder_match_is_by_segment_not_prefix(self):
        self.assertFalse(op.is_under("C:/MoB_Claro/x", "C:/MoB"))
        self.assertFalse(op.is_under("C:/Dumps2", "C:/Dumps"))
        self.assertTrue(op.is_under("c:\\dumps\\todos_enms\\", "C:/Dumps"))

    def test_claro_dump_cannot_erase_the_root(self):
        error = op.check_request(op.CLARO, "/api/run-dump", {"output_dir": "C:/Claro_Reports"}, "C:/Claro_Reports")
        self.assertIn("would erase the Claro root", error)
        error = op.check_request(op.CLARO, "/api/run-dump", {"output_dir": "C:/"}, "C:/Claro_Reports")
        self.assertIn("drive root", error)

    def test_claro_root_must_be_separate_from_vivo(self):
        self.assertIn("drive root", op.validate_claro_root("D:/"))
        self.assertIn("overlaps", op.validate_claro_root("C:/Camilo/Claro"))
        self.assertIn("drive root", op.validate_claro_root("C:/"))
        self.assertIn("overlaps", op.validate_claro_root("C:/Vivo Reports"))
        self.assertIsNone(op.validate_claro_root("C:/Claro_Reports"))
        self.assertIn("overlaps", op.check_request(op.CLARO, "/api/run-dump",
                                                   {"output_dir": "C:/Dumps/x"}, "C:/Dumps"))

    def test_vivo_only_endpoints_are_refused_for_claro(self):
        for endpoint in ("/api/run-weekly-workflow", "/api/run-cellref", "/api/run-audits",
                         "/api/run-post-process-4", "/api/load-site-list"):
            self.assertIn("Not available for Claro", op.check_request(op.CLARO, endpoint, {}))
            self.assertIsNone(op.check_request(op.VIVO, endpoint, {}))

    def test_claro_cellref_is_claro_only_and_stays_in_claro_folders(self):
        payload = {"txt_dir": "C:/Claro_Reports/Dumps", "mando_path": "C:/MoB_Claro/cellref",
                   "output_dir": "C:/Claro_Reports/Cellref"}
        self.assertIn("Only available for Claro", op.check_request(op.VIVO, "/api/run-claro-cellref", payload))
        self.assertIsNone(op.check_request(op.CLARO, "/api/run-claro-cellref", payload))
        vivo_out = dict(payload, output_dir="C:/Camilo")
        self.assertIn("output_dir", op.check_request(op.CLARO, "/api/run-claro-cellref", vivo_out))
        vivo_mando = dict(payload, mando_path="C:/Cellref/mando_cells_2026-11-09.csv")
        self.assertIn("mando_path", op.check_request(op.CLARO, "/api/run-claro-cellref", vivo_mando))

    def test_claro_process_mos_needs_its_own_folder(self):
        same = {"output_dir": "C:/Claro_Reports/Dumps", "customize_txts": True}
        self.assertIn("must be different", op.check_request(op.CLARO, "/api/run-parser-pipeline", same))
        same["enriched_dir"] = "c:\\claro_reports\\dumps\\"
        self.assertIn("must be different", op.check_request(op.CLARO, "/api/run-parser-pipeline", same))
        ok = {"output_dir": "C:/Claro_Reports/Dumps", "enriched_dir": "C:/Claro_Reports/MOs", "customize_txts": True}
        self.assertIsNone(op.check_request(op.CLARO, "/api/run-parser-pipeline", ok))
        vivo_cellref = dict(ok, cellref_dir="C:/Downloader/cellref")
        self.assertIn("cellref_dir", op.check_request(op.CLARO, "/api/run-parser-pipeline", vivo_cellref))

    def test_geography_has_regions_and_municipalities(self):
        geography = op.claro_geography()
        self.assertEqual(len(geography["regions"]), 5)
        self.assertEqual(len(geography["municipalities"]), 78)
        codes = {m["code"]: m["region"] for m in geography["municipalities"]}
        self.assertEqual(codes["CAR"], "Metro East")
        self.assertEqual(codes["ABU"], "Southeast")


class ServerGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server_downloader
        cls.server = server_downloader
        cls.client = server_downloader.app.test_client()

    def post(self, path, payload, operator=None, root=None):
        headers = {}
        if operator:
            headers[op.HEADER_OPERATOR] = operator
        if root:
            headers[op.HEADER_CLARO_ROOT] = root
        return self.client.post(path, data=json.dumps(payload), headers=headers, content_type="application/json")

    def test_claro_weekly_workflow_is_refused_before_any_job(self):
        response = self.post("/api/run-weekly-workflow", {"input_dir": "C:/Claro_Reports/Dumps"}, "claro")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Not available for Claro", response.get_data(as_text=True))
        self.assertFalse(self.server._workflow_lock.locked())

    def test_claro_dump_into_vivo_folder_is_refused(self):
        response = self.post("/api/run-dump", {"output_dir": "C:/Dumps/todos_enms"}, "claro")
        self.assertEqual(response.status_code, 400)
        self.assertIn("belongs to the Vivo folders", response.get_data(as_text=True))

    def test_encoded_claro_root_header_is_decoded(self):
        response = self.post("/api/run-dump", {"output_dir": "C:/Relatórios PR/Dumps"}, "vivo",
                             root="C%3A%2FRelat%C3%B3rios%20PR")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Claro folders", response.get_data(as_text=True))

    def test_unknown_operator_is_refused(self):
        response = self.post("/api/run-dump", {"output_dir": "C:/Dumps/x"}, "tim")
        self.assertEqual(response.status_code, 400)

    def test_busy_and_geography_endpoints(self):
        self.assertEqual(self.client.get("/api/busy").get_json(), {"busy": False})
        geography = self.client.get("/api/claro/geography").get_json()
        self.assertEqual(len(geography["municipalities"]), 78)

    def test_audit_catalog_is_blocked_for_claro_only(self):
        claro = self.client.get("/api/audits", headers={op.HEADER_OPERATOR: "claro"}).get_json()
        self.assertTrue(all(item["operator_blocked"] and not item["ready"] for item in claro["audits"]))
        vivo = self.client.get("/api/audits").get_json()
        self.assertFalse(any(item.get("operator_blocked") for item in vivo["audits"]))

    def test_parser_keeps_5g_to_4g_relations_only_for_claro(self):
        calls = []
        original = self.server.stream_parser_pipeline

        def fake(*args, **kwargs):
            calls.append(kwargs.get("include_nr_relations"))
            yield "PIPELINE COMPLETED.\n"

        self.server.stream_parser_pipeline = fake
        try:
            for operator, folder in (("claro", "C:/Claro_Reports/Dumps"), ("vivo", "C:/Dumps/todos_enms")):
                response = self.post("/api/run-parser-pipeline", {"input_dir": folder, "output_dir": folder}, operator)
                self.assertEqual(response.status_code, 200)
                response.get_data()
        finally:
            self.server.stream_parser_pipeline = original
        self.assertEqual(calls, [True, False])

        captured = []
        original_run = self.server._stream_run_script

        def fake_run(python, script, args):
            captured.append(args)
            return iter(())

        self.server._stream_run_script = fake_run
        try:
            list(self.server.stream_parser_pipeline("in", "out", False, "", "", None, include_nr_relations=True))
            list(self.server.stream_parser_pipeline("in", "out", False, "", "", None))
        finally:
            self.server._stream_run_script = original_run
        self.assertIn("--include-nr-relations", captured[0])
        self.assertNotIn("--include-nr-relations", captured[1])

    def test_claro_process_mos_runs_the_claro_script_only(self):
        scripts = []
        original_run = self.server._stream_run_script

        def fake_run(python, script, args):
            scripts.append((os.path.basename(script), args[1:]))
            return iter(())

        self.server._stream_run_script = fake_run
        try:
            body = {"input_dir": "C:/Claro_Reports/Dumps", "output_dir": "C:/Claro_Reports/Dumps",
                    "enriched_dir": "C:/Claro_Reports/MOs", "customize_txts": True}
            response = self.post("/api/run-parser-pipeline", body, "claro")
            self.assertEqual(response.status_code, 200)
            log = response.get_data(as_text=True)
        finally:
            self.server._stream_run_script = original_run
        names = [name for name, _ in scripts]
        self.assertEqual(names, ["xml_to_txt.py", "pos_processamento_claro.py"])
        # No cellref folder sent: the Vivo default (C:/Downloader/cellref) must not be used.
        self.assertEqual(len(scripts[1][1]), 2)
        self.assertTrue(scripts[1][1][1].endswith("MOs"))
        self.assertIn("STEP 2/2: Process MOs (Claro network rules)", log)

        scripts.clear()
        self.server._stream_run_script = fake_run
        try:
            body = {"input_dir": "C:/Dumps/todos_enms", "output_dir": "C:/Dumps/todos_enms",
                    "enriched_dir": "C:/Camilo", "customize_txts": True}
            self.post("/api/run-parser-pipeline", body).get_data()
        finally:
            self.server._stream_run_script = original_run
        self.assertEqual([name for name, _ in scripts],
                         ["xml_to_txt.py", "post_process_4_camilo.py", "post_process_5_tdd.py", "post_process_6_5g.py"])

    def test_cors_allows_operator_headers(self):
        response = self.client.get("/api/busy")
        allowed = response.headers["Access-Control-Allow-Headers"]
        self.assertIn(op.HEADER_OPERATOR, allowed)
        self.assertIn(op.HEADER_CLARO_ROOT, allowed)


if __name__ == "__main__":
    unittest.main()
