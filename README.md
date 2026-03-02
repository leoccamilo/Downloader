# Downloader

ENM dump + XML parsing + enrichment tool with a local web UI.

## Main Components
- `server_downloader.py`: local backend/API used by the web app.
- `web-tool/`: frontend (`index.html`, `app.js`, `styles.css`).
- `dump_multiple_enms.py`: Execute Dump workflow for multiple ENMs.
- `xml_to_parquet.py`, `parquet_to_txt.py`: parser pipeline.
- `post_process_4_camilo.py`, `post_process_5_tdd.py`, `post_process_6_5g.py`: enrichment steps.
- `START_DOWNLOADER.bat` / `START_DOWNLOADER_HIDDEN.vbs`: app launchers.

## Setup
1. Create and activate a Python 3 environment.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Optional (ENM client scripting wheel):
   - `pip install enm_client_scripting-1.22.2-py2.py3-none-any.whl`

## Run
- Visible mode: `START_DOWNLOADER.bat`
- Hidden mode: `START_DOWNLOADER_HIDDEN.vbs`

## Default Folders
- Site list base dir (default): `C:/Downloader/cellref`
- Parser pipeline:
  - Input: `C:/Downloader/data/input`
  - Output: `C:/Downloader/data/output`
  - Enriched: `C:/Downloader/data/enriched`

## Notes
- Runtime/generated files are ignored by Git.
- Change history is maintained in `alteracoes.md`.
