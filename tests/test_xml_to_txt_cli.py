"""xml_to_txt.py command line as the server calls it (Vivo default and Claro option)."""
import csv
import os
import subprocess
from contextlib import redirect_stdout
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# One 4G relation (under EUtranCellFDD) and one 5G -> 4G relation (under NRCellCU), Claro naming.
XML = '''<root xmlns:g="genericNrm.xsd" xmlns:e="EricssonSpecificAttributes.xsd">
<g:MeContext id="SJU1029_2"><g:ManagedElement id="SJU1029_2">
<g:VsDataContainer id="1"><g:attributes><g:vsDataType>vsDataENodeBFunction</g:vsDataType>
<e:vsDataENodeBFunction><e:eNBId>102902</e:eNBId></e:vsDataENodeBFunction></g:attributes>
 <g:VsDataContainer id="SJU1029_B66_4_RR_A_1"><g:attributes><g:vsDataType>vsDataEUtranCellFDD</g:vsDataType>
 <e:vsDataEUtranCellFDD><e:cellId>11</e:cellId></e:vsDataEUtranCellFDD></g:attributes>
  <g:VsDataContainer id="66986"><g:attributes><g:vsDataType>vsDataEUtranFreqRelation</g:vsDataType>
  <e:vsDataEUtranFreqRelation><e:cellReselectionPriority>5</e:cellReselectionPriority></e:vsDataEUtranFreqRelation></g:attributes>
   <g:VsDataContainer id="SJU1029_B66_4_RR_B_1"><g:attributes><g:vsDataType>vsDataEUtranCellRelation</g:vsDataType>
   <e:vsDataEUtranCellRelation><e:isHoAllowed>true</e:isHoAllowed></e:vsDataEUtranCellRelation></g:attributes></g:VsDataContainer>
  </g:VsDataContainer>
 </g:VsDataContainer>
</g:VsDataContainer>
<g:VsDataContainer id="1"><g:attributes><g:vsDataType>vsDataGNBCUCPFunction</g:vsDataType>
<e:vsDataGNBCUCPFunction><e:gNBId>102902</e:gNBId></e:vsDataGNBCUCPFunction></g:attributes>
 <g:VsDataContainer id="SJU1029_N66_5_RR_A_1"><g:attributes><g:vsDataType>vsDataNRCellCU</g:vsDataType>
 <e:vsDataNRCellCU><e:cellLocalId>1</e:cellLocalId></e:vsDataNRCellCU></g:attributes>
  <g:VsDataContainer id="330110-771101-33"><g:attributes><g:vsDataType>vsDataEUtranCellRelation</g:vsDataType>
  <e:vsDataEUtranCellRelation><e:isHoAllowed>true</e:isHoAllowed></e:vsDataEUtranCellRelation></g:attributes></g:VsDataContainer>
 </g:VsDataContainer>
</g:VsDataContainer>
</g:ManagedElement></g:MeContext></root>'''


def run_parser(folder: Path, *extra):
    listing = folder / "inputs.txt"
    # Windows tools often save the list with a BOM: it must not break the first path.
    listing.write_bytes("﻿".encode("utf-8") + str(folder / "dump.xml").encode("utf-8") + b"\n")
    out = folder / "out"
    result = subprocess.run([sys.executable, str(ROOT / "xml_to_txt.py"), "--file-list", str(listing),
                             "--out", str(out), *extra], capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    with open(out / "EUtranCellRelation.txt", encoding="latin-1", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


class XmlToTxtCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        (self.folder / "dump.xml").write_text(XML, encoding="utf-8")

    def test_default_keeps_only_4g_relations(self):
        rows = run_parser(self.folder)
        self.assertEqual([r["EUtranCell"] for r in rows], ["SJU1029_B66_4_RR_A_1"])

    def test_claro_option_keeps_5g_to_4g_relations(self):
        rows = run_parser(self.folder, "--include-nr-relations")
        self.assertEqual(len(rows), 2)
        nr = next(r for r in rows if r.get("NRCell"))
        self.assertEqual(nr["NRCell"], "SJU1029_N66_5_RR_A_1")
        self.assertEqual(nr["GNBCUCPFunction"], "1")
        self.assertEqual(nr["eNB"], "SJU1029_2")


class SpillTests(unittest.TestCase):
    """The memory budget only decides when rows go to disk; the TXT must not change."""

    def test_output_is_identical_with_or_without_spilling(self):
        sys.path.insert(0, str(ROOT))
        import xml_to_txt
        outputs = {}
        original = xml_to_txt._SPILL_BYTES
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "dump.xml").write_text(XML, encoding="utf-8")
            try:
                for name, budget in (("every_row", 1), ("never", 1 << 40)):
                    xml_to_txt._SPILL_BYTES = budget
                    out = folder / name
                    with open(os.devnull, "w") as quiet, redirect_stdout(quiet):
                        xml_to_txt.parse_ericsson_xmls([folder / "dump.xml"], str(out), include_nr_relations=True)
                    self.assertFalse((out / ".xml_to_txt_spool").exists(), "spool must be removed")
                    outputs[name] = {p.name: p.read_bytes() for p in sorted(out.glob("*.txt"))}
            finally:
                xml_to_txt._SPILL_BYTES = original
        self.assertEqual(len(outputs["never"]), 6)
        self.assertEqual(outputs["every_row"], outputs["never"])


if __name__ == "__main__":
    unittest.main()
