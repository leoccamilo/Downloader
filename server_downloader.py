#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Small server for the Downloader web-tool.
- Serves the web-tool (index.html, app.js, etc.) at http://localhost:8765
- POST /api/run-dump: receives JSON config, runs dump_multiple_enms.py and streams output

Run from the folder that contains dump_multiple_enms.py and web-tool/:
  python server_downloader.py

Then open http://localhost:8765 and use "Execute Dump" to see logs in the page.
"""

import json
import os
import io
import csv
import re
import unicodedata
import subprocess
import sys
import tempfile
import shutil
import threading

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

try:
    from flask import Flask, request, send_from_directory, Response, jsonify
except ImportError:
    print("Install Flask: pip install flask")
    sys.exit(1)

# Resolve runtime base directory for source, standalone and onefile modes.
# In onefile mode, data files are extracted to a temp folder where __file__ lives.
if getattr(sys, "frozen", False):
    module_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else ""
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    if module_dir and os.path.isdir(os.path.join(module_dir, "web-tool")):
        SCRIPT_DIR = module_dir
    else:
        SCRIPT_DIR = exe_dir
else:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_TOOL_DIR = os.path.join(SCRIPT_DIR, "web-tool")
DUMP_SCRIPT = os.path.join(SCRIPT_DIR, "dump_multiple_enms.py")
XML_TO_TXT_SCRIPT = os.path.join(SCRIPT_DIR, "xml_to_txt.py")
POST_PROCESS_4_SCRIPT = os.path.join(SCRIPT_DIR, "post_process_4_camilo.py")
POST_PROCESS_5_SCRIPT = os.path.join(SCRIPT_DIR, "post_process_5_tdd.py")
POST_PROCESS_6_SCRIPT = os.path.join(SCRIPT_DIR, "post_process_6_5g.py")
WEEKLY_WORKFLOW_SCRIPT = os.path.join(SCRIPT_DIR, "weekly_workflow.py")
_workflow_lock = threading.Lock()
# Default cellref path when using Downloader at C:\Downloader (e.g. portable)
CELLREF_DEFAULT_PATH = "C:\\Downloader\\cellref"


def get_python_for_dump():
    """Use bundled python_embed, venv's Python, or sys.executable for running dump/parser scripts."""
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    if sys.platform == "win32":
        candidates = [
            os.path.join(SCRIPT_DIR, "python_embed", "python.exe"),
            os.path.join(SCRIPT_DIR, "venv", "Scripts", "python.exe"),
            # When exe is in dist_nuitka/, check venv one level up (C:\Downloader\venv)
            os.path.normpath(os.path.join(exe_dir, "..", "venv", "Scripts", "python.exe")),
            os.path.join(exe_dir, "venv", "Scripts", "python.exe"),
        ]
    else:
        candidates = [
            os.path.join(SCRIPT_DIR, "python_embed", "bin", "python3"),
            os.path.join(SCRIPT_DIR, "venv", "bin", "python"),
            os.path.normpath(os.path.join(exe_dir, "..", "venv", "bin", "python")),
            os.path.join(exe_dir, "venv", "bin", "python"),
        ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    if getattr(sys, "frozen", False):
        system_python = shutil.which("python") or shutil.which("py")
        if system_python:
            return system_python
    return sys.executable


# Disable Flask's automatic static route (/<path:filename>) because it can
# interfere with API POST routes when static_url_path is root-like.
app = Flask(__name__, static_folder=None)


def _build_direct_network_env():
    """Return env without proxy variables for ENM direct access."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
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
        env.pop(key, None)
    return env


def _detect_delimiter(sample_text):
    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(sample_text, delimiters=[",", ";", "\t", "|"])
        return dialect.delimiter
    except csv.Error:
        for delim in [",", ";", "\t", "|"]:
            if delim in sample_text:
                return delim
    return ","


def _read_uploaded_table(file_storage):
    filename = os.path.basename(file_storage.filename or "")
    ext = os.path.splitext(filename)[1].lower()
    content = file_storage.read()
    file_storage.stream.seek(0)

    try:
        import pandas as pd
    except ImportError as e:
        raise RuntimeError(f"pandas is required: {e}")

    if ext in (".csv", ".txt"):
        decoded = None
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                decoded = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if decoded is None:
            decoded = content.decode("latin-1", errors="replace")
        sample = "\n".join(decoded.splitlines()[:5])
        delim = _detect_delimiter(sample)
        df = pd.read_csv(io.StringIO(decoded), sep=delim, dtype=str, keep_default_na=False)
    elif ext in (".xlsx", ".xls"):
        df = pd.read_excel(io.BytesIO(content), dtype=str)
        df = df.fillna("")
    else:
        raise ValueError(f"Unsupported file extension: {ext}")

    df.columns = [(c or "").strip() for c in df.columns]
    return df


def _pick_col(columns_map, options):
    for opt in options:
        if opt in columns_map:
            return columns_map[opt]
    return None


def _normalize_col_name(name):
    """Normalize column name for robust alias matching."""
    txt = str(name or "").strip().lower()
    txt = unicodedata.normalize("NFKD", txt)
    txt = "".join(ch for ch in txt if not unicodedata.combining(ch))
    txt = re.sub(r"[^a-z0-9]+", "", txt)
    return txt


def _read_disk_table(path):
    """Read an xlsx/csv/txt file from disk path and return a DataFrame."""
    try:
        import pandas as pd
    except ImportError as e:
        raise RuntimeError(f"pandas is required: {e}")

    ext = os.path.splitext(path)[1].lower()
    if ext in (".xlsx", ".xls"):
        df = pd.read_excel(path, dtype=str)
        df = df.fillna("")
    elif ext in (".csv", ".txt"):
        with open(path, "rb") as f:
            content = f.read()
        decoded = None
        for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
            try:
                decoded = content.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if decoded is None:
            decoded = content.decode("latin-1", errors="replace")
        sample = "\n".join(decoded.splitlines()[:5])
        delim = _detect_delimiter(sample)
        df = pd.read_csv(io.StringIO(decoded), sep=delim, dtype=str, keep_default_na=False)
    else:
        raise ValueError(f"Unsupported file extension: {ext}")
    df.columns = [(c or "").strip() for c in df.columns]
    return df


def _extract_site_rows(df, filename, rows_out, seen):
    """
    Extract site rows from a DataFrame into rows_out (list of dicts).
    seen is a set used for deduplication (mutated in place).
    Returns (added_count, warning_or_None).
    """
    cols_map = {_normalize_col_name(c): c for c in df.columns}
    regional_col = _pick_col(cols_map, ["regional", "regiao", "region", "regionalname", "area", "macroregiao"])
    cn_col = _pick_col(cols_map, ["cn", "ddd", "market", "mercado"])
    uf_col = _pick_col(cols_map, ["uf", "estado", "state", "siglauf"])
    municipio_col = _pick_col(cols_map, ["municipio", "municpio", "cidade", "city", "municipality", "mun", "cluster"])
    enb_col = _pick_col(cols_map, ["enb", "enodeb", "enodebid", "idenb", "enodebname", "siteenb"])
    site_col = _pick_col(cols_map, ["siteid", "site", "sitecode", "sitecodeid", "site_name", "siteidnr",
                                    "siteid5g", "siteidnr5g", "nrsiteid", "gnbsiteid", "gnb"])

    if not (uf_col and municipio_col and (enb_col or site_col)):
        return 0, f"{filename}: missing required columns (UF, MUNICIPIO, and eNB or SiteID)."

    cell_col = _pick_col(cols_map, ["cell", "cellname", "nrcellcuid", "nrcellduid", "nrcellid",
                                    "eutrancell", "eutrancellfdd", "eutrancelltdd"])
    tipo_col = _pick_col(cols_map, ["tipo", "type", "rat", "technology", "tech"])
    tech_col = _pick_col(cols_map, ["tech", "technology", "rat"])
    gnbid_col = _pick_col(cols_map, ["gnbid", "gnb_id"])
    nrcell_col = _pick_col(cols_map, ["nrcellcuid", "nrcellduid", "nrcellid"])
    nrfreq_col = _pick_col(cols_map, ["nrfrequency", "ssbfrequency"])
    nrpci_col = _pick_col(cols_map, ["nrpci"])

    id_col = enb_col or site_col
    tech_cols = {
        "tech": tech_col, "cell": cell_col, "tipo": tipo_col, "site": id_col,
        "gnbid": gnbid_col, "nrcell": nrcell_col, "nrfrequency": nrfreq_col,
        "nrpci": nrpci_col, "ssbfrequency": nrfreq_col,
    }

    added = 0
    for _, rec in df.iterrows():
        regional = str(rec.get(regional_col, "")).strip() if regional_col else ""
        if not regional and cn_col:
            regional = str(rec.get(cn_col, "")).strip()
        uf = str(rec.get(uf_col, "")).strip().upper()
        municipio = str(rec.get(municipio_col, "")).strip()
        site_id = str(rec.get(id_col, "")).strip()
        if not site_id:
            continue
        tech = _infer_tech_from_row(rec, filename, tech_cols)
        key = (regional, uf, municipio, site_id, tech)
        if key in seen:
            continue
        seen.add(key)
        rows_out.append({"Regional": regional, "UF": uf, "MUNICIPIO": municipio, "SiteID": site_id, "Tech": tech})
        added += 1
    return added, None


def _save_site_list_txt(path, rows):
    """Write rows to a TSV sites_list.txt (UTF-8 with BOM)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        f.write("Regional\tUF\tMUNICIPIO\tSiteID\tTech\n")
        for r in rows:
            regional = str(r.get("Regional", "")).strip()
            uf = str(r.get("UF", "")).strip().upper()
            municipio = str(r.get("MUNICIPIO", "")).strip()
            site_id = str(r.get("SiteID", "")).strip()
            tech = str(r.get("Tech", "LTE")).strip().upper() or "LTE"
            f.write("\t".join([regional, uf, municipio, site_id, tech]) + "\n")


def _auto_build_site_list_from_dir(base_dir, references_only=False):
    """
    Scan base_dir for xlsx/csv files, build and return site rows.
    Returns (rows, sources, warnings).
    """
    table_exts = {".xlsx", ".xls", ".csv"}
    try:
        candidates = [
            os.path.join(base_dir, fn)
            for fn in os.listdir(base_dir)
            if os.path.splitext(fn)[1].lower() in table_exts
            and (not references_only or fn.lower() in {"cellref.xlsx", "cellref_5g.xlsx"})
        ]
    except OSError:
        return [], [], [f"Cannot list directory: {base_dir}"]

    rows, seen, sources, warnings = [], set(), [], []
    for fpath in sorted(candidates):
        fname = os.path.basename(fpath)
        try:
            df = _read_disk_table(fpath)
        except Exception as e:
            warnings.append(f"{fname}: skipped ({e})")
            continue
        added, warn = _extract_site_rows(df, fname, rows, seen)
        if warn:
            warnings.append(warn)
        else:
            sources.append(f"{fname}: {added} site(s)")
    return rows, sources, warnings


def _infer_tech_from_row(rec, filename, cols):
    """
    Infer LTE/NR using Vivo-oriented rules.
    Priority:
    1) explicit tech column, 2) cell id patterns, 3) NR-specific columns,
    4) LTE type hints, 5) site prefix (T/S), 6) filename hint, fallback LTE.
    """
    def _val(col):
        if not col:
            return ""
        return str(rec.get(col, "")).strip()

    tech_txt = _val(cols.get("tech")).upper()
    if tech_txt:
        if "NR" in tech_txt or "5G" in tech_txt:
            return "NR"
        if "LTE" in tech_txt or "4G" in tech_txt:
            return "LTE"

    cell_txt = _val(cols.get("cell")).upper()
    if cell_txt:
        # NR cell naming in Vivo rules (5S/5O; may appear as any 5* in practice)
        if cell_txt.startswith("5"):
            return "NR"
        # LTE cell prefixes (examples from rules)
        if cell_txt[:1] in {"T", "U", "V", "Z", "O"}:
            return "LTE"

    # Presence of NR-specific identifiers with values in the row
    for key in ("nrcell", "gnbid", "nrfrequency", "nrpci", "ssbfrequency"):
        if _val(cols.get(key)):
            return "NR"

    tipo_txt = _val(cols.get("tipo")).upper()
    if tipo_txt and any(x in tipo_txt for x in ("FDD", "TDD", "LTE", "4G")):
        return "LTE"

    site_txt = _val(cols.get("site")).upper()
    # Vivo site prefix rule: T => LTE, S => NR, M => ambiguous
    if site_txt.startswith("T"):
        return "LTE"
    if site_txt.startswith("S"):
        return "NR"

    f = (filename or "").lower()
    if "5g" in f or "nr" in f:
        return "NR"
    if "4g" in f or "lte" in f or "eutran" in f:
        return "LTE"
    return "LTE"


@app.after_request
def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


@app.route("/")
def index():
    return send_from_directory(WEB_TOOL_DIR, "index.html")


@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory(WEB_TOOL_DIR, path)


def stream_run_dump(config):
    """Run dump_multiple_enms.py with config and yield stdout/stderr line by line."""
    import traceback as _tb
    try:
        fd, path = tempfile.mkstemp(suffix=".json", prefix="downloader_config_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            if not os.path.isfile(DUMP_SCRIPT):
                yield f"Error: dump_multiple_enms.py not found.\n  SCRIPT_DIR: {SCRIPT_DIR}\n  DUMP_SCRIPT: {DUMP_SCRIPT}\n"
                return
            python_exe = get_python_for_dump()
            yield from _stream_checked_script(python_exe, DUMP_SCRIPT, [path])
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
    except Exception as _exc:
        yield f"[dump error] {type(_exc).__name__}: {_exc}\n"
        yield f"  python_exe: {get_python_for_dump()}\n"
        yield f"  SCRIPT_DIR: {SCRIPT_DIR}\n"
        yield f"  DUMP_SCRIPT: {DUMP_SCRIPT}\n"
        yield _tb.format_exc() + "\n"


@app.route("/api/run-dump", methods=["POST", "OPTIONS"])
def api_run_dump():
    if request.method == "OPTIONS":
        return "", 204
    config = request.get_json(force=True, silent=True)
    if not config:
        return Response("Invalid JSON body\n", status=400, mimetype="text/plain")
    return _workflow_response(stream_run_dump(config))


@app.route("/api/update-site-list", methods=["POST", "OPTIONS"])
def api_update_site_list():
    if request.method == "OPTIONS":
        return "", 204

    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "error": "No files uploaded."}), 400

    rows, seen, sources, warnings = [], set(), [], []
    for f in files:
        filename = os.path.basename(f.filename or "")
        if not filename:
            continue
        try:
            df = _read_uploaded_table(f)
        except Exception as e:
            warnings.append(f"{filename}: skipped ({e})")
            continue
        added, warn = _extract_site_rows(df, filename, rows, seen)
        if warn:
            warnings.append(warn)
        else:
            sources.append(f"{filename}: {added} site(s)")

    return jsonify({"ok": True, "rows": rows, "count": len(rows), "sources": sources, "warnings": warnings})

@app.route("/api/save-site-list", methods=["POST", "OPTIONS"])
def api_save_site_list():
    if request.method == "OPTIONS":
        return "", 204

    data = request.get_json(force=True, silent=True) or {}
    rows = data.get("rows")
    save_dir = (data.get("save_dir") or "").strip().replace("/", os.sep)
    if not isinstance(rows, list):
        return jsonify({"ok": False, "error": "rows must be a list."}), 400
    if not save_dir:
        return jsonify({"ok": False, "error": "save_dir is required."}), 400

    try:
        os.makedirs(save_dir, exist_ok=True)
    except OSError as e:
        return jsonify({"ok": False, "error": f"Could not create directory: {e}"}), 400

    out_path = os.path.join(save_dir, "sites_list.txt")
    try:
        with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
            f.write("Regional\tUF\tMUNICIPIO\tSiteID\tTech\n")
            for r in rows:
                if not isinstance(r, dict):
                    continue
                regional = str(r.get("Regional", "")).strip()
                uf = str(r.get("UF", "")).strip().upper()
                municipio = str(r.get("MUNICIPIO", "")).strip()
                site_id = str(r.get("SiteID", "")).strip()
                tech = str(r.get("Tech", "")).strip()
                f.write("\t".join([regional, uf, municipio, site_id, tech]) + "\n")
    except OSError as e:
        return jsonify({"ok": False, "error": f"Could not write sites_list.txt: {e}"}), 400

    return jsonify({"ok": True, "path": out_path, "count": len(rows)})


def _read_site_list_txt(path):
    """Read a TSV sites_list.txt and return list of row dicts."""
    rows = []
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        lines = [ln.rstrip("\n\r") for ln in f if ln.strip()]
    if len(lines) < 2:
        return rows
    header = [h.strip() for h in lines[0].split("\t")]
    idx = {h: i for i, h in enumerate(header)}
    for ln in lines[1:]:
        cells = ln.split("\t")
        def cell(name, _cells=cells, _idx=idx):
            i = _idx.get(name)
            return _cells[i].strip() if i is not None and i < len(_cells) else ""
        rows.append({
            "Regional": cell("Regional"),
            "UF": cell("UF").upper(),
            "MUNICIPIO": cell("MUNICIPIO"),
            "SiteID": cell("SiteID"),
            "Tech": cell("Tech").upper() or "LTE",
        })
    return rows


@app.route("/api/load-site-list", methods=["POST", "OPTIONS"])
def api_load_site_list():
    if request.method == "OPTIONS":
        return "", 204

    data = request.get_json(force=True, silent=True) or {}
    base_dir = (data.get("base_dir") or "").strip().replace("/", os.sep)
    if not base_dir:
        return jsonify({"ok": False, "error": "base_dir is required."}), 400

    path = os.path.join(base_dir, "sites_list.txt")
    refresh_references = data.get("refresh_from_references") is True

    # Try reading existing sites_list.txt
    rows = []
    if os.path.isfile(path) and not refresh_references:
        try:
            rows = _read_site_list_txt(path)
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 500

    # If no real data found, try auto-building from xlsx/csv files in the same dir
    if len(rows) < 5 or refresh_references:
        try:
            official_refs = any(os.path.isfile(os.path.join(base_dir, name)) for name in ("cellref.xlsx", "cellref_5g.xlsx"))
            built_rows, sources, warnings = _auto_build_site_list_from_dir(base_dir, references_only=refresh_references or official_refs)
        except Exception:
            built_rows = []
        if built_rows:
            try:
                _save_site_list_txt(path, built_rows)
            except OSError:
                pass
            return jsonify({
                "ok": True,
                "path": path,
                "rows": built_rows,
                "count": len(built_rows),
                "auto_built": True,
                "sources": sources,
                "warnings": warnings,
            })
        # No Excel files found either → return 404
        if not rows:
            return jsonify({"ok": False, "error": f"sites_list.txt not found in {base_dir}"}), 404

    return jsonify({"ok": True, "path": path, "rows": rows, "count": len(rows)})


def _stream_run_script(python_exe, script_path, args_list):
    """Run a Python script with args; yield stdout line by line."""
    code = yield from _stream_checked_script(python_exe, script_path, args_list[1:])
    if code:
        raise RuntimeError(f"{os.path.basename(script_path)} exited with code {code}")


def _stream_checked_script(python_exe, script_path, args):
    """Stream logs and return the exit code; terminate children on disconnect."""
    if not os.path.isfile(script_path):
        yield f"Error: {os.path.basename(script_path)} not found.\n"
        return 1
    proc = subprocess.Popen(
        [python_exe, "-u", script_path] + args,
        cwd=SCRIPT_DIR,
        env=_build_direct_network_env(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=_NO_WINDOW,
    )
    try:
        processing_error = False
        for line in proc.stdout:
            if script_path in (XML_TO_TXT_SCRIPT, POST_PROCESS_4_SCRIPT, POST_PROCESS_5_SCRIPT, POST_PROCESS_6_SCRIPT):
                if re.search(r"(?:^\s*ERROR\b|:\s*(?:ERROR|FAILED)\b)", line, re.I):
                    processing_error = True
            yield line if line.endswith("\n") else line + "\n"
        proc.wait()
        if proc.returncode:
            yield f"\nProcess exited with code {proc.returncode}\n"
        if processing_error and not proc.returncode:
            yield "\nERROR: Script reported a processing failure.\n"
            return 1
        return proc.returncode
    finally:
        if proc.poll() is None:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True, creationflags=_NO_WINDOW)
            else:
                proc.terminate()
            proc.wait()
        proc.stdout.close()


def stream_weekly_workflow(data):
    """Preflight, optional ENM extraction, then notebooks 2 through 6."""
    path = None
    try:
        fd, path = tempfile.mkstemp(suffix=".json", prefix="weekly_workflow_")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            # Never write ENM passwords into retained workflow manifests.
            json.dump({key: value for key, value in data.items() if key != "dump_config"}, handle)
        python_exe = get_python_for_dump()
        yield "STEP 0/6: Checking notebooks, references and dependencies...\n"
        check_lines, code = _run_step(python_exe, WEEKLY_WORKFLOW_SCRIPT, [path, "--check"])
        for line in check_lines:
            yield line
        if code:
            raise RuntimeError("Preflight failed. ENM dump was not started.")
        dump_config = data.get("dump_config")
        if dump_config:
            dump_config = dict(dump_config)
            required_line = next(line for line in check_lines if line.startswith("REQUIRED_MOS="))
            required = json.loads(required_line.split("=", 1)[1])
            selected = dump_config.get("selected_mos") or []
            dump_config["selected_mos"] = list(dict.fromkeys(selected + required))
            yield f"\nSTEP 1/6: ENM dump ({len(dump_config['selected_mos'])} MOs, including notebook lookups)...\n"
            fd, dump_path = tempfile.mkstemp(suffix=".json", prefix="weekly_dump_")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(dump_config, handle)
                code = yield from _stream_checked_script(python_exe, DUMP_SCRIPT, [dump_path])
                if code:
                    raise RuntimeError("ENM dump failed. Notebook processing was not started.")
            finally:
                os.unlink(dump_path)
        code = yield from _stream_checked_script(python_exe, WEEKLY_WORKFLOW_SCRIPT, [path])
        if code:
            raise RuntimeError("Notebook processing failed. Check the cell and manifest above.")
    except Exception as exc:
        yield f"\nERROR: {exc}\nPIPELINE FAILED.\n"
    finally:
        if path and os.path.exists(path):
            os.unlink(path)


def _workflow_response(iterator):
    if not _workflow_lock.acquire(blocking=False):
        return Response("Another workflow is already running.\n", status=409, mimetype="text/plain")

    released = False
    release_guard = threading.Lock()

    def release_once():
        nonlocal released
        with release_guard:
            if not released:
                released = True
                _workflow_lock.release()

    def stream():
        try:
            yield from iterator
        except Exception as exc:
            yield f"\nERROR: {exc}\nPIPELINE FAILED.\n"
        finally:
            release_once()

    response = Response(stream(), mimetype="text/plain", headers={"X-Content-Type-Options": "nosniff"})
    response.call_on_close(release_once)
    return response


@app.route("/api/run-weekly-workflow", methods=["POST", "OPTIONS"])
def api_run_weekly_workflow():
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(force=True, silent=True) or {}
    dump_config = data.get("dump_config")
    if dump_config:
        if not isinstance(dump_config, dict) or not dump_config.get("output_dir"):
            return Response("dump_config.output_dir required\n", status=400)
        data["input_dir"] = dump_config["output_dir"]
        data["dump_output_dir"] = dump_config["output_dir"]
        data.pop("input_files", None)
    if not data.get("input_dir") and not data.get("input_files"):
        return Response("input_dir or input_files required\n", status=400)
    for key in ("create_weekly", "transfer_vivo"):
        if key in data and not isinstance(data[key], bool):
            return Response(f"{key} must be a boolean\n", status=400)
    return _workflow_response(stream_weekly_workflow(data))


@app.route("/api/run-cellref", methods=["POST", "OPTIONS"])
def api_run_cellref():
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(force=True, silent=True) or {}
    if not all(str(data.get(key) or "").strip() for key in ("reference_dir", "output_dir", "enriched_dir")):
        return Response("reference_dir, output_dir and enriched_dir required\n", status=400)

    def stream():
        fd, path = tempfile.mkstemp(suffix=".json", prefix="cellref_config_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle)
            code = yield from _stream_checked_script(get_python_for_dump(), WEEKLY_WORKFLOW_SCRIPT, [path, "--cellref-only"])
            if code:
                yield "\nPIPELINE FAILED.\n"
        finally:
            os.unlink(path)

    return _workflow_response(stream())


@app.route("/api/run-post-process-4", methods=["POST", "OPTIONS"])
def api_run_post_process_4():
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(force=True, silent=True) or {}
    input_dir = (data.get("input_txt_dir") or "").strip().replace("/", os.sep)
    cellref_dir = (data.get("cellref_dir") or CELLREF_DEFAULT_PATH).strip().replace("/", os.sep)
    output_dir = (data.get("output_dir") or input_dir).strip().replace("/", os.sep)
    if not input_dir:
        return Response("input_txt_dir required\n", status=400, mimetype="text/plain")
    python_exe = get_python_for_dump()
    args_list = [POST_PROCESS_4_SCRIPT, input_dir, cellref_dir, output_dir]
    return _workflow_response(_stream_run_script(python_exe, POST_PROCESS_4_SCRIPT, args_list))


@app.route("/api/run-post-process-5", methods=["POST", "OPTIONS"])
def api_run_post_process_5():
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(force=True, silent=True) or {}
    input_dir = (data.get("input_txt_dir") or "").strip().replace("/", os.sep)
    output_dir = (data.get("output_dir") or input_dir).strip().replace("/", os.sep)
    if not input_dir:
        return Response("input_txt_dir required\n", status=400, mimetype="text/plain")
    python_exe = get_python_for_dump()
    args_list = [POST_PROCESS_5_SCRIPT, input_dir, output_dir]
    return _workflow_response(_stream_run_script(python_exe, POST_PROCESS_5_SCRIPT, args_list))


@app.route("/api/run-post-process-6", methods=["POST", "OPTIONS"])
def api_run_post_process_6():
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(force=True, silent=True) or {}
    input_dir = (data.get("input_txt_dir") or "").strip().replace("/", os.sep)
    output_dir = (data.get("output_dir") or input_dir).strip().replace("/", os.sep)
    if not input_dir:
        return Response("input_txt_dir required\n", status=400, mimetype="text/plain")
    python_exe = get_python_for_dump()
    args_list = [POST_PROCESS_6_SCRIPT, input_dir, output_dir]
    return _workflow_response(_stream_run_script(python_exe, POST_PROCESS_6_SCRIPT, args_list))


def _run_step(python_exe, script, args):
    """Run a script as subprocess and return (output_lines, return_code)."""
    if not os.path.isfile(script):
        return [f"Error: {os.path.basename(script)} not found.\n"], 1
    proc = subprocess.Popen(
        [python_exe, script] + args,
        cwd=SCRIPT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=_NO_WINDOW,
    )
    lines = []
    for line in proc.stdout:
        lines.append(line if line.endswith("\n") else line + "\n")
    proc.wait()
    return lines, proc.returncode or 0


def stream_parser_pipeline(input_dir, output_dir, customize_txts, cellref_dir, enriched_dir, input_files=None):
    """Pipeline: ZIP/XML -> one TXT per MO -> (optional) enrich 4/5/6.

    Input is either a list of files (.zip/.xml/.xml.gz) or a folder containing them.
    ZIPs are read in place by xml_to_txt.py — no extraction step.
    """
    python_exe = get_python_for_dump()
    txt_dir = output_dir or input_dir
    enr_dir = enriched_dir or txt_dir
    total_steps = 4 if customize_txts else 1

    if input_files:
        yield f"Input:    {len(input_files)} file(s)\n"
        for f in input_files:
            yield f"          {f}\n"
    else:
        yield f"Input:    {input_dir}\n"
    yield f"Output:   {txt_dir}\n"
    if customize_txts:
        yield f"Enriched: {enr_dir}\n"
    yield "\n"

    yield "=" * 50 + "\n"
    yield f"STEP 1/{total_steps}: Parsing ZIP/XML to TXT...\n"
    yield "=" * 50 + "\n"
    list_path = None
    if input_files:
        fd, list_path = tempfile.mkstemp(prefix="parser_inputs_", suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(input_files))
        args = [XML_TO_TXT_SCRIPT, "--file-list", list_path, "--out", txt_dir]
    else:
        args = [XML_TO_TXT_SCRIPT, input_dir, txt_dir]
    try:
        for line in _stream_run_script(python_exe, XML_TO_TXT_SCRIPT, args):
            yield line
    finally:
        if list_path:
            try:
                os.unlink(list_path)
            except OSError:
                pass

    # Optional: Enrich files
    if customize_txts:
        cellref = cellref_dir or CELLREF_DEFAULT_PATH

        yield "\n" + "=" * 50 + "\n"
        yield f"STEP 2/{total_steps}: Enrich Files (LTE FDD + ENodeBFunction)...\n"
        yield "=" * 50 + "\n"
        for line in _stream_run_script(python_exe, POST_PROCESS_4_SCRIPT, [POST_PROCESS_4_SCRIPT, txt_dir, cellref, enr_dir]):
            yield line

        yield "\n" + "=" * 50 + "\n"
        yield f"STEP 3/{total_steps}: Enrich Files (TDD + FDD combined)...\n"
        yield "=" * 50 + "\n"
        for line in _stream_run_script(python_exe, POST_PROCESS_5_SCRIPT, [POST_PROCESS_5_SCRIPT, txt_dir, enr_dir]):
            yield line

        yield "\n" + "=" * 50 + "\n"
        yield f"STEP 4/{total_steps}: Enrich Files (5G NR)...\n"
        yield "=" * 50 + "\n"
        for line in _stream_run_script(python_exe, POST_PROCESS_6_SCRIPT, [POST_PROCESS_6_SCRIPT, txt_dir, enr_dir]):
            yield line

    yield "\n" + "=" * 50 + "\n"
    yield "PIPELINE COMPLETED.\n"
    yield "=" * 50 + "\n"


@app.route("/api/save-file-viewer-export", methods=["POST", "OPTIONS"])
def api_save_file_viewer_export():
    """Save File Viewer export (CSV/TXT/XLSX) to a folder on disk."""
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(force=True, silent=True) or {}
    output_dir = (data.get("output_dir") or "").strip().replace("/", os.sep)
    filename = (data.get("filename") or "export.csv").strip()
    content_b64 = data.get("content_base64")
    if not output_dir or not filename or content_b64 is None:
        return {"ok": False, "error": "output_dir, filename and content_base64 required"}, 400
    # Security: ensure filename has no path segments
    if ".." in filename or os.sep in filename or "/" in filename:
        return {"ok": False, "error": "Invalid filename"}, 400
    try:
        import base64
        content = base64.b64decode(content_b64)
    except Exception as e:
        return {"ok": False, "error": f"Invalid base64: {e}"}, 400
    try:
        os.makedirs(output_dir, exist_ok=True)
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "wb") as f:
            f.write(content)
        return {"ok": True, "path": filepath}
    except OSError as e:
        return {"ok": False, "error": str(e)}, 500
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500


@app.route("/api/run-parser-pipeline", methods=["POST", "OPTIONS"])
def api_run_parser_pipeline():
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(force=True, silent=True) or {}
    input_dir = (data.get("input_dir") or "").strip().replace("/", os.sep)
    raw_files = data.get("input_files") or []
    if not isinstance(raw_files, list):
        raw_files = []
    input_files = [str(f).strip().replace("/", os.sep) for f in raw_files if str(f).strip()]
    output_dir = (data.get("output_dir") or "").strip().replace("/", os.sep) or input_dir
    customize_txts = bool(data.get("customize_txts", False))
    cellref_dir = (data.get("cellref_dir") or CELLREF_DEFAULT_PATH).strip().replace("/", os.sep)
    enriched_dir = (data.get("enriched_dir") or "").strip().replace("/", os.sep) or output_dir
    if not input_dir and not input_files:
        return Response("input_dir or input_files required\n", status=400, mimetype="text/plain")
    if not output_dir:
        return Response("output_dir required\n", status=400, mimetype="text/plain")
    return _workflow_response(
        stream_parser_pipeline(input_dir, output_dir, customize_txts, cellref_dir, enriched_dir, input_files)
    )


@app.route("/api/debug-routes")
def api_debug_routes():
    rules = [{"rule": r.rule, "methods": sorted(r.methods)} for r in app.url_map.iter_rules()]
    return jsonify(sorted(rules, key=lambda x: x["rule"]))


@app.route("/api/export-site-ids", methods=["POST", "OPTIONS"])
def api_export_site_ids():
    """Save a plain-text site ID list (one per line) to the requested file path."""
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(force=True, silent=True) or {}
    file_path = (data.get("file_path") or "").strip().replace("/", os.sep)
    ids = data.get("ids", [])
    if not file_path:
        return jsonify({"ok": False, "error": "file_path is required."}), 400
    if not isinstance(ids, list):
        return jsonify({"ok": False, "error": "ids must be a list."}), 400
    try:
        parent = os.path.dirname(file_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(ids))
        return jsonify({"ok": True, "path": file_path, "count": len(ids)})
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/local/list", methods=["POST", "OPTIONS"])
def api_local_list():
    """List folders and files of a path for the file/folder browser modal.

    Empty path → drive list ("This PC"). With "nearest": true, a missing path
    falls back to its closest existing parent (handy for not-yet-created outputs).
    """
    if request.method == "OPTIONS":
        return "", 204
    import stat as _stat
    import string as _string
    data = request.get_json(silent=True) or {}
    raw = (data.get("path") or "").strip().strip('"').replace("/", os.sep)
    if not raw:
        entries = [
            {"name": f"{d}:", "is_dir": True, "size": 0, "mtime": None, "path": f"{d}:/"}
            for d in _string.ascii_uppercase if os.path.exists(f"{d}:\\")
        ]
        return jsonify({"path": "", "parent": None, "entries": entries})
    if re.fullmatch(r"[A-Za-z]:", raw):
        raw += os.sep
    raw = os.path.abspath(raw)
    if not os.path.isdir(raw) and data.get("nearest"):
        while not os.path.isdir(raw) and os.path.dirname(raw) != raw:
            raw = os.path.dirname(raw)
    if not os.path.isdir(raw):
        return jsonify({"error": f"Folder not found: {raw}"}), 404
    hidden_mask = getattr(_stat, "FILE_ATTRIBUTE_HIDDEN", 0) | getattr(_stat, "FILE_ATTRIBUTE_SYSTEM", 0)
    entries = []
    try:
        with os.scandir(raw) as it:
            for e in it:
                if e.name.startswith((".", "$")):
                    continue
                try:
                    st = e.stat()
                    if getattr(st, "st_file_attributes", 0) & hidden_mask:
                        continue
                    is_dir = e.is_dir()
                except OSError:
                    continue  # broken junctions, locked system files
                entries.append({
                    "name": e.name,
                    "is_dir": is_dir,
                    "size": 0 if is_dir else st.st_size,
                    "mtime": st.st_mtime,
                    "path": e.path.replace("\\", "/"),
                })
    except PermissionError:
        return jsonify({"error": f"Permission denied: {raw}"}), 403
    except OSError as e:
        return jsonify({"error": str(e)}), 500
    entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    parent = os.path.dirname(raw)
    return jsonify({
        "path": raw.replace("\\", "/"),
        # Drive root → parent "" (the drive list)
        "parent": parent.replace("\\", "/") if parent != raw else "",
        "entries": entries,
    })


@app.route("/api/local/places")
def api_local_places():
    """Quick-access shortcuts for the file browser (Explorer-style): Downloader
    data, OneDrive (corporate/personal), Home, Desktop, Documents, Downloads, drives."""
    import string as _string
    places = []
    seen_paths = set()
    seen_labels = set()

    def add(label, path, icon):
        if not path or label in seen_labels:
            return
        p = os.path.normpath(path)
        key = os.path.normcase(p)
        if key in seen_paths or not os.path.isdir(p):
            return
        seen_paths.add(key)
        seen_labels.add(label)
        places.append({"label": label, "path": p.replace("\\", "/"), "icon": icon})

    app_dir = os.path.dirname(os.path.abspath(sys.executable)) if getattr(sys, "frozen", False) else SCRIPT_DIR
    add("Downloader data", os.path.join(app_dir, "data"), "bi-box-seam")
    add("Downloader data", "C:\\Downloader\\data", "bi-box-seam")

    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    onedrive = os.environ.get("OneDrive") or ""
    for var in ("OneDriveCommercial", "OneDrive", "OneDriveConsumer"):
        od = os.environ.get(var)
        if od:
            base = os.path.basename(os.path.normpath(od))
            add(base if base.lower().startswith("onedrive") else "OneDrive", od, "bi-cloud")
    add("Home", home, "bi-house")
    # Desktop/Documents are often redirected into OneDrive
    for label, sub, icon in (("Desktop", "Desktop", "bi-display"), ("Documents", "Documents", "bi-file-earmark-text")):
        if onedrive:
            add(label, os.path.join(onedrive, sub), icon)
        add(label, os.path.join(home, sub), icon)
    add("Downloads", os.path.join(home, "Downloads"), "bi-download")
    for letter in _string.ascii_uppercase:
        drive = f"{letter}:\\"
        if os.path.exists(drive):
            add(f"{letter}:", drive, "bi-hdd")
    return jsonify({"places": places})


_shutdown_timer = None

@app.route("/api/shutdown", methods=["POST", "GET"])
def api_shutdown():
    """Schedule a delayed shutdown. Cancelled if any request arrives within 3s (e.g. page refresh)."""
    import threading
    global _shutdown_timer
    if _shutdown_timer and _shutdown_timer.is_alive():
        _shutdown_timer.cancel()
    def _exit():
        import time
        time.sleep(3)
        os._exit(0)
    _shutdown_timer = threading.Timer(3, os._exit, args=(0,))
    _shutdown_timer.daemon = True
    _shutdown_timer.start()
    return "OK", 200


@app.before_request
def _cancel_shutdown():
    global _shutdown_timer
    if _shutdown_timer and _shutdown_timer.is_alive():
        path = request.path
        if path != "/api/shutdown":
            _shutdown_timer.cancel()
            _shutdown_timer = None


if __name__ == "__main__":
    if not os.path.isdir(WEB_TOOL_DIR):
        print("web-tool directory not found next to server_downloader.py")
        sys.exit(1)
    print("Downloader server: http://localhost:8765")
    print("Use 'Execute Dump' in the tool to run the script and see logs here.")
    app.run(host="127.0.0.1", port=8765, threaded=True)
