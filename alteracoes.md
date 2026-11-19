# Alterações Realizadas

## 2026-11-19 — Vivo: pasta raiz para a equipe (ou as pastas clássicas)

- Card **Vivo folders** na aba ENM Dump, no mesmo formato do card da Claro. Há dois modos:
  - **Pastas clássicas:** `C:/Dumps/todos_enms`, `C:/Dumps/LTE_Total`, `C:/Camilo`,
    `C:/Vivo Reports`, `C:/Camilao` e `C:/Cellref/...`. É o modo da máquina original;
    nela nada muda.
  - **Uma raiz para a equipe** (padrão `C:/Vivo_Downloader`), com as subpastas
    `Dumps/todos_enms`, `Dumps/LTE_Total`, `Referencias` (no lugar de Camilo),
    `Relatorios`, `Relatorios/Adicionais` (no lugar de Camilao), `Cellref/...` e `Exports`.
- Na primeira abertura, o navegador escolhe o modo uma única vez. Se já tinha
  configurações da Vivo, fica no modo clássico. Se não tinha, pergunta ao servidor
  (`/api/vivo/folders`): o modo é clássico quando `C:/Camilo` e `C:/Dumps/LTE_Total`
  existem na máquina; caso contrário, a raiz. Trocar de modo leva as pastas salvas
  para o modo novo, papel por papel.
- Os notebooks e os audits não foram editados. A rotina semanal já traduzia os
  caminhos dela. Os audits passaram a traduzir com `audit_workflow.VivoPaths`, com a
  mesma regra; no modo raiz, um caminho absoluto desconhecido interrompe o audit.
  A tela passou a enviar também as pastas de saída dos cellrefs da Vivo, que antes
  eram fixas (`C:/Cellref/LTE` e `NR`).
- A trava entre operadoras agora considera a raiz da Vivo configurada (cabeçalho
  `X-Downloader-Vivo-Root`) e também `C:/Vivo_Downloader`. Um dump da Vivo também
  não pode apagar a raiz.
- Validação com dados reais (semana 47): os 16 audits rodaram com as pastas clássicas
  e com uma raiz que continha cópias das entradas (125 arquivos, 8,2 GB). Na rodada
  clássica, os relatórios foram desviados para uma pasta temporária, para não tocar
  nos relatórios reais. Os **22 relatórios saíram idênticos** (as planilhas comparadas
  aba por aba, o CSV byte a byte).
- Pela tela: escolha automática do modo clássico, troca para a raiz e volta, com
  todos os campos e o catálogo de audits seguindo as pastas.
- Testes: `tests/test_vivo_root.py` e `tests/test_vivo_root.cjs`.

## 2026-11-19 — Exe sem Python na máquina

- O `Downloader.exe` roda os scripts com o Python embutido (`worker_mode.py`), como o
  MoB_Tool_Box. No teste com o exe isolado e o PATH sem Python, na W42 inteira, os
  21 TXT, os 19 MOs e o cellref saíram idênticos byte a byte, sem nenhum `python.exe`
  aberto. O exe passou de 28,8 para 46,4 MB.

## 2026-11-19 — Claro, fase 4: cellref da Claro pelo MANDO

- Copiado do MoB_Claro (commit b9a443e): `cadastro_claro.py`. A função `construir`
  ficou igual ao original. Mudanças: import local de `regras_claro`, leitura dos
  TXT em latin-1 e linha de comando
  (`python cadastro_claro.py <pasta_txt> <mando.csv | pasta> <pasta_cellref>`).
  Dada uma pasta, o script usa o `mando_cells_<data>.csv` (ou `.csv.zip`) de data
  mais recente. Ele se recusa a gravar numa pasta da Vivo ou na pasta dos TXT.
- Aba **Cellrefs** no modo Claro: pasta dos TXT da rede inteira, MANDO e pasta
  de saída (`<raiz>/Cellref`), com o botão **Generate Claro cellref**. A rota é
  `/api/run-claro-cellref`, só da Claro (`CLARO_ONLY_ENDPOINTS` em `operator_profiles.py`).
  O "Process MOs" da Claro passou a ler o cadastro desta mesma pasta.
- Validação na rede inteira de PR (W42 + MANDO de 09/11/2026: 14.913 células LTE,
  5.759 NR e 1.052.788 relações, cerca de 34 s):
  - Cópia × original, sobre os mesmos TXT do Downloader: os 8 arquivos de dados
    são idênticos byte a byte (o `.xlsx` sem a data de criação). No
    `cadastro_resumo.json` muda só a barra do caminho do MANDO.
  - Cadeia completa (TXT do Downloader → cópia) × MoB (TXT do conversor do MoB →
    original): os cellrefs, os alertas, as relações e o IP de X2 são idênticos.
    `5G_NRCellDU.txt` e `Slot.txt` (cópias do TXT de entrada) têm o mesmo conteúdo
    e mudam só a ordem das colunas.
  - Pela tela (servidor + navegador): a saída é a mesma.
- Testes: `tests/test_cadastro_claro.py` e um caso novo em
  `tests/test_operator_profiles.py` (98 testes OK).

## 2026-11-18 — Claro, fase 3: "Process MOs" com as regras da Claro

- Copiados do MoB_Claro (commit b9a443e), sem depender dele em tempo de execução:
  `regras_claro.py`, `pos_processamento_claro.py` e `enm_dump_claro.py` (as 7
  funções do `enm_dump.py` que o pós-processamento usa, sem alteração).
- Na tela da Claro, o cartão do parser tem **Process MOs (Claro network rules)**
  (ligado por padrão) e a pasta **Processed MOs folder** (`<raiz>/MOs`). O Run All
  e o Run Parser da Claro fazem dump → TXT → MOs processados.
- O servidor roda só o script da Claro (passo 2/2) quando a operadora é Claro.
  Recusa a mesma pasta para TXT e MOs processados (os arquivos têm o mesmo nome)
  e não usa o cellref padrão da Vivo como cadastro da Claro.
- Validação no dump da rede inteira de PR (W42): os 19 arquivos gerados são
  idênticos byte a byte aos do original do MoB, com e sem o cadastro
  `C:/MoB_Claro/Cadastro`; também pela linha de comando e pelo servidor
  (ZIP → TXT → MOs). Cerca de 15 s para a rede inteira.
- Testes: `tests/test_pos_processamento_claro.py` e casos novos em
  `tests/test_operator_profiles.py` (90 testes OK).

## 2026-11-18 — Claro, fase 2: parser validado no dump da rede inteira de PR

- `xml_to_txt.py` testado no `PR_mob_W42.zip` (XML de 4,2 GB): 21 MOs com
  conteúdo idêntico ao conversor do MoB_Claro, em ~2,5 min e ~1,36 GB de RAM.
- Nova opção `--include-nr-relations` (ligada pelo servidor só para a Claro):
  mantém as `EUtranCellRelation` 5G→4G (91.650 na W42) que o audit PSCell da
  Claro usa. A Vivo continua sem elas, como antes.
- A lista de arquivos do parser aceita BOM no início (arquivos salvos por
  ferramentas do Windows).
- Memória do parser: o buffer passa a ser limitado por tamanho estimado (64 MB)
  em vez de 200 mil linhas. TXTs idênticos byte a byte (SHA256) antes e depois,
  mesmo tempo:
  - Vivo BARA (8,8 GB de XML, 88 MOs): 446 s / 444 MB → 440 s / 131 MB.
  - Claro PR W42 (4,2 GB de XML, 21 MOs): 187 s / 1.358 MB → 184 s / 142 MB.
  - Vivo, dump semanal inteiro de 16/11 (BARA + BARB + CTPB, 37,8 GB de XML,
    modo Vivo, as duas versões rodando juntas): 1.652 s / 436 MB → 1.581 s / 120 MB;
    os 90 TXTs (7,26 GB) idênticos.
- Testes: `tests/test_xml_to_txt_cli.py` (inclui spool × sem spool) e caso novo em
  `tests/test_operator_profiles.py`.

## 2026-11-18 — Operadora VIVO | CLARO (fase 1) e tema por operadora

- Botão VIVO | CLARO no cabeçalho. Cada operadora tem as próprias
  configurações no navegador: a Vivo continua com as chaves de sempre (nada
  muda para ela); a Claro usa as mesmas chaves com o prefixo `claro:`. Trocar
  recarrega a página e é bloqueado enquanto houver dump/parser/audit rodando.
- Claro: lista de ENMs própria e editável (vem com `ENMSANTURCE` =
  `https://renmsanturce.prt.local/`), pasta raiz editável (padrão
  `C:/Claro_Reports`, com `Dumps`, `MOs`, `Cellref`, `Exports`) e escopo por
  rede inteira (`-n *`), região ou município (`-n CAR*;SJU*`), a partir do
  cadastro de 78 municípios / 5 regiões do Portal RAN PR.
- Claro, nesta fase: Run All = dump + XML/ZIP → TXT. Notebooks 3–6, cellrefs,
  enriquecimento e audits da Vivo ficam bloqueados para a Claro no servidor
  (`operator_profiles.py`), com mensagem clara, antes de qualquer subprocesso.
- Trava de pastas: a Claro não lê nem grava as pastas da Vivo (`C:/Camilo`,
  `C:/Vivo Reports`, `C:/Dumps`, `C:/Cellref`, `C:/MoB`...) e a Vivo não usa a
  raiz da Claro nem `C:/MoB_Claro`. Na Claro, o dump (que apaga a própria pasta)
  não pode apontar para a raiz.
- Tema no padrão do Portal RAN: cabeçalho branco com filete da marca, logos
  Amdocs e da operadora, roxo Vivo `#660099` ou vermelho Claro `#C8102E`, e
  tema claro/escuro.
- Testes: `tests/test_operator_profiles.py` e `tests/test_operator_storage.cjs`.

## 2026-11-08 — Rotina semanal completa

- Pasta única das referências no primeiro cartão da aba ENM Dump; removidos
  os seletores duplicados do parser. A lista de sites pode ser reconstruída
  somente de `cellref.xlsx` e `cellref_5g.xlsx`, ignorando históricos.
- Nova aba Cellrefs: leitura dos downloads manuais LTE/NR, execução do LTE v2
  e 5G v3, publicação na pasta compartilhada e reaplicação dos passos 4/5.
- Run All pode encadear a geração dos cellrefs após os parâmetros ENM. A
  atualização isolada pode reutilizar os MOs brutos retidos em `.refresh_inputs`.
- Notebook 4 atualizado para `4_MOs_Camilo.ipynb`, respeitando o site físico
  da célula em Hotel de BTS. SCIENCE pode ser derivado do cellref LTE quando ausente.
- Validação de cabeçalhos, mistura de semanas, preservação do TDD e cobertura
  de coordenadas. Originais e destinos de produção preservados nos testes.

- Novo executor `weekly_workflow.py`: execução encadeada dos notebooks 2–6,
  preservando os originais de `C:/Users/leocc/Novos_Audits` e as referências
  `cellref.xlsx`/`SCIENCE.xlsx` de `C:/Camilo`.
- Run All oferece dump + rotina completa em um único job, com verificação
  prévia das fontes e inclusão dos MOs auxiliares necessários.
- Opções independentes e persistentes para histórico semanal em `C:/Camilo`
  e relatórios em `C:/Vivo Reports`, com destinos configuráveis.
- Execuções isoladas e manifesto com hashes dos notebooks, semana, avisos e
  arquivos publicados. A publicação começa após sucesso do processamento.
- Tratamento de recortes pequenos, variantes de IDs, atributos opcionais,
  regex com Arrow e inventário FDD quando o escopo não contém TDD.
- Falhas de ENM retornam código de erro; a interface deixa de tratar falhas
  do parser como conclusão com sucesso. Controle de concorrência e encerramento
  dos subprocessos quando o stream é interrompido.
- Dependência `pyarrow`, inclusão do executor no build e testes do fluxo,
  das opções de saída e da preservação de resultados quando há falhas.

Data de referência do histórico abaixo: 2026-03-02

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
