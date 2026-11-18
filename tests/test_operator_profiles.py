"""Operator switch: Vivo and Claro never share folders or Vivo-only jobs."""
import json
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
        enrich = {"output_dir": "C:/Claro_Reports/Dumps", "customize_txts": True}
        self.assertIn("Enrich Files", op.check_request(op.CLARO, "/api/run-parser-pipeline", enrich))

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

    def test_cors_allows_operator_headers(self):
        response = self.client.get("/api/busy")
        allowed = response.headers["Access-Control-Allow-Headers"]
        self.assertIn(op.HEADER_OPERATOR, allowed)
        self.assertIn(op.HEADER_CLARO_ROOT, allowed)


if __name__ == "__main__":
    unittest.main()
