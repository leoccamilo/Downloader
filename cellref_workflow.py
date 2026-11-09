"""Generate the user's LTE v2 / NR v3 references and refresh physical reports.

Portal downloads are supplied by the user. Source notebooks and portal files
are read only; every run stages its results before publishing to the shared
reference directory selected in the Site List card.
"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import uuid
from bundled_sources import CELLREF_SCRIPTS

LTE_NOTEBOOK = "cellref_LTE_v2.ipynb"
NR_NOTEBOOK = "CellRef_5G_v3.ipynb"
REFRESH_MOS = ("EUtranCellTDD", "GUtranFreqRelation", "CapacityState", "TermPointToENB")
PORTAL_COLUMNS = {
    "SIG_ERB", "SIG_ESTADO", "SIG_LOGICA", "NOME_MUNICIPIO", "AREA_REGISTRO",
    "NOM_ERB", "NUM_ENB_ID", "NUM_AZIMUTE_ANTENA", "NUM_TILT_MECAN_ANTENA",
    "NUM_TILT_ELETRICO", "DES_MODELO_ANTENA", "FORNECEDOR", "COBERTURA_SETOR",
    "NUM_ALT_MAX_SUP_ANTENA", "STR_LATITUDE_SITE", "STR_LONGITUDE_SITE",
    "DES_ENDERECO_SITE", "NOM_BAIRRO",
}


def read_table(path, **kwargs):
    import pandas as pd
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(path, encoding=encoding, low_memory=False, **kwargs)
        except UnicodeDecodeError:
            continue


def portal_files(directory):
    directory = Path(directory)
    files = sorted(p for p in directory.glob("*.xlsx") if not p.name.startswith("~$"))
    if not files:
        raise ValueError(f"No downloaded portal XLSX files in {directory}")
    weeks = {int(match.group(1)) for p in files for match in [re.search(r"_W(\d{1,2})(?:\D|$)", p.stem, re.I)] if match}
    if len(weeks) > 1:
        raise ValueError(f"Portal folder contains different weeks {sorted(weeks)}: {directory}. Keep only this run's downloads.")
    return files


def preflight_cellrefs(config, require_parameters=True):
    import ast
    import pandas as pd
    from weekly_workflow import notebook_cells

    options = config.get("cellref") or {}
    scripts = Path(options.get("scripts_dir") or CELLREF_SCRIPTS)
    for name in (LTE_NOTEBOOK, NR_NOTEBOOK):
        path = scripts / name
        if not path.is_file():
            raise ValueError(f"Cellref notebook not found: {path}")
        for index, source in notebook_cells(path):
            ast.parse(source, filename=f"{name}:cell_{index}")
    inputs = {}
    for technology, default in (("lte", "C:/Cellref/LTE_dump"), ("nr", "C:/Cellref/NR_dump")):
        files = portal_files(options.get(technology + "_input_dir") or default)
        for file in files:
            columns = set(pd.read_excel(file, header=2, nrows=0).columns)
            required = PORTAL_COLUMNS | ({"SITUACAO_ERB"} if technology == "lte" else set())
            if required - columns:
                raise ValueError(f"Invalid {technology.upper()} portal headers (row 3) in {file.name}: missing {sorted(required - columns)}")
        inputs[technology] = files
    input_weeks = {int(match.group(1)) for files in inputs.values() for file in files
                   for match in [re.search(r"_W(\d{1,2})(?:\D|$)", file.stem, re.I)] if match}
    if len(input_weeks) > 1:
        raise ValueError(f"LTE and NR portal downloads are from different weeks: {sorted(input_weeks)}")
    if not config.get("reference_dir"):
        raise ValueError("Select the shared references folder in Site List")
    if require_parameters:
        parameters = Path(options.get("parameter_dir") or config.get("enriched_dir") or "")
        find_parameter(parameters, "EUtranCell_TDD_FDD.txt")
        for name in ("5G_GNBDUFunction.txt", "5G_NRCellDU.txt", "5G_NRSectorCarrier.txt"):
            find_parameter(parameters, name)
        if options.get("refresh_reports", True):
            from weekly_workflow import NOTEBOOKS, DEFAULT_NOTEBOOK_DIR
            for name in NOTEBOOKS[2:4]:
                path = Path(config.get("notebook_dir") or DEFAULT_NOTEBOOK_DIR) / name
                if not path.is_file():
                    raise ValueError(f"Physical refresh notebook not found: {path}")
            for name in ("EUtranCellFDD.txt", "ENodeBFunction.txt"):
                if not (Path(config["output_dir"]) / name).is_file():
                    raise ValueError(f"Missing processed MO {name} in {config['output_dir']}; run the ENM workflow before refreshing reports.")
    return inputs


def find_parameter(directory, name):
    """Prefer the canonical current file; accept dated legacy Camilo inputs."""
    directory = Path(directory)
    canonical = directory / name
    if canonical.is_file():
        return canonical
    stem = Path(name).stem
    candidates = [p for p in directory.glob(stem + "_*" + Path(name).suffix)
                  if re.fullmatch(re.escape(stem) + r"_\d{1,2}" + re.escape(Path(name).suffix), p.name)]
    if not candidates:
        raise ValueError(f"Missing ENM parameter {name} in {directory}. Run the ENM workflow first or select its current report folder.")
    return max(candidates, key=lambda p: p.stat().st_mtime_ns)


def science_from_cellref(path):
    """The Camilo notebook only needs SITE / municipality / neighbourhood here."""
    import pandas as pd
    frame = pd.read_excel(path)
    required = {"eNB", "CLUSTER", "BAIRRO"}
    if required - set(frame.columns):
        raise ValueError(f"Cellref cannot supply site geography: missing {sorted(required - set(frame.columns))}")
    # Prefer the host's own physical cells for node-level site geography. Remote
    # Hotel cells retain their per-cell coordinates in the operational cellref.
    if "CELL" in frame:
        frame["_host"] = frame["CELL"].astype("string").str[1:4].eq(frame["eNB"].astype("string").str[1:4])
        frame = frame.sort_values("_host", ascending=False, kind="stable")
    return (frame[["eNB", "CLUSTER", "BAIRRO"]].dropna(subset=["eNB"])
            .drop_duplicates("eNB").rename(columns={"eNB": "SITE", "CLUSTER": "MUNICÍPIO"}))


def generate_cellrefs(config, run_dir, processed, enriched, week, warnings):
    import pandas as pd
    from weekly_workflow import execute_notebook

    inputs = preflight_cellrefs(config, require_parameters=False)
    stage = Path(run_dir) / "cellrefs"
    parameters = stage / "parameters"
    lte_out, nr_out = stage / "LTE", stage / "NR"
    for directory in (parameters, lte_out, nr_out, stage / "LTE_dump", stage / "NR_dump"):
        directory.mkdir(parents=True, exist_ok=True)
    manifest_inputs = []
    for technology, files in inputs.items():
        for index, file in enumerate(files):
            shutil.copy2(file, stage / ("LTE_dump" if technology == "lte" else "NR_dump") / f"input_{index:03d}.xlsx")
            manifest_inputs.append({"path": str(file), "bytes": file.stat().st_size,
                                    "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
            print(f"Portal {technology.upper()}: {file.name}", flush=True)
    for name in ("EUtranCell_TDD_FDD.txt", "5G_GNBDUFunction.txt", "5G_NRCellDU.txt", "5G_NRSectorCarrier.txt"):
        source = find_parameter(enriched, name)
        frame = read_table(source, sep="\t")
        if name == "5G_NRSectorCarrier.txt" and "NRSectorCarrier" not in frame:
            identifiers = [key for key in ("NRSectorCarrierId", "nRSectorCarrierId") if key in frame]
            if identifiers:
                frame["NRSectorCarrier"] = frame[identifiers].bfill(axis=1).iloc[:, 0]
        frame.to_csv(parameters / name, sep="\t", index=False, encoding="utf-8")
        if name.startswith("5G_"):
            frame.to_csv(parameters / (Path(name).stem + f"_{week}.txt"), sep="\t", index=False, encoding="utf-8")
        print(f"ENM parameters: {source} ({len(frame):,} rows)", flush=True)
    sector_txt = Path(processed) / "SectorCarrier.txt"
    sector_csv = Path(processed) / "SectorCarrier.csv"
    source = sector_txt if sector_txt.is_file() else sector_csv
    if not source.is_file():
        raise ValueError(f"Missing SectorCarrier.txt / SectorCarrier.csv in {processed}; no Vivo export is required, but this ENM MO is needed.")
    required = {"eNB", "CELL", "maximumTransmissionPower"}
    columns = set(read_table(source, sep="\t" if source.suffix == ".txt" else ",", nrows=0).columns)
    available = required | {"ManagedElement", "SectorCarrierId", "sectorCarrierId"}
    power = read_table(source, sep="\t" if source.suffix == ".txt" else ",", usecols=sorted(available & columns))
    if "eNB" not in power and "ManagedElement" in power:
        power["eNB"] = power["ManagedElement"]
    if "CELL" not in power:
        identifiers = [key for key in ("SectorCarrierId", "sectorCarrierId") if key in power]
        if identifiers:
            power["CELL"] = power[identifiers].bfill(axis=1).iloc[:, 0]
    if required - set(power.columns):
        raise ValueError(f"SectorCarrier lacks derived columns {sorted(required - columns)}; run the complete parser first.")
    power[sorted(required)].to_csv(parameters / "SectorCarrier.csv", index=False)
    roots = [("C:/cellref/LTE_dump", stage / "LTE_dump"), ("C:/cellref/NR_dump", stage / "NR_dump"),
             ("C:/cellref/LTE", lte_out), ("C:/cellref/NR", nr_out),
             ("C:/Vivo Reports/LTE/LTE MOs/SectorCarrier.csv", parameters / "SectorCarrier.csv"),
             ("C:/Camilo", parameters), ("C:/Dumps/todos_enms", Path(run_dir) / "raw")]
    scripts = Path((config.get("cellref") or {}).get("scripts_dir") or CELLREF_SCRIPTS)
    notebook_hashes = {}
    for name in (LTE_NOTEBOOK, NR_NOTEBOOK):
        print(f"\nCELLREF: {name}", flush=True)
        path = scripts / name
        notebook_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        execute_notebook(path, roots, week, warnings)
    quality = {}
    for source, target in ((lte_out / "cellref.xlsx", stage / "cellref.xlsx"),
                           (nr_out / "cellref_5g.xlsx", stage / "cellref_5g.xlsx")):
        if not source.is_file():
            raise ValueError(f"Notebook did not generate {source.name}")
        frame = pd.read_excel(source)
        required = {"eNB", "CELL", "Latitude", "Longitude", "Azimuth", "Height"} if target.name == "cellref.xlsx" else {"SiteID", "SectorID", "Latitude", "Longitude", "Azimuth", "Height"}
        if frame.empty or required - set(frame.columns):
            raise ValueError(f"Invalid generated {source.name}: empty output or missing {sorted(required - set(frame.columns))}")
        latitude = pd.to_numeric(frame["Latitude"], errors="coerce")
        longitude = pd.to_numeric(frame["Longitude"], errors="coerce")
        if (latitude.dropna().abs() > 90).any() or (longitude.dropna().abs() > 180).any():
            raise ValueError(f"Invalid coordinate range in generated {source.name}")
        missing_geo = int((latitude.isna() | longitude.isna()).sum())
        quality[target.name] = {"rows": len(frame), "missing_coordinates": missing_geo}
        if missing_geo:
            message = f"{target.name}: {missing_geo:,} of {len(frame):,} cells have no complete coordinates in the supplied reference data."
            warnings.append(message)
            print("WARNING: " + message, flush=True)
        shutil.copy2(source, target)
        print(f"Validated {source.name}: {len(frame):,} rows", flush=True)
    science_from_cellref(stage / "cellref.xlsx").to_excel(stage / "SCIENCE.xlsx", index=False)
    (stage / "generation.json").write_text(json.dumps({"inputs": manifest_inputs, "notebooks": notebook_hashes, "quality": quality}, indent=2), encoding="utf-8")
    return stage


def cache_refresh_inputs(raw, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    files = []
    for mo in REFRESH_MOS:
        for source in sorted(Path(raw).glob(mo + "_*_part*.parquet")):
            shutil.copy2(source, destination / source.name)
            files.append(source.name)
    (destination / "index.json").write_text(json.dumps({"snapshot": destination.parent.name, "files": files}), encoding="utf-8")


def prepare_refresh_inputs(processed_source, raw, inventory_source):
    """Reuse the raw MOs retained by Run All; support the earlier TXT parser."""
    import pandas as pd
    processed_source, raw = Path(processed_source), Path(raw)
    index = processed_source / ".refresh_inputs/current.json"
    if index.is_file():
        saved = json.loads(index.read_text(encoding="utf-8"))
        snapshot = saved["snapshot"]
        if snapshot in {"", ".", ".."} or Path(snapshot).name != snapshot:
            raise ValueError("Invalid refresh snapshot")
        for name in saved["files"]:
            if Path(name).name != name:
                raise ValueError("Invalid refresh input name")
            shutil.copy2(index.parent / snapshot / name, raw / name)
    else:
        for mo in REFRESH_MOS:
            source = processed_source / (mo + ".txt")
            if source.is_file():
                frame = read_table(source, sep="\t", dtype=str)
                frame.to_parquet(raw / (mo + "_refresh_part00000.parquet"), index=False)
    inventory = read_table(inventory_source, sep="\t")
    if "Tipo" in inventory and inventory["Tipo"].eq("TDD").any() and not list(raw.glob("EUtranCellTDD_*_part*.parquet")):
        raise ValueError("The current inventory contains TDD but its raw parameters are unavailable. Run All once to retain the refresh inputs; no existing files were updated.")


def refresh_physical_reports(config, raw, processed, enriched, vivo, references, week, warnings):
    from weekly_workflow import execute_notebook, NOTEBOOKS

    roots = [("C:/Camilo/SCIENCE.xlsx", references / "SCIENCE.xlsx"),
             ("C:/Camilo/cellref.xlsx", references / "cellref.xlsx"),
             ("C:/Dumps/todos_enms", raw), ("C:/Dumps/LTE_Total", processed),
             ("C:/Camilo", enriched), ("C:/Vivo Reports", vivo)]
    for name in NOTEBOOKS[2:4]:
        print(f"\nREFRESH PHYSICAL DATA: {name}", flush=True)
        execute_notebook(Path(config["notebook_dir"]) / name, roots, week, warnings, skip_missing_auxiliary=True)


def publish_cellrefs(config, generated, exports):
    from weekly_workflow import publish_file
    destination = Path(config["reference_dir"])
    for name in ("cellref.xlsx", "cellref_5g.xlsx"):
        publish_file(generated / name, destination / name, exports)
    for folder in ("LTE", "NR"):
        for file in (generated / folder).glob("*.xlsx"):
            if file.name.lower() not in {"cellref.xlsx", "cellref_5g.xlsx"}:
                publish_file(file, destination / "history" / folder / file.name, exports)


def run_cellref_workflow(config):
    from weekly_workflow import DEFAULT_NOTEBOOK_DIR
    config.setdefault('notebook_dir', DEFAULT_NOTEBOOK_DIR)
    if config.get('raw_txt_dir'):
        from direct_workflow import run_direct_cellrefs
        return run_direct_cellrefs(config)
    from weekly_workflow import publish_file, DEFAULT_NOTEBOOK_DIR

    preflight_cellrefs(config)
    config.setdefault("notebook_dir", DEFAULT_NOTEBOOK_DIR)
    date = datetime.fromisoformat(config["run_date"]) if config.get("run_date") else datetime.now()
    week = int(date.strftime("%U")) + 1
    run_dir = Path(config["output_dir"]).parent / ".cellref_runs" / (date.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8])
    raw, processed, enriched, vivo = [run_dir / name for name in ("raw", "processed", "enriched", "vivo")]
    for directory in (raw, processed, enriched, vivo / "LTE/LTE MOs", vivo / "5G/5G MOs", vivo / "MoB_IMP"):
        directory.mkdir(parents=True, exist_ok=True)
    options = config.get("cellref") or {}
    parameter_dir = Path(options.get("parameter_dir") or config["enriched_dir"])
    manifest = {"status": "running", "week": week, "exports": [], "warnings": [], "parameters": str(parameter_dir)}
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Run directory: {run_dir}", flush=True)
    try:
        for source in Path(config["output_dir"]).iterdir():
            if source.is_file() and source.suffix.lower() in {".txt", ".csv"}:
                shutil.copy2(source, processed / source.name)
        for name in ("EUtranCell_TDD_FDD.txt", "5G_GNBDUFunction.txt", "5G_NRCellDU.txt", "5G_NRSectorCarrier.txt"):
            shutil.copy2(find_parameter(parameter_dir, name), enriched / name)
        if options.get("refresh_reports", True):
            prepare_refresh_inputs(Path(config["output_dir"]), raw, enriched / "EUtranCell_TDD_FDD.txt")
            # Generation inputs must describe the same scope as the raw report
            # inputs. Otherwise a stale smaller dump could silently trim output.
            current = read_table(enriched / "EUtranCell_TDD_FDD.txt", sep="\t")
            fdd = read_table(processed / "EUtranCellFDD.txt", sep="\t")
            if "Tipo" in current:
                expected = set(current.loc[current["Tipo"].eq("FDD"), "eNB"].dropna())
                if "eNB" in fdd:
                    nodes = fdd["eNB"]
                    if "ManagedElement" in fdd:
                        nodes = nodes.fillna(fdd["ManagedElement"])
                elif "ManagedElement" in fdd:
                    nodes = fdd["ManagedElement"]
                else:
                    raise ValueError("Parsed EUtranCellFDD is missing eNB / ManagedElement")
                actual = set(nodes.dropna())
                if not expected.issubset(actual):
                    raise ValueError("The selected ENM reports and parsed MO folder describe different scopes. Run All or select matching parameters before refreshing steps 4/5.")
        generated = generate_cellrefs(config, run_dir, processed, enriched, week, manifest["warnings"])
        if options.get("refresh_reports", True):
            refresh_physical_reports(config, raw, processed, enriched, vivo, generated, week, manifest["warnings"])
        publish_cellrefs(config, generated, manifest["exports"])
        if options.get("refresh_reports", True):
            suffix = re.compile(r"_" + str(week) + r"(?=\.[^.]+$)")
            # Only files written by steps 4/5 carry the current week suffix,
            # except their canonical FDD/combined CSV/TXT outputs.
            canonical = {"EUtranCellFDD.csv", "EUtranCell_TDD_FDD.txt", "EUtranCell_TDD_FDD.csv"}
            for file in enriched.iterdir():
                if file.is_file() and (suffix.search(file.name) or file.name in canonical):
                    publish_file(file, Path(config["enriched_dir"]) / suffix.sub("", file.name), manifest["exports"])
                    if config.get("create_weekly") and suffix.search(file.name):
                        publish_file(file, Path(config["history_dir"]) / file.name, manifest["exports"])
            if config.get("transfer_vivo"):
                for file in vivo.rglob("*"):
                    if file.is_file():
                        publish_file(file, Path(config["vivo_dir"]) / file.relative_to(vivo), manifest["exports"])
        manifest["status"] = "completed"
        print("\nPIPELINE COMPLETED.", flush=True)
    except Exception as exc:
        manifest.update(status="failed", error=str(exc))
        raise
    finally:
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Manifest: {manifest_path}", flush=True)
