#!/usr/bin/env python3
"""Execute the user's audit notebooks with isolated inputs and configurable exports.

The notebooks remain the source of the report rules. Runtime adaptations cover
paths, week numbering, notebook magics, schema/Arrow compatibility and two stale
output-frame references. No notebook is edited and notebook ENM credentials
are not used.
"""

import argparse
import ast
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import traceback
import uuid
from bundled_sources import WEEKLY_SCRIPTS, CELLREF_SCRIPTS

NOTEBOOKS = (
    "2_Parser_XML_parquet.ipynb",
    "3_Arquivos_Glob_parquet.ipynb",
    "4_MOs_Camilo.ipynb",
    "5_MOs_TDD.ipynb",
    "6_MOs_5G.ipynb",
)
DEFAULT_NOTEBOOK_DIR = str(WEEKLY_SCRIPTS)
DEFAULT_REFERENCE_DIR = "C:/Camilo"
DEFAULT_HISTORY_DIR = "C:/Camilo"
DEFAULT_VIVO_DIR = "C:/Vivo Reports"


class NoReportRows(Exception):
    """A self-contained relation report has no rows in the selected scope."""


def notebook_cells(path):
    document = json.loads(path.read_text(encoding="utf-8-sig"))
    for index, cell in enumerate(document["cells"]):
        if cell["cell_type"] != "code":
            continue
        source = "".join(cell["source"])
        lines = []
        for line in source.splitlines():
            if line.strip() in ("%%time", "%time"):
                continue
            if line.lstrip().startswith(("%", "!")):
                raise ValueError(f"Unsupported notebook command: {path.name}, cell {index}")
            lines.append(line)
        source = "\n".join(lines)
        if source.strip():
            yield index, source


def required_mos(notebook_dir):
    """Include lookup MOs as well as primary MOs in the weekly ENM export."""
    found = set()
    for name in NOTEBOOKS[1:]:
        for _, source in notebook_cells(Path(notebook_dir) / name):
            found.update(re.findall(r"base_path.*?\\(\w+)_\*", source))
    return sorted(found, key=str.lower)


def preflight(config):
    """Fail before extraction/publication when sources or references are missing."""
    from importlib.util import find_spec

    missing = [name for name in ("pandas", "numpy", "pyarrow", "lxml", "openpyxl")
               if find_spec(name) is None]
    if missing:
        raise ValueError("Missing Python dependencies: " + ", ".join(missing))
    notebook_dir = Path(config.get("notebook_dir") or DEFAULT_NOTEBOOK_DIR)
    reference_dir = Path(config.get("reference_dir") or DEFAULT_REFERENCE_DIR)
    for name in NOTEBOOKS:
        path = notebook_dir / name
        if not path.is_file():
            raise ValueError(f"Notebook not found: {path}")
        for index, source in notebook_cells(path):
            ast.parse(source, filename=f"{name}:cell_{index}")
    for name in ("cellref.xlsx",):
        if not (reference_dir / name).is_file():
            raise ValueError(f"Reference file not found: {reference_dir / name}")
    for key in ("output_dir", "enriched_dir"):
        if not str(config.get(key) or "").strip():
            raise ValueError(f"{key} is required")
    if config.get("create_weekly") and not str(config.get("history_dir") or "").strip():
        raise ValueError("history_dir is required when weekly history is enabled")
    if config.get("transfer_vivo") and not str(config.get("vivo_dir") or "").strip():
        raise ValueError("vivo_dir is required when Vivo export is enabled")
    if (config.get("cellref") or {}).get("enabled"):
        from cellref_workflow import preflight_cellrefs
        preflight_cellrefs(config, require_parameters=False)
    if config.get("dump_output_dir"):
        dump_dir = Path(config["dump_output_dir"]).resolve()
        protected = [notebook_dir, reference_dir, Path(__file__).resolve().parent,
                     Path(config["output_dir"]), Path(config["enriched_dir"])]
        cellref_options = config.get("cellref") or {}
        if cellref_options.get("enabled"):
            protected.extend(Path(cellref_options.get(key) or default) for key, default in (
                ("scripts_dir", str(CELLREF_SCRIPTS)), ("lte_input_dir", "C:/Cellref/LTE_dump"),
                ("nr_input_dir", "C:/Cellref/NR_dump")))
        for key in ("history_dir", "vivo_dir"):
            if key == "vivo_dir" and not config.get("transfer_vivo"):
                continue
            if config.get(key):
                protected.append(Path(config[key]))
        for directory in protected:
            directory = directory.resolve()
            if dump_dir == directory or dump_dir in directory.parents:
                raise ValueError(f"Dump folder {dump_dir} would erase protected folder {directory}. Choose a separate dump folder.")
    return required_mos(notebook_dir)


class AdaptNotebook(ast.NodeTransformer):
    def __init__(self, roots, week, guard_empty_relations=False, txt_mode=False):
        self.roots = roots
        self.week = week
        self.guard_empty_relations = guard_empty_relations
        self.txt_mode = txt_mode

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            normalized = node.value.replace("\\", "/")
            for old, new in self.roots:
                if normalized.lower() == old.lower() or normalized.lower().startswith(old.lower() + "/"):
                    suffix = normalized[len(old):].lstrip("/")
                    translated = str(new / suffix).replace("\\", "/")
                    if normalized.endswith("/"):
                        translated += "/"
                    return ast.copy_location(ast.Constant(translated), node)
            if re.match(r"^[A-Za-z]:[/\\]", node.value):
                raise ValueError(f"Unmapped absolute path in notebook: {node.value}")
        return node

    def visit_Assign(self, node):
        node = self.generic_visit(node)
        if any(isinstance(target, ast.Name) and target.id == "semana_atual" for target in node.targets):
            node.value = ast.copy_location(ast.Constant(self.week), node.value)
        if (self.guard_empty_relations and isinstance(node.value, ast.Subscript)
                and isinstance(node.value.value, ast.Name) and node.value.value.id == "df1"
                and not isinstance(node.value.slice, ast.Constant)
                and any(isinstance(target, ast.Name) and target.id == "df1" for target in node.targets)):
            node.value = ast.copy_location(ast.Call(func=ast.Name(id="require_report_rows", ctx=ast.Load()),
                                                    args=[node.value], keywords=[]), node.value)
        return node

    def visit_Expr(self, node):
        # Notebook previews materialize large frames and are unnecessary in a job.
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Attribute):
            if node.value.func.attr in ("head", "tail", "sample"):
                return None
        return self.generic_visit(node)

    def visit_BinOp(self, node):
        node = self.generic_visit(node)
        if isinstance(node.op, ast.Add):
            return ast.copy_location(ast.Call(func=ast.Name(id="notebook_add", ctx=ast.Load()),
                                              args=[node.left, node.right], keywords=[]), node)
        return node

    def visit_Call(self, node):
        node = self.generic_visit(node)
        if self.txt_mode and ((isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                               and node.func.value.id == 'glob' and node.func.attr == 'glob')
                              or isinstance(node.func, ast.Name) and node.func.id == 'glob'):
            node.func = ast.copy_location(ast.Name(id='notebook_glob', ctx=ast.Load()), node.func)
        if (isinstance(node.func, ast.Attribute) and node.func.attr == "replace"
                and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "str"):
            # Arrow's regex engine cannot execute the notebook's callable regex
            # replacements. Use pandas' Python string engine for this operation.
            receiver = node.func.value.value
            node.func.value.value = ast.Call(func=ast.Attribute(value=receiver, attr="astype", ctx=ast.Load()),
                                             args=[ast.Constant("string[python]")], keywords=[])
        if isinstance(node.func, ast.Attribute) and node.func.attr == "convert_dtypes":
            if any(k.arg == "dtype_backend" and isinstance(k.value, ast.Constant) and k.value.value == "pyarrow" for k in node.keywords):
                return ast.copy_location(ast.Call(func=ast.Name(id="convert_notebook_dtypes", ctx=ast.Load()),
                                                  args=[node.func.value], keywords=[]), node)
        if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
            if node.func.value.id == "pd" and node.func.attr == "read_excel":
                node.func = ast.copy_location(ast.Name(id="read_reference_excel", ctx=ast.Load()), node.func)
            elif node.func.value.id == "pd" and node.func.attr == "read_parquet":
                node.func = ast.copy_location(ast.Name(id="read_notebook_parquet", ctx=ast.Load()), node.func)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "dropna":
            # The notebooks use 10/100 to drop sparse columns in national dumps.
            # For a smaller selected scope that deletes every column, including
            # site identifiers. Keep columns with at least one configured value.
            for keyword in node.keywords:
                if keyword.arg == "thresh" and isinstance(keyword.value, ast.Constant) and keyword.value.value in (10, 100):
                    keyword.value = ast.copy_location(ast.Constant(1), keyword.value)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "drop":
            # ENMs expose different ID spellings; removing an already absent
            # column must not prevent otherwise valid reports being generated.
            if not any(keyword.arg == "errors" for keyword in node.keywords):
                node.keywords.append(ast.keyword(arg="errors", value=ast.Constant("ignore")))
        return node

    def visit_Subscript(self, node):
        node = self.generic_visit(node)
        if (isinstance(node.ctx, ast.Load) and isinstance(node.slice, ast.List)
                and all(isinstance(item, ast.Constant) and isinstance(item.value, str) for item in node.slice.elts)):
            return ast.copy_location(ast.Call(func=ast.Name(id="select_notebook_columns", ctx=ast.Load()),
                                              args=[node.value, node.slice], keywords=[]), node)
        if (isinstance(node.ctx, ast.Load) and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str) and (node.slice.value.endswith("Id") or node.slice.value in {
                    "ENodeBFunction", "GNBCUCPFunction", "GNBDUFunction", "EUtranCell", "NRCell"})):
            return ast.copy_location(ast.Call(func=ast.Name(id="read_notebook_column", ctx=ast.Load()),
                                              args=[node.value, node.slice], keywords=[]), node)
        if (isinstance(node.ctx, ast.Load) and isinstance(node.value, ast.Attribute)
                and node.value.attr == "loc" and isinstance(node.slice, ast.Tuple)
                and len(node.slice.elts) == 2 and isinstance(node.slice.elts[0], ast.Slice)
                and node.slice.elts[0].lower is None and node.slice.elts[0].upper is None):
            return ast.copy_location(ast.Call(func=ast.Name(id="select_notebook_columns", ctx=ast.Load()),
                                              args=[node.value.value, node.slice.elts[1]], keywords=[]), node)
        return node

    def visit_ExceptHandler(self, node):
        node = self.generic_visit(node)
        # Several legacy cells print an error and continue. A job must propagate
        # that error; optional convert_dtypes/engine fallbacks stay intact.
        printed_error = any(isinstance(part, ast.Constant) and isinstance(part.value, str)
                            and re.search(r"\b(erro|error)\b", part.value, re.I)
                            for statement in node.body for part in ast.walk(statement))
        if printed_error:
            node.body.append(ast.Raise())
            node.body = [part for part in node.body if not isinstance(part, ast.Continue)]
        return node


def execute_notebook(path, roots, week, warnings, reference_cache=None, skip_missing_auxiliary=False, txt_mode=False):
    import numpy as np
    import pandas as pd

    reference_cache = reference_cache if reference_cache is not None else {}

    def read_notebook_parquet(filename, **kwargs):
        import pyarrow as pa
        if txt_mode and Path(filename).suffix.lower() == '.txt':
            frame = pd.read_csv(filename, sep='\t', encoding='latin-1', dtype='string[pyarrow]',
                                usecols=kwargs.get('columns'), low_memory=False, keep_default_na=False, na_values=[''])
            mo = Path(filename).stem
        else:
            frame = pd.read_parquet(filename, **kwargs)
            mo = Path(filename).name.split("_")[0]
        variants = (mo + "Id", mo[:1].lower() + mo[1:] + "Id")
        if any(column in frame.columns for column in variants):
            for column in variants:
                if column not in frame.columns:
                    frame[column] = pd.Series(pd.NA, index=frame.index, dtype=pd.ArrowDtype(pa.string()))
        return frame

    def notebook_glob(pattern, *args, **kwargs):
        import glob
        normalized = str(pattern).replace('\\', '/')
        match = re.search(r'/([^/]+)_\*_part\*\.parquet$', normalized)
        if txt_mode and match:
            requested = Path(normalized).parent / (match.group(1) + '.txt')
            if requested.is_file():
                return [str(requested)]
            return [str(p) for p in requested.parent.glob('*.txt') if p.name.lower() == requested.name.lower()]
        return glob.glob(pattern, *args, **kwargs)

    def read_notebook_column(frame, column):
        if column in frame:
            return frame[column]
        if column in {"ENodeBFunction", "GNBCUCPFunction", "GNBDUFunction", "EUtranCell", "NRCell"}:
            import pyarrow as pa
            return pd.Series(pd.NA, index=frame.index, dtype=pd.ArrowDtype(pa.string()))
        alternate = column[0].swapcase() + column[1:]
        if alternate in frame:
            return pd.Series(pd.NA, index=frame.index, dtype=frame[alternate].dtype)
        return frame[column]  # Keep a meaningful KeyError for truly absent IDs.

    def convert_notebook_dtypes(frame):
        import pyarrow as pa
        frame = frame.convert_dtypes(dtype_backend="pyarrow")
        for column in frame.columns:
            if str(frame[column].dtype) == "null[pyarrow]":
                frame[column] = frame[column].astype(pd.ArrowDtype(pa.string()))
        return frame

    def select_notebook_columns(frame, columns):
        missing = set(columns) - set(frame.columns)
        if missing & {"eNB", "CELL", "ManagedElement", "gNBId", "eNBId", "nRCellCUId", "nRCellDUId"}:
            raise ValueError(f"Missing report identifiers: {sorted(missing)}")
        if missing:
            message = f"{path.name}: optional report columns absent in this scope: {sorted(missing)}"
            warnings.append(message)
            print("WARNING: " + message, flush=True)
        return frame.reindex(columns=columns)

    def require_report_rows(frame):
        if frame.empty:
            raise NoReportRows()
        return frame

    def notebook_add(left, right):
        try:
            return left + right
        except TypeError:
            # Merges with CSV/reference frames can mix Arrow and pandas string
            # columns. Retry text concatenation with one consistent engine.
            def is_text(value):
                if isinstance(value, str):
                    return True
                return isinstance(value, pd.Series) and all(isinstance(item, str) for item in value.dropna())

            if not (is_text(left) and is_text(right)):
                raise
            if isinstance(left, pd.Series):
                left = left.astype("string[python]")
            if isinstance(right, pd.Series):
                right = right.astype("string[python]")
            return left + right

    def read_reference_excel(filename, **kwargs):
        if set(kwargs) - {"usecols"}:
            return pd.read_excel(filename, **kwargs)
        key = str(filename)
        if key not in reference_cache:
            if Path(filename).name.lower() == "science.xlsx" and not Path(filename).is_file():
                from cellref_workflow import science_from_cellref
                reference_cache[key] = science_from_cellref(Path(filename).parent / "cellref.xlsx")
                print("SCIENCE.xlsx absent: using site fields from cellref.xlsx.", flush=True)
            else:
                reference_cache[key] = pd.read_excel(filename)
        frame = reference_cache[key]
        columns = kwargs.get("usecols")
        if columns is not None:
            absent = set(columns) - set(frame.columns)
            if absent:
                raise ValueError(f"Missing reference columns in {filename}: {sorted(absent)}")
            frame = frame[[col for col in frame.columns if col in columns]]
        return frame.copy()

    def read_cellref_csv(filename, **kwargs):
        # Original cellref notebooks use a CSV SectorCarrier and a legacy
        # NRSectorCarrier alias. Normalize only these input representations.
        filename = Path(filename)
        requested = kwargs.pop('usecols', None)
        if filename.name == 'SectorCarrier.txt':
            kwargs.pop('delimiter', None)
            kwargs['sep'] = '\t'
        frame = pd.read_csv(filename, **kwargs)
        if filename.name.startswith('5G_NRSectorCarrier') and 'NRSectorCarrier' not in frame:
            identifiers = [c for c in ('NRSectorCarrierId', 'nRSectorCarrierId') if c in frame]
            if identifiers:
                frame['NRSectorCarrier'] = frame[identifiers].bfill(axis=1).iloc[:, 0]
        return frame if requested is None else frame[list(requested)]

    namespace = {"__name__": "__main__", "__file__": str(path),
                 "np": np, "pd": pd, "semana_atual": week,
                 "read_reference_excel": read_reference_excel,
                 "convert_notebook_dtypes": convert_notebook_dtypes,
                 "select_notebook_columns": select_notebook_columns,
                 "read_notebook_parquet": read_notebook_parquet,
                 "read_notebook_column": read_notebook_column,
                 "require_report_rows": require_report_rows,
                 "notebook_add": notebook_add}
    namespace['notebook_glob'] = notebook_glob
    namespace['read_cellref_csv'] = read_cellref_csv
    raw = next(new for old, new in roots if old == "C:/Dumps/todos_enms")
    enriched = next(new for old, new in roots if old == "C:/Camilo")
    def has_raw(mo):
        return bool(notebook_glob(str(raw / (mo + '_*_part*.parquet')))) if txt_mode else bool(list(raw.glob(mo + '_*_part*.parquet')))
    fdd_only = path.name.startswith("5_") and not has_raw('EUtranCellTDD')
    inventory_saved = False
    for index, source in notebook_cells(path):
        auxiliary = re.findall(r"base_path.*?\\(\w+)_\*", source)
        if (skip_missing_auxiliary and auxiliary and path.name.startswith(("4_", "5_"))
                and auxiliary[0] != "EUtranCellTDD" and not has_raw(auxiliary[0])):
            print(f"Keeping existing {auxiliary[0]} report; no auxiliary raw MO available for refresh.", flush=True)
            continue
        # These original cells compute df2 but write the previous cell's df3.
        # Publish the frame computed for the current MO instead.
        if path.name.startswith("3_") and any(name in source for name in (
                "SignalingRadioBearer.txt", "CarrierAggregationFunction.txt")):
            source = source.replace("df3.to_csv(", "df2.to_csv(")
        saves_inventory = "tdd_fdd.to_csv" in source
        if fdd_only and not inventory_saved and not saves_inventory and "def load_parquet" not in source:
            continue
        if fdd_only and not inventory_saved and saves_inventory:
            frame = pd.read_csv(enriched / "EUtranCellFDD.csv", encoding="latin-1")
            frame["Tipo"] = "FDD"
            frame["Regional"] = frame["UF"].replace({"AM": "N", "AP": "N", "MA": "N", "PA": "N", "RR": "N", "BA": "BASE", "SE": "BASE"})
            regional = frame.pop("Regional")
            frame.insert(0, "Regional", regional)
            frame.dropna(subset=["administrativeState"], inplace=True)
            namespace["tdd_fdd"] = frame
            inventory_saved = True
            print("No EUtranCellTDD in this scope; producing FDD-only inventory.", flush=True)
        print(f"[{path.name} / cell {index}]", flush=True)
        guard_empty = path.name.startswith("6_") and any(name in source for name in ("'5G_EUtranCellRelation'", "'5G_EUtranFreqRelation'"))
        tree = AdaptNotebook(roots, week, guard_empty, txt_mode=txt_mode).visit(ast.parse(source))
        if txt_mode and path.name in ('cellref_LTE_v2.ipynb', 'CellRef_5G_v3.ipynb'):
            class CellrefCSV(ast.NodeTransformer):
                def visit_Call(self, node):
                    self.generic_visit(node)
                    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == 'pd' and node.func.attr == 'read_csv':
                        node.func = ast.copy_location(ast.Name(id='read_cellref_csv', ctx=ast.Load()), node.func)
                    return node
            tree = CellrefCSV().visit(tree)
        ast.fix_missing_locations(tree)
        try:
            exec(compile(tree, f"{path.name}:cell_{index}", "exec"), namespace)
        except NoReportRows:
            message = f"{path.name}, cell {index}: no NR relation rows in this scope; report skipped."
            warnings.append(message)
            print("WARNING: " + message, flush=True)
        except Exception as exc:
            raise RuntimeError(f"{path.name}, cell {index}: {exc}") from exc


def copy_input_files(config, destination):
    from xml_to_txt import collect_xml_sources

    inputs = config.get("input_files") or [config.get("input_dir")]
    if not all(inputs):
        raise ValueError("Select input files or an input folder")
    # Reuse the direct parser's ZIP/XML/gzip readers. Stream every selected XML
    # to a unique file, avoiding ZIP extraction paths and duplicate ZIP+XML rows.
    sources = collect_xml_sources(inputs)
    if not sources:
        raise ValueError("No ZIP/XML inputs found")
    for index, (label, opener) in enumerate(sources, 1):
        print(f"Input {index}/{len(sources)}: {label}", flush=True)
        with opener() as source, (destination / f"dump_{index:04d}.xml").open("wb") as target:
            shutil.copyfileobj(source, target)


def publish_file(source, target, exports):
    """Use a sibling temporary file so a reader never sees a half-written file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    exports.append({"source": str(source), "target": str(target), "bytes": target.stat().st_size})
    print(f"Saved: {target}", flush=True)


def publish_mob_imports(config, enriched, exports=None):
    """Publish the reference files formerly copied manually from Camilo."""
    if not config.get('transfer_vivo'):
        return
    references = Path(config.get('reference_dir') or DEFAULT_REFERENCE_DIR)
    sources = [references / 'cellref.xlsx', references / 'cellref_5g.xlsx',
               Path(enriched) / 'EUtranCell_TDD_FDD.csv']
    missing = [str(source) for source in sources if not source.is_file()]
    if missing:
        raise ValueError('MoB_IMP: arquivos obrigatórios ausentes: ' + ', '.join(missing))
    destination = Path(config.get('vivo_dir') or DEFAULT_VIVO_DIR) / 'MoB_IMP'
    exports = exports if exports is not None else []
    for source in sources:
        target = destination / source.name
        if source.resolve() != target.resolve():
            publish_file(source, target, exports)
    inventory = Path(enriched) / 'EUtranCell_TDD_FDD.csv'
    lte_target = destination.parent / 'LTE' / 'LTE MOs' / inventory.name
    if inventory.resolve() != lte_target.resolve():
        publish_file(inventory, lte_target, exports)


def run_workflow(config):
    config.setdefault('notebook_dir', DEFAULT_NOTEBOOK_DIR)
    if config.get('raw_txt_dir'):
        from direct_workflow import run_direct_workflow
        return run_direct_workflow(config)
    preflight(config)
    run_date = datetime.fromisoformat(config["run_date"]) if config.get("run_date") else datetime.now()
    week = int(run_date.strftime("%U")) + 1  # Preserve notebook week numbering.
    notebook_dir = Path(config.get("notebook_dir") or DEFAULT_NOTEBOOK_DIR)
    reference_dir = Path(config.get("reference_dir") or DEFAULT_REFERENCE_DIR)
    output_dir = Path(config["output_dir"])
    enriched_dir = Path(config["enriched_dir"])
    run_dir = output_dir.parent / ".weekly_runs" / (run_date.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8])
    raw = run_dir / "raw"
    processed = run_dir / "processed"
    enriched = run_dir / "enriched"
    vivo = run_dir / "vivo"
    for directory in (raw, processed, enriched, vivo / "LTE/LTE MOs", vivo / "5G/5G MOs", vivo / "MoB_IMP"):
        directory.mkdir(parents=True, exist_ok=True)
    roots = [("C:/Camilo/SCIENCE.xlsx", reference_dir / "SCIENCE.xlsx"),
             ("C:/Camilo/cellref.xlsx", reference_dir / "cellref.xlsx"),
             ("C:/Dumps/todos_enms", raw), ("C:/Dumps/LTE_Total", processed),
             ("C:/Camilo", enriched), ("C:/Vivo Reports", vivo)]
    manifest = {"status": "running", "week": week, "year": run_date.year,
                "run_dir": str(run_dir), "notebooks": [], "exports": [], "warnings": []}
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Run directory: {run_dir}\nNotebook week: {week} / {run_date.year}", flush=True)
    try:
        copy_input_files(config, raw)
        reference_cache = {}
        for step, name in enumerate(NOTEBOOKS, 2):
            path = notebook_dir / name
            manifest["notebooks"].append({"name": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            print(f"\nSTEP {step}/6: {name}", flush=True)
            execute_notebook(path, roots, week, manifest["warnings"], reference_cache)
        from cellref_workflow import cache_refresh_inputs, generate_cellrefs, refresh_physical_reports, publish_cellrefs
        cache_refresh_inputs(raw, run_dir / "refresh_inputs")
        generated = None
        if (config.get("cellref") or {}).get("enabled"):
            print("\nGenerating LTE v2 / 5G v3 references, then refreshing steps 4 and 5...", flush=True)
            generated = generate_cellrefs(config, run_dir, processed, enriched, week, manifest["warnings"])
            refresh_physical_reports(config, raw, processed, enriched, vivo, generated, week, manifest["warnings"])
        if not any(processed.glob("*.txt")):
            raise ValueError("The notebooks did not produce any processed TXT files")
        # Publication only starts once every notebook has completed.
        exports = manifest["exports"]
        if generated:
            publish_cellrefs(config, generated, exports)
        for file in (run_dir / "refresh_inputs").glob("*.parquet"):
            publish_file(file, output_dir / ".refresh_inputs" / run_dir.name / file.name, exports)
        publish_file(run_dir / "refresh_inputs" / "index.json", output_dir / ".refresh_inputs" / "current.json", exports)
        for file in processed.iterdir():
            if file.is_file():
                publish_file(file, output_dir / file.name, exports)
        suffix = re.compile(r"_" + str(week) + r"(?=\.[^.]+$)")
        for file in enriched.iterdir():
            if not file.is_file():
                continue
            latest_name = suffix.sub("", file.name)
            publish_file(file, enriched_dir / latest_name, exports)
            if config.get("create_weekly") and suffix.search(file.name):
                publish_file(file, Path(config["history_dir"]) / file.name, exports)
        if config.get("transfer_vivo"):
            for file in vivo.rglob("*"):
                if file.is_file():
                    publish_file(file, Path(config["vivo_dir"]) / file.relative_to(vivo), exports)
        manifest["status"] = "completed"
        if manifest["warnings"]:
            print(f"WARNING: {len(manifest['warnings'])} report schema warning(s). See manifest for details.", flush=True)
        print("\nPIPELINE COMPLETED.", flush=True)
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["error"] = str(exc)
        raise
    finally:
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Manifest: {manifest_path}", flush=True)
        # Intermediate XML/Parquet copies are only needed to diagnose failures.
        if manifest["status"] == "completed":
            shutil.rmtree(raw)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="JSON workflow configuration")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--cellref-only", action="store_true")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8-sig"))
    try:
        if args.check:
            mos = preflight(config)
            print("REQUIRED_MOS=" + json.dumps(mos))
            print("PREFLIGHT OK")
        elif args.cellref_only:
            from cellref_workflow import run_cellref_workflow
            run_cellref_workflow(config)
        else:
            run_workflow(config)
    except Exception:
        traceback.print_exc()
        print("PIPELINE FAILED.", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
