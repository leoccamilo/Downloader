#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generate a single lightweight site list (4G + 5G) by Regional/UF/MUNICIPIO.

Reads:
  - cellref/EUtranCell_TDD_FDD.csv (LTE: columns Regional, UF, MUNICIPIO, eNB)
  - cellref/Cellref_5G*.csv (NR: columns Regional, UF, MUNICIPIO, SiteID)

Outputs:
  - cellref/sites_list.txt (tab-separated: Regional, UF, MUNICIPIO, SiteID, Tech)

One row per site (eNB or SiteID), deduplicated. Use this file in the Downloader
tool via "Load site list" so the tool can filter by Regional/UF/Municipality.

Usage:
  python update_site_list.py [cellref_folder]
  Default cellref_folder = folder containing this script + /cellref
"""

import csv
import os
import glob
import sys


def normalize_header(name):
    return (name or "").strip()


def read_csv_path(path, encoding="utf-8"):
    """Read CSV; return list of dicts (first row = headers)."""
    rows = []
    with open(path, "r", encoding=encoding, errors="replace") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return []
        header = [normalize_header(h) for h in header]
        for row in reader:
            if len(row) < len(header):
                row.extend([""] * (len(header) - len(row)))
            rows.append(dict(zip(header, row[: len(header)])))
    return rows


def run(cellref_dir: str) -> str:
    cellref_dir = os.path.abspath(cellref_dir)
    out_path = os.path.join(cellref_dir, "sites_list.txt")
    seen = set()
    out_rows = []

    # LTE: EUtranCell_TDD_FDD.csv
    lte_path = os.path.join(cellref_dir, "EUtranCell_TDD_FDD.csv")
    if os.path.isfile(lte_path):
        data = read_csv_path(lte_path)
        for r in data:
            regional = (r.get("Regional") or "").strip()
            uf = (r.get("UF") or "").strip().upper()
            municipio = (r.get("MUNICIPIO") or "").strip()
            enb = (r.get("eNB") or "").strip()
            if not enb:
                continue
            key = (regional, uf, municipio, enb, "LTE")
            if key in seen:
                continue
            seen.add(key)
            out_rows.append((regional, uf, municipio, enb, "LTE"))
        print(f"LTE: {len([k for k in seen if k[4] == 'LTE'])} sites from {lte_path}")
    else:
        print(f"LTE file not found: {lte_path}")

    # 5G: Cellref_5G*.csv
    for path in sorted(glob.glob(os.path.join(cellref_dir, "Cellref_5G*.csv"))):
        data = read_csv_path(path)
        for r in data:
            regional = (r.get("Regional") or "").strip()
            uf = (r.get("UF") or "").strip().upper()
            municipio = (r.get("MUNICIPIO") or "").strip()
            site_id = (r.get("SiteID") or r.get("SiteId") or "").strip()
            if not site_id:
                continue
            key = (regional, uf, municipio, site_id, "NR")
            if key in seen:
                continue
            seen.add(key)
            out_rows.append((regional, uf, municipio, site_id, "NR"))
        print(f"NR: read {path}")

    # Also try Cellref_5G*.txt if present
    for path in sorted(glob.glob(os.path.join(cellref_dir, "Cellref_5G*.txt"))):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            first = f.readline()
            if "\t" in first:
                sep = "\t"
            else:
                sep = ","
            f.seek(0)
            reader = csv.DictReader(f, delimiter=sep)
            for r in reader:
                regional = (r.get("Regional") or "").strip()
                uf = (r.get("UF") or "").strip().upper()
                municipio = (r.get("MUNICIPIO") or "").strip()
                site_id = (r.get("SiteID") or r.get("SiteId") or "").strip()
                if not site_id:
                    continue
                key = (regional, uf, municipio, site_id, "NR")
                if key in seen:
                    continue
                seen.add(key)
                out_rows.append((regional, uf, municipio, site_id, "NR"))
        print(f"NR: read {path}")

    os.makedirs(cellref_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write("Regional\tUF\tMUNICIPIO\tSiteID\tTech\n")
        for t in out_rows:
            f.write("\t".join(t) + "\n")

    print(f"Written {len(out_rows)} sites to {out_path}")
    return out_path


def main():
    if len(sys.argv) > 1:
        cellref_dir = sys.argv[1]
    else:
        base = os.path.dirname(os.path.abspath(__file__))
        cellref_dir = os.path.join(base, "cellref")
    run(cellref_dir)


if __name__ == "__main__":
    main()
