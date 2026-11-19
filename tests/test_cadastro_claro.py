"""Claro cellref (cadastro_claro.py) on a tiny Claro network written as parser TXT.

The copy was checked byte by byte against the MoB_Claro original on the whole
PR network (W42 + MANDO of 2026-11-09, 8 data files): see alteracoes.md.
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

import cadastro_claro  # noqa: E402

NODE = "SJU1029_2"
CELL_A = "SJU1029_B66_4_RR_A_1"
CELL_B = "SJU1029_B66_4_RR_B_1"
NR_A = "SJU1029_N66_5_RR_A_1"

# Parser output: tab separated, latin-1 (the xml_to_txt contract).
NETWORK = {
    "ENodeBFunction": [["eNB", "eNBId", "eNodeBPlmnId_mcc", "eNodeBPlmnId_mnc"], [NODE, "771100", "330", "110"]],
    "EUtranCellFDD": [
        ["eNB", "eUtranCellFDDId", "cellId", "earfcndl", "dlChannelBandwidth", "tac",
         "physicalLayerCellIdGroup", "physicalLayerSubCellId", "administrativeState",
         "operationalState", "latitude", "longitude", "rachRootSequence", "crsGain", "cellRange",
         "primaryPlmnReserved", "primaryUpperLayerInd"],
        [NODE, CELL_A, "11", "66786", "20000", "100", "10", "2", "UNLOCKED", "ENABLED", "", "",
         "100", "0", "15", "false", "ON"],
        [NODE, CELL_B, "12", "66786", "20000", "100", "10", "1", "UNLOCKED", "ENABLED", "", "",
         "110", "0", "15", "false", "ON"],
    ],
    "EUtranCellTDD": [["eNB", "eUtranCellTDDId", "cellId", "earfcn", "channelBandwidth",
                       "latitude", "longitude"]],
    "EUtranCellRelation": [
        ["eNB", "EUtranCell", "eUtranCellRelationId", "EUtranFreqRelation", "isHoAllowed", "neighborCellRef"],
        [NODE, CELL_A, "330110-771100-12", "66786", "true",
         f"SubNetwork=PR,MeContext={NODE},ManagedElement={NODE},vsDataENodeBFunction=1,vsDataEUtranCellFDD={CELL_B}"],
    ],
    "NRCellCU": [["eNB", "nRCellCUId", "cellLocalId", "nCI", "nRTAC", "cellState", "serviceState"],
                 [NODE, NR_A, "1", "1685946369", "100", "ACTIVE", "IN_SERVICE"]],
    "NRCellDU": [["eNB", "nRCellDUId", "nRPCI", "ssbFrequency", "ssbFrequencyAutoSelected", "bandList",
                  "administrativeState", "operationalState", "nRTAC"],
                 [NODE, NR_A, "300", "0", "432590", "66", "UNLOCKED", "ENABLED", "100"]],
    "GNBCUCPFunction": [["eNB", "gNBId", "gNBIdLength", "pLMNId_mcc", "pLMNId_mnc"],
                        [NODE, "771100", "22", "330", "110"]],
}

MANDO_HEADER = ["C_UTRANCell_Name", "C_Status", "CC_NodebID", "C_Face", "C_Tech", "CS_Name",
                "T_Town_Name", "L_Latitude", "L_Longitude", "A_Latitude", "A_Longitude",
                "A_Azimuth_TN", "A_Mechanical_Tilt", "C_Electrical_Tilt", "A_Height_AGL_Ft",
                "AC_H_Beam_Width_Deg", "AC_Model", "C_MIMO_Type", "A_Coverage", "CS_Class",
                "CS_Op_Cluster", "CS_Morphology"]
# Only cell A is in MANDO: B falls back to the sector letter, the NR cell of
# sector A inherits the LTE azimuth of the same site + sector.
MANDO_ROWS = [[CELL_A, "On Air", NODE, "A", "LTE", "SJU Test Site", "San Juan", "18.40", "-66.05",
               "18.40", "-66.05", "30", "2", "4", "100", "65", "ANT-1", "4T4R", "Outdoor", "Macro",
               "CL_San Juan", "Urban"]]


def write_network(folder):
    folder.mkdir(parents=True, exist_ok=True)
    for mo, rows in NETWORK.items():
        with open(folder / f"{mo}.txt", "w", encoding="latin-1", newline="") as handle:
            csv.writer(handle, delimiter="\t", lineterminator="\r\n").writerows(rows)


def write_mando(path):
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        csv.writer(handle).writerows([MANDO_HEADER] + MANDO_ROWS)


class ClaroCellrefTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        base = Path(cls._tmp.name)
        cls.txt = base / "txt"
        cls.out = base / "Cellref"
        cls.mando = base / "mando_cells_2026-11-09.csv"
        write_network(cls.txt)
        write_mando(cls.mando)
        with redirect_stdout(io.StringIO()):
            cls.summary = cadastro_claro.construir(cls.txt, cls.mando, cls.out)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_writes_the_files_process_mos_reads(self):
        for name in ("EUtranCell_TDD_FDD.csv", "EUtranCell_TDD_FDD.txt", "cellref_5g.xlsx",
                     "EUtranCellRelation.txt", "5G_NRCellDU.txt", "cadastro_alertas.xlsx",
                     "cadastro_resumo.json"):
            self.assertTrue((self.out / name).is_file(), name)
        self.assertEqual((self.summary["celulas_lte"], self.summary["celulas_nr"]), (2, 1))

    def test_lte_physical_fields_and_their_source(self):
        with open(self.out / "EUtranCell_TDD_FDD.csv", encoding="latin-1", newline="") as handle:
            rows = {r["CELL"]: r for r in csv.DictReader(handle)}
        a, b = rows[CELL_A], rows[CELL_B]
        self.assertEqual((a["UF"], a["Site"], a["Setor"], a["CGI"]), ("SJU", "SJU1029", "A", "330110-771100-11"))
        self.assertEqual((float(a["Azimute"]), a["Azimute_Fonte"], a["Coord_Fonte"]), (30.0, "mando", "mando"))
        self.assertAlmostEqual(float(a["Altura"]), 30.5)  # 100 ft
        # B: not in MANDO -> site coordinates still from MANDO, azimuth from the letter.
        self.assertEqual((b["Coord_Fonte"], float(b["Latitude"])), ("mando", 18.40))
        self.assertEqual((float(b["Azimute"]), b["Azimute_Fonte"]), (120.0, "padrao_setor"))
        self.assertIn("cell not in MANDO", b["Alerta"])

    def test_nr_cell_inherits_the_sector_azimuth(self):
        import pandas as pd
        nr = pd.read_excel(self.out / "cellref_5g.xlsx", dtype=str).set_index("Cellname")
        self.assertEqual(nr.loc[NR_A, "Azimuth_Fonte"], "mando_setor")
        self.assertEqual(float(nr.loc[NR_A, "Azimuth"]), 30.0)
        self.assertEqual(nr.loc[NR_A, "CGI"], "330110-771100-1")
        self.assertEqual(nr.loc[NR_A, "DL_NR_ARFCN"], "432590")  # ssbFrequency 0 = chosen by the node

    def test_relation_target_comes_from_neighbor_cell_ref(self):
        with open(self.out / "EUtranCellRelation.txt", encoding="utf-8", newline="") as handle:
            rel = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual([(r["CELL"], r["CELL_tgt"], r["eNB_tgt"]) for r in rel], [(CELL_A, CELL_B, NODE)])


class MandoAndCliTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_folder_picks_newest_date_and_prefers_csv(self):
        folder = self.base / "MANDO"
        folder.mkdir()
        for name in ("mando_cells_2026-09-14.csv", "mando_cells_2026-11-09.csv.zip",
                     "mando_cells_2026-11-09.csv", "mando_cells_old.csv", "notes.txt"):
            (folder / name).write_text("x")
        self.assertEqual(cadastro_claro.achar_mando(folder).name, "mando_cells_2026-11-09.csv")
        (folder / "mando_cells_2026-11-09.csv").unlink()
        self.assertEqual(cadastro_claro.achar_mando(folder).name, "mando_cells_2026-11-09.csv.zip")
        self.assertEqual(cadastro_claro.achar_mando(folder / "notes.txt").name, "notes.txt")
        with self.assertRaises(FileNotFoundError):
            cadastro_claro.achar_mando(self.base / "missing")

    def _cli(self, *args):
        result = subprocess.run([sys.executable, str(ROOT / "cadastro_claro.py"), *map(str, args)],
                                cwd=str(ROOT), capture_output=True, text=True)
        return result.returncode, result.stdout

    def test_cli_refuses_same_folder_vivo_folder_and_missing_mando(self):
        txt = self.base / "txt"
        write_network(txt)
        write_mando(self.base / "mando_cells_2026-11-09.csv")
        code, out = self._cli(txt, self.base, txt)
        self.assertEqual(code, 1)
        self.assertIn("must be different", out)
        code, out = self._cli(txt, self.base, "C:/MoB/cellref_teste_claro")
        self.assertEqual(code, 1)
        self.assertIn("Vivo folder", out)
        self.assertFalse(os.path.exists("C:/MoB/cellref_teste_claro"))
        code, out = self._cli(txt, self.base / "empty", self.base / "out")
        self.assertEqual(code, 1)
        self.assertIn("MANDO not found", out)

    def test_cli_with_mando_folder(self):
        txt = self.base / "txt"
        write_network(txt)
        write_mando(self.base / "mando_cells_2026-11-09.csv")
        code, out = self._cli(txt, self.base, self.base / "Cellref")
        self.assertEqual(code, 0, out)
        self.assertIn('"celulas_lte": 2', out)
        self.assertTrue((self.base / "Cellref" / "cellref_5g.xlsx").is_file())


if __name__ == "__main__":
    unittest.main()
