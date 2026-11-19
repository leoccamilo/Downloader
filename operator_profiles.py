"""Operator profiles (Vivo / Claro PR) and the cross-operator folder guard.

The web UI chooses the operator with the VIVO | CLARO switch and sends it on
every API call (header ``X-Downloader-Operator``). Rules here:

- The two operators have incompatible network rules, so each one only reads
  and writes its own folders. A request that points a path field at the other
  operator's folders is refused before any subprocess starts.
- Each operator has a root folder editable in the UI. Claro: default
  ``C:/Claro_Reports``, header ``X-Downloader-Claro-Root``. Vivo: either the
  historical "classic" folders the notebooks were written for (C:/Camilo,
  C:/Dumps/..., C:/Vivo Reports — the original machine keeps them) or one root
  for the team (default ``C:/Vivo_Downloader``, ``Referencias`` instead of
  ``Camilo``), header ``X-Downloader-Vivo-Root`` ("classic" or the root).
  ``vivo_folders()`` maps either one to the same named folders; the audits
  translate the notebooks' hard-coded paths with it.
- The Vivo notebook/enrichment endpoints are refused for Claro: running them
  on a Claro dump would silently produce wrong reports (UF = eNB[-2:], Hotel
  de BTS, PLMN 724/11...). The Claro processing of the MOs runs inside the
  parser pipeline (pos_processamento_claro.py) and the Claro cellref (MANDO)
  has its own endpoint (cadastro_claro.py), refused for Vivo; audits come later.
- A missing operator header means Vivo, so older clients keep working.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

VIVO = "vivo"
CLARO = "claro"
OPERATORS = (VIVO, CLARO)
DEFAULT_OPERATOR = VIVO

HEADER_OPERATOR = "X-Downloader-Operator"
HEADER_CLARO_ROOT = "X-Downloader-Claro-Root"
HEADER_VIVO_ROOT = "X-Downloader-Vivo-Root"

DEFAULT_CLARO_ROOT = "C:/Claro_Reports"
DEFAULT_VIVO_ROOT = "C:/Vivo_Downloader"
VIVO_CLASSIC = "classic"

# Vivo folders by role. "classic" = the historical folders hard-coded in the
# weekly notebooks and audits (the original machine keeps using them).
VIVO_CLASSIC_FOLDERS = {
    "raw": "C:/Dumps/todos_enms",          # dump (XML/ZIP) + parsed TXT
    "processed": "C:/Dumps/LTE_Total",     # treated MOs
    "references": "C:/Camilo",             # cellref, SCIENCE, weekly history
    "reports": "C:/Vivo Reports",          # final reports
    "extras": "C:/Camilao",                # 2 extra PSCell reports
    "cellref_lte_input": "C:/Cellref/LTE_dump",
    "cellref_nr_input": "C:/Cellref/NR_dump",
    "cellref_lte_output": "C:/Cellref/LTE",
    "cellref_nr_output": "C:/Cellref/NR",
    "exports": "C:/Downloader/data/exports",
}
# Same roles inside one root (team machines). Mirrored in web-tool/app.js (VIVO_ROOT_LAYOUT).
VIVO_ROOT_LAYOUT = {
    "raw": "Dumps/todos_enms",
    "processed": "Dumps/LTE_Total",
    "references": "Referencias",
    "reports": "Relatorios",
    "extras": "Relatorios/Adicionais",
    "cellref_lte_input": "Cellref/LTE_dump",
    "cellref_nr_input": "Cellref/NR_dump",
    "cellref_lte_output": "Cellref/LTE",
    "cellref_nr_output": "Cellref/NR",
    "exports": "Exports",
}

# Folders written by the Vivo notebooks and the Vivo MoB, plus the default Vivo
# root. Claro never touches them (a custom Vivo root is added per request).
VIVO_ROOTS = (
    "C:/Camilo",
    "C:/Camilao",
    "C:/Vivo Reports",
    "C:/Dumps",
    "C:/Cellref",
    "C:/MoB",
    "C:/Downloader/cellref",
    DEFAULT_VIVO_ROOT,
)
# Claro folders that exist regardless of the configured root.
CLARO_FIXED_ROOTS = ("C:/MoB_Claro",)

# Endpoints that only implement Vivo rules today.
VIVO_ONLY_ENDPOINTS = {
    "/api/run-weekly-workflow": "the weekly notebooks (steps 3 to 6) use Vivo rules",
    "/api/run-cellref": "the cellref generators read the Vivo portal files",
    "/api/run-post-process-4": "the enrichment scripts use Vivo rules",
    "/api/run-post-process-5": "the enrichment scripts use Vivo rules",
    "/api/run-post-process-6": "the enrichment scripts use Vivo rules",
    "/api/run-audits": "the registered audits use Vivo rules",
    "/api/update-site-list": "the site list is built from the Vivo cellrefs",
    "/api/save-site-list": "the site list is built from the Vivo cellrefs",
    "/api/load-site-list": "the site list is built from the Vivo cellrefs",
    "/api/export-site-ids": "the Claro scope is chosen by region / municipality",
}

# Endpoints that only implement Claro rules.
CLARO_ONLY_ENDPOINTS = {
    "/api/run-claro-cellref": "the Claro cellref uses the MANDO export and the Claro network rules",
}

# POST endpoints that do not carry workflow paths.
GUARD_EXEMPT = {"/api/local/list", "/api/shutdown"}

PATH_KEY_SUFFIXES = ("_dir", "_dirs", "_path", "_paths")
PATH_LIST_KEYS = {"input_files"}

_GEOGRAPHY = Path(__file__).resolve().parent / "bundled_scripts" / "claro" / "claro_pr_geography.json"


def normalize_operator(value) -> str | None:
    """Operator id from the header; empty means the default (Vivo)."""
    text = str(value or "").strip().lower()
    if not text:
        return DEFAULT_OPERATOR
    return text if text in OPERATORS else None


def _norm(path) -> str:
    text = str(path or "").strip().replace("\\", "/")
    while "//" in text:
        text = text.replace("//", "/")
    return text.rstrip("/").lower()


def is_drive_root(path) -> bool:
    text = _norm(path)
    return text in ("", "/") or (len(text) == 2 and text[1] == ":")


def is_under(path, root) -> bool:
    """True when ``path`` is ``root`` or inside it (by folder, not by prefix)."""
    p, r = _norm(path), _norm(root)
    return bool(p and r) and (p == r or p.startswith(r + "/"))


def normalize_vivo_root(value) -> str:
    """'classic' (historical folders, also when the header is missing) or the root folder."""
    text = str(value or "").strip().replace("\\", "/").rstrip("/")
    return VIVO_CLASSIC if not text or text.lower() == VIVO_CLASSIC else text


def vivo_folders(vivo_root=None) -> dict:
    """Vivo folders by role for 'classic' or a root (see VIVO_CLASSIC_FOLDERS / VIVO_ROOT_LAYOUT)."""
    root = normalize_vivo_root(vivo_root)
    if root == VIVO_CLASSIC:
        return dict(VIVO_CLASSIC_FOLDERS)
    return {role: f"{root}/{sub}" for role, sub in VIVO_ROOT_LAYOUT.items()}


def vivo_roots(vivo_root=None) -> list[str]:
    """Every folder that belongs to Vivo: the historical ones plus the configured root."""
    root = normalize_vivo_root(vivo_root)
    return list(VIVO_ROOTS) + ([root] if root != VIVO_CLASSIC else [])


def validate_vivo_root(root, claro_root=None) -> str | None:
    """Error message when the Vivo root cannot be used safely ('classic' is always valid)."""
    root = normalize_vivo_root(root)
    if root == VIVO_CLASSIC:
        return None
    if is_drive_root(root):
        return f"The Vivo root folder cannot be a drive root ({root}). Use a folder such as {DEFAULT_VIVO_ROOT}."
    for claro in claro_roots(claro_root):
        if is_under(root, claro) or is_under(claro, root):
            return f"The Vivo root folder {root} overlaps the Claro folder {claro}. Choose a separate folder."
    return None


def validate_claro_root(root, vivo_root=None) -> str | None:
    """Error message when the Claro root cannot be used safely."""
    if not str(root or "").strip():
        return "The Claro root folder is empty."
    if is_drive_root(root):
        return f"The Claro root folder cannot be a drive root ({root}). Use a folder such as {DEFAULT_CLARO_ROOT}."
    for vivo in vivo_roots(vivo_root):
        if is_under(root, vivo) or is_under(vivo, root):
            return f"The Claro root folder {root} overlaps the Vivo folder {vivo}. Choose a separate folder."
    return None


def claro_roots(claro_root) -> list[str]:
    return [claro_root or DEFAULT_CLARO_ROOT, *CLARO_FIXED_ROOTS]


def foreign_roots(operator: str, claro_root, vivo_root=None) -> list[str]:
    """Folders the given operator must never read or write."""
    if operator == CLARO:
        return vivo_roots(vivo_root)
    return claro_roots(claro_root)


def collect_paths(payload, prefix="") -> list[tuple[str, str]]:
    """(field, path) for every path-like field in a JSON payload, nested included."""
    found = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            name = f"{prefix}{key}"
            if isinstance(value, (dict, list)) and key not in PATH_LIST_KEYS:
                found.extend(collect_paths(value, name + "."))
            elif key in PATH_LIST_KEYS and isinstance(value, list):
                found.extend((name, str(v)) for v in value if isinstance(v, str) and v.strip())
            elif isinstance(value, str) and value.strip() and str(key).lower().endswith(PATH_KEY_SUFFIXES):
                found.append((name, value))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found.extend(collect_paths(value, f"{prefix}{index}."))
    return found


def _dump_dir(endpoint: str, payload) -> str | None:
    if not isinstance(payload, dict):
        return None
    if endpoint == "/api/run-dump":
        return payload.get("output_dir")
    dump = payload.get("dump_config")
    return dump.get("output_dir") if isinstance(dump, dict) else None


def check_request(operator: str, endpoint: str, payload, claro_root=None, vivo_root=None) -> str | None:
    """Plain-language error when the request must not run; None when it is allowed."""
    label = "Claro" if operator == CLARO else "Vivo"
    if operator != CLARO and endpoint in CLARO_ONLY_ENDPOINTS:
        return f"Only available for Claro: {CLARO_ONLY_ENDPOINTS[endpoint]}. Switch to CLARO."
    if operator == CLARO:
        reason = VIVO_ONLY_ENDPOINTS.get(endpoint)
        if reason:
            return f"Not available for Claro yet: {reason}. Switch to VIVO or wait for the Claro version."
        if endpoint == "/api/run-parser-pipeline" and isinstance(payload, dict) and payload.get("customize_txts"):
            # Claro "Process MOs" rewrites ENodeBFunction.txt, EUtranCellFDD.txt... with the same
            # names: in the parsed TXT folder it would replace the parser output.
            txt_dir = payload.get("output_dir") or payload.get("input_dir") or ""
            processed = payload.get("enriched_dir") or txt_dir
            if _norm(processed) == _norm(txt_dir):
                return (f"The processed MOs folder must be different from the parsed TXT folder ({txt_dir}). "
                        f"Use e.g. {str(claro_root or '').strip() or DEFAULT_CLARO_ROOT}/MOs.")
    root = str(claro_root or "").strip() or DEFAULT_CLARO_ROOT
    vroot = normalize_vivo_root(vivo_root)
    error = validate_claro_root(root, vroot) or validate_vivo_root(vroot, root)
    if error:
        return error
    forbidden = foreign_roots(operator, root, vroot)
    for field, path in collect_paths(payload):
        for blocked in forbidden:
            if is_under(path, blocked):
                other = "Vivo" if operator == CLARO else "Claro"
                return (f"{label} cannot use {path} ({field}): it belongs to the {other} folders ({blocked}). "
                        f"Choose a {label} folder.")
    dump_dir = _dump_dir(endpoint, payload)
    if dump_dir:
        # The dump step erases everything inside its output folder first.
        if is_drive_root(dump_dir):
            return f"The dump folder cannot be a drive root ({dump_dir}): the dump erases its contents first."
        if operator == CLARO and is_under(root, dump_dir):
            return (f"The dump folder {dump_dir} would erase the Claro root folder {root} before downloading. "
                    f"Use a subfolder, e.g. {root}/Dumps.")
        if operator == VIVO and vroot != VIVO_CLASSIC and is_under(vroot, dump_dir):
            return (f"The dump folder {dump_dir} would erase the Vivo root folder {vroot} before downloading. "
                    f"Use a subfolder, e.g. {vivo_folders(vroot)['raw']}.")
    return None


def claro_geography() -> dict:
    """Regions and municipalities of Claro Puerto Rico (copy of the Portal RAN PR file)."""
    with open(_GEOGRAPHY, encoding="utf-8") as handle:
        data = json.load(handle)
    regions = {r["id"]: r.get("label_en") or r.get("label") or r["id"] for r in data.get("regions", [])}
    municipalities = [
        {"code": m["code"], "name": m.get("name") or m["code"], "region": regions.get(m.get("region_id"), "Unmapped")}
        for m in data.get("municipalities", [])
    ]
    return {"regions": list(regions.values()), "municipalities": sorted(municipalities, key=lambda m: m["code"])}
