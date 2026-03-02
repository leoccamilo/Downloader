#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Post-processing step 4 (Camilo): derive columns + merge TXT outputs with cellref.xlsx.

Reads raw TXT files from Parquet->TXT output, derives missing columns (UF, CELL,
Termpoint, PCI, Banda), enriches with cellref data, and writes results to the output
folder. Cellref folder is typically C:/Downloader/cellref.
Only cellref.xlsx is required (SCIENCE.xlsx is NOT used).
MOs may be missing from the dump; the script skips missing files/columns and does not fail.
Cellref is OPTIONAL: if cellref.xlsx is missing, script continues and still processes
EUtranCellRelation (which does not require cellref).

Usage:
  python post_process_4_camilo.py <input_txt_dir> <cellref_dir> [output_dir]
  If output_dir is omitted, uses input_txt_dir.
"""

import os
import sys

CELLREF_DEFAULT = "C:/Downloader/cellref"


def main():
    if len(sys.argv) < 3:
        print("Usage: python post_process_4_camilo.py <input_txt_dir> <cellref_dir> [output_dir]")
        print("  input_txt_dir = folder with TXT files from Parquet->TXT")
        print("  cellref_dir   = folder with cellref.xlsx (e.g. C:/Downloader/cellref)")
        print("  output_dir    = folder for enriched output (default: same as input_txt_dir)")
        sys.exit(1)

    input_dir = os.path.abspath(sys.argv[1].replace("/", os.sep))
    cellref_dir = os.path.abspath(sys.argv[2].replace("/", os.sep))
    output_dir = os.path.abspath((sys.argv[3] if len(sys.argv) > 3 else sys.argv[1]).replace("/", os.sep))

    if not os.path.isdir(input_dir):
        print(f"Input directory not found: {input_dir}")
        sys.exit(1)
    os.makedirs(output_dir, exist_ok=True)

    try:
        import pandas as pd
    except ImportError:
        print("Requires pandas and openpyxl: pip install pandas openpyxl")
        sys.exit(1)

    # Cellref is optional: TermpointToMme, ENodeBFunction, EUtranCellFDD need it;
    # EUtranCellRelation does NOT need cellref (only eNB/EUtranCell from parser).
    cellref_full = None
    cellref_site = None
    if os.path.isdir(cellref_dir):
        cellref_path = os.path.join(cellref_dir, "cellref.xlsx")
        if os.path.isfile(cellref_path):
            print(f"Loading cellref.xlsx from {cellref_dir} ...")
            cellref_full = pd.read_excel(cellref_path)
            if "eNB" in cellref_full.columns:
                print(f"  cellref: {len(cellref_full)} rows, {len(cellref_full.columns)} cols")
                site_cols = [c for c in ["eNB", "CLUSTER", "BAIRRO"] if c in cellref_full.columns]
                cellref_site = cellref_full[site_cols].copy()
                cellref_site.rename(columns={"CLUSTER": "MUNICÍPIO"}, inplace=True)
                cellref_site.drop_duplicates(subset=["eNB"], keep="first", inplace=True)
                print(f"  cellref_site: {len(cellref_site)} unique eNBs")
            else:
                print("  cellref.xlsx has no eNB column; skipping cellref merge")
                cellref_full = None
                cellref_site = None
        else:
            print(f"cellref.xlsx not found in {cellref_dir}; continuing without cellref (EUtranCellRelation will still be processed)")
    else:
        print(f"Cellref directory not found: {cellref_dir}; continuing without cellref")

    # =====================================================================
    # Helper: derive standard columns from raw parser output
    # =====================================================================
    def _derive_enb(df):
        """eNB is always ManagedElement (matches notebook convention)."""
        if "ManagedElement" in df.columns:
            df["eNB"] = df["ManagedElement"]
        return df

    def _derive_uf(df):
        """Derive UF from last 2 chars of eNB."""
        if "eNB" in df.columns:
            df["UF"] = df["eNB"].astype(str).str[-2:]
        return df

    # =====================================================================
    # 1. TermPointToMme
    # =====================================================================
    tpt_path = os.path.join(input_dir, "TermPointToMme.txt")
    if os.path.isfile(tpt_path):
        try:
            df1 = pd.read_csv(tpt_path, sep="\t", low_memory=False, encoding="latin-1")
            df1 = _derive_enb(df1)
            if "eNB" not in df1.columns:
                print("  TermpointToMme: skip (missing eNB / ManagedElement)")
            else:
                _derive_uf(df1)

                # Derive Termpoint from termPointToMmeId / TermPointToMmeId
                if "Termpoint" not in df1.columns:
                    for candidate in ["termPointToMmeId", "TermPointToMmeId"]:
                        if candidate in df1.columns:
                            df1["Termpoint"] = df1[candidate]
                            break

                need_cols = ["UF", "eNB", "Termpoint", "administrativeState", "ipAddress1", "ipAddress2"]
                df1 = df1[[c for c in need_cols if c in df1.columns]]

                df2 = pd.merge(df1, cellref_site, on="eNB", how="left") if cellref_site is not None else df1
                out_cols = [c for c in ["UF", "MUNICÍPIO", "BAIRRO", "eNB", "Termpoint",
                                        "administrativeState", "ipAddress1", "ipAddress2"] if c in df2.columns]
                df3 = df2[out_cols] if out_cols else df2
                subset_dup = [c for c in ["eNB", "Termpoint", "administrativeState"] if c in df3.columns]
                if subset_dup:
                    df3 = df3.drop_duplicates(subset=subset_dup, keep="first")
                out_path = os.path.join(output_dir, "TermpointToMme.txt")
                df3.to_csv(out_path, sep="\t", index=False, encoding="latin-1", errors="replace")
                print(f"  TermpointToMme: {len(df3)} rows -> {out_path}")
        except Exception as e:
            print(f"  TermpointToMme: ERROR - {e}")
    else:
        print("  TermpointToMme: skip (no TermPointToMme.txt in input)")

    # =====================================================================
    # 2. ENodeBFunction (needed later for EUtranCellFDD enrichment)
    # =====================================================================
    df_enb = None
    enb_path = os.path.join(input_dir, "ENodeBFunction.txt")
    if os.path.isfile(enb_path):
        try:
            df_enb = pd.read_csv(enb_path, sep="\t", low_memory=False, encoding="latin-1")
            df_enb = df_enb.dropna(thresh=1, axis="columns")
            df_enb = _derive_enb(df_enb)
            if "eNB" not in df_enb.columns:
                print("  ENodeBFunction: skip (no eNB or ManagedElement)")
                df_enb = None
            else:
                _derive_uf(df_enb)

                # Merge with cellref site-level (skip if cellref not available)
                df_enb_out = pd.merge(df_enb, cellref_site, on="eNB", how="left") if cellref_site is not None else df_enb.copy()
                cols_drop = [c for c in ["alignTtiBundWUlTrigSinr", "allowMocnCellLevelCommonTac"] if c in df_enb_out.columns]
                if cols_drop:
                    df_enb_out = df_enb_out.dropna(subset=cols_drop, how="all")

                # Reorder: MO, UF, eNB first
                priority = ["MO", "UF", "MUNICÍPIO", "BAIRRO", "eNB"]
                ordered = [c for c in priority if c in df_enb_out.columns]
                ordered += [c for c in df_enb_out.columns if c not in ordered]
                df_enb_out = df_enb_out[ordered]

                df_enb_out.drop_duplicates(subset=["eNB"], keep="first", inplace=True)

                out_path = os.path.join(output_dir, "ENodeBFunction.txt")
                df_enb_out.to_csv(out_path, sep="\t", index=False, encoding="latin-1", errors="replace")
                print(f"  ENodeBFunction: {len(df_enb_out)} rows -> {out_path}")
        except Exception as e:
            print(f"  ENodeBFunction: ERROR - {e}")
            df_enb = None
    else:
        print("  ENodeBFunction: skip (no ENodeBFunction.txt in input)")

    # =====================================================================
    # 3. EUtranCellFDD (sector-level join + ENodeBFunction enrichment)
    # =====================================================================
    fdd_path = os.path.join(input_dir, "EUtranCellFDD.txt")
    if os.path.isfile(fdd_path):
        try:
            df1 = pd.read_csv(fdd_path, sep="\t", low_memory=False, encoding="latin-1")
            df1 = _derive_enb(df1)

            if "eNB" not in df1.columns:
                print("  EUtranCellFDD: skip (no eNB / ManagedElement)")
            else:
                # Derive CELL from eUtranCellFDDId / EUtranCellFDDId (combine_first, like notebook)
                if "CELL" not in df1.columns:
                    if "eUtranCellFDDId" in df1.columns and "EUtranCellFDDId" in df1.columns:
                        df1["CELL"] = df1["eUtranCellFDDId"].combine_first(df1["EUtranCellFDDId"])
                    elif "eUtranCellFDDId" in df1.columns:
                        df1["CELL"] = df1["eUtranCellFDDId"]
                    elif "EUtranCellFDDId" in df1.columns:
                        df1["CELL"] = df1["EUtranCellFDDId"]

                if "CELL" not in df1.columns:
                    print("  EUtranCellFDD: skip (cannot derive CELL column)")
                else:
                    _derive_uf(df1)

                    # PCI
                    if "physicalLayerCellIdGroup" in df1.columns and "physicalLayerSubCellId" in df1.columns:
                        df1["physicalLayerCellIdGroup"] = pd.to_numeric(df1["physicalLayerCellIdGroup"], errors="coerce")
                        df1["physicalLayerSubCellId"] = pd.to_numeric(df1["physicalLayerSubCellId"], errors="coerce")
                        df1["PCI"] = df1["physicalLayerCellIdGroup"] * 3 + df1["physicalLayerSubCellId"]

                    # Banda (1st char of CELL name)
                    df1["Banda"] = df1["CELL"].astype(str).str[0:1].replace(
                        ["T", "Q", "V", "Z", "U", "P", "Y", "C", "O", "L"],
                        ["2600", "2600", "1800", "700", "2100", "2600", "850", "1800", "2300", "2300"])

                    if "cellId" in df1.columns:
                        df1["cellId"] = pd.to_numeric(df1["cellId"], errors="coerce")
                        df1 = df1.dropna(subset=["cellId"])

                    # Select relevant columns before merge
                    keep_cols = ["UF", "eNB", "CELL", "cellId", "Banda", "earfcndl",
                                 "dlChannelBandwidth", "tac", "physicalLayerCellIdGroup",
                                 "physicalLayerSubCellId", "rachRootSequence",
                                 "catm1SupportEnabled", "PCI", "crsGain",
                                 "primaryPlmnReserved", "administrativeState",
                                 "operationalState", "qRxLevMin", "qQualMin",
                                 "cellRange", "primaryUpperLayerInd"]
                    df1 = df1[[c for c in keep_cols if c in df1.columns]]

                    # --- Sector-level cellref join (Site + Setor) ---
                    df2 = df1
                    if cellref_full is not None:
                        cellref = cellref_full.copy()
                        cellref.rename(columns={"CLUSTER": "MUNICIPIO", "Azimuth": "Azimute", "Height": "Altura"}, inplace=True)
                        if "CELL" in cellref.columns and "eNB" in cellref.columns:
                            cellref["Setor"] = cellref["CELL"].astype(str).str[-1].replace(
                                ["4", "5", "6", "7", "8", "9"], ["1", "2", "3", "1", "2", "3"])
                            cellref["Site"] = cellref["eNB"].astype(str).str[-2:] + cellref["eNB"].astype(str).str[1:4]
                            cellref = cellref.drop(columns=["eNB", "CELL"], errors="ignore")
                            cellref.drop_duplicates(subset=["Site", "Setor"], inplace=True)
                            df1["Site"] = df1["eNB"].astype(str).str[-2:] + df1["eNB"].astype(str).str[1:4]
                            df1["Setor"] = df1["CELL"].astype(str).str[-1].replace(
                                ["4", "5", "6", "7", "8", "9"], ["1", "2", "3", "1", "2", "3"])
                            df2 = pd.merge(df1, cellref, on=["Site", "Setor"], how="left")
                        else:
                            print("  EUtranCellFDD: cellref missing CELL/eNB, skipping geo merge")

                    # --- ENodeBFunction enrichment (CGI, eNBId) ---
                    if df_enb is not None:
                        enb_want = ["eNB", "eNBId", "eNodeBPlmnId_mcc", "eNodeBPlmnId_mnc", "eNodeBPlmnId_mncLength"]
                        enb_merge_cols = [c for c in enb_want if c in df_enb.columns]
                        if "eNB" in enb_merge_cols and len(enb_merge_cols) >= 2:
                            df_enb_sub = df_enb[enb_merge_cols].drop_duplicates(subset=["eNB"], keep="first")
                            df2 = pd.merge(df2, df_enb_sub, on="eNB", how="left", suffixes=("", "_enb"))
                            # Derive CGI
                            cgi_cols = ["eNodeBPlmnId_mcc", "eNodeBPlmnId_mnc", "eNBId", "cellId"]
                            if all(c in df2.columns for c in cgi_cols):
                                df2["CGI"] = (df2["eNodeBPlmnId_mcc"].fillna(0).astype(int).astype(str) +
                                              df2["eNodeBPlmnId_mnc"].fillna(0).astype(int).astype(str) + "-" +
                                              df2["eNBId"].fillna(0).astype(int).astype(str) + "-" +
                                              df2["cellId"].fillna(0).astype(int).astype(str))

                    # Resolve UF if merge created UF_x/UF_y (cellref also has UF)
                    if "UF" not in df2.columns:
                        if "UF_x" in df2.columns:
                            df2["UF"] = df2["UF_x"]
                            df2.drop(columns=["UF_x"], inplace=True, errors="ignore")
                        elif "UF_y" in df2.columns:
                            df2["UF"] = df2["UF_y"]
                            df2.drop(columns=["UF_y"], inplace=True, errors="ignore")
                    if "UF_x" in df2.columns:
                        df2.drop(columns=["UF_x"], inplace=True, errors="ignore")
                    if "UF_y" in df2.columns:
                        df2.drop(columns=["UF_y"], inplace=True, errors="ignore")
                    if "UF" not in df2.columns and "eNB" in df2.columns:
                        df2["UF"] = df2["eNB"].astype(str).str[-2:]

                    # Final column selection
                    out_cols = [c for c in [
                        "UF", "CN", "MUNICIPIO", "BAIRRO", "ENDERECO", "Site_Name",
                        "eNB", "eNBId", "CELL", "cellId", "Banda", "earfcndl",
                        "dlChannelBandwidth", "tac", "physicalLayerCellIdGroup",
                        "physicalLayerSubCellId", "rachRootSequence",
                        "catm1SupportEnabled", "PCI", "CGI", "crsGain", "cellRange",
                        "primaryPlmnReserved", "primaryUpperLayerInd",
                        "Latitude", "Longitude", "Azimute", "Altura",
                        "administrativeState", "operationalState", "SiteType"
                    ] if c in df2.columns]
                    df3 = df2[out_cols].copy() if out_cols else df2.copy()

                    for col in ["tac", "cellId"]:
                        if col in df3.columns:
                            df3[col] = pd.to_numeric(df3[col], errors="coerce").astype("Int64")

                    if "UF" in df3.columns:
                        df3["SITE"] = df3["eNB"].str[1:4] + "_" + df3["UF"]

                    df3.drop_duplicates(subset=["eNB", "CELL"], keep="first", inplace=True)

                    out_path = os.path.join(output_dir, "EUtranCellFDD.txt")
                    df3.to_csv(out_path, sep="\t", index=False, encoding="latin-1", errors="replace")
                    print(f"  EUtranCellFDD: {len(df3)} rows -> {out_path}")
        except Exception as e:
            print(f"  EUtranCellFDD: ERROR - {e}")
    else:
        print("  EUtranCellFDD: skip (no EUtranCellFDD.txt in input)")

    # =====================================================================
    # 4. EUtranCellRelation (UF + CELL for MoB)
    # =====================================================================
    ecr_path = os.path.join(input_dir, "EUtranCellRelation.txt")
    if os.path.isfile(ecr_path):
        try:
            df1 = pd.read_csv(ecr_path, sep="\t", low_memory=False, encoding="latin-1")
            df1 = _derive_enb(df1)

            if "eNB" not in df1.columns:
                print("  EUtranCellRelation: skip (no eNB / ManagedElement)")
            else:
                # Derive CELL from EUtranCell (source cell of the relation)
                if "CELL" not in df1.columns:
                    for candidate in ["EUtranCell", "eUtranCell"]:
                        if candidate in df1.columns:
                            df1["CELL"] = df1[candidate]
                            break

                if "CELL" not in df1.columns:
                    print("  EUtranCellRelation: skip (cannot derive CELL from EUtranCell)")
                else:
                    # Filter rows with valid CELL
                    df1 = df1[df1["CELL"].notna()]

                    # Normalize EUtranCellRelationId
                    if "EUtranCellRelationId" not in df1.columns and "eUtranCellRelationId" in df1.columns:
                        df1["EUtranCellRelationId"] = df1["eUtranCellRelationId"]
                    elif "EUtranCellRelationId" in df1.columns and "eUtranCellRelationId" in df1.columns:
                        df1["EUtranCellRelationId"] = df1["EUtranCellRelationId"].combine_first(df1["eUtranCellRelationId"])
                    df1.drop(columns=["eUtranCellRelationId"], inplace=True, errors="ignore")

                    # Freq_tgt from EUtranFreqRelation
                    if "EUtranFreqRelation" in df1.columns:
                        df1["Freq_tgt"] = df1["EUtranFreqRelation"].astype(str).str.replace("LTE_", "")

                    _derive_uf(df1)

                    # Reorder: UF, CELL first (required by MoB)
                    priority_cols = ["MO", "UF", "eNB", "CELL", "EUtranCellRelationId", "Freq_tgt"]
                    existing_priority = [c for c in priority_cols if c in df1.columns]
                    other_cols = [c for c in df1.columns if c not in existing_priority]
                    df2 = df1[existing_priority + other_cols].copy()
                    df2 = df2.dropna(thresh=1, axis="columns")

                    df2.drop_duplicates(inplace=True)

                    out_path = os.path.join(output_dir, "EUtranCellRelation.txt")
                    df2.to_csv(out_path, sep="\t", index=False, encoding="latin-1", errors="replace")
                    print(f"  EUtranCellRelation: {len(df2)} rows -> {out_path}")
        except Exception as e:
            print(f"  EUtranCellRelation: ERROR - {e}")
    else:
        print("  EUtranCellRelation: skip (no EUtranCellRelation.txt in input)")

    print("Step 4 (Camilo) completed.")


if __name__ == "__main__":
    main()
