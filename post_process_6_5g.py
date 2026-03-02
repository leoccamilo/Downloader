#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Post-processing step 6 (5G): full enrichment of NR MOs.

Reads raw TXT files from Parquet->TXT output and produces enriched 5G files
plus a consolidated MOs_5G.xlsx Excel workbook.

Processed MOs (when present in the dump):
  NRCellCU, NRCellDU, GNBCUCPFunction, GNBDUFunction,
  TermPointToENodeB, TermPointToGNB, TermPointToGNodeB,
  TermPointToAmf, TermPointToGNBDU, TermPointToGNBCUCP,
  NRFreqRelation, NRSectorCarrier, CommonBeamforming,
  AnrFunction, AnrFunctionNR, CUUP5qi,
  ExternalGUtranCell, ExternalNRCellCU,
  McfbCellProfileUeCfg, UeMCEUtranFreqRelProfileUeCfg

Usage:
  python post_process_6_5g.py <input_txt_dir> [output_dir]
"""

import os
import sys


REGIONAL_MAP = {
    "AM": "N", "AP": "N", "MA": "N", "PA": "N", "RR": "N",
    "BA": "BASE", "SE": "BASE",
}


def _ensure_enb(df):
    if "ManagedElement" in df.columns:
        df["eNB"] = df["ManagedElement"]
    return df


def _add_uf(df):
    if "eNB" in df.columns:
        df["UF"] = df["eNB"].astype(str).str[-2:]
    return df


def _add_regional(df):
    if "UF" in df.columns:
        df["Regional"] = df["UF"].replace(REGIONAL_MAP)
    return df


def _safe_cols(df, cols):
    """Select only columns that exist in df."""
    return [c for c in cols if c in df.columns]


def _read_txt(path):
    import pandas as pd
    return pd.read_csv(path, sep="\t", low_memory=False, encoding="latin-1")


def _write_txt(df, path, index=False):
    df.to_csv(path, sep="\t", index=index, encoding="latin-1", errors="replace")


def main():
    if len(sys.argv) < 2:
        print("Usage: python post_process_6_5g.py <input_txt_dir> [output_dir]")
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

    def inp(name):
        return os.path.join(input_dir, name)

    def out(name):
        return os.path.join(output_dir, name)

    excel_sheets = {}

    # ==================================================================
    # 1. NRCellCU (basic)
    # ==================================================================
    nrcellcu_df = None
    if os.path.isfile(inp("NRCellCU.txt")):
        try:
            df = _read_txt(inp("NRCellCU.txt"))
            df = _ensure_enb(df)
            df = _add_uf(df)
            df = df.dropna(thresh=1, axis="columns")
            subset = [c for c in ["eNB", "nRCellCUId"] if c in df.columns]
            if subset:
                df.drop_duplicates(subset=subset, inplace=True)
            _write_txt(df, out("5G_NRCellCU.txt"))
            nrcellcu_df = df.copy()
            print(f"  5G_NRCellCU: {len(df)} rows -> {out('5G_NRCellCU.txt')}")
        except Exception as e:
            print(f"  5G_NRCellCU: ERROR - {e}")
    else:
        print("  NRCellCU.txt not found; skip.")

    # ==================================================================
    # 2. NRCellDU
    # ==================================================================
    if os.path.isfile(inp("NRCellDU.txt")):
        try:
            df = _read_txt(inp("NRCellDU.txt"))
            df = _ensure_enb(df)
            df = _add_uf(df)
            df = df.dropna(thresh=1, axis="columns")
            subset = [c for c in ["eNB", "nRCellDUId"] if c in df.columns]
            if subset:
                df.drop_duplicates(subset=subset, inplace=True)
            _write_txt(df, out("5G_NRCellDU.txt"))
            excel_sheets["NRCellDU"] = df
            print(f"  5G_NRCellDU: {len(df)} rows -> {out('5G_NRCellDU.txt')}")
        except Exception as e:
            print(f"  5G_NRCellDU: ERROR - {e}")
    else:
        print("  NRCellDU.txt not found; skip.")

    # ==================================================================
    # 3. GNBCUCPFunction
    # ==================================================================
    gnbcucp_df = None
    if os.path.isfile(inp("GNBCUCPFunction.txt")):
        try:
            df = _read_txt(inp("GNBCUCPFunction.txt"))
            df = _ensure_enb(df)
            df = _add_uf(df)
            keep = [
                "MO", "UF", "eNB", "endpointResourceRef",
                "gNBCUCPFunctionId", "gNBId", "pLMNId_mcc", "pLMNId_mnc",
                "gNBIdLength", "maxCommonProcTime", "maxNgRetryTime",
                "nasInactivityTime", "ngcDedProcTime", "ribTmAutoMax",
                "rrcReestSupportType", "tDcOverall", "xnIpAddrViaNgActive",
            ]
            df = df[_safe_cols(df, keep)].copy()
            _write_txt(df, out("5G_GNBCUCPFunction.txt"))
            gnbcucp_df = df.copy()
            excel_sheets["GNBCUCPFunction"] = df
            print(f"  5G_GNBCUCPFunction: {len(df)} rows -> {out('5G_GNBCUCPFunction.txt')}")
        except Exception as e:
            print(f"  5G_GNBCUCPFunction: ERROR - {e}")
    else:
        print("  GNBCUCPFunction.txt not found; skip.")

    # ==================================================================
    # 3b. Enrich NRCellCU with GNBCUCPFunction (CGI + nRFrequency)
    # ==================================================================
    if nrcellcu_df is not None and gnbcucp_df is not None:
        try:
            gdf = gnbcucp_df[_safe_cols(gnbcucp_df, ["eNB", "pLMNId_mcc", "pLMNId_mnc", "gNBId"])].copy()
            gdf.rename(columns={"eNB": "NR_Site"}, inplace=True)
            nrc = pd.merge(nrcellcu_df, gdf, left_on="eNB", right_on="NR_Site", how="left")
            if "NR_Site" in nrc.columns:
                nrc.drop(columns=["NR_Site"], inplace=True)
            nrc.dropna(subset=["pLMNId_mcc"], inplace=True)
            cgi_cols = ["pLMNId_mcc", "pLMNId_mnc", "gNBId", "cellLocalId"]
            if all(c in nrc.columns for c in cgi_cols):
                for c in cgi_cols:
                    nrc[c] = pd.to_numeric(nrc[c], errors="coerce").fillna(0).astype(int).astype(str)
                nrc["CGI"] = nrc["pLMNId_mcc"] + nrc["pLMNId_mnc"] + "-" + nrc["gNBId"] + "-" + nrc["cellLocalId"]
            if "nRFrequencyRef" in nrc.columns:
                nrc["nRFrequency"] = nrc["nRFrequencyRef"].astype(str).str.extract(r"NRFrequency=(\w+)", expand=False)
            keep_cu = [
                "MO", "UF", "eNB", "nRCellCUId", "cellLocalId", "cellState",
                "pLMNId_mcc", "pLMNId_mnc", "gNBId", "CGI", "nRFrequency",
                "hiPrioDetEnabled", "intraFreqMCCellProfileRef",
                "mcfbCellProfileRef", "mcpcPCellEnabled", "mcpcPSCellEnabled",
                "nCI", "nRFrequencyRef", "nRTAC", "pmUeIntraFreqEnabled",
                "primaryPLMNId_mcc", "primaryPLMNId_mnc", "pSCellCapable",
                "qHyst", "reservedBy", "serviceState", "sNonIntraSearchP",
                "threshServingLowP", "transmitSib2", "transmitSib4",
                "transmitSib5", "ueMCCellProfileRef",
            ]
            nrc = nrc[_safe_cols(nrc, keep_cu)].copy()
            _write_txt(nrc, out("5G_NRCellCU.txt"))
            nrcellcu_df = nrc.copy()
            excel_sheets["NRCellCU"] = nrc
            print(f"  5G_NRCellCU (enriched): {len(nrc)} rows -> {out('5G_NRCellCU.txt')}")
        except Exception as e:
            print(f"  5G_NRCellCU enrichment: ERROR - {e}")
            excel_sheets["NRCellCU"] = nrcellcu_df
    elif nrcellcu_df is not None:
        excel_sheets["NRCellCU"] = nrcellcu_df

    # ==================================================================
    # 4. GNBDUFunction
    # ==================================================================
    if os.path.isfile(inp("GNBDUFunction.txt")):
        try:
            df = _read_txt(inp("GNBDUFunction.txt"))
            df = _ensure_enb(df)
            df = _add_uf(df)
            df = df.dropna(thresh=10, axis="columns")
            df.dropna(subset=["gNBId"] if "gNBId" in df.columns else [], inplace=True)
            keep = [
                "MO", "UF", "eNB", "caVlanPortRef", "gNBId",
                "altDepHServAdapUPProfEnabled", "autoLockDelay",
                "capacityAllocationPolicy", "dlBbCapacityMaxLimit",
                "dlBbCapacityNet", "dUpLMNId_mcc", "dUpLMNId_mnc",
                "dynTACConfigEnabled", "endpointResourceRef",
                "gNBDUFunctionId", "gNBDUId", "gNBIdLength",
                "multiTddPatternSmEnabled", "pimCancAutoConfigEnabled",
                "pwsEtwsPrimaryInd", "servAdapUPProfDepHEnabled",
                "ulBbCapacityMaxLimit", "ulBbCapacityNet",
            ]
            df = df[_safe_cols(df, keep)].copy()
            _write_txt(df, out("5G_GNBDUFunction.txt"))
            excel_sheets["GNBDUFunction"] = df
            print(f"  5G_GNBDUFunction: {len(df)} rows -> {out('5G_GNBDUFunction.txt')}")
        except Exception as e:
            print(f"  5G_GNBDUFunction: ERROR - {e}")
    else:
        print("  GNBDUFunction.txt not found; skip.")

    # ==================================================================
    # 5. TermPointToENodeB (complex: aux parsing + ENodeBFunction merge)
    # ==================================================================
    if os.path.isfile(inp("TermPointToENodeB.txt")):
        try:
            df = _read_txt(inp("TermPointToENodeB.txt"))
            df = _ensure_enb(df)
            df = _add_uf(df)
            df = df.dropna(thresh=1, axis="columns")

            if "ExternalENodeBFunction" in df.columns and "termPointToENodeBId" in df.columns:
                df["termPointToENodeBId_Aux"] = df["ExternalENodeBFunction"].copy()
                mask_auto_auto = (df["termPointToENodeBId"] == "auto1") & (df["termPointToENodeBId_Aux"].astype(str).str[:4] == "auto")
                mask_auto_other = (df["termPointToENodeBId"] == "auto1") & (df["termPointToENodeBId_Aux"].astype(str).str[:4] != "auto")
                mask_normal = df["termPointToENodeBId"].astype(str).str[:4] != "auto"
                df.loc[mask_auto_auto, "termPointToENodeBId_Aux"] = (
                    df.loc[mask_auto_auto, "termPointToENodeBId_Aux"]
                    .astype(str).str.replace("auto", "", regex=False)
                    .apply(lambda x: x[:3] + x[4:6] + "-" + x[9:] if len(x) > 9 else x)
                )
                df.loc[mask_auto_other, "termPointToENodeBId_Aux"] = (
                    df.loc[mask_auto_other, "termPointToENodeBId_Aux"]
                    .astype(str).str.replace("_2_", "-", regex=False).str.replace("_", "-", regex=False)
                )
                df.loc[mask_normal, "termPointToENodeBId_Aux"] = df.loc[mask_normal, "termPointToENodeBId"]

            keep = _safe_cols(df, [
                "MO", "UF", "eNB", "administrativeState",
                "availabilityStatus", "operationalState",
                "termPointToENodeBId", "termPointToENodeBId_Aux",
            ])
            for c in keep:
                if c not in df.columns:
                    df[c] = ""
            result = df[keep].copy()

            enb_path = inp("ENodeBFunction.txt")
            enb_enr = out("ENodeBFunction.txt")
            enb_file = enb_enr if os.path.isfile(enb_enr) else enb_path
            if os.path.isfile(enb_file) and "termPointToENodeBId_Aux" in result.columns:
                enb = pd.read_csv(enb_file, sep="\t", low_memory=False, encoding="latin-1")
                enb = _ensure_enb(enb)
                enb_cols = _safe_cols(enb, ["eNB", "eNBId", "eNodeBPlmnId_mcc", "eNodeBPlmnId_mnc"])
                if "eNB" in enb_cols and len(enb_cols) >= 2:
                    enb = enb[enb_cols].drop_duplicates(subset=["eNB"], keep="first")
                    for c in ["eNodeBPlmnId_mcc", "eNodeBPlmnId_mnc", "eNBId"]:
                        if c in enb.columns:
                            enb[c] = pd.to_numeric(enb[c], errors="coerce").fillna(0).astype(int).astype(str)
                    enb["Aux"] = enb.get("eNodeBPlmnId_mcc", "") + enb.get("eNodeBPlmnId_mnc", "") + "-" + enb.get("eNBId", "")
                    enb.rename(columns={"eNB": "Ancora"}, inplace=True)
                    enb.drop(columns=["eNBId", "eNodeBPlmnId_mcc", "eNodeBPlmnId_mnc"], errors="ignore", inplace=True)
                    result = pd.merge(result, enb, left_on="termPointToENodeBId_Aux", right_on="Aux", how="left")
                    result.drop(columns=["Aux"], errors="ignore", inplace=True)

            subset_dup = _safe_cols(result, ["UF", "eNB", "Ancora"])
            if subset_dup:
                result.drop_duplicates(subset=subset_dup, inplace=True)
            _write_txt(result, out("5G_TermPointToENodeB.txt"))
            excel_sheets["TermPointToENodeB"] = result
            print(f"  5G_TermPointToENodeB: {len(result)} rows -> {out('5G_TermPointToENodeB.txt')}")
        except Exception as e:
            print(f"  5G_TermPointToENodeB: ERROR - {e}")
    else:
        print("  TermPointToENodeB.txt not found; skip.")

    # ==================================================================
    # 6. TermPointToGNB (merge with NRCellCU for Ancora via gNBId)
    # ==================================================================
    if os.path.isfile(inp("TermPointToGNB.txt")):
        try:
            df = _read_txt(inp("TermPointToGNB.txt"))
            df = _ensure_enb(df)
            df = _add_uf(df)
            df = df.dropna(thresh=1, axis="columns")

            if "ExternalGNodeBFunction" in df.columns:
                df["termPointToGNB"] = df["ExternalGNodeBFunction"]

                def _process_tpgnb(value):
                    v = str(value)
                    if "_" in v:
                        return v.split("_")[0]
                    elif "-" in v:
                        return v.split("-")[1].replace("000000", "")
                    return v

                df["termPointToGNB_gNBId"] = df["termPointToGNB"].apply(_process_tpgnb)
                df["termPointToGNB_gNBId"] = pd.to_numeric(df["termPointToGNB_gNBId"], errors="coerce").astype("Int64")

            if nrcellcu_df is not None and "gNBId" in nrcellcu_df.columns and "termPointToGNB_gNBId" in df.columns:
                ref = nrcellcu_df[["eNB", "gNBId"]].copy()
                ref.rename(columns={"eNB": "Ancora"}, inplace=True)
                ref.drop_duplicates(inplace=True)
                ref["gNBId"] = pd.to_numeric(ref["gNBId"], errors="coerce").astype("Int64")
                df = pd.merge(df, ref, left_on="termPointToGNB_gNBId", right_on="gNBId", how="left", suffixes=("", "_ref"))
                df.drop(columns=["gNBId_ref"], errors="ignore", inplace=True)

            keep = [
                "MO", "UF", "eNB", "Ancora", "administrativeState",
                "availabilityStatus", "createdBy", "ipAddress",
                "ipsecEpAddress", "ipv6Address", "operationalState",
                "termPointToGNBId", "termPointToGNB_gNBId",
                "upIpAddress", "usedIpAddress",
            ]
            for c in keep:
                if c not in df.columns:
                    df[c] = ""
            df = df[_safe_cols(df, keep)].copy()
            subset_dup = _safe_cols(df, ["UF", "eNB", "termPointToGNB_gNBId"])
            if subset_dup:
                df.drop_duplicates(subset=subset_dup, inplace=True)
            _write_txt(df, out("5G_TermPointToGNB.txt"))
            excel_sheets["TermPointToGNB"] = df
            print(f"  5G_TermPointToGNB: {len(df)} rows -> {out('5G_TermPointToGNB.txt')}")
        except Exception as e:
            print(f"  5G_TermPointToGNB: ERROR - {e}")
    else:
        print("  TermPointToGNB.txt not found; skip.")

    # ==================================================================
    # 7. TermPointToGNodeB (anchor resolution via NRCellCU CGI)
    # ==================================================================
    if os.path.isfile(inp("TermPointToGNodeB.txt")):
        try:
            df = _read_txt(inp("TermPointToGNodeB.txt"))
            df = _ensure_enb(df)
            df = _add_uf(df)

            def _extract_tpgnodeb(row):
                try:
                    tid = str(row.get("termPointToGNodeBId", ""))
                    ext = str(row.get("ExternalGNBCUCPFunction", ""))
                    if tid.startswith("auto"):
                        return ext.replace("auto", "").replace("_2_", "-").replace("_", "")
                    return ext
                except Exception:
                    return None

            if "ExternalGNBCUCPFunction" in df.columns:
                df["termPointToGNodeB"] = df.apply(_extract_tpgnodeb, axis=1)
                df["termPointToGNodeB"] = df["termPointToGNodeB"].astype(str).replace({"auto": "", "_2_": "-", "_": ""}, regex=True)

            if nrcellcu_df is not None and "termPointToGNodeB" in df.columns:
                needed = _safe_cols(nrcellcu_df, ["UF", "eNB", "pLMNId_mcc", "pLMNId_mnc", "gNBId"])
                if len(needed) >= 3:
                    ref = nrcellcu_df[needed].copy()
                    for c in ["pLMNId_mcc", "pLMNId_mnc", "gNBId"]:
                        if c in ref.columns:
                            ref[c] = pd.to_numeric(ref[c], errors="coerce").fillna(0).astype(int).astype(str)
                    ref["Ancora"] = ref.get("pLMNId_mcc", "") + ref.get("pLMNId_mnc", "") + "-" + ref.get("gNBId", "")
                    ref.drop(columns=["pLMNId_mcc", "pLMNId_mnc", "gNBId"], errors="ignore", inplace=True)
                    ref.drop_duplicates(inplace=True)
                    df = pd.merge(df, ref, left_on="termPointToGNodeB", right_on="Ancora", how="left", suffixes=("_src", "_tgt"))

            df = _add_regional(df)
            src_uf = "UF_src" if "UF_src" in df.columns else "UF"
            src_enb = "eNB_src" if "eNB_src" in df.columns else "eNB"
            tgt_enb = "eNB_tgt" if "eNB_tgt" in df.columns else None
            keep = _safe_cols(df, [
                "Regional", "MO", src_uf, src_enb, "termPointToGNodeB",
            ])
            if tgt_enb:
                keep.append(tgt_enb)
            keep += _safe_cols(df, [
                "administrativeState", "availabilityStatus",
                "ipv4Address", "ipv6Address", "operationalState",
                "termPointToGNodeBId", "usedIpAddress",
                "usedPLMNId_mcc", "usedPLMNId_mnc",
            ])
            df = df[[c for c in keep if c in df.columns]].copy()
            renames = {}
            if src_uf != "UF":
                renames[src_uf] = "UF"
            if src_enb != "eNB":
                renames[src_enb] = "gNB"
            if tgt_enb:
                renames[tgt_enb] = "Ancora"
            if "UF_tgt" in df.columns:
                df.drop(columns=["UF_tgt"], errors="ignore", inplace=True)
            if "Ancora" in df.columns and tgt_enb and tgt_enb != "Ancora":
                df.drop(columns=["Ancora"], errors="ignore", inplace=True)
            if renames:
                df.rename(columns=renames, inplace=True)
            subset_dup = _safe_cols(df, ["UF", "gNB", "Ancora"])
            if subset_dup:
                df.drop_duplicates(subset=subset_dup, inplace=True)
            _write_txt(df, out("5G_TermPointToGNodeB.txt"))
            print(f"  5G_TermPointToGNodeB: {len(df)} rows -> {out('5G_TermPointToGNodeB.txt')}")
        except Exception as e:
            print(f"  5G_TermPointToGNodeB: ERROR - {e}")
    else:
        print("  TermPointToGNodeB.txt not found; skip.")

    # ==================================================================
    # 8. TermPointToAmf
    # ==================================================================
    if os.path.isfile(inp("TermPointToAmf.txt")):
        try:
            df = _read_txt(inp("TermPointToAmf.txt"))
            df = _ensure_enb(df)
            df = _add_uf(df)
            df = df.dropna(thresh=1, axis="columns")
            df = _add_regional(df)
            keep = [
                "Regional", "MO", "UF", "eNB", "administrativeState",
                "amfName", "defaultAmf", "ipv4Address1", "ipv4Address2",
                "ipv6Address1", "ipv6Address2", "operationalState",
                "pLMNIdList_mcc", "pLMNIdList_mnc", "pwsRestartHandling",
                "relativeCapacity", "servedGuamiList_amfPointer",
                "servedGuamiList_amfRegionId", "servedGuamiList_amfSetId",
                "servedGuamiList_mcc", "servedGuamiList_mnc",
                "sNSSAIList_sd", "sNSSAIList_sst", "termPointToAmfId",
                "usedIpAddress",
            ]
            df = df[_safe_cols(df, keep)].copy()
            subset_dup = _safe_cols(df, ["UF", "eNB", "termPointToAmfId"])
            if subset_dup:
                df.drop_duplicates(subset=subset_dup, inplace=True)
            _write_txt(df, out("5G_TermPointToAmf.txt"))
            excel_sheets["TermPointToAmf"] = df
            print(f"  5G_TermPointToAmf: {len(df)} rows -> {out('5G_TermPointToAmf.txt')}")
        except Exception as e:
            print(f"  5G_TermPointToAmf: ERROR - {e}")
    else:
        print("  TermPointToAmf.txt not found; skip.")

    # ==================================================================
    # 9. TermPointToGNBDU
    # ==================================================================
    if os.path.isfile(inp("TermPointToGNBDU.txt")):
        try:
            df = _read_txt(inp("TermPointToGNBDU.txt"))
            df = _ensure_enb(df)
            df = _add_uf(df)
            df = df.dropna(thresh=1, axis="columns")
            df = _add_regional(df)
            keep = [
                "Regional", "MO", "UF", "eNB", "gNBDUId",
                "operationalState", "termPointToGNBDUId", "usedIpAddress",
            ]
            df = df[_safe_cols(df, keep)].copy()
            subset_dup = _safe_cols(df, ["UF", "eNB", "termPointToGNBDUId"])
            if subset_dup:
                df.drop_duplicates(subset=subset_dup, inplace=True)
            _write_txt(df, out("5G_TermPointToGNBDU.txt"))
            excel_sheets["TermPointToGNBDU"] = df
            print(f"  5G_TermPointToGNBDU: {len(df)} rows -> {out('5G_TermPointToGNBDU.txt')}")
        except Exception as e:
            print(f"  5G_TermPointToGNBDU: ERROR - {e}")
    else:
        print("  TermPointToGNBDU.txt not found; skip.")

    # ==================================================================
    # 10. TermPointToGNBCUCP
    # ==================================================================
    if os.path.isfile(inp("TermPointToGNBCUCP.txt")):
        try:
            df = _read_txt(inp("TermPointToGNBCUCP.txt"))
            df = _ensure_enb(df)
            df = _add_uf(df)
            df = df.dropna(thresh=1, axis="columns")
            df = _add_regional(df)
            keep = [
                "Regional", "MO", "UF", "eNB", "administrativeState",
                "ipv4Address", "ipv6Address", "operationalState",
                "termPointToGNBCUCPId", "usedIpAddress",
            ]
            df = df[_safe_cols(df, keep)].copy()
            subset_dup = _safe_cols(df, ["UF", "eNB", "termPointToGNBCUCPId"])
            if subset_dup:
                df.drop_duplicates(subset=subset_dup, inplace=True)
            _write_txt(df, out("5G_TermPointToGNBCUCP.txt"))
            excel_sheets["TermPointToGNBCUCP"] = df
            print(f"  5G_TermPointToGNBCUCP: {len(df)} rows -> {out('5G_TermPointToGNBCUCP.txt')}")
        except Exception as e:
            print(f"  5G_TermPointToGNBCUCP: ERROR - {e}")
    else:
        print("  TermPointToGNBCUCP.txt not found; skip.")

    # ==================================================================
    # 11. NRFreqRelation
    # ==================================================================
    if os.path.isfile(inp("NRFreqRelation.txt")):
        try:
            df = _read_txt(inp("NRFreqRelation.txt"))
            df = _ensure_enb(df)
            df = _add_uf(df)
            if "NRCell" in df.columns:
                df.rename(columns={"NRCell": "NRCellCU"}, inplace=True)
            df = df.dropna(thresh=1, axis="columns")
            df = _add_regional(df)
            keep = [
                "Regional", "MO", "UF", "eNB", "NRCellCU",
                "nRFreqRelationId", "mcpcPCellNrFreqRelProfileRef",
                "mcpcPSCellNrFreqRelProfileRef", "nRFrequencyRef",
                "ueMCNrFreqRelProfileRef", "reservedBy", "anrMeasOn",
                "cellReselectionPriority", "plmnRestriction", "pMax",
                "qOffsetFreq", "qRxLevMin", "sIntraSearchP",
                "threshXHighP", "threshXLowP", "tReselectionNR",
            ]
            df = df[_safe_cols(df, keep)].copy()
            _write_txt(df, out("5G_NRFreqRelation.txt"))
            print(f"  5G_NRFreqRelation: {len(df)} rows -> {out('5G_NRFreqRelation.txt')}")
        except Exception as e:
            print(f"  5G_NRFreqRelation: ERROR - {e}")
    else:
        print("  NRFreqRelation.txt not found; skip.")

    # ==================================================================
    # 12. NRSectorCarrier
    # ==================================================================
    if os.path.isfile(inp("NRSectorCarrier.txt")):
        try:
            df = _read_txt(inp("NRSectorCarrier.txt"))
            df = _ensure_enb(df)
            df = _add_uf(df)
            if "nRSectorCarrierId" in df.columns:
                df["NRSectorCarrier"] = df["nRSectorCarrierId"]
            df = df.dropna(thresh=1, axis="columns")
            df = _add_regional(df)
            keep = [
                "Regional", "MO", "UF", "eNB", "nRSectorCarrierId",
                "NRSectorCarrier", "administrativeState", "arfcnDL",
                "arfcnUL", "availabilityStatus", "bbOnlyBackoffAllowed",
                "bSChannelBwDL", "bSChannelBwUL", "cbrsEnabled",
                "configuredMaxTxPower",
                "dlCalibrationData_dlCalibrationActiveMethod",
                "dlCalibrationData_dlCalibrationStatus",
                "dlCalibrationData_dlCalibrationSupportedMethods",
                "dlCalibrationEnabled", "frameStartOffset",
                "frequencyDL", "frequencyUL", "latitude", "longitude",
                "massiveMimoSleepEnabled", "maxAllowedEirpPsd",
                "maxRegPowerLimit", "maxTransmissionPower",
                "muEirpPmiDistBasedThreshold", "noOfRxAntennas",
                "noOfTxAntennas", "noOfUsedRxAntennas",
                "noOfUsedTxAntennas", "nRMicroSleepTxEnabled",
                "nullSteeringMode", "operationalState",
                "pimAvoidDlMutingPeriod", "pimAvoidLevel",
                "powerBackoffMode", "powerBackoffOffset",
                "radioTransmitPerfMode", "reservedBy",
                "scaledTransmissionPower", "sectorEquipmentFunctionRef",
                "txDirection", "txPowerChangeRate",
                "txPowerPersistentLock", "txPowerRatio",
                "ueAssistedPrecodingOptEnabled",
                "ueAssistedPrecodingOptStatus",
                "ueAssistedPrecodingOptTimeGap",
                "ulCalibrationData_ulCalibrationActiveMethod",
                "ulCalibrationData_ulCalibrationStatus",
                "ulCalibrationData_ulCalibrationSupportedMethods",
            ]
            df = df[_safe_cols(df, keep)].copy()
            _write_txt(df, out("5G_NRSectorCarrier.txt"))
            excel_sheets["NRSectorCarrier"] = df
            print(f"  5G_NRSectorCarrier: {len(df)} rows -> {out('5G_NRSectorCarrier.txt')}")
        except Exception as e:
            print(f"  5G_NRSectorCarrier: ERROR - {e}")
    else:
        print("  NRSectorCarrier.txt not found; skip.")

    # ==================================================================
    # 13-18. Simple MOs (basic processing pattern)
    # ==================================================================
    simple_mos = [
        ("CommonBeamforming.txt", "5G_CommonBeamforming"),
        ("AnrFunction.txt", "5G_AnrFunction"),
        ("AnrFunctionNR.txt", "5G_AnrFunctionNR"),
        ("CUUP5qi.txt", "5G_CUUP5qi"),
        ("ExternalGUtranCell.txt", "5G_ExternalGUtranCell"),
        ("ExternalNRCellCU.txt", "5G_ExternalNRCellCU"),
        ("McfbCellProfileUeCfg.txt", "5G_McfbCellProfileUeCfg"),
        ("UeMCEUtranFreqRelProfileUeCfg.txt", "UeMCEUtranFreqRelProfileUeCfg"),
    ]
    for src_file, out_name in simple_mos:
        src_path = inp(src_file)
        if os.path.isfile(src_path):
            try:
                df = _read_txt(src_path)
                df = _ensure_enb(df)
                df = _add_uf(df)
                df = df.dropna(thresh=1, axis="columns")
                out_path = out(out_name + ".txt")
                _write_txt(df, out_path)
                print(f"  {out_name}: {len(df)} rows -> {out_path}")
            except Exception as e:
                print(f"  {out_name}: ERROR - {e}")
        else:
            print(f"  {src_file} not found; skip.")

    # ==================================================================
    # 19. Consolidated Excel: MOs_5G.xlsx
    # ==================================================================
    if excel_sheets:
        try:
            xlsx_path = out("MOs_5G.xlsx")
            with pd.ExcelWriter(xlsx_path, engine="xlsxwriter") as writer:
                for sheet_name, sheet_df in excel_sheets.items():
                    sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)
            print(f"  MOs_5G.xlsx: {len(excel_sheets)} sheets -> {xlsx_path}")
        except Exception as e:
            print(f"  MOs_5G.xlsx: ERROR - {e}")
            try:
                xlsx_path = out("MOs_5G.xlsx")
                with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
                    for sheet_name, sheet_df in excel_sheets.items():
                        sheet_df.to_excel(writer, sheet_name=sheet_name, index=False)
                print(f"  MOs_5G.xlsx (openpyxl): {len(excel_sheets)} sheets -> {xlsx_path}")
            except Exception as e2:
                print(f"  MOs_5G.xlsx: FAILED with both engines - {e2}")

    print("Step 6 (5G) completed.")


if __name__ == "__main__":
    main()
