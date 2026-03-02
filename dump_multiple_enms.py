#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Dump multiple ENMs in parallel.
Used by the Downloader (web-tool): export JSON and run:
  python dump_multiple_enms.py <config.json>

Requires: pip install enmscripting
"""

import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Available MOs (aligned with script 3). Conversion only processes those present in the dump.
AVAILABLE_MOS = [
    {"id": "EUtranCellRelation", "name": "EUtranCellRelation.*", "description": "LTE Neighbor Relations"},
    {"id": "EUtranCellFDD", "name": "EUtranCellFDD.*", "description": "LTE FDD Cells"},
    {"id": "EUtranCellTDD", "name": "EUtranCellTDD.*", "description": "LTE TDD Cells"},
    {"id": "ENodeBFunction", "name": "ENodeBFunction.*", "description": "eNodeB Functions"},
    {"id": "ExternalEUtranCellFDD", "name": "ExternalEUtranCellFDD.*", "description": "External LTE FDD"},
    {"id": "ExternalEUtranCellTDD", "name": "ExternalEUtranCellTDD.*", "description": "External LTE TDD"},
    {"id": "UtranFreqRelation", "name": "UtranFreqRelation.*", "description": "Utran Freq Relation"},
    {"id": "RetSubUnit", "name": "RetSubUnit.*", "description": "Ret Sub Unit"},
    {"id": "EUtranFreqRelation", "name": "EUtranFreqRelation.*", "description": "LTE Freq Relation"},
    {"id": "TermPointToMme", "name": "TermPointToMme.*", "description": "Term Point To MME"},
    {"id": "ReportConfigSearch", "name": "ReportConfigSearch.*", "description": "Report Config Search"},
    {"id": "ReportConfigEUtraInterFreqLb", "name": "ReportConfigEUtraInterFreqLb.*", "description": "Report Config EUtra Inter Freq Lb"},
    {"id": "ReportConfigA5", "name": "ReportConfigA5.*", "description": "Report Config A5"},
    {"id": "ReportConfigA5UlTrig", "name": "ReportConfigA5UlTrig.*", "description": "Report Config A5 UL Trig"},
    {"id": "SectorCarrier", "name": "SectorCarrier.*", "description": "Sector Carrier"},
    {"id": "LoadBalancingFunction", "name": "LoadBalancingFunction.*", "description": "Load Balancing Function"},
    {"id": "QciProfilePredefined", "name": "QciProfilePredefined.*", "description": "QCI Profile Predefined"},
    {"id": "GigaBitEthernet", "name": "GigaBitEthernet.*", "description": "GigaBit Ethernet"},
    {"id": "EthernetPort", "name": "EthernetPort.*", "description": "Ethernet Port"},
    {"id": "FeatureState", "name": "FeatureState.*", "description": "Feature State"},
    {"id": "OptionalFeatureLicense", "name": "OptionalFeatureLicense.*", "description": "Optional Feature License"},
    {"id": "ReportConfigB2Utra", "name": "ReportConfigB2Utra.*", "description": "Report Config B2 Utra"},
    {"id": "DataRadioBearer", "name": "DataRadioBearer.*", "description": "Data Radio Bearer"},
    {"id": "SignalingRadioBearer", "name": "SignalingRadioBearer.*", "description": "Signaling Radio Bearer"},
    {"id": "EUtranFrequency", "name": "EUtranFrequency.*", "description": "LTE Frequency"},
    {"id": "CarrierAggregationFunction", "name": "CarrierAggregationFunction.*", "description": "Carrier Aggregation Function"},
    {"id": "AdmissionControl", "name": "AdmissionControl.*", "description": "Admission Control"},
    {"id": "AnrFunctionEUtran", "name": "AnrFunctionEUtran.*", "description": "ANR Function EUtran"},
    {"id": "AnrFunction", "name": "AnrFunction.*", "description": "ANR Function"},
    {"id": "AnrFunctionUtran", "name": "AnrFunctionUtran.*", "description": "ANR Function Utran"},
    {"id": "NbIotCell", "name": "NbIotCell.*", "description": "NB-IoT Cell"},
    {"id": "Router", "name": "Router.*", "description": "Router"},
    {"id": "InterfaceIPv4", "name": "InterfaceIPv4.*", "description": "Interface IPv4"},
    {"id": "InterfaceIPv6", "name": "InterfaceIPv6.*", "description": "Interface IPv6"},
    {"id": "Paging", "name": "Paging.*", "description": "Paging"},
    {"id": "ReportConfigA1Prim", "name": "ReportConfigA1Prim.*", "description": "Report Config A1 Prim"},
    {"id": "ReportConfigA1Sec", "name": "ReportConfigA1Sec.*", "description": "Report Config A1 Sec"},
    {"id": "ReportConfigB1Geran", "name": "ReportConfigB1Geran.*", "description": "Report Config B1 Geran"},
    {"id": "ReportConfigB1Utra", "name": "ReportConfigB1Utra.*", "description": "Report Config B1 Utra"},
    {"id": "ReportConfigB1GUtra", "name": "ReportConfigB1GUtra.*", "description": "Report Config B1 GUtra"},
    {"id": "ReportConfigB1NR", "name": "ReportConfigB1NR.*", "description": "Report Config B1 NR"},
    {"id": "ReportConfigEUtraBadCovPrim", "name": "ReportConfigEUtraBadCovPrim.*", "description": "Report Config EUtra Bad Cov Prim"},
    {"id": "ReportConfigEUtraBadCovSec", "name": "ReportConfigEUtraBadCovSec.*", "description": "Report Config EUtra Bad Cov Sec"},
    {"id": "ReportConfigEUtraBestCell", "name": "ReportConfigEUtraBestCell.*", "description": "Report Config EUtra Best Cell"},
    {"id": "ReportConfigA5UlTraffic", "name": "ReportConfigA5UlTraffic.*", "description": "Report Config A5 UL Traffic"},
    {"id": "ReportConfigSCellA1A2", "name": "ReportConfigSCellA1A2.*", "description": "Report Config SCell A1 A2"},
    {"id": "DrxProfile", "name": "DrxProfile.*", "description": "DRX Profile"},
    {"id": "Rrc", "name": "Rrc.*", "description": "RRC"},
    {"id": "UeMeasControl", "name": "UeMeasControl.*", "description": "UE Meas Control"},
    {"id": "Rcs", "name": "Rcs.*", "description": "RCS"},
    {"id": "ManagedElement", "name": "ManagedElement.*", "description": "Managed Element"},
    {"id": "AddressIPv4", "name": "AddressIPv4.*", "description": "Address IPv4"},
    {"id": "Slot", "name": "Slot.*", "description": "Slot"},
    {"id": "CellSleepFunction", "name": "CellSleepFunction.*", "description": "Cell Sleep Function"},
    {"id": "ExternalENodeBFunction", "name": "ExternalENodeBFunction.*", "description": "External eNodeB Function"},
    {"id": "GUtranCellRelation", "name": "GUtranCellRelation.*", "description": "GUtran Cell Relation"},
    {"id": "GUtranFreqRelation", "name": "GUtranFreqRelation.*", "description": "GUtran Freq Relation"},
    {"id": "ReportConfigA4", "name": "ReportConfigA4.*", "description": "Report Config A4"},
    {"id": "ReportConfigA5Anr", "name": "ReportConfigA5Anr.*", "description": "Report Config A5 Anr"},
    {"id": "ReportConfigA5DlComp", "name": "ReportConfigA5DlComp.*", "description": "Report Config A5 Dl Comp"},
    {"id": "ReportConfigB2Geran", "name": "ReportConfigB2Geran.*", "description": "Report Config B2 Geran"},
    {"id": "AnrFunctionGeran", "name": "AnrFunctionGeran.*", "description": "ANR Function Geran"},
    {"id": "SystemFunctions", "name": "SystemFunctions.*", "description": "System Functions"},
    {"id": "CapacityState", "name": "CapacityState.*", "description": "Capacity State"},
    {"id": "TermPointToENodeB", "name": "TermPointToENodeB.*", "description": "Term Point To ENodeB"},
    {"id": "TermPointToENB", "name": "TermPointToENB.*", "description": "Term Point To ENB"},
    {"id": "TermPointToGNBCUCP", "name": "TermPointToGNBCUCP.*", "description": "Term Point To GNBCUCP"},
    {"id": "TermPointToGNBDU", "name": "TermPointToGNBDU.*", "description": "Term Point To GNBDU"},
    {"id": "TermPointToAmf", "name": "TermPointToAmf.*", "description": "Term Point To Amf"},
    {"id": "TermPointToGNB", "name": "TermPointToGNB.*", "description": "Term Point To GNB"},
    {"id": "TermPointToGNodeB", "name": "TermPointToGNodeB.*", "description": "Term Point To GNodeB"},
    {"id": "GNBCUCPFunction", "name": "GNBCUCPFunction.*", "description": "GNB CUCP Function"},
    {"id": "GNBCUUPFunction", "name": "GNBCUUPFunction.*", "description": "GNB CUUP Function"},
    {"id": "GNBDUFunction", "name": "GNBDUFunction.*", "description": "GNB DU Function"},
    {"id": "NRCellCU", "name": "NRCellCU.*", "description": "NR Cell CU"},
    {"id": "NRCellDU", "name": "NRCellDU.*", "description": "NR Cell DU"},
    {"id": "SharingGroup", "name": "SharingGroup.*", "description": "Sharing Group"},
    {"id": "NRFreqRelation", "name": "NRFreqRelation.*", "description": "NR Freq Relation"},
    {"id": "NRCellRelation", "name": "NRCellRelation.*", "description": "NR Cell Relation"},
    {"id": "NRSectorCarrier", "name": "NRSectorCarrier.*", "description": "NR Sector Carrier"},
    {"id": "CommonBeamforming", "name": "CommonBeamforming.*", "description": "Common Beamforming"},
    {"id": "RadioEquipmentClockReference", "name": "RadioEquipmentClockReference.*", "description": "Radio Equipment Clock Reference"},
    {"id": "AnrFunctionNR", "name": "AnrFunctionNR.*", "description": "ANR Function NR"},
    {"id": "CUUP5qi", "name": "CUUP5qi.*", "description": "CUUP 5qi"},
    {"id": "ExternalGNodeBFunction", "name": "ExternalGNodeBFunction.*", "description": "External GNodeB Function"},
    {"id": "ExternalGUtranCell", "name": "ExternalGUtranCell.*", "description": "External GUtran Cell"},
    {"id": "McfbCellProfileUeCfg", "name": "McfbCellProfileUeCfg.*", "description": "Mcfb Cell Profile UE Cfg"},
    {"id": "ExternalNRCellCU", "name": "ExternalNRCellCU.*", "description": "External NR Cell CU"},
    {"id": "UeMCEUtranFreqRelProfileUeCfg", "name": "UeMCEUtranFreqRelProfileUeCfg.*", "description": "UE MC EUtran Freq Rel Profile UE Cfg"},
]

# Set of known IDs: avoids crash if JSON has an MO that no longer exists
AVAILABLE_MO_IDS = {mo["id"] for mo in AVAILABLE_MOS}


def disable_proxy_env() -> None:
    """Disable proxy env vars to allow direct ENM connectivity."""
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "GIT_HTTP_PROXY",
        "GIT_HTTPS_PROXY",
    ):
        os.environ.pop(key, None)


def clear_output_dir(output_dir: str, keep_mos_file: str = None) -> None:
    """Remove all files and subdirs in output_dir so old dumps do not accumulate.
    If keep_mos_file is set (e.g. 'mos_downloader.txt'), that file is not deleted."""
    if not os.path.isdir(output_dir):
        return
    keep = os.path.basename(keep_mos_file) if keep_mos_file else None
    for name in os.listdir(output_dir):
        if keep and name == keep:
            continue
        path = os.path.join(output_dir, name)
        try:
            if os.path.isfile(path):
                os.unlink(path)
            elif os.path.isdir(path):
                shutil.rmtree(path)
        except OSError as e:
            print(f"Warning: could not remove {path}: {e}")


def create_mos_file(output_dir: str, mos_file_name: str, selected_mos: list) -> str:
    """Create the MO list file in output_dir. Includes listed MOs and Additional MOs
    (not in the list): for those the XML parser produces parquet and the generic converter produces TXT."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, mos_file_name)
    selected = [mo_id for mo_id in (selected_mos or []) if mo_id]
    lines = []
    for mo in AVAILABLE_MOS:
        if mo["id"] in selected:
            lines.append(f"{mo['name']};")
    for mo_id in selected:
        if mo_id not in AVAILABLE_MO_IDS:
            lines.append(f"{mo_id}.*;")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def ensure_writable_output_dir(output_dir: str) -> str:
    """Ensure selected output dir is writable; raise clear error otherwise."""
    target = os.path.abspath(output_dir)
    probe_name = ".downloader_write_probe.tmp"
    try:
        os.makedirs(target, exist_ok=True)
        probe_path = os.path.join(target, probe_name)
        with open(probe_path, "w", encoding="utf-8") as f:
            f.write("ok")
        try:
            os.unlink(probe_path)
        except OSError:
            pass
        return target
    except Exception as e:
        raise PermissionError(
            f"Selected output folder is not writable: {target}. "
            f"Choose another output folder. Details: {e}"
        )


def adjust_command_job_name(command: str, job_name: str) -> str:
    """Replace -jn value in command with job_name."""
    pattern = re.compile(r"(-jn\s+)(\S+)", re.IGNORECASE)
    if pattern.search(command):
        return pattern.sub(rf"\g<1>{job_name}", command)
    return f"{command} -jn {job_name}"


def process_enm(enm: dict, command_template: str, output_dir: str, mos_file_path: str) -> str:
    """
    Process one ENM: adjust command with ENM job name, run export and download.
    enm: { "id", "name_short", "url", "username", "password" }
    """
    import enmscripting

    name_short = enm.get("name_short") or enm.get("id", "").replace("ENM", "")
    url = (enm.get("url") or "").strip()
    username = (enm.get("username") or "").strip()
    password = enm.get("password") or ""

    if not url or not username:
        return f"ERROR {name_short}: URL and username required"

    try:
        print(f"\n{'='*60}")
        print(f"[{name_short}] STARTING ENM PROCESSING")
        print(f"{'='*60}")
        print(f"[{name_short}] Target URL: {url}")
        print(f"[{name_short}] Username: {username}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        job_name = f"{name_short}_{timestamp}"
        command = adjust_command_job_name(command_template, job_name)
        print(f"[{name_short}] Step 1/5 - Prepared export command")
        print(f"[{name_short}] Job name: {job_name}")
        print(f"[{name_short}] MO list file: {mos_file_path}")
        print(f"[{name_short}] Output directory: {output_dir}")

        print(f"[{name_short}] Step 2/5 - Opening ENM session...")
        session = enmscripting.open(url, username, password)
        try:
            terminal = session.terminal()
            with open(mos_file_path, "rb") as f:
                print(f"[{name_short}] Step 3/5 - Uploading MO list and submitting export command...")
                result = terminal.execute(command, f)

            if not result.is_command_result_available():
                raise RuntimeError("Export command returned with no output available.")

            export_output = "\n".join(result.get_output())
            match = re.search(r"job\s*id\D*(\d+)", export_output, flags=re.IGNORECASE)
            if not match:
                raise ValueError(f"Job ID not found. Output: {export_output}")

            job_id = match.group(1)
            print(f"[{name_short}] Export accepted. Job ID: {job_id}")

            print(f"[{name_short}] Step 4/5 - Monitoring export job status...")
            for attempt in range(1, 241):  # 4h
                status_cmd = f"cmedit export --status --job {job_id}"
                status_resp = terminal.execute(status_cmd)
                if not status_resp.is_command_result_available():
                    print(f"[{name_short}] [{attempt}] No status output yet. Retrying in 60s...")
                    time.sleep(60)
                    continue
                status_output = "\n".join(status_resp.get_output())
                status_upper = status_output.upper()
                if "COMPLETED" in status_upper:
                    print(f"[{name_short}] Job completed successfully!")
                    break
                if "FAILED" in status_upper:
                    raise RuntimeError(f"Job failed. Status: {status_output}")

                match_exported = re.search(r"Nodes exported\s+(\d+)", status_output, flags=re.IGNORECASE)
                match_total = re.search(r"Expected nodes exported\s+(\d+)", status_output, flags=re.IGNORECASE)
                if match_exported and match_total:
                    exported = match_exported.group(1)
                    total = match_total.group(1)
                    print(f"[{name_short}] [{attempt}] Progress: {exported}/{total} nodes exported.")
                else:
                    compact_status = " ".join(line.strip() for line in status_output.splitlines() if line.strip())
                    if compact_status:
                        print(f"[{name_short}] [{attempt}] Current status: {compact_status[:180]}")
                    else:
                        print(f"[{name_short}] [{attempt}] Waiting for first status details...")
                time.sleep(60)
            else:
                raise TimeoutError(f"Timeout waiting for job {job_id}")

            print(f"[{name_short}] Step 5/5 - Downloading export files...")
            os.makedirs(output_dir, exist_ok=True)
            download_cmd = f"cmedit export --download --job {job_id}"
            print(f"[{name_short}] Running command: {download_cmd}")
            download_resp = terminal.execute(download_cmd)

            if not download_resp.has_files():
                print(f"[{name_short}] No files to download.")
                return f"OK {name_short}: No files"

            downloaded = 0
            for enm_file in download_resp.files():
                try:
                    enm_file.download(output_dir)
                    downloaded += 1
                    print(f"[{name_short}] Downloaded file #{downloaded}.")
                except Exception as e:
                    print(f"[{name_short}] Download error: {e}")
            print(f"[{name_short}] ENM processing completed successfully.")
            return f"OK {name_short}: Success ({downloaded} file(s) downloaded)"

        finally:
            enmscripting.close(session)
            print(f"[{name_short}] Session closed.")

    except Exception as e:
        print(f"[{name_short}] Error: {e}")
        return f"ERROR {name_short}: {str(e)}"


def main():
    disable_proxy_env()

    if len(sys.argv) < 2:
        print("Usage: python dump_multiple_enms.py <config.json>")
        print("  config.json = file exported from Downloader (Export for script)")
        sys.exit(1)

    config_path = os.path.abspath(sys.argv[1])
    if not os.path.isfile(config_path):
        print(f"File not found: {config_path}")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    enms = config.get("enms") or []
    output_dir = (config.get("output_dir") or "C:/eNB_Fake/data/input").replace("/", os.sep)
    mos_file_name = config.get("mos_file") or "mos_downloader.txt"
    command_template = (config.get("command_template") or "").strip()
    selected_mos = config.get("selected_mos") or [m["id"] for m in AVAILABLE_MOS]

    if not enms:
        print("No ENM in config. Check and fill ENMs in the Downloader and export again.")
        sys.exit(1)
    if not command_template:
        print("command_template empty in config. Generate the command in the Downloader and export again.")
        sys.exit(1)

    selected = [mo_id for mo_id in (selected_mos or []) if mo_id]
    if not selected:
        print("No MO selected. Check at least one MO in the Downloader (or add in Additional MOs) and export again.")
        sys.exit(1)

    try:
        output_dir = ensure_writable_output_dir(output_dir)
    except PermissionError as e:
        print(f"ERROR: {e}")
        sys.exit(1)

    # Clear output dir so old dumps are not kept
    clear_output_dir(output_dir)
    mos_file_path = create_mos_file(output_dir, mos_file_name, selected_mos)
    print(f"MOs file: {mos_file_path} ({len(selected)} MOs)")

    print("\n" + "=" * 60)
    print("STARTING PARALLEL PROCESSING OF MULTIPLE ENMs")
    print("=" * 60)
    print(f"Total ENMs: {len(enms)}")
    for i, e in enumerate(enms, 1):
        print(f"  [{i}] {e.get('name_short') or e.get('id')}")
    print("\nStarting threads...\n")

    results = []
    max_workers = min(4, len(enms))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(process_enm, enm, command_template, output_dir, mos_file_path): enm
            for enm in enms
        }
        for future in as_completed(futures):
            enm = futures[future]
            try:
                r = future.result()
                results.append(r)
                print(f"\n{'='*60}\nCOMPLETED: {r}\n{'='*60}\n")
            except Exception as e:
                name = enm.get("name_short") or enm.get("id")
                print(f"\nError processing {name}: {e}\n")
                results.append(f"ERROR {name}: {str(e)}")

    print("\n" + "=" * 60)
    print("FINAL SUMMARY - ALL ENMs")
    print("=" * 60)
    for r in results:
        print(r)
    print("=" * 60)
    print("PARALLEL PROCESSING COMPLETED.")
    print("=" * 60)


if __name__ == "__main__":
    main()
