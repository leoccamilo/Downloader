# Alterações Realizadas

Data de referência: 2026-03-02

## 1) Dependências Python / ambiente
- Tentativa de instalação do pacote Ericsson informada pelo usuário:
  - `pip install C:\Tools\enm_client_scripting-1.22.2-py2.py3-none-any.whl`
- Falha por dependência rígida (`six==1.9.0`) sem índice disponível.
- Instalação realizada com sucesso usando:
  - `pip install --no-deps C:\Tools\enm_client_scripting-1.22.2-py2.py3-none-any.whl`
- Havia processo Python bloqueando escrita no `venv`; processo encerrado para concluir instalação.
- Após isso, surgiu dependência ausente (`requests`) no `venv`.
- Como o ambiente não baixava pacotes do índice, foi feito reaproveitamento local (cópia para o `venv`) de:
  - `requests` (2.6.0)
  - `urllib3`
  - `certifi`
  - `idna`
- Validação feita: `import enmscripting` passou no `venv`.

## 2) Correção de erro de proxy no Execute Dump
Problema observado:
- `ProxyError('Cannot connect to proxy...', ConnectionRefusedError 10061)`
- Ambiente tinha `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY` apontando para `http://127.0.0.1:9`.

Ajustes aplicados:
- Arquivo: `server_downloader.py`
  - Criada função para montar ambiente sem variáveis de proxy (`_build_direct_network_env`).
  - `subprocess.Popen` do dump passou a executar com `env` sem proxies.
- Arquivo: `dump_multiple_enms.py`
  - Criada função `disable_proxy_env()`.
  - Chamada no início de `main()` para execução direta também ignorar proxy de ambiente.

## 3) Ajustes sobre pasta de saída (output_dir)
Problema observado:
- `PermissionError` ao criar `mos_downloader.txt` em `C:\Dumps\todos_enms`.

Evolução da solução:
- Primeiro foi implementado fallback automático para pasta local gravável.
- Depois, por decisão do usuário, o comportamento foi alterado para respeitar estritamente a pasta escolhida.

Estado final (atual):
- Arquivo: `dump_multiple_enms.py`
  - Removido fallback automático.
  - Adicionada validação de escrita na pasta de saída selecionada (`ensure_writable_output_dir`).
  - Se não gravável, o script encerra com erro claro pedindo escolha de outra pasta.

## 4) Melhoria de visibilidade no frontend
- Arquivo: `web-tool/app.js`
  - Antes do `Execute Dump`, o log agora exibe explicitamente a pasta usada:
  - `Output folder: <caminho>`

## 5) Comportamento validado com usuário
- Usuário confirmou que ao usar `C:/Downloader/output` o fluxo funcionou.
- Diretriz adotada: manter opção de escolha de pasta e não trocar automaticamente sem aviso.

## Arquivos alterados no projeto
- `C:\Downloader\server_downloader.py`
- `C:\Downloader\dump_multiple_enms.py`
- `C:\Downloader\web-tool\app.js`

## Observações
- Alguns testes de compilação para `.pyc` falharam por permissão de escrita em `__pycache__`; validação de sintaxe foi feita via `compile(...)` em memória.

## 6) Execute Dump message flow improvements (based on notebook)
Reference used:
- `1_Dump_MOs_one_batch.ipynb` (log sequence and operational steps)

Changes applied:
- File: `dump_multiple_enms.py`
  - Updated ENM execution logs to a detailed, step-based sequence:
    - `Step 1/5 - Prepared export command`
    - `Step 2/5 - Opening ENM session`
    - `Step 3/5 - Uploading MO list and submitting export command`
    - `Step 4/5 - Monitoring export job status`
    - `Step 5/5 - Downloading export files`
  - Added richer status polling logs:
    - Explicit retry message when status output is not yet available.
    - Progress extraction from status output (`Nodes exported X / Expected Y`).
    - Compact current status preview when progress counters are absent.
  - Improved completion summary per ENM:
    - Returns success with downloaded file count.
  - Internal naming cleanup for readability:
    - `processar_enm` -> `process_enm`
    - `resultados` -> `results`

## 7) English-only / message normalization
- File: `web-tool/app.js`
  - Normalized runtime banner message to plain ASCII English:
    - `Running dump - watch the Logs panel below.`
- The `Execute Dump` flow now consistently logs the selected output directory and the backend emits fully English operational messages.

## 8) Sync Dump output -> Parser input
- File: `web-tool/app.js`
  - In `executeDump()`, the selected ENM output folder is now automatically copied to `Parser Input Directory`.
  - The synced parser input path is persisted in `localStorage` (`downloader_parser_input_dir`).
  - Added explicit log line:
    - `Parser input synced to: <path>`
- Goal: avoid mismatch where dump writes to one folder and parser reads another.

## 9) Parquet cleanup reliability on Windows
- File: parquet_to_txt.py
  - Added delete_file_with_retry() with retry/backoff for transient file locks.
  - Added os.chmod(path, 0o666) before delete to avoid read-only deletion issues.
  - Added explicit memory release (del df, del dfs, gc.collect()) after each MO conversion to reduce locked parquet handles.
- Goal: avoid repeated WinError 5 Access is denied during parquet cleanup when conversion already succeeded.

## 10) Update site list improvements (file visibility + smart formats)
- Goal:
  - Allow selecting files directly (so users can see files), not only folder picker mode.
  - Support smarter ingestion for multiple formats.

### Frontend changes
- File: web-tool/index.html
  - Update site list now uses a multi-file picker (not webkitdirectory only).
  - Accepted formats: .csv, .txt, .xlsx, .xls.
  - Updated labels/help text to reflect file-based workflow.

- File: web-tool/app.js
  - updateSiteListFromFolder(files) now first tries backend smart parsing via:
    - POST /api/update-site-list with FormData(files[]).
  - On backend success:
    - updates in-memory site list,
    - updates UF selector,
    - shows source/warning summary,
    - downloads generated sites_list.txt.
  - Keeps local fallback parser for CSV/TXT when backend is unavailable.
  - Selection summary now shows file count + sample file names in the input field.

### Backend changes
- File: server_downloader.py
  - Added endpoint POST /api/update-site-list.
  - Added smart table reader with support for:
    - CSV/TXT: delimiter detection (,, ;, \t, |) + encoding fallback (utf-8-sig, utf-8, latin-1).
    - XLSX/XLS: pandas.read_excel.
  - Column-based detection for required fields (Regional, UF, MUNICIPIO, plus eNB or SiteID).
  - Returns merged/deduped rows (LTE/NR) with source and warning details.

## 11) Smart column alias mapping for Site List (MoB KML-style)
- File: server_downloader.py
  - Added robust column-name normalization:
    - case-insensitive
    - accent-insensitive (e.g. MUNICÍPIO == MUNICIPIO)
    - ignores spaces/symbols (site id, site_id, Site-ID map to same key)
  - Expanded alias dictionaries for required fields:
    - Regional: Regional, Regiao, Region, etc.
    - UF: UF, Estado, State, etc.
    - Municipio: Municipio, Municipio with accent, Cidade, City, etc.
    - Site/eNB: eNB, ENodeB, SiteID, Site, gNB, and other common variants.
- Goal:
  - Automatically detect columns from heterogeneous files without manual renaming.

## 12) Scope behavior aligned with loaded Site List (UF/City)
- Files: web-tool/app.js, web-tool/index.html
- Changes:
  - UI label changed from By Municipality to By City.
  - UF controls now become dynamic from loaded site list data (instead of static-only behavior).
  - Added centralized refresh flow: efreshScopeUfControls().
  - By UF now shows UFs found in the selected/loaded site list files.
  - By City now filters municipalities using:
    - a specific UF from dropdown, OR
    - multiple UF checkboxes selected in By UF panel.
  - Improved helper text/messages from "municipality" to "city" for user-facing prompts.
  - Tech toggles (LTE/NR) now refresh city suggestions immediately.

## 13) Scope sync rule fixed (default vs loaded file) + validated
- File: web-tool/app.js
- Rule implemented:
  - If no site list file was loaded: UF list stays default (AVAILABLE_UFS).
  - If a site list file is loaded/updated: Scope UF controls switch to UFs from that file only.
- Added state flag: siteListLoadedFromFile.
- City scope behavior:
  - UF dropdown auto-selects first UF from loaded file.
  - getSitesString() and city suggestions use loaded-file UFs.

Validation executed:
- Backend endpoint validated: POST /api/update-site-list returned 200.
- Playwright end-to-end validation:
  - Uploaded site_scope_test.csv via UI.
  - Site List status became Updated: 4 sites.
  - By UF checkboxes reduced to file UFs only: AM, SP.
  - By City UF dropdown options: AM, SP.
  - Typing MANAUS produced 1 site(s) selected. and site string SITE001.

## 14) Startup hardening (avoid duplicated server instances)
- Files: START_DOWNLOADER.bat, START_DOWNLOADER_HIDDEN.vbs
- Added pre-start cleanup for port 8765 listeners.
- Behavior now:
  - Before starting server_downloader.py, the launcher kills any process listening on 127.0.0.1:8765.
  - Reduces race/conflict where multiple Python/Pythonw processes answer different app versions.

## 15) Site list Tech inference aligned with Vivo rules (eNB may be 5G)
- File: `server_downloader.py`
- Replaced fixed rule (`eNB => LTE`) with row-level heuristic inference for `Tech`:
  - explicit Tech/RAT column (`NR/5G` vs `LTE/4G`)
  - cell naming (`5*` => `NR`, `T/U/V/Z/O*` => `LTE`)
  - NR-specific identifiers (`nRCell*`, `gNBId`, `ssbFrequency`, `nRPCI`)
  - LTE type hints (`FDD/TDD` in Tipo/Type)
  - site prefix fallback (`T*` => `LTE`, `S*` => `NR`; `M*` ambiguous)
  - filename hint fallback (`*5g*/*nr*` => `NR`, `*lte*/*eutran*/*4g*` => `LTE`)
- Result: files where 5G site is still in column `eNB` are now classified correctly as `NR` when row signals indicate 5G.

## 16) UF ↔ City correlation and incremental 4G+5G merge in Site List
- Files: `server_downloader.py`, `web-tool/app.js`
- Backend (`server_downloader.py`):
  - `Regional` is now optional when building site list rows.
  - If `Regional` is missing, fallback may use `CN/Market` when available.
  - Required columns are now: `UF`, `MUNICIPIO`, and one site identifier (`eNB` or `SiteID`).
- Frontend (`web-tool/app.js`):
  - Added incremental merge behavior for Site List updates:
    - loading a second file now appends to existing `siteListData` and performs dedup (`concat + drop duplicates`), instead of replacing.
  - Added normalization/dedup helpers (`normalizeSiteRow`, `dedupeAndSortSiteRows`, `mergeSiteListRows`).
  - `By City` filtering is now accent-insensitive for municipality matching (e.g., `CORREA` matches `CORRÊA`).
  - Status message now shows batch delta and total, e.g. `Updated: +X site(s), total Y`.
- Validation with files in `arquivos/`:
  - `DT_Info_LTE_10.csv` -> LTE rows loaded.
  - `EUtranCellFDD.csv` -> LTE rows loaded.
  - `cellref_5g.xlsx` -> NR rows loaded.
  - Combined 4G + 5G returns both techs and preserves UF -> City relation (e.g., `PA` with municipality list).

## 17) Default save location for `sites_list.txt` = `C:/Downloader/cellref`
- Files: `web-tool/app.js`, `web-tool/index.html`
- `Site List` path field now defaults to `C:/Downloader/cellref` and remains editable.
- Save fallback no longer uses dump output directory; default save target is now always `C:/Downloader/cellref` unless user changes it.
- UI text adjusted to clarify automatic 4G/5G detection and base directory behavior.

Validation:
- Backend site-list generation with `cellref.xlsx` + `cellref_5g.xlsx` returns:
  - `status=200`
  - `count=12208`
  - `techs=['LTE','NR']`
  - `warnings=[]`

## 18) Multi-city selection in Scope -> By City
- Files: `web-tool/index.html`, `web-tool/app.js`
- Added multi-city workflow:
  - New `Add` button next to city input.
  - Selected cities are shown as removable chips.
  - Added `Clear cities` action.
- Filtering behavior:
  - If one or more chips are selected, site scope uses the union of selected cities.
  - If no chip is selected, legacy partial-text behavior is preserved.
- Suggestions behavior:
  - Suggestion buttons now add city directly to selected chips.
  - Enter key in city input adds a resolved city candidate.
  - Candidate resolver now prefers shortest prefix match (e.g. `MAN` -> `MANAUS`).

Validation:
- Playwright: with UF=`AM`, typing `MAN` + Enter adds `MANAUS`.
- Playwright: adding multiple cities results in combined site list/count.

## 19) Base dir sync when selecting folder in Site List
- Files: `web-tool/index.html`, `web-tool/app.js`
- Added a dedicated folder browse control for `Base dir` in Site List:
  - new hidden directory input: `#folder-picker-site-list-base`
  - new button: `#btn-browse-site-list-base`
- When user selects a folder, `site-list-folder-path` is updated immediately and persisted.
- Auto-load check is triggered after folder selection (`sites_list.txt` detection in selected base dir).
- Goal: prevent saving to stale path when user selects a different folder.

## 20) Auto-update Base dir from selected Site List files (best effort)
- File: `web-tool/app.js`
- Added base-dir inference from selected files in `Update site list` flow:
  - Uses `file.path` (when available in desktop shells) to detect common parent directory.
  - Automatically updates `Base dir` and persists it in localStorage before upload.
- If browser does not expose real file paths, app now shows explicit message:
  - `Base dir not auto-detected by browser; keeping current value.`

## 21) End-of-day snapshot (2026-03-02)
- Markdown docs verified/updated in project root:
  - `alteracoes.md`
  - `sites_list.md`
  - `DATA_MODEL_RULES.md`
  - `INSTALL_ENMSCRIPTING.md`
- Current repository status:
  - `C:\Downloader` has no `.git` directory (not a Git repository), so commit/push is not available from this folder.
- Operational note:
  - Site List `Base dir` remains user-editable and persisted; automatic base-dir inference depends on browser exposing local file path metadata.

## 22) GitHub publication (clean scope)
- Repository: `https://github.com/leoccamilo/Downloader`
- Published only project-essential source/docs/runtime launchers.
- Excluded local-only artifacts:
  - `venv/`, `__pycache__/`
  - local dump/parser outputs (`data/*` generated content, `output/`)
  - heavy binaries/installers (`*.zip`, `*.whl`)
  - ad-hoc test notebook/files (`*.ipynb`, `site_scope_test.csv`)
- Added placeholders (`.gitkeep`) for expected runtime folders:
  - `data/input`, `data/output`, `data/enriched`, `cellref`, `arquivos`
