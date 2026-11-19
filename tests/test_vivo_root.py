"""Vivo folders: classic (original machine) or one root (team), and the audit path translation."""
import json
import re
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import operator_profiles as op  # noqa: E402
import audit_workflow as aw  # noqa: E402


def _js_object(name):
    """Parse a flat `const NAME = {key: 'value', ...};` literal from app.js."""
    source = (ROOT / "web-tool" / "app.js").read_text(encoding="utf-8")
    body = re.search(r"const " + name + r" = \{(.*?)\};", source, re.S).group(1)
    return dict(re.findall(r"(\w+):\s*'([^']*)'", body))


class VivoFoldersTests(unittest.TestCase):
    def test_classic_is_the_default_and_matches_the_notebooks(self):
        self.assertEqual(op.normalize_vivo_root(None), op.VIVO_CLASSIC)
        self.assertEqual(op.normalize_vivo_root(" Classic "), op.VIVO_CLASSIC)
        folders = op.vivo_folders(None)
        self.assertEqual((folders["raw"], folders["processed"], folders["references"], folders["reports"]),
                         ("C:/Dumps/todos_enms", "C:/Dumps/LTE_Total", "C:/Camilo", "C:/Vivo Reports"))

    def test_root_layout_for_the_team(self):
        folders = op.vivo_folders("D:\\Equipe\\Vivo\\")
        self.assertEqual(folders["raw"], "D:/Equipe/Vivo/Dumps/todos_enms")
        self.assertEqual(folders["references"], "D:/Equipe/Vivo/Referencias")
        self.assertEqual(folders["reports"], "D:/Equipe/Vivo/Relatorios")
        self.assertEqual(folders["extras"], "D:/Equipe/Vivo/Relatorios/Adicionais")
        self.assertEqual(op.vivo_folders(op.DEFAULT_VIVO_ROOT)["references"], "C:/Vivo_Downloader/Referencias")

    def test_web_tool_mirror_is_identical(self):
        self.assertEqual(_js_object("VIVO_CLASSIC_FOLDERS"), op.VIVO_CLASSIC_FOLDERS)
        self.assertEqual(_js_object("VIVO_ROOT_LAYOUT"), op.VIVO_ROOT_LAYOUT)


class GuardTests(unittest.TestCase):
    def test_claro_cannot_use_a_custom_vivo_root(self):
        payload = {"output_dir": "D:/Equipe/Vivo/Dumps/x"}
        self.assertIsNone(op.check_request(op.CLARO, "/api/run-dump", payload))  # classic: not a Vivo folder
        error = op.check_request(op.CLARO, "/api/run-dump", payload, None, "D:/Equipe/Vivo")
        self.assertIn("Vivo folders", error)
        # The default Vivo root is always off-limits for Claro.
        self.assertIn("Vivo folders", op.check_request(op.CLARO, "/api/run-dump", {"output_dir": "C:/Vivo_Downloader/x"}))

    def test_vivo_root_must_not_overlap_claro(self):
        self.assertIn("overlaps the Claro folder", op.validate_vivo_root("C:/Claro_Reports/Vivo"))
        self.assertIn("drive root", op.validate_vivo_root("D:/"))
        self.assertIsNone(op.validate_vivo_root("classic"))
        self.assertIn("overlaps the Vivo folder", op.validate_claro_root("D:/Equipe/Vivo/Claro", "D:/Equipe/Vivo"))

    def test_vivo_dump_cannot_erase_the_vivo_root(self):
        error = op.check_request(op.VIVO, "/api/run-dump", {"output_dir": "D:/Equipe"}, None, "D:/Equipe/Vivo")
        self.assertIn("would erase the Vivo root", error)
        ok = {"output_dir": "D:/Equipe/Vivo/Dumps/todos_enms"}
        self.assertIsNone(op.check_request(op.VIVO, "/api/run-dump", ok, None, "D:/Equipe/Vivo"))


class AuditPathTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "Vivo"
        self.paths = aw.VivoPaths(op.vivo_folders(str(self.root)))

    def tearDown(self):
        self._tmp.cleanup()

    def test_classic_changes_nothing(self):
        classic = aw.VivoPaths()
        self.assertTrue(classic.classic)
        for text in ("C:/Camilo/x.txt", "C:\\Dumps\\LTE_total\\a.txt", "C:/Windows/x", "plain text"):
            self.assertEqual(classic.translate(text), text)

    def test_root_translation_by_folder(self):
        base = str(self.root).replace("\\", "/")
        t = self.paths.translate
        self.assertEqual(t("C:/Camilo/cellref_5g.xlsx"), f"{base}/Referencias/cellref_5g.xlsx")
        self.assertEqual(t("C:/Dumps/LTE_total/5G_ExternalNRCellCU.txt"), f"{base}/Dumps/LTE_Total/5G_ExternalNRCellCU.txt")
        self.assertEqual(t("C:\\Vivo Reports\\5G\\"), f"{base}/Relatorios/5G/")
        self.assertEqual(t("C:/Camilao/missing.xlsx"), f"{base}/Relatorios/Adicionais/missing.xlsx")
        self.assertEqual(t("C:/Camilo"), f"{base}/Referencias")
        self.assertEqual(t("Sheet1"), "Sheet1")
        with self.assertRaises(ValueError):
            t("C:/Outra/pasta/arquivo.xlsx")

    def test_catalog_lists_the_root_folders(self):
        result = aw.catalog(op.vivo_folders(str(self.root)))
        everything = [p for a in result["audits"] for p in a["inputs"] + a["outputs"]]
        self.assertTrue(everything)
        base = str(self.root).replace("\\", "/").lower()
        self.assertTrue(all(p.replace("\\", "/").lower().startswith(base) for p in everything), everything[:3])

    def test_audit_reads_and_writes_inside_the_root(self):
        script = Path(self._tmp.name) / "Fake_Audit.py"
        script.write_text(textwrap.dedent("""
            from pathlib import Path
            source = Path("C:/Camilo/entrada.txt").read_text()
            target = Path(r"C:\\Vivo Reports\\LTE\\saida.txt")
            target.write_text(source.upper())
        """), encoding="utf-8")
        (self.root / "Referencias").mkdir(parents=True)
        (self.root / "Referencias" / "entrada.txt").write_text("dados da semana")
        item = dict(id="fake", title="Fake", path=str(script), inputs=["Camilo/entrada.txt"],
                    outputs=["Vivo Reports/LTE/saida.txt"])
        self.assertEqual(aw.check_audit(item, 47, paths=self.paths), [])
        outputs = aw.execute_audit(item, 47, paths=self.paths)
        written = self.root / "Relatorios" / "LTE" / "saida.txt"
        self.assertEqual([Path(o) for o in outputs], [written])
        self.assertEqual(written.read_text(), "DADOS DA SEMANA")

    def test_unknown_absolute_path_stops_the_audit(self):
        script = Path(self._tmp.name) / "Bad_Audit.py"
        script.write_text('open("D:/somewhere/else.txt", "w").write("x")\n', encoding="utf-8")
        item = dict(id="bad", title="Bad", path=str(script), inputs=[], outputs=[])
        with self.assertRaises(RuntimeError) as ctx:
            aw.execute_audit(item, 47, paths=self.paths)
        self.assertIn("D:/somewhere/else.txt", str(ctx.exception))


class ServerTests(unittest.TestCase):
    def test_folders_route_and_audit_catalog_follow_the_header(self):
        import server_downloader as server
        client = server.app.test_client()
        data = client.get("/api/vivo/folders", headers={op.HEADER_VIVO_ROOT: "D%3A%2FEquipe%2FVivo"}).get_json()
        self.assertEqual(data["folders"]["references"], "D:/Equipe/Vivo/Referencias")
        self.assertIn(data["suggested"], (op.VIVO_CLASSIC, op.DEFAULT_VIVO_ROOT))
        catalog = client.get("/api/audits", headers={op.HEADER_VIVO_ROOT: "D%3A%2FEquipe%2FVivo"}).get_json()
        self.assertEqual(catalog["folders"]["reports"], "D:/Equipe/Vivo/Relatorios")
        classic = client.get("/api/audits").get_json()
        self.assertEqual(classic["folders"]["reports"], "C:/Vivo Reports")


if __name__ == "__main__":
    unittest.main()
