#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Post-processing step 5 (TDD): Combine enriched EUtranCellFDD + raw EUtranCellTDD
into EUtranCell_TDD_FDD.csv and EUtranCell_TDD_FDD.txt.

The output file is always produced when EUtranCellFDD exists, even if the region
has no TDD sites (EUtranCellTDD is absent from the dump). In that case, the file
contains FDD-only enriched data.

Reads:
  - EUtranCellFDD.txt   (enriched from step 4, with geo columns) — required
  - EUtranCellTDD.txt   (raw from Parquet->TXT) — optional (MO may not be in dump)
  - ENodeBFunction.txt  (raw from Parquet->TXT, for eNBId / mcc / mnc) — for TDD

Outputs:
  - EUtranCell_TDD_FDD.csv  (comma-separated, ISO-8859-1)
  - EUtranCell_TDD_FDD.txt  (tab-separated, utf-8)

Usage:
  python post_process_5_tdd.py <input_txt_dir> [output_dir]
  If output_dir is omitted, uses input_txt_dir.
"""

import os
import sys


def main():
    if len(sys.argv) < 2:
        print("Usage: python post_process_5_tdd.py <input_txt_dir> [output_dir]")
        sys.exit(1)

    input_dir = os.path.abspath(sys.argv[1].replace("/", os.sep))
    output_dir = os.path.abspath(
        (sys.argv[2] if len(sys.argv) > 2 else sys.argv[1]).replace("/", os.sep)
    )

    if not os.path.isdir(input_dir):
        print(f"Input directory not found: {input_dir}")
        sys.exit(1)
    os.makedirs(output_dir, exist_ok=True)

    try:
        import pandas as pd
    except ImportError:
        print("Requires pandas: pip install pandas")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 1. Load EUtranCellTDD.txt (optional — region may have no TDD sites)
    # ------------------------------------------------------------------
    df_tdd = None
    tdd_path = os.path.join(input_dir, "EUtranCellTDD.txt")
    if os.path.isfile(tdd_path):
        print(f"  Loading EUtranCellTDD.txt ...")
        df_tdd = pd.read_csv(tdd_path, sep="\t", low_memory=False, encoding="latin-1")
        print(f"  EUtranCellTDD: {len(df_tdd)} rows loaded")

        if "ManagedElement" in df_tdd.columns:
            df_tdd["eNB"] = df_tdd["ManagedElement"]

        cell_cols = [c for c in df_tdd.columns if "UtranCellTDDId" in c]
        if cell_cols:
            df_tdd["CELL"] = (
                df_tdd[cell_cols].bfill(axis=1).iloc[:, 0]
                if len(cell_cols) > 1
                else df_tdd[cell_cols[0]]
            )

        if "eNB" not in df_tdd.columns or "CELL" not in df_tdd.columns:
            print("  Cannot derive eNB or CELL from TDD; skipping TDD")
            df_tdd = None
        else:
            df_tdd["UF"] = df_tdd["eNB"].astype(str).str[-2:]

            if (
                "physicalLayerCellIdGroup" in df_tdd.columns
                and "physicalLayerSubCellId" in df_tdd.columns
            ):
                df_tdd["physicalLayerCellIdGroup"] = pd.to_numeric(
                    df_tdd["physicalLayerCellIdGroup"], errors="coerce"
                )
                df_tdd["physicalLayerSubCellId"] = pd.to_numeric(
                    df_tdd["physicalLayerSubCellId"], errors="coerce"
                )
                df_tdd["PCI"] = (
                    df_tdd["physicalLayerCellIdGroup"] * 3
                    + df_tdd["physicalLayerSubCellId"]
                )

            # 2. Merge TDD with ENodeBFunction for eNBId, mcc, mnc → CGI
            enb_path = os.path.join(input_dir, "ENodeBFunction.txt")
            if os.path.isfile(enb_path):
                print("  Merging TDD with ENodeBFunction ...")
                df_enb = pd.read_csv(enb_path, sep="\t", low_memory=False, encoding="latin-1")
                if "ManagedElement" in df_enb.columns:
                    df_enb["eNB"] = df_enb["ManagedElement"]
                if "eNB" in df_enb.columns:
                    if "UF" not in df_enb.columns:
                        df_enb["UF"] = df_enb["eNB"].astype(str).str[-2:]
                    enb_want = ["UF", "eNB", "eNBId", "eNodeBPlmnId_mcc", "eNodeBPlmnId_mnc"]
                    enb_cols = [c for c in enb_want if c in df_enb.columns]
                    df_enb_sub = df_enb[enb_cols].drop_duplicates(subset=["eNB"], keep="first")
                    df_tdd = pd.merge(df_tdd, df_enb_sub, on=["UF", "eNB"], how="inner")

                    for col in ["eNodeBPlmnId_mcc", "eNodeBPlmnId_mnc", "eNBId", "cellId"]:
                        if col in df_tdd.columns:
                            df_tdd[col] = (
                                pd.to_numeric(df_tdd[col], errors="coerce")
                                .fillna(0)
                                .astype(int)
                                .astype(str)
                            )

                    cgi_cols = ["eNodeBPlmnId_mcc", "eNodeBPlmnId_mnc", "eNBId", "cellId"]
                    if all(c in df_tdd.columns for c in cgi_cols):
                        df_tdd["CGI"] = (
                            df_tdd["eNodeBPlmnId_mcc"]
                            + df_tdd["eNodeBPlmnId_mnc"]
                            + "-"
                            + df_tdd["eNBId"]
                            + "-"
                            + df_tdd["cellId"]
                        )
            else:
                print("  ENodeBFunction.txt not found; CGI will not be derived for TDD")

            # 3. Select TDD columns, derive Site + Setor
            tdd_keep = [
                "UF", "eNB", "eNBId", "CELL", "cellId", "earfcn", "channelBandwidth",
                "tac", "PCI", "physicalLayerCellIdGroup", "physicalLayerSubCellId",
                "CGI", "crsGain", "cellRange", "primaryPlmnReserved",
                "primaryUpperLayerInd", "rachRootSequence",
                "administrativeState", "operationalState",
            ]
            df_tdd = df_tdd[[c for c in tdd_keep if c in df_tdd.columns]].copy()

            df_tdd["Site"] = df_tdd["eNB"].astype(str).str[1:4] + "_" + df_tdd["UF"]
            df_tdd["Setor"] = (
                df_tdd["CELL"]
                .astype(str)
                .str[-1]
                .replace(
                    ["4", "5", "6", "7", "8", "9"],
                    ["1", "2", "3", "1", "2", "3"],
                )
            )

            if "cellId" in df_tdd.columns:
                df_tdd.dropna(subset=["cellId"], inplace=True)

            for col in df_tdd.select_dtypes(include="float64").columns:
                df_tdd[col] = pd.to_numeric(df_tdd[col], errors="coerce").astype("Int64")

            print(f"  TDD after column selection: {len(df_tdd)} rows")
    else:
        print("  EUtranCellTDD.txt not found (region has no TDD sites); will produce FDD-only output")

    # ------------------------------------------------------------------
    # 4. Load enriched EUtranCellFDD.txt (from step 4)
    #    Check output_dir first (enriched dir), then fall back to input_dir
    # ------------------------------------------------------------------
    fdd_path = os.path.join(output_dir, "EUtranCellFDD.txt")
    if not os.path.isfile(fdd_path):
        fdd_path = os.path.join(input_dir, "EUtranCellFDD.txt")
    fdd_copy = None
    geo_from_fdd = None

    if os.path.isfile(fdd_path):
        print("  Loading EUtranCellFDD.txt (enriched from step 4) ...")
        df_fdd = pd.read_csv(fdd_path, sep="\t", low_memory=False, encoding="latin-1")
        print(f"  EUtranCellFDD: {len(df_fdd)} rows loaded")

        fdd_copy = df_fdd.copy()
        fdd_copy["Tipo"] = "FDD"

        # Build geo reference from FDD for TDD merge
        if "CELL" in df_fdd.columns and "eNB" in df_fdd.columns:
            df_fdd["Setor"] = (
                df_fdd["CELL"]
                .astype(str)
                .str[-1]
                .replace(
                    ["4", "5", "6", "7", "8", "9"],
                    ["1", "2", "3", "1", "2", "3"],
                )
            )
            df_fdd["Site"] = (
                df_fdd["eNB"].astype(str).str[1:4]
                + "_"
                + df_fdd["UF"].astype(str)
            )

            geo_cols = [
                "UF", "CN", "MUNICIPIO", "BAIRRO", "ENDERECO", "Site_Name",
                "Setor", "Latitude", "Longitude", "Azimute", "Altura", "SiteType",
                "Site",
            ]
            geo_from_fdd = df_fdd[
                [c for c in geo_cols if c in df_fdd.columns]
            ].copy()

            dedup_cols = [
                c
                for c in ["Site_Name", "Setor"]
                if c in geo_from_fdd.columns
            ]
            if not dedup_cols:
                dedup_cols = [
                    c for c in ["Site", "Setor"] if c in geo_from_fdd.columns
                ]
            if dedup_cols:
                geo_from_fdd.drop_duplicates(subset=dedup_cols, keep="first", inplace=True)

            print(f"  Geo reference from FDD: {len(geo_from_fdd)} unique site-sectors")
    else:
        print("  EUtranCellFDD.txt not found; will produce TDD-only output" if df_tdd is not None else "  EUtranCellFDD.txt not found; cannot produce output")

    if fdd_copy is None and df_tdd is None:
        print("  No FDD or TDD data; skip step 5")
        print("Step 5 (TDD) completed.")
        return

    # ------------------------------------------------------------------
    # 5. Merge TDD with FDD geo info (only if TDD exists)
    # ------------------------------------------------------------------
    if df_tdd is not None and geo_from_fdd is not None:
        merge_keys = [c for c in ["UF", "Site", "Setor"] if c in df_tdd.columns and c in geo_from_fdd.columns]
        if merge_keys:
            df_tdd = pd.merge(df_tdd, geo_from_fdd, on=merge_keys, how="left")
            print(f"  TDD after geo merge: {len(df_tdd)} rows")

        df_tdd["Tipo"] = "TDD"

        rename_map = {}
        if "earfcn" in df_tdd.columns:
            rename_map["earfcn"] = "earfcndl"
        if "channelBandwidth" in df_tdd.columns:
            rename_map["channelBandwidth"] = "dlChannelBandwidth"
        if rename_map:
            df_tdd.rename(columns=rename_map, inplace=True)

    # ------------------------------------------------------------------
    # 6. Concat FDD + TDD (or FDD-only / TDD-only)
    # ------------------------------------------------------------------
    if fdd_copy is not None and df_tdd is not None:
        tdd_fdd = pd.concat([fdd_copy, df_tdd], ignore_index=True)
        print(f"  Combined FDD+TDD: {len(tdd_fdd)} rows ({len(fdd_copy)} FDD + {len(df_tdd)} TDD)")
    elif fdd_copy is not None:
        tdd_fdd = fdd_copy.copy()
        print(f"  FDD-only: {len(tdd_fdd)} rows (no TDD in region)")
    else:
        tdd_fdd = df_tdd.copy()
        print(f"  TDD-only: {len(tdd_fdd)} rows")

    # ------------------------------------------------------------------
    # 7. Regional derivation
    # ------------------------------------------------------------------
    if "UF" in tdd_fdd.columns:
        tdd_fdd["Regional"] = tdd_fdd["UF"].replace(
            ["AM", "AP", "MA", "PA", "RR", "BA", "SE"],
            ["N", "N", "N", "N", "N", "BASE", "BASE"],
        )
        regional_col = tdd_fdd.pop("Regional")
        tdd_fdd.insert(0, "Regional", regional_col)

    # ------------------------------------------------------------------
    # 8. Sort and cleanup
    # ------------------------------------------------------------------
    if "eNB" in tdd_fdd.columns:
        tdd_fdd["_site_sort"] = tdd_fdd["eNB"].astype(str).str[1:4]
        sort_cols = [c for c in ["Regional", "UF", "_site_sort", "eNB", "CELL"] if c in tdd_fdd.columns]
        if sort_cols:
            tdd_fdd.sort_values(by=sort_cols, inplace=True)
        tdd_fdd.drop(columns=["_site_sort"], inplace=True, errors="ignore")

    tdd_fdd.drop(columns=["Site", "Setor"], inplace=True, errors="ignore")

    # Do NOT dropna(administrativeState) - FDD rows often lack it, would remove them
    # if "administrativeState" in tdd_fdd.columns:
    #     tdd_fdd.dropna(subset=["administrativeState"], inplace=True)

    # ------------------------------------------------------------------
    # 9. Fill blank geo data from other rows of the same eNB
    #    (a TDD cell may lack MUNICIPIO/Azimute while a co-located FDD has it)
    # ------------------------------------------------------------------
    geo_fill_cols = ["MUNICIPIO", "BAIRRO", "ENDERECO", "Latitude", "Longitude", "Altura"]
    available_fill = [c for c in geo_fill_cols if c in tdd_fdd.columns]
    if available_fill and "eNB" in tdd_fdd.columns:
        print("  Filling blank geo data from co-located cells ...")
        filled = 0
        for enb_name, grp in tdd_fdd.groupby("eNB"):
            for col in available_fill:
                mask = grp[col].isna()
                if mask.any():
                    donor = grp.loc[grp[col].notna(), col]
                    if not donor.empty:
                        tdd_fdd.loc[mask[mask].index, col] = donor.iloc[0]
                        filled += mask.sum()
        if "Azimute" in tdd_fdd.columns and "CELL" in tdd_fdd.columns:
            az_mask = tdd_fdd["Azimute"].isna()
            if az_mask.any():
                tdd_fdd["_sector_digit"] = tdd_fdd["CELL"].astype(str).str[-1]
                for enb_name, grp in tdd_fdd[az_mask | tdd_fdd["Azimute"].notna()].groupby("eNB"):
                    for digit, sub in grp.groupby("_sector_digit"):
                        donor = sub.loc[sub["Azimute"].notna(), "Azimute"]
                        if not donor.empty:
                            blank = sub["Azimute"].isna()
                            if blank.any():
                                tdd_fdd.loc[blank[blank].index, "Azimute"] = donor.iloc[0]
                                filled += blank.sum()
                tdd_fdd.drop(columns=["_sector_digit"], inplace=True, errors="ignore")
        print(f"  Filled {filled} blank geo values")

    # ------------------------------------------------------------------
    # 10. Save outputs
    # ------------------------------------------------------------------
    out_csv = os.path.join(output_dir, "EUtranCell_TDD_FDD.csv")
    out_txt = os.path.join(output_dir, "EUtranCell_TDD_FDD.txt")

    tdd_fdd.to_csv(out_csv, index=False, encoding="latin-1", errors="replace")
    tdd_fdd.to_csv(out_txt, sep="\t", index=False, encoding="latin-1", errors="replace")

    print(f"  EUtranCell_TDD_FDD: {len(tdd_fdd)} rows -> {out_csv}")
    print(f"  EUtranCell_TDD_FDD: {len(tdd_fdd)} rows -> {out_txt}")
    print("Step 5 (TDD) completed.")


if __name__ == "__main__":
    main()
