#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Extract (unzip) dump output so XML files are available for the XML→Parquet step.

Pipeline: Execute Dump → [this step] → Parse XML to Parquet → Parquet to TXT.
  - Input: folder where the dump wrote files (e.g. .zip per ENM job).
  - Output: folder where extracted XML/export files will be written (default: input_dir/extracted).

Usage:
  python extract_dump.py <input_dir> [output_dir]
"""

import os
import sys
import zipfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    if len(sys.argv) < 2:
        print("Usage: python extract_dump.py <input_dir> [output_dir]")
        print("  input_dir  = folder with dump output (e.g. .zip files)")
        print("  output_dir = folder for extracted XML (default: input_dir/extracted)")
        sys.exit(1)

    input_dir = os.path.abspath(sys.argv[1].replace("/", os.sep))
    if len(sys.argv) > 2:
        output_dir = os.path.abspath(sys.argv[2].replace("/", os.sep))
    else:
        output_dir = os.path.join(input_dir, "extracted")

    if not os.path.isdir(input_dir):
        print(f"Input directory not found: {input_dir}")
        sys.exit(1)
    os.makedirs(output_dir, exist_ok=True)

    zip_files = [f for f in os.listdir(input_dir) if f.lower().endswith(".zip")]
    if not zip_files:
        print(f"No .zip files found in {input_dir}")
        print("If the dump already wrote XML files here, skip this step and run Parse XML to Parquet.")
        sys.exit(0)

    print(f"Found {len(zip_files)} .zip file(s). Extracting to {output_dir}")
    for i, name in enumerate(zip_files, 1):
        path = os.path.join(input_dir, name)
        try:
            with zipfile.ZipFile(path, "r") as zf:
                zf.extractall(output_dir)
            print(f"  [{i}/{len(zip_files)}] {name} -> extracted")
        except zipfile.BadZipFile as e:
            print(f"  [{i}/{len(zip_files)}] {name} SKIP (not a valid zip): {e}")
        except Exception as e:
            print(f"  [{i}/{len(zip_files)}] {name} ERROR: {e}")
            sys.exit(1)

    print("Extract completed. Next step: Parse XML to Parquet (use output folder as input).")


if __name__ == "__main__":
    main()
