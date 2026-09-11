#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XML Parser - Converts 3GPP XMLs (Ericsson) straight to one TXT per MO.

Adapted from eNB_Fake Detector (nr_neighbor_viewer).
Uses lxml iterparse; records are buffered per MO and spilled to a temporary
spool when the buffer grows, so memory stays bounded on large dumps. The TXT
header is only known at the end (columns appear as the XML is read), so each
MO is written once, at the end, from spool + buffer.

Output format (same as the old XML -> Parquet -> TXT chain): tab-separated,
latin-1, CRLF, columns in order of first appearance, one <MO>.txt per MO.

Accepts .xml, .xml.gz and .zip inputs. ZIPs are read in place (each XML
member is streamed straight from the archive) — no extraction to disk.

Usage:
  python xml_to_txt.py <input_dir> [output_dir]
      Parse every *.xml in input_dir. If output_dir is omitted, TXTs are
      written to input_dir.
  python xml_to_txt.py --file-list <list.txt> --out <output_dir>
      Parse the files listed in list.txt (one path per line: .zip/.xml/.xml.gz).

Requires: lxml
"""

import argparse
import csv
import gzip
import marshal
import os
import shutil
import sys
import zipfile
from contextlib import contextmanager
from pathlib import Path

_4G_ONLY_MOS = {"EUtranCellRelation"}
# Total buffered rows (all MOs) before spilling to the spool on disk.
_SPILL_ROWS = 200_000
_SPOOL_DIR_NAME = ".xml_to_txt_spool"


def _is_xml_name(name: str) -> bool:
    n = name.lower()
    return n.endswith(".xml") or n.endswith(".xml.gz")


@contextmanager
def _open_xml_file(path: Path):
    opener = gzip.open if path.name.lower().endswith(".gz") else open
    with opener(path, "rb") as fh:
        yield fh


@contextmanager
def _open_zip_member(zip_path: Path, member: str):
    with zipfile.ZipFile(zip_path) as zf, zf.open(member) as fh:
        if member.lower().endswith(".gz"):
            with gzip.GzipFile(fileobj=fh) as gz:
                yield gz
        else:
            yield fh


def _zip_sources(zip_path: Path, skip_names):
    """(label, opener) pairs for the XML members of a ZIP.

    Members whose file name is in skip_names (already present as a plain XML,
    e.g. extracted earlier next to the ZIP) are skipped to avoid double rows.
    """
    try:
        with zipfile.ZipFile(zip_path) as zf:
            members = [m for m in zf.namelist() if not m.endswith("/") and _is_xml_name(m)]
    except zipfile.BadZipFile as e:
        print(f"Invalid ZIP, skipped: {zip_path.name} ({e})")
        return []
    if not members:
        print(f"No XML inside {zip_path.name}, skipped")
        return []
    fresh = [m for m in members if Path(m).name.lower() not in skip_names]
    if not fresh:
        print(f"{zip_path.name}: already extracted, using the XML file(s) instead")
        return []
    out = []
    for m in fresh:
        label = f"{zip_path.name} > {m}" if len(members) > 1 else f"{zip_path.name} > {Path(m).name}"
        out.append((label, lambda p=zip_path, m=m: _open_zip_member(p, m)))
    return out


def collect_xml_sources(inputs):
    """Expand inputs (folders, .xml, .xml.gz, .zip) into (label, opener) pairs.

    A folder contributes its XML files and its ZIPs. Each opener is a context
    manager factory yielding a binary stream of XML.
    """
    files = []
    for raw in inputs:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted((x for x in p.iterdir() if x.is_file()), key=lambda x: x.name.lower()))
        elif p.is_file():
            files.append(p)
        else:
            print(f"Not found, skipped: {p}")

    xml_names = {f.name.lower() for f in files if _is_xml_name(f.name)}
    sources = []
    for f in files:
        if _is_xml_name(f.name):
            sources.append((f.name, lambda f=f: _open_xml_file(f)))
        elif f.suffix.lower() == ".zip":
            sources.extend(_zip_sources(f, xml_names))
        elif len(inputs) == 1 and Path(inputs[0]).is_dir():
            continue  # other files in a scanned folder are simply ignored
        else:
            print(f"Unsupported file type, skipped: {f.name}")
    return sources


class TxtSink:
    """Collects records per MO and writes one tab-separated TXT per MO.

    Columns only ever grow (first-appearance order), so a row stored when an
    MO had k columns is a prefix of the final header; it is padded at the end.
    """

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.spool_dir = output_dir / _SPOOL_DIR_NAME
        self.columns = {}   # mo -> {column: index}
        self.buffers = {}   # mo -> [row lists]
        self.spooled = set()
        self.row_counts = {}
        self.buffered = 0
        if self.spool_dir.exists():
            shutil.rmtree(self.spool_dir, ignore_errors=True)

    def add(self, mo_name, record):
        cols = self.columns.setdefault(mo_name, {})
        for key in record:
            if key not in cols:
                cols[key] = len(cols)
        row = [""] * len(cols)
        for key, value in record.items():
            row[cols[key]] = value
        self.buffers.setdefault(mo_name, []).append(row)
        self.row_counts[mo_name] = self.row_counts.get(mo_name, 0) + 1
        self.buffered += 1
        if self.buffered >= _SPILL_ROWS:
            self._spill()

    def _spool_path(self, mo_name):
        return self.spool_dir / f"{mo_name}.bin"

    def _spill(self):
        self.spool_dir.mkdir(parents=True, exist_ok=True)
        for mo_name, rows in self.buffers.items():
            if rows:
                with open(self._spool_path(mo_name), "ab") as f:
                    marshal.dump(rows, f)
                self.spooled.add(mo_name)
                self.buffers[mo_name] = []
        self.buffered = 0

    def _iter_rows(self, mo_name):
        if mo_name in self.spooled:
            with open(self._spool_path(mo_name), "rb") as f:
                while True:
                    try:
                        chunk = marshal.load(f)
                    except EOFError:
                        break
                    yield from chunk
        yield from self.buffers.get(mo_name, [])

    def write_all(self):
        """Write <MO>.txt for every MO seen. Returns {mo: row_count}."""
        written = {}
        for mo_name in sorted(self.columns):
            header = list(self.columns[mo_name])
            width = len(header)
            out_path = self.output_dir / f"{mo_name}.txt"
            with open(out_path, "w", encoding="latin-1", errors="replace", newline="") as f:
                writer = csv.writer(f, delimiter="\t", lineterminator="\r\n")
                writer.writerow(header)
                for row in self._iter_rows(mo_name):
                    if len(row) < width:
                        row.extend([""] * (width - len(row)))
                    writer.writerow(row)
            self.buffers[mo_name] = []
            written[mo_name] = self.row_counts.get(mo_name, 0)
        shutil.rmtree(self.spool_dir, ignore_errors=True)
        return written


def clear_output_txt_files(output_dir: Path):
    """Remove existing .txt files in output_dir so old parser results are not kept."""
    removed = 0
    for f in output_dir.glob("*.txt"):
        try:
            f.unlink()
            removed += 1
        except OSError as e:
            print(f"Warning: could not remove {f}: {e}")
    return removed


def parse_ericsson_xmls(inputs, output_dir: str):
    """Convert 3GPP XMLs (Ericsson) to one TXT per MO.

    inputs: a folder path, or a list of folders / .xml / .xml.gz / .zip paths.
    """
    try:
        from lxml import etree
    except ImportError:
        print("lxml is not installed. Install with: pip install lxml")
        sys.exit(1)

    if isinstance(inputs, (str, Path)):
        inputs = [inputs]

    sources = collect_xml_sources(inputs)
    if not sources:
        print("No XML files found to process.")
        return

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    removed = clear_output_txt_files(output_path)
    if removed:
        print(f"Output directory cleared ({removed} old .txt file(s) removed).")

    sink = TxtSink(output_path)
    skipped_nr = 0

    print(f"Processing {len(sources)} XML file(s)...", flush=True)

    TAG_VS = "{genericNrm.xsd}VsDataContainer"
    TAG_ME_CONTEXT = "{genericNrm.xsd}MeContext"
    TAG_MANAGED_ELEMENT = "{genericNrm.xsd}ManagedElement"
    TAG_VS_DATA_TYPE = "{genericNrm.xsd}attributes/{genericNrm.xsd}vsDataType"

    for file_idx, (label, opener) in enumerate(sources, 1):
        print(f"[{file_idx}/{len(sources)}] Processing: {label}", flush=True)

        me_context = ""
        managed_element = ""
        vs_stack = []
        record_count = 0

        try:
            with opener() as stream:
                context = etree.iterparse(stream, events=("start", "end"))

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
                                sink.add(mo_name, parameters)

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
        except (etree.XMLSyntaxError, OSError, zipfile.BadZipFile, EOFError) as e:
            print(f"  ERROR reading {label}: {e} — records parsed so far are kept", flush=True)

        print(f"  {label}: {record_count:,} total records parsed", flush=True)

    if skipped_nr > 0:
        print(f"4G filter: skipped {skipped_nr:,} NR (5G) records from EUtranCellRelation")

    print("Writing TXT files...", flush=True)
    written = sink.write_all()
    for mo_name, total in written.items():
        print(f"  {mo_name}: {total:,} rows -> {mo_name}.txt")

    print(f"XML parsing completed: {len(written)} MO(s) written as TXT.")


def main():
    parser = argparse.ArgumentParser(
        description="Convert 3GPP XMLs (Ericsson) to one tab-separated TXT per MO."
    )
    parser.add_argument("input_dir", nargs="?", help="Folder with 3GPP XML files (.xml)")
    parser.add_argument("output_dir", nargs="?", help="Folder for <MO>.txt (default: input_dir)")
    parser.add_argument("--file-list", help="Text file with one input path per line (.zip/.xml/.xml.gz)")
    parser.add_argument("--out", help="Output folder (required with --file-list)")
    args = parser.parse_args()

    if args.file_list:
        if not args.out:
            parser.error("--out is required with --file-list")
        with open(args.file_list, "r", encoding="utf-8") as f:
            inputs = [line.strip() for line in f if line.strip()]
        if not inputs:
            print("File list is empty.")
            sys.exit(1)
        parse_ericsson_xmls(inputs, os.path.abspath(args.out))
        return

    if not args.input_dir:
        parser.print_help()
        sys.exit(1)

    input_dir = os.path.abspath(args.input_dir.replace("/", os.sep))
    output_dir = os.path.abspath((args.output_dir or args.input_dir).replace("/", os.sep))

    if not os.path.isdir(input_dir):
        print(f"Input directory not found: {input_dir}")
        sys.exit(1)

    parse_ericsson_xmls(input_dir, output_dir)


if __name__ == "__main__":
    main()
