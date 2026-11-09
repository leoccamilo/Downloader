# Guia de Atualização — Projeto Downloader (para Cursor)

> **Objetivo:** Comparar o projeto local da máquina de trabalho com a versão mais recente
> no GitHub (`https://github.com/leoccamilo/Downloader`) e aplicar todas as atualizações
> necessárias sem sobrescrever arquivos de ambiente local (venv, dados, credenciais).

---

## 1. Repositório de referência

```
GitHub : https://github.com/leoccamilo/Downloader
Branch : main
Commit mais recente: d207d95
```

---

## 2. Estrutura esperada do projeto

```
Downloader/
├── server_downloader.py          ← servidor Flask (entry point principal)
├── dump_multiple_enms.py         ← subprocess: dump ENM
├── parquet_to_txt.py             ← subprocess: converte parquet → txt
├── xml_to_parquet.py             ← subprocess: converte XML → parquet
├── extract_dump.py               ← subprocess: extrai ZIPs
├── post_process_4_camilo.py      ← subprocess: enriquecimento LTE FDD
├── post_process_5_tdd.py         ← subprocess: enriquecimento TDD/FDD
├── post_process_6_5g.py          ← subprocess: enriquecimento 5G NR
├── update_site_list.py           ← utilitário legado (mantido)
├── requirements.txt              ← deps de dev (inclui pyarrow, lxml, etc.)
├── requirements_build.txt        ← NOVO — deps mínimas para o build Nuitka
├── build_nuitka.ps1              ← NOVO — script de build Nuitka → Downloader.exe
├── BUILD.bat                     ← NOVO — atalho para executar build_nuitka.ps1
├── START_DOWNLOADER.bat          ← launcher para execução via Python do sistema
├── INSTALL_ENMSCRIPTING.bat      ← helper para instalar enmscripting
├── INSTALL_ENMSCRIPTING.md       ← instruções de instalação enmscripting
├── CLAUDE.md                     ← instruções de desenvolvimento para AI
├── DATA_MODEL_RULES.md           ← regras do modelo de dados
├── README.md
├── alteracoes.md                 ← histórico de alterações
├── sites_list.md
├── mos_mob.txt
├── run_dump.bat
├── web-tool/
│   ├── index.html
│   ├── app.js
│   ├── file-viewer.js
│   └── styles.css
├── data/
│   ├── input/      ← pasta de entrada do dump (não versionar conteúdo)
│   ├── output/     ← pasta de saída processada
│   └── enriched/   ← pasta de saída enriquecida
├── cellref/        ← arquivos de referência celular (não versionar)
└── arquivos/       ← arquivos de trabalho locais (não versionar)
```

---

## 3. Arquivos NÃO devem ser sobrescritos / são locais

Os itens abaixo existem apenas localmente e **não devem ser criados, sobrescritos ou deletados**:

| Caminho | Motivo |
|---|---|
| `venv/` | Ambiente virtual Python de desenvolvimento |
| `venv_build/` | Ambiente virtual para build Nuitka |
| `dist_nuitka/` | Output do build (exe compilado) |
| `data/input/*` | Dados de dump gerados localmente |
| `data/output/*` | Dados processados localmente |
| `data/enriched/*` | Dados enriquecidos localmente |
| `cellref/*.xlsx`, `cellref/*.csv` | Arquivos de referência da empresa |
| `cellref/sites_list.txt` | Gerado pelo uso da ferramenta |
| `arquivos/` | Arquivos de trabalho locais |
| `__pycache__/` | Cache Python |
| `*.zip`, `*.whl` | Binários locais |
| `.env` (se existir) | Credenciais |

---

## 4. Procedimento recomendado para atualizar

### Passo 1 — Fazer pull do repositório remoto
```bash
cd C:\Downloader   # ou o caminho da máquina de trabalho
git fetch origin
git status         # verificar diferenças locais antes de mesclar
git pull origin main
```

> **Atenção:** Se houver conflitos em arquivos locais modificados,
> usar `git stash` antes do pull e `git stash pop` depois.

### Passo 2 — Se não for um repositório Git ainda
```bash
cd C:\Downloader
git init
git remote add origin https://github.com/leoccamilo/Downloader.git
git fetch origin
git checkout main
```

### Passo 3 — Verificar os arquivos NOVOS que podem não existir na máquina de trabalho

Os arquivos abaixo são **novos** e provavelmente não existem na máquina de trabalho.
Após o pull, confirmar que foram criados:

```
requirements_build.txt   ← novo (necessário para o build Nuitka)
build_nuitka.ps1         ← novo (script de build)
BUILD.bat                ← novo (atalho para o build)
web-tool/file-viewer.js  ← pode ser novo
```

---

## 5. Resumo das principais mudanças desde a versão anterior

### 5.1 `server_downloader.py` — mudanças críticas

| Função / Endpoint | O que mudou |
|---|---|
| `get_python_for_dump()` | Agora busca Python em: `python_embed/`, `venv/Scripts/`, **`../venv/Scripts/`** (novo — detecta venv quando exe está em `dist_nuitka/`), depois `shutil.which("python")`, depois `sys.executable` |
| `stream_run_dump()` | Adicionado `try/except` em torno de todo o corpo do gerador para evitar HTTP 500 — exceções agora são retornadas como texto no log da UI |
| `_build_direct_network_env()` | Função que remove variáveis de proxy do ambiente antes de subprocessos (fix para `ProxyError`) |
| `/api/update-site-list` | **Novo endpoint** — recebe upload de arquivos CSV/TXT/XLSX e retorna rows parsed (LTE+NR) com detecção automática de colunas e delimitadores |
| `/api/save-site-list` | **Novo endpoint** — salva `sites_list.txt` em disco na pasta configurada |
| `/api/load-site-list` | **Novo endpoint** — lê `sites_list.txt` da pasta configurada para recarregar a lista |
| `/api/run-parser-pipeline` | **Novo endpoint** — pipeline completo: extract ZIP → XML→Parquet → Parquet→TXT → (opcional) enriquecer |
| `/api/run-xml-to-parquet` | **Novo endpoint** |
| `/api/run-extract-dump` | **Novo endpoint** |
| `/api/run-parquet-to-txt` | **Novo endpoint** |
| `/api/run-post-process-4/5/6` | **Novos endpoints** — executam scripts de pós-processamento |
| `/api/save-file-viewer-export` | **Novo endpoint** — salva exportação do file viewer em disco |
| `_infer_tech_from_row()` | **Nova função** — inferência LTE/NR por regras de negócio Vivo (prefixo de célula, colunas NR, prefixo de site) |
| `_read_uploaded_table()` | **Nova função** — lê CSV/TXT/XLSX com detecção de encoding e delimitador |
| `_normalize_col_name()` | **Nova função** — normalização de nomes de colunas (case, acentos, símbolos) |
| `stream_parser_pipeline()` | **Nova função** — gerador que executa o pipeline completo de parsers |
| `_stream_run_script()` | **Nova função** — helper para executar scripts subprocess com streaming |
| `SCRIPT_DIR` resolution | Lógica melhorada para onefile Nuitka: usa `__file__` se `web-tool/` estiver ao lado, senão usa `exe_dir` |

### 5.2 `dump_multiple_enms.py` — mudanças

- `disable_proxy_env()`: chamada no início de `main()` para evitar `ProxyError`
- Logs de execução melhorados em 5 steps (Step 1/5 … Step 5/5)
- Polling de status com extração de progresso (`Nodes exported X / Expected Y`)
- Validação de pasta de saída (`ensure_writable_output_dir`) — encerra com erro claro se pasta não é gravável
- `clear_output_dir()`: limpa pasta de saída antes de novo dump

### 5.3 `parquet_to_txt.py` — mudanças

- `delete_file_with_retry()`: retry com backoff para locks transitórios no Windows (`WinError 5`)
- `os.chmod(path, 0o666)` antes de deletar para evitar problema de somente-leitura
- Liberação explícita de memória (`del df`, `gc.collect()`) após cada conversão

### 5.4 `web-tool/app.js` — mudanças principais

- **Update site list** agora tenta primeiro o backend `/api/update-site-list` (FormData com arquivos)
- Merge incremental: novo upload adiciona sites ao existente (não substitui)
- Helpers de normalização: `normalizeSiteRow()`, `dedupeAndSortSiteRows()`, `mergeSiteListRows()`
- **Multi-cidade** em Scope → By City: chips de cidade, botão Add, Clear cities
- Controles de UF dinâmicos: se site list carregado, UFs vêm do arquivo; senão, lista estática
- `refreshScopeUfControls()`: função centralizada de atualização dos controles de escopo
- Sync automático dump output → parser input: `Parser input synced to: <path>` no log
- `getSiteListSaveDir()` retorna `C:/Downloader/cellref` como default
- `tryAutoLoadSiteListFromBaseDir()`: auto-carrega `sites_list.txt` ao iniciar
- Inferência de base dir a partir de arquivos selecionados (`file.path`)
- `executeDump()` com `try/except` em torno do streaming e mensagens em inglês

### 5.5 `web-tool/index.html` — mudanças

- Update site list usa file picker (não só folder picker) — aceita `.csv,.txt,.xlsx,.xls`
- Controles de multi-cidade (chips, Add, Clear cities)
- Campo e botão de base dir para site list
- Parser pipeline: novos controles (Customize TXTs, Enriched dir, etc.)

### 5.6 `web-tool/file-viewer.js` — arquivo novo ou muito modificado

Viewer de arquivos com suporte a:
- Carregamento de arquivos TXT/CSV do servidor
- Navegação por abas de arquivos
- Exportação CSV/TXT/XLSX

### 5.7 `build_nuitka.ps1` — arquivo novo

Script de build completo para gerar `dist_nuitka/Downloader.exe`:
- Usa `venv_build` (venv separada e mínima, sem pyarrow/lxml)
- `--windows-console-mode=disable` (sem janela de prompt)
- `--nofollow-import-to=pandas.tests` (reduz tamanho do exe)
- Inclui todos os `.py` subprocess como data files
- Cria atalhos no Desktop e Start Menu
- Erros de startup vão para `downloader_error.log`

### 5.8 `requirements_build.txt` — arquivo novo

```
flask>=2.0
pandas
openpyxl
```
Apenas o que o `server_downloader.py` precisa diretamente.
**Não inclui:** pyarrow, lxml, xlsxwriter, enmscripting.

---

## 6. Checklist de verificação após atualizar

```
[ ] git pull rodou sem conflitos
[ ] requirements_build.txt existe
[ ] build_nuitka.ps1 existe
[ ] BUILD.bat existe
[ ] web-tool/file-viewer.js existe
[ ] server_downloader.py tem get_python_for_dump() com check de ../venv/
[ ] server_downloader.py tem stream_run_dump() com try/except externo
[ ] server_downloader.py tem /api/update-site-list, /api/save-site-list, /api/load-site-list
[ ] server_downloader.py tem /api/run-parser-pipeline
[ ] dump_multiple_enms.py tem disable_proxy_env()
[ ] parquet_to_txt.py tem delete_file_with_retry()
[ ] web-tool/app.js tem tryAutoLoadSiteListFromBaseDir()
[ ] web-tool/app.js tem mergeSiteListRows()
[ ] venv/ NÃO foi modificada/deletada
[ ] cellref/ NÃO foi modificada
[ ] data/ NÃO foi modificada
```

---

## 7. Como rodar na máquina de trabalho (sem compilar)

```bat
cd C:\Downloader
call venv\Scripts\activate
python server_downloader.py
```

Ou usar o `START_DOWNLOADER.bat`.

Abrir `http://localhost:8765` no browser.

---

## 8. Como compilar o exe na máquina de trabalho

**Pré-requisitos:**
- Python 3.9 instalado e no PATH
- Visual Studio Build Tools (compilador C, cl.exe)
- Nuitka será instalado automaticamente no `venv_build`

```powershell
cd C:\Downloader
powershell -ExecutionPolicy Bypass -File build_nuitka.ps1
```

Ou simplesmente executar `BUILD.bat`.

Output: `dist_nuitka\Downloader.exe` (~28 MB)

---

## 9. Observações para o Cursor

- **Nunca altere** `venv/`, `venv_build/`, `dist_nuitka/`, `cellref/`, `data/`, `arquivos/`
- O arquivo `CLAUDE.md` contém instruções detalhadas de arquitetura e lições de build — leia antes de modificar
- Os scripts subprocess (`dump_multiple_enms.py`, `parquet_to_txt.py`, etc.) **precisam** de Python com `enmscripting` instalado. O `enmscripting` é instalado a partir de um `.whl` da Ericsson — ver `INSTALL_ENMSCRIPTING.md`
- `enmscripting` **não vai no exe** — fica no Python do sistema ou no `venv`
- O `server_downloader.py` é o único arquivo compilado no exe; os demais scripts ficam como data files e rodam via Python externo
