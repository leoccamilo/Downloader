"""Claro "Process MOs" (pos_processamento_claro.py) on a small Claro dump.

The copy was checked byte by byte against the MoB_Claro original on the whole
PR network (W42, 19 files, with and without cellref): see alteracoes.md.
"""
import csv
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pos_processamento_claro  # noqa: E402
import xml_to_txt  # noqa: E402
from test_xml_to_txt_cli import XML as _PARSER_XML  # noqa: E402

# Real dumps carry each MO's own id and the cell PCI as attributes; the processing relies on them.
XML = _PARSER_XML.replace(
    "<e:cellId>11</e:cellId>",
    "<e:eUtranCellFDDId>SJU1029_B66_4_RR_A_1</e:eUtranCellFDDId><e:cellId>11</e:cellId>"
    "<e:physicalLayerCellIdGroup>10</e:physicalLayerCellIdGroup>"
    "<e:physicalLayerSubCellId>2</e:physicalLayerSubCellId>").replace(
    "<e:cellLocalId>1</e:cellLocalId>",
    "<e:nRCellCUId>SJU1029_N66_5_RR_A_1</e:nRCellCUId><e:cellLocalId>1</e:cellLocalId>"
    "<e:nCI>1685946369</e:nCI>")
# The 5G -> 4G relation points at an external LTE cell labelled with its CGI.
_head, _tail = XML.split('id="330110-771101-33">')
XML = _head + 'id="330110-771101-33">' + _tail.replace(
    "<e:vsDataEUtranCellRelation>",
    "<e:vsDataEUtranCellRelation><e:neighborCellRef>MeContext=SJU1029_2,ManagedElement=SJU1029_2,"
    "vsDataGNBCUCPFunction=1,vsDataExternalENodeBFunction=auto330_110_3_771101,"
    "vsDataExternalEUtranCell=330110-771101-33</e:neighborCellRef>", 1)


def read_rows(path, delimiter="\t"):
    with open(path, encoding="latin-1", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=delimiter))


class ProcessMosTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        base = Path(cls._tmp.name)
        (base / "dump.xml").write_text(XML, encoding="utf-8")
        cls.txt = base / "txt"
        cls.mos = base / "mos"
        with redirect_stdout(io.StringIO()):
            xml_to_txt.parse_ericsson_xmls([base / "dump.xml"], str(cls.txt), include_nr_relations=True)
            pos_processamento_claro.processar(cls.txt, cls.mos)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_lte_cells_use_claro_rules(self):
        rows = read_rows(self.mos / "EUtranCell_TDD_FDD.txt")
        self.assertEqual(len(rows), 1)
        cell = rows[0]
        self.assertEqual(cell["CELL"], "SJU1029_B66_4_RR_A_1")
        self.assertEqual(cell["UF"], "SJU")                  # municipality, not eNB[-2:]
        self.assertEqual(cell["Regional"], "Metro East")     # Claro operational region
        self.assertEqual(cell["Site"], "SJU1029")            # node name without _2
        self.assertEqual(cell["Setor"], "A")                 # sector letter
        self.assertEqual(cell["Portadora"], "B66")
        self.assertEqual(cell["CGI"], "330110-102902-11")    # PLMN 330/110
        self.assertEqual(cell["PCI"], "32")

    def test_5g_to_4g_relations_are_kept_apart(self):
        rows = read_rows(self.mos / "5G_EUtranCellRelation.txt")
        self.assertEqual([r["CELL"] for r in rows], ["SJU1029_N66_5_RR_A_1"])
        self.assertEqual(rows[0]["UF"], "SJU")
        self.assertEqual(rows[0]["eNBId_tgt"], "771101")
        self.assertEqual(rows[0]["CGI"], "330110-771101-33")

    def test_parsed_txt_is_left_untouched(self):
        raw = read_rows(self.txt / "EUtranCellFDD.txt")
        self.assertNotIn("UF", raw[0])


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "pos_processamento_claro.py"), *map(str, args)],
                              capture_output=True, text=True)

    def test_same_folder_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli(tmp, tmp)
        self.assertEqual(result.returncode, 1)
        self.assertIn("must be different", result.stdout)

    def test_vivo_folder_is_refused(self):
        target = Path("C:/Dumps/claro_process_test_must_not_exist")
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli(tmp, target)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Vivo folder", result.stdout)
        self.assertFalse(target.exists())

    def test_missing_cellref_folder_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            txt = Path(tmp) / "txt"
            txt.mkdir()
            result = self.run_cli(txt, Path(tmp) / "mos", Path(tmp) / "no_cellref")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Cellref folder not found", result.stdout)


if __name__ == "__main__":
    unittest.main()
