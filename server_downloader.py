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
PARQUET_TO_TXT_SCRIPT = os.path.join(SCRIPT_DIR, "parquet_to_txt.py")
XML_TO_PARQUET_SCRIPT = os.path.join(SCRIPT_DIR, "xml_to_parquet.py")
EXTRACT_DUMP_SCRIPT = os.path.join(SCRIPT_DIR, "extract_dump.py")
POST_PROCESS_4_SCRIPT = os.path.join(SCRIPT_DIR, "post_process_4_camilo.py")
POST_PROCESS_5_SCRIPT = os.path.join(SCRIPT_DIR, "post_process_5_tdd.py")
POST_PROCESS_6_SCRIPT = os.path.join(SCRIPT_DIR, "post_process_6_5g.py")
# Default cellref path when using Downloader at C:\Downloader (e.g. portable)
CELLREF_DEFAULT_PATH = "C:\\Downloader\\cellref"


def get_python_for_dump():
    """Use bundled python_embed, venv's Python, or sys.executable for running dump/parser scripts."""
    if sys.platform == "win32":
        embed_python = os.path.join(SCRIPT_DIR, "python_embed", "python.exe")
        venv_python = os.path.join(SCRIPT_DIR, "venv", "Scripts", "python.exe")
    else:
        embed_python = os.path.join(SCRIPT_DIR, "python_embed", "bin", "python3")
        venv_python = os.path.join(SCRIPT_DIR, "venv", "bin", "python")
    if os.path.isfile(embed_python):
        return embed_python
    if os.path.isfile(venv_python):
        return venv_python
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
        for enc in ("utf-8-sig", "utf-8", "latin-1"):
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
    fd, path = tempfile.mkstemp(suffix=".json", prefix="downloader_config_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        if not os.path.isfile(DUMP_SCRIPT):
            yield "Error: dump_multiple_enms.py not found in script directory.\n"
            return
        python_exe = get_python_for_dump()
        proc = subprocess.Popen(
            [python_exe, DUMP_SCRIPT, path],
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
        for line in proc.stdout:
            yield line if line.endswith("\n") else line + "\n"
        proc.wait()
        if proc.returncode != 0:
            yield f"\nProcess exited with code {proc.returncode}\n"
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


@app.route("/api/run-dump", methods=["POST", "OPTIONS"])
def api_run_dump():
    if request.method == "OPTIONS":
        return "", 204
    config = request.get_json(force=True, silent=True)
    if not config:
        return Response("Invalid JSON body\n", status=400, mimetype="text/plain")
    return Response(
        stream_run_dump(config),
        mimetype="text/plain",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.route("/api/update-site-list", methods=["POST", "OPTIONS"])
def api_update_site_list():
    if request.method == "OPTIONS":
        return "", 204

    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "error": "No files uploaded."}), 400

    rows = []
    seen = set()
    sources = []
    warnings = []

    for f in files:
        filename = os.path.basename(f.filename or "")
        if not filename:
            continue
        try:
            df = _read_uploaded_table(f)
        except Exception as e:
            warnings.append(f"{filename}: skipped ({e})")
            continue

        cols_map = {_normalize_col_name(c): c for c in df.columns}
        regional_col = _pick_col(cols_map, [
            "regional", "regiao", "region", "regionalname", "area", "macroregiao"
        ])
        cn_col = _pick_col(cols_map, ["cn", "ddd", "market", "mercado"])
        uf_col = _pick_col(cols_map, [
            "uf", "estado", "state", "siglauf"
        ])
        municipio_col = _pick_col(cols_map, [
            "municipio", "municpio", "cidade", "city", "municipality", "mun", "cluster"
        ])
        enb_col = _pick_col(cols_map, [
            "enb", "enodeb", "enodebid", "idenb", "enodebname", "siteenb"
        ])
        site_col = _pick_col(cols_map, [
            "siteid", "site", "sitecode", "sitecodeid", "site_name", "siteidnr",
            "siteid5g", "siteidnr5g", "nrsiteid", "gnbsiteid", "gnb"
        ])

        if not (uf_col and municipio_col and (enb_col or site_col)):
            warnings.append(
                f"{filename}: missing required columns (UF, MUNICIPIO, and eNB or SiteID)."
            )
            continue

        cell_col = _pick_col(cols_map, [
            "cell", "cellname", "nrcellcuid", "nrcellduid", "nrcellid", "eutrancell", "eutrancellfdd", "eutrancelltdd"
        ])
        tipo_col = _pick_col(cols_map, ["tipo", "type", "rat", "technology", "tech"])
        tech_col = _pick_col(cols_map, ["tech", "technology", "rat"])
        gnbid_col = _pick_col(cols_map, ["gnbid", "gnb_id"])
        nrcell_col = _pick_col(cols_map, ["nrcellcuid", "nrcellduid", "nrcellid"])
        nrfreq_col = _pick_col(cols_map, ["nrfrequency", "ssbfrequency"])
        nrpci_col = _pick_col(cols_map, ["nrpci"])

        id_col = enb_col or site_col
        tech_cols = {
            "tech": tech_col,
            "cell": cell_col,
            "tipo": tipo_col,
            "site": id_col,
            "gnbid": gnbid_col,
            "nrcell": nrcell_col,
            "nrfrequency": nrfreq_col,
            "nrpci": nrpci_col,
            "ssbfrequency": nrfreq_col,
        }
        added = 0
        total = 0
        for _, rec in df.iterrows():
            total += 1
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
            rows.append(
                {
                    "Regional": regional,
                    "UF": uf,
                    "MUNICIPIO": municipio,
                    "SiteID": site_id,
                    "Tech": tech,
                }
            )
            added += 1
        sources.append(f"{filename}: {added} site(s) from {total} row(s)")

    return jsonify(
        {
            "ok": True,
            "rows": rows,
            "count": len(rows),
            "sources": sources,
            "warnings": warnings,
        }
    )

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


@app.route("/api/load-site-list", methods=["POST", "OPTIONS"])
def api_load_site_list():
    if request.method == "OPTIONS":
        return "", 204

    data = request.get_json(force=True, silent=True) or {}
    base_dir = (data.get("base_dir") or "").strip().replace("/", os.sep)
    if not base_dir:
        return jsonify({"ok": False, "error": "base_dir is required."}), 400

    path = os.path.join(base_dir, "sites_list.txt")
    if not os.path.isfile(path):
        return jsonify({"ok": False, "error": f"sites_list.txt not found in {base_dir}"}), 404

    rows = []
    try:
        with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
            lines = [ln.rstrip("\n\r") for ln in f if ln.strip()]
        if len(lines) < 2:
            return jsonify({"ok": True, "path": path, "rows": [], "count": 0})

        header = [h.strip() for h in lines[0].split("\t")]
        idx = {h: i for i, h in enumerate(header)}
        for ln in lines[1:]:
            cells = ln.split("\t")
            def cell(name):
                i = idx.get(name)
                return cells[i].strip() if i is not None and i < len(cells) else ""
            rows.append(
                {
                    "Regional": cell("Regional"),
                    "UF": cell("UF").upper(),
                    "MUNICIPIO": cell("MUNICIPIO"),
                    "SiteID": cell("SiteID"),
                    "Tech": cell("Tech").upper() or "LTE",
                }
            )
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": True, "path": path, "rows": rows, "count": len(rows)})


def stream_run_parquet_to_txt(input_dir, output_dir):
    """Run parquet_to_txt.py with input_dir and output_dir; yield stdout line by line."""
    if not os.path.isfile(PARQUET_TO_TXT_SCRIPT):
        yield "Error: parquet_to_txt.py not found.\n"
        return
    python_exe = get_python_for_dump()
    args = [python_exe, PARQUET_TO_TXT_SCRIPT, input_dir, output_dir]
    proc = subprocess.Popen(
        args,
        cwd=SCRIPT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=_NO_WINDOW,
    )
    for line in proc.stdout:
        yield line if line.endswith("\n") else line + "\n"
    proc.wait()
    if proc.returncode != 0:
        yield f"\nProcess exited with code {proc.returncode}\n"


def stream_run_xml_to_parquet(input_dir, output_dir):
    """Run xml_to_parquet.py with input_dir and output_dir; yield stdout line by line."""
    if not os.path.isfile(XML_TO_PARQUET_SCRIPT):
        yield "Error: xml_to_parquet.py not found.\n"
        return
    python_exe = get_python_for_dump()
    out = output_dir if output_dir else input_dir
    args = [python_exe, XML_TO_PARQUET_SCRIPT, input_dir, out]
    proc = subprocess.Popen(
        args,
        cwd=SCRIPT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=_NO_WINDOW,
    )
    for line in proc.stdout:
        yield line if line.endswith("\n") else line + "\n"
    proc.wait()
    if proc.returncode != 0:
        yield f"\nProcess exited with code {proc.returncode}\n"


@app.route("/api/run-xml-to-parquet", methods=["POST", "OPTIONS"])
def api_run_xml_to_parquet():
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(force=True, silent=True) or {}
    input_dir = (data.get("input_dir") or "").strip().replace("/", os.sep)
    output_dir = (data.get("output_dir") or "").strip().replace("/", os.sep)
    if not input_dir:
        return Response("input_dir required\n", status=400, mimetype="text/plain")
    return Response(
        stream_run_xml_to_parquet(input_dir, output_dir or input_dir),
        mimetype="text/plain",
        headers={"X-Content-Type-Options": "nosniff"},
    )


def stream_run_extract_dump(input_dir, output_dir):
    """Run extract_dump.py with input_dir and optional output_dir; yield stdout line by line."""
    if not os.path.isfile(EXTRACT_DUMP_SCRIPT):
        yield "Error: extract_dump.py not found.\n"
        return
    python_exe = get_python_for_dump()
    args = [python_exe, EXTRACT_DUMP_SCRIPT, input_dir]
    if output_dir:
        args.append(output_dir)
    proc = subprocess.Popen(
        args,
        cwd=SCRIPT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=_NO_WINDOW,
    )
    for line in proc.stdout:
        yield line if line.endswith("\n") else line + "\n"
    proc.wait()
    if proc.returncode != 0:
        yield f"\nProcess exited with code {proc.returncode}\n"


@app.route("/api/run-extract-dump", methods=["POST", "OPTIONS"])
def api_run_extract_dump():
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(force=True, silent=True) or {}
    input_dir = (data.get("input_dir") or "").strip().replace("/", os.sep)
    output_dir = (data.get("output_dir") or "").strip().replace("/", os.sep)
    if not input_dir:
        return Response("input_dir required\n", status=400, mimetype="text/plain")
    return Response(
        stream_run_extract_dump(input_dir, output_dir or ""),
        mimetype="text/plain",
        headers={"X-Content-Type-Options": "nosniff"},
    )


@app.route("/api/run-parquet-to-txt", methods=["POST", "OPTIONS"])
def api_run_parquet_to_txt():
    if request.method == "OPTIONS":
        return "", 204
    data = request.get_json(force=True, silent=True) or {}
    input_dir = (data.get("input_dir") or "").strip().replace("/", os.sep)
    output_dir = (data.get("output_dir") or "").strip().replace("/", os.sep)
    if not input_dir:
        return Response("input_dir required\n", status=400, mimetype="text/plain")
    if not output_dir:
        output_dir = input_dir
    return Response(
        stream_run_parquet_to_txt(input_dir, output_dir),
        mimetype="text/plain",
        headers={"X-Content-Type-Options": "nosniff"},
    )


def _stream_run_script(python_exe, script_path, args_list):
    """Run a Python script with args; yield stdout line by line."""
    if not os.path.isfile(script_path):
        yield f"Error: {os.path.basename(script_path)} not found.\n"
        return
    proc = subprocess.Popen(
        [python_exe] + args_list,
        cwd=SCRIPT_DIR,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        creationflags=_NO_WINDOW,
    )
    for line in proc.stdout:
        yield line if line.endswith("\n") else line + "\n"
    proc.wait()
    if proc.returncode != 0:
        yield f"\nProcess exited with code {proc.returncode}\n"


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
    return Response(
        _stream_run_script(python_exe, POST_PROCESS_4_SCRIPT, args_list),
        mimetype="text/plain",
        headers={"X-Content-Type-Options": "nosniff"},
    )


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
    return Response(
        _stream_run_script(python_exe, POST_PROCESS_5_SCRIPT, args_list),
        mimetype="text/plain",
        headers={"X-Content-Type-Options": "nosniff"},
    )


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
    return Response(
        _stream_run_script(python_exe, POST_PROCESS_6_SCRIPT, args_list),
        mimetype="text/plain",
        headers={"X-Content-Type-Options": "nosniff"},
    )


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


def stream_parser_pipeline(input_dir, output_dir, customize_txts, cellref_dir, enriched_dir):
    """Full pipeline: extract ZIP -> XML->Parquet -> Parquet->TXT -> (optional) enrich 4/5/6."""
    python_exe = get_python_for_dump()
    src_dir = input_dir
    txt_dir = output_dir or input_dir
    enr_dir = enriched_dir or txt_dir

    yield f"Input:    {src_dir}\n"
    yield f"Output:   {txt_dir}\n"
    if customize_txts:
        yield f"Enriched: {enr_dir}\n"
    yield "\n"

    # Step 1: Extract ZIPs (XMLs stay alongside ZIPs in src_dir)
    yield "=" * 50 + "\n"
    yield "STEP 1/3: Extracting ZIP files...\n"
    yield "=" * 50 + "\n"
    for line in _stream_run_script(python_exe, EXTRACT_DUMP_SCRIPT, [EXTRACT_DUMP_SCRIPT, src_dir, src_dir]):
        yield line

    # Step 2: XML -> Parquet (read XMLs from src_dir, write parquets to txt_dir)
    yield "\n" + "=" * 50 + "\n"
    yield "STEP 2/3: Parsing XML to Parquet...\n"
    yield "=" * 50 + "\n"
    for line in _stream_run_script(python_exe, XML_TO_PARQUET_SCRIPT, [XML_TO_PARQUET_SCRIPT, src_dir, txt_dir]):
        yield line

    # Step 3: Parquet -> TXT (read/write in txt_dir, clean up parquets)
    yield "\n" + "=" * 50 + "\n"
    yield "STEP 3/3: Parquet to TXT (+ cleanup)...\n"
    yield "=" * 50 + "\n"
    for line in _stream_run_script(python_exe, PARQUET_TO_TXT_SCRIPT, [PARQUET_TO_TXT_SCRIPT, txt_dir, txt_dir]):
        yield line

    # Optional: Enrich files
    if customize_txts:
        cellref = cellref_dir or CELLREF_DEFAULT_PATH

        yield "\n" + "=" * 50 + "\n"
        yield "STEP 4: Enrich Files (LTE FDD + ENodeBFunction)...\n"
        yield "=" * 50 + "\n"
        for line in _stream_run_script(python_exe, POST_PROCESS_4_SCRIPT, [POST_PROCESS_4_SCRIPT, txt_dir, cellref, enr_dir]):
            yield line

        yield "\n" + "=" * 50 + "\n"
        yield "STEP 5: Enrich Files (TDD + FDD combined)...\n"
        yield "=" * 50 + "\n"
        for line in _stream_run_script(python_exe, POST_PROCESS_5_SCRIPT, [POST_PROCESS_5_SCRIPT, txt_dir, enr_dir]):
            yield line

        yield "\n" + "=" * 50 + "\n"
        yield "STEP 6: Enrich Files (5G NR)...\n"
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
    output_dir = (data.get("output_dir") or "").strip().replace("/", os.sep) or input_dir
    customize_txts = bool(data.get("customize_txts", False))
    cellref_dir = (data.get("cellref_dir") or CELLREF_DEFAULT_PATH).strip().replace("/", os.sep)
    enriched_dir = (data.get("enriched_dir") or "").strip().replace("/", os.sep) or output_dir
    if not input_dir:
        return Response("input_dir required\n", status=400, mimetype="text/plain")
    return Response(
        stream_parser_pipeline(input_dir, output_dir, customize_txts, cellref_dir, enriched_dir),
        mimetype="text/plain",
        headers={"X-Content-Type-Options": "nosniff"},
    )


if __name__ == "__main__":
    if not os.path.isdir(WEB_TOOL_DIR):
        print("web-tool directory not found next to server_downloader.py")
        sys.exit(1)
    print("Downloader server: http://localhost:8765")
    print("Use 'Execute Dump' in the tool to run the script and see logs here.")
    app.run(host="127.0.0.1", port=8765, threaded=True)
