#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Generic Parquet → TXT (tab-separated) conversion for any MO.

Use after the XML parser: produces one .txt per MO from parquet files.
For MOs added as "Additional MOs" in the Downloader this ensures every
MO present in parquet is converted to TXT.

Usage:
  python parquet_to_txt.py [input_dir] [output_dir]
  If omitted, uses current directory for both.

Requires: pandas, pyarrow
"""

import argparse
import gc
import glob
import os
import re
import time
import sys


def mo_name_from_parquet_path(path: str) -> str:
    """
    Extract MO name from parquet path.
    Format: {mo_name}_{xml_stem}_{timestamp}_part{N}.parquet
    """
    base = os.path.basename(path).replace(".parquet", "")
    if "_part" in base:
        base = base.split("_part")[0]
    # Remove timestamp: _DD_HH_MM_SS
    base = re.sub(r"_\d{1,2}_\d{1,2}_\d{1,2}_\d{1,2}$", "", base)
    # Remove stem: _ENM_YYYYMMDD_HH_MM_SS
    base = re.sub(r"_[A-Z0-9]+_\d{8}_\d{2}_\d{2}_\d{2}$", "", base)
    return base or "Unknown"


def clear_output_txt_files(output_dir: str) -> None:
    """Remove existing .txt files in output_dir so old parser results are not kept."""
    if not os.path.isdir(output_dir):
        return
    for name in os.listdir(output_dir):
        if name.endswith(".txt"):
            path = os.path.join(output_dir, name)
            try:
                if os.path.isfile(path):
                    os.unlink(path)
            except OSError as e:
                print(f"Warning: could not remove {path}: {e}")


def delete_file_with_retry(path: str, retries: int = 5, delay_sec: float = 0.4) -> bool:
    """Delete a file with retries to handle transient Windows file locks."""
    for attempt in range(1, retries + 1):
        try:
            if os.path.exists(path):
                # Ensure read-only attributes do not block deletion.
                os.chmod(path, 0o666)
                os.unlink(path)
            return True
        except OSError as e:
            if attempt == retries:
                print(f"  Warning: could not remove {path}: {e}")
                return False
            time.sleep(delay_sec)
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Convert parquet files (XML parser output) to tab-separated TXT per MO."
    )
    parser.add_argument(
        "input_dir",
        nargs="?",
        default=os.getcwd(),
        help="Folder with *_part*.parquet files (default: current directory)",
    )
    parser.add_argument(
        "output_dir",
        nargs="?",
        default=None,
        help="Folder for .txt output (default: same as input)",
    )
    args = parser.parse_args()
    input_dir = os.path.abspath(args.input_dir)
    output_dir = os.path.abspath(args.output_dir or args.input_dir or input_dir)

    if not os.path.isdir(input_dir):
        print(f"Folder not found: {input_dir}")
        sys.exit(1)
    os.makedirs(output_dir, exist_ok=True)

    # Clear existing .txt in output so old results are not kept
    clear_output_txt_files(output_dir)
    print("Output directory cleared (old .txt files removed).")

    pattern = os.path.join(input_dir, "*_part*.parquet")
    files = sorted(glob.glob(pattern))
    if not files:
        print(f"No *_part*.parquet files in {input_dir}")
        sys.exit(0)

    # Group by MO
    by_mo = {}
    for f in files:
        mo = mo_name_from_parquet_path(f)
        by_mo.setdefault(mo, []).append(f)

    try:
        import pandas as pd
    except ImportError:
        print("Requires pandas: pip install pandas pyarrow")
        sys.exit(1)

    print(f"Found {len(by_mo)} MO(s), {len(files)} parquet file(s).")
    for mo, paths in sorted(by_mo.items()):
        try:
            dfs = [pd.read_parquet(p) for p in paths]
            df = pd.concat(dfs, ignore_index=True)
            out_path = os.path.join(output_dir, f"{mo}.txt")
            df.to_csv(out_path, sep="\t", index=False, encoding="latin-1", errors="replace")
            print(f"  {mo}: {len(df)} rows -> {out_path}")
            # Release references to avoid keeping parquet file handles open on Windows.
            del df
            del dfs
            gc.collect()
        except Exception as e:
            print(f"  {mo}: ERROR - {e}")

    # Clean up parquet files (intermediate, no longer needed)
    removed = 0
    for f in files:
        try:
            if delete_file_with_retry(f):
                removed += 1
        except Exception as e:
            print(f"  Warning: could not remove {f}: {e}")
    print(f"Cleanup: removed {removed} parquet file(s).")

    print("Generic conversion completed.")


if __name__ == "__main__":
    main()
