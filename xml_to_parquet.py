#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XML Parser - Converts 3GPP XMLs (Ericsson) to Parquet part files per MO.

Adapted from eNB_Fake Detector (nr_neighbor_viewer).
Uses lxml iterparse with streaming flush to keep memory bounded.

Usage:
  python xml_to_parquet.py <input_dir> [output_dir]
  If output_dir is omitted, parquets are written to input_dir.

Requires: lxml, pandas, pyarrow
"""

import os
import sys
from pathlib import Path

_4G_ONLY_MOS = {"EUtranCellRelation"}
_FLUSH_SIZE = 100_000


def parse_ericsson_xmls(input_dir: str, output_dir: str):
    """Convert 3GPP XMLs (Ericsson) to Parquet part files, one set per MO."""
    try:
        from lxml import etree
    except ImportError:
        print("lxml is not installed. Install with: pip install lxml")
        sys.exit(1)

    import pandas as pd

    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    old_parts = list(output_path.glob("*_part_*.parquet"))
    if old_parts:
        for f in old_parts:
            f.unlink()
        print(f"Cleaned {len(old_parts)} old parquet part files")

    mo_data = {}
    mo_part_counts = {}
    mo_total_counts = {}
    skipped_nr = 0

    def _flush_mo(mo_name):
        if mo_name not in mo_data or not mo_data[mo_name]:
            return
        part_num = mo_part_counts.get(mo_name, 0)
        df = pd.DataFrame(mo_data[mo_name])
        part_file = output_path / f"{mo_name}_part_{part_num:04d}.parquet"
        df.to_parquet(part_file, index=False, engine="pyarrow")
        count = len(mo_data[mo_name])
        mo_part_counts[mo_name] = part_num + 1
        mo_total_counts[mo_name] = mo_total_counts.get(mo_name, 0) + count
        mo_data[mo_name] = []

    xml_files = list(input_path.glob("*.xml"))
    if not xml_files:
        print("No XML files found to process.")
        return

    print(f"Processing {len(xml_files)} XML file(s)...", flush=True)

    TAG_VS = "{genericNrm.xsd}VsDataContainer"
    TAG_ME_CONTEXT = "{genericNrm.xsd}MeContext"
    TAG_MANAGED_ELEMENT = "{genericNrm.xsd}ManagedElement"
    TAG_VS_DATA_TYPE = "{genericNrm.xsd}attributes/{genericNrm.xsd}vsDataType"

    for xml_path in xml_files:
        print(f"Processing: {xml_path.name}", flush=True)

        me_context = ""
        managed_element = ""
        vs_stack = []
        record_count = 0

        context = etree.iterparse(str(xml_path), events=("start", "end"))

        for event, elem in context:
            tag = elem.tag

            if event == "start":
                if tag == TAG_ME_CONTEXT:
                    me_context = elem.get("id", "")
                elif tag == TAG_MANAGED_ELEMENT:
                    me_id = elem.get("id", "")
                    managed_element = me_context if me_id == "1" else me_id
                elif tag == TAG_VS:
                    vs_id = elem.get("id", "")
                    vs_stack.append((vs_id, None))
                continue

            if tag == TAG_VS:
                type_elem = elem.find(TAG_VS_DATA_TYPE)
                vs_type = type_elem.text.strip() if type_elem is not None and type_elem.text else None

                if vs_stack:
                    vs_stack[-1] = (vs_stack[-1][0], vs_type)

                # Backfill ancestor types (iterparse gives child 'end' before parent 'end')
                # Walk up the tree to get vsDataType for each VsDataContainer ancestor
                stack_ids = [s[0] for s in vs_stack]
                p = elem.getparent()
                anc_idx = len(vs_stack) - 2  # index of first ancestor
                while p is not None and anc_idx >= 0:
                    if p.tag == TAG_VS:
                        pid = p.get("id", "")
                        te = p.find(TAG_VS_DATA_TYPE)
                        pt = te.text.strip() if te is not None and te.text else None
                        if pt and vs_stack[anc_idx][0] == pid:
                            vs_stack[anc_idx] = (pid, pt)
                            anc_idx -= 1
                    p = p.getparent()

                if vs_type is not None:
                    mo_name = vs_type.replace("vsData", "")

                    if mo_name not in mo_data:
                        mo_data[mo_name] = []

                    parameters = {
                        "eNB": me_context,
                        "ManagedElement": managed_element,
                        "MO": mo_name,
                    }

                    has_eutran_cell = False
                    has_nr_cell = False
                    for anc_id, anc_type in vs_stack[:-1]:
                        if not anc_id or not anc_type:
                            continue
                        if anc_type in ("vsDataEUtranCellFDD", "vsDataEUtranCellTDD"):
                            parameters["EUtranCell"] = anc_id
                            has_eutran_cell = True
                        elif anc_type in ("vsDataNRCellCU", "vsDataNRCellDU"):
                            parameters["NRCell"] = anc_id
                            has_nr_cell = True
                        elif anc_type == "vsDataENodeBFunction":
                            parameters["ENodeBFunction"] = anc_id
                        elif anc_type == "vsDataGNBCUCPFunction":
                            parameters["GNBCUCPFunction"] = anc_id
                        elif anc_type == "vsDataGNBDUFunction":
                            parameters["GNBDUFunction"] = anc_id
                        elif anc_type == "vsDataEUtranFreqRelation":
                            parameters["EUtranFreqRelation"] = anc_id
                        elif anc_type == "vsDataNRFreqRelation":
                            parameters["NRFreqRelation"] = anc_id
                        elif anc_type.startswith("vsData") and anc_type != vs_type:
                            column_name = anc_type.replace("vsData", "")
                            parameters[column_name] = anc_id

                    if mo_name in _4G_ONLY_MOS and has_nr_cell and not has_eutran_cell:
                        skipped_nr += 1
                        vs_stack.pop()
                        elem.clear()
                        continue

                    vs_data_element = elem.find(
                        f"{{genericNrm.xsd}}attributes/{{EricssonSpecificAttributes.xsd}}{vs_type}"
                    )
                    record_has_data = False
                    if vs_data_element is not None:
                        for param in vs_data_element:
                            param_name = param.tag.split("}")[-1]
                            if len(param):
                                for sub_param in param:
                                    sub_param_name = sub_param.tag.split("}")[-1]
                                    sub_param_value = (sub_param.text or "").strip()
                                    if sub_param_value != "":
                                        parameters[f"{param_name}_{sub_param_name}"] = sub_param_value
                                        record_has_data = True
                            else:
                                param_value = (param.text or "").strip()
                                if param_value != "":
                                    parameters[param_name] = param_value
                                    record_has_data = True

                    if record_has_data:
                        mo_data[mo_name].append(parameters)
                        if len(mo_data[mo_name]) >= _FLUSH_SIZE:
                            _flush_mo(mo_name)
                            print(f"  {mo_name}: flushed {mo_total_counts[mo_name]:,} records so far", flush=True)

                    record_count += 1
                    if record_count % 200000 == 0:
                        print(f"  ...{record_count:,} records processed", flush=True)

                vs_stack.pop()
                elem.clear()
                prev = elem.getprevious()
                while prev is not None:
                    if prev.tag == TAG_VS:
                        prev.getparent().remove(prev)
                        prev = elem.getprevious()
                    else:
                        break

            elif tag == TAG_ME_CONTEXT or tag == TAG_MANAGED_ELEMENT:
                elem.clear()
                while elem.getprevious() is not None:
                    del elem.getparent()[0]

        del context
        print(f"  {xml_path.name}: {record_count:,} total records parsed", flush=True)

    for mo_name in list(mo_data.keys()):
        _flush_mo(mo_name)

    if skipped_nr > 0:
        print(f"4G filter: skipped {skipped_nr:,} NR (5G) records from EUtranCellRelation")

    files_written = 0
    for mo_name, total in sorted(mo_total_counts.items()):
        parts = mo_part_counts.get(mo_name, 0)
        print(f"  {mo_name}: {total:,} records in {parts} parquet part(s)")
        files_written += 1

    print(f"XML parsing completed: {files_written} MO(s) written as Parquet.")


def main():
    if len(sys.argv) < 2:
        print("Usage: python xml_to_parquet.py <input_dir> [output_dir]")
        print("  input_dir  = folder with 3GPP XML files (.xml)")
        print("  output_dir = folder for *_part*.parquet (default: same as input_dir)")
        sys.exit(1)

    input_dir = os.path.abspath(sys.argv[1].replace("/", os.sep))
    output_dir = os.path.abspath((sys.argv[2] if len(sys.argv) > 2 else sys.argv[1]).replace("/", os.sep))

    if not os.path.isdir(input_dir):
        print(f"Input directory not found: {input_dir}")
        sys.exit(1)

    parse_ericsson_xmls(input_dir, output_dir)


if __name__ == "__main__":
    main()
