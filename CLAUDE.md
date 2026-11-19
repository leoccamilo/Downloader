# CLAUDE.md — Guia de desenvolvimento do Downloader

## Estrutura do projeto

```
Downloader/
├── server_downloader.py      # Servidor Flask (porta 8765) — entry point principal
├── web-tool/                 # Frontend estático (index.html, app.js, file-viewer.js, styles.css)
├── dump_multiple_enms.py     # Script subprocess — dump ENM
├── xml_to_txt.py             # Script subprocess — XML/ZIP → TXT por MO (lê ZIP direto, sem extrair)
├── post_process_4_camilo.py  # Script subprocess — enriquecimento LTE FDD
├── post_process_5_tdd.py     # Script subprocess — enriquecimento TDD/FDD
├── post_process_6_5g.py      # Script subprocess — enriquecimento 5G NR
├── pos_processamento_claro.py # Script subprocess — "Process MOs" da Claro (cópia do MoB_Claro)
├── regras_claro.py           # Regras da rede Claro PR (cópia do MoB_Claro)
├── enm_dump_claro.py         # 7 funções do enm_dump.py do MoB_Claro (cópia sem alteração)
├── requirements.txt          # Dependências de desenvolvimento (inclui lxml, etc.)
├── requirements_build.txt    # Dependências do BUILD Nuitka (servidor + libs dos scripts)
├── worker_mode.py            # exe roda os scripts com o Python embutido (sem Python na máquina)
├── worker_imports.py         # tudo o que os scripts importam (para o Nuitka embutir)
├── build_nuitka.ps1          # Script de build Nuitka
├── venv/                     # venv de desenvolvimento (completa, com pyarrow/lxml/etc.)
├── venv_build/               # venv de build Nuitka (só requirements_build.txt + wheel do ENM)
└── dist_nuitka/              # Output do build — Downloader.exe
```

## Operadora (Vivo × Claro PR)

- `operator_profiles.py` é a fonte única das regras de operadora no servidor:
  pastas proibidas para cada uma, endpoints só-Vivo, raiz da Claro, cadastro
  de municípios. O `before_request` do `server_downloader.py` aplica a trava a
  todo POST `/api/*` (cabeçalhos `X-Downloader-Operator` e `X-Downloader-Claro-Root`,
  este com `encodeURIComponent`). Sem cabeçalho = Vivo.
- Na tela, `opStorage` (topo do `app.js`) separa as configurações: Vivo = chaves
  históricas sem prefixo (não renomear!), Claro = prefixo `claro:`. Elementos
  de uma operadora só: atributo `data-only="vivo|claro"` no HTML.
- Antes de habilitar qualquer fluxo para a Claro, ele precisa usar as regras
  da Claro (skill `claro-rede-pr`): mesma saída da Vivo, só muda a regra da rede.
  Base já validada no MoB_Claro (`regras_claro`, `pos_processamento_claro`,
  `cadastro_claro`, audits) — copiar para dentro do Downloader, nunca importar do MoB.
- Fase 3 (feita): `regras_claro.py`, `pos_processamento_claro.py` e `enm_dump_claro.py`
  copiados do MoB_Claro (commit b9a443e). Mudanças na cópia: imports locais, TXT lido
  em latin-1, linha de comando, geografia de `bundled_scripts/claro/` e trava de
  pasta com `operator_profiles.VIVO_ROOTS`. Na Claro, "Enrich Files" do servidor
  roda só este script (`customize_txts` + `enriched_dir` ≠ pasta dos TXT; sem
  `cellref_dir` = sem cadastro, nunca o cellref padrão da Vivo). Validação: rede
  inteira de PR (W42), 19 arquivos idênticos byte a byte ao original, com e sem
  cadastro. Ao trazer correção do MoB, comparar de novo do mesmo jeito.
- Fase 4 (feita): `cadastro_claro.py` (cellref da Claro = TXT da rede inteira + MANDO
  `mando_cells_<data>.csv`) copiado do MoB_Claro b9a443e, com `construir` sem alteração.
  Roda pela aba Cellrefs (rota `/api/run-claro-cellref`, recusada para a Vivo).
  Grava em `<raiz>/Cellref`, a mesma pasta que o "Process MOs" lê como cadastro
  (`getSiteListSaveDir()` no modo Claro). Validação na W42: 8 arquivos idênticos
  byte a byte ao original (ver `alteracoes.md`).
- Scripts novos que o servidor roda precisam de `--include-data-files` no
  `build_nuitka.ps1` (o Nuitka ignora `.py` soltos).
- Tema: variáveis `--marca*` em `styles.css`, trocadas por `html[data-operator]`;
  claro/escuro por `html[data-tema]` + `data-bs-theme`.

## Parser XML — por que é XML → TXT direto (sem Parquet)

Antes era `extract_dump.py` (extrai ZIP) → `xml_to_parquet.py` → `parquet_to_txt.py`.
O Parquet era só buffer temporário (apagado no fim) e o `parquet_to_txt` fazia
`pd.concat` de todas as partes na memória — anulando o "streaming".

Benchmark (dump real de 196 MB, 85 MOs): antigo 11,7 s / pico 590 MB;
`xml_to_txt.py` 5,5 s / pico 215 MB, TXTs **idênticos byte a byte**
(latin-1, CRLF, colunas na ordem de aparição). Também não precisa de pyarrow/pandas.

- ZIPs são lidos no lugar (`zipfile` + `iterparse` no stream) — sem extrair para disco.
- Memória limitada: quando o buffer passa de `_SPILL_BYTES` (tamanho estimado dos
  objetos Python, 64 MB), ele vai para um spool (`.xml_to_txt_spool/`, `marshal`) e
  cada `<MO>.txt` é montado no final. O limite é por **bytes**, não por linhas: linha
  de relação tem ~50 colunas e a de `EUtranCellFDD` centenas. Antes era 200 mil linhas,
  o que dava 1,36 GB de pico no dump de PR. A leitura do XML sozinha usa ~22 MB:
  quase toda a memória é o buffer. O momento do spool não muda o TXT (teste
  `SpillTests`). Dump semanal da Vivo inteiro (37,8 GB de XML, 90 MOs): pico
  436 → 120 MB, ~26 min, TXTs idênticos.
- Ao ler uma pasta, um ZIP cujo XML já está extraído ao lado é ignorado (evita linhas duplicadas).
- Se mexer no formato de saída, validar comparando SHA256 dos TXTs com a versão anterior:
  os `post_process_*.py` dependem desse formato.
- **Claro (validado em 18/11/2026):** no dump da rede inteira de PR (`PR_mob_W42.zip`,
  XML único de 4,2 GB) o `xml_to_txt.py` gerou os 21 MOs com conteúdo idêntico ao
  conversor do MoB_Claro (comparação por conteúdo; muda só ordem de colunas, encoding
  e colunas sempre vazias). ~3 min; pico de 142 MB de RAM. Para a Claro o
  servidor passa `--include-nr-relations`: mantém as 91.650 `EUtranCellRelation`
  sob `NRCellCU` (5G→4G, usadas no audit PSCell). Na Vivo o padrão continua 4G-only.
- O dump da Claro não tem nenhum caractere fora de ASCII; mesmo assim, código da Claro
  que ler estes TXT deve usar latin-1 (o encoding que o parser grava), não utf-8.

## Arquitetura: server vs subprocessos

O `server_downloader.py` é um servidor Flask que **não executa** os dumps diretamente.
Ele inicia subprocessos via `subprocess.Popen` (`[python, -u, script.py, args]`): assim
cada etapa pode ser cancelada, libera a memória ao terminar e o log sai ao vivo.

**O exe não precisa de Python na máquina (desde 2026-11-19), como o MoB_Tool_Box.**
Dentro do exe, `get_python_for_dump()` devolve o PRÓPRIO `Downloader.exe`. O launcher
chama primeiro `worker_mode.maybe_run_worker()`: se recebeu `[-u] <script>.py args`, roda o
script com o Python embutido (`runpy`, `__main__`, `sys.argv`, código de saída) e sai; senão
sobe o servidor. Os scripts continuam data files (`--include-data-files`), sem mudança.
- `worker_imports.py` lista TUDO o que os scripts e notebooks importam (o Nuitka só embute o
  que vê importado). `tests/test_worker_mode.py` varre scripts + `bundled_scripts` e falha se
  faltar algum. Script novo com import novo → acrescentar lá.
- `enmscripting` quebra no exe (lê o próprio fonte com `inspect.stack()`): o worker instala o
  mesmo calço do MoB (`install_enmscripting_shim`) antes de rodar o script.
- Nuitka 4.3.5 não define `sys.frozen` e `sys.executable` aponta para um python.exe inexistente
  no temp: use `_is_compiled()` / `_real_exe()` / `_exe_dirs()` do servidor, nunca `sys.executable`.

Fora do exe (código-fonte), `get_python_for_dump()` usa `python_embed/`, `venv/` ou o Python do sistema.

## Build com Nuitka

### Pré-requisitos
- Executar do diretório `C:\Downloader`
- Python 3.9 instalado e no PATH
- Visual Studio Build Tools (compilador C)

### Comando
```powershell
powershell -ExecutionPolicy Bypass -File build_nuitka.ps1
```

### O que o script faz
1. Cria/usa `venv_build` (só `requirements_build.txt`, nada da venv de dev)
2. Instala `requirements_build.txt` (servidor + libs dos scripts: pandas, openpyxl,
   xlsxwriter, lxml, pyarrow, haversine, requests) e o wheel do enmscripting
   (`C:\Tools\enm_client_scripting-1.22.2-...whl`; sem ele o build para)
3. Verifica que `import worker_imports` funciona na venv_build
4. Cria `launcher.py` temporário (modo worker primeiro, depois o servidor)
5. Compila com Nuitka → `dist_nuitka/Downloader.exe`
6. Limpa launcher.py temporário

### Output
- `dist_nuitka/Downloader.exe` (~46 MB, sem Python na máquina; era ~28 MB quando dependia do Python instalado)
- Atalho no Start Menu criado automaticamente
- **Depois de todo build, testar um subprocesso pelo exe** (parser, cellref) numa pasta isolada
  e com PATH sem Python: o exe abre normal mesmo quando nada roda por trás.

---

## ⚠️ LIÇÕES APRENDIDAS — problemas de tamanho do exe

### Problema 1: pyarrow inflando o exe (+16 MB)
**Causa:** pyarrow estava na `venv` de dev. O Nuitka o incluía porque pandas
faz imports opcionais de pyarrow. Como pyarrow inclui DLLs Arrow (21 MB),
arrow_compute (9.9 MB), parquet (6 MB), etc., o exe ficava com 62 MB.

**Solução:** usar `venv_build` separada com apenas `requirements_build.txt`
(sem pyarrow, lxml, xlsxwriter). Nuitka só vê o que está na venv ativa.

**Nunca usar a `venv` completa para o build Nuitka.**

**Atualização 2026-11-19:** pyarrow, lxml e xlsxwriter voltaram ao exe **de propósito**: o exe
passou a rodar os scripts sem Python na máquina e a rotina semanal usa `string[pyarrow]`.
Custo medido: 28,8 → ~46 MB. A regra da venv_build mínima continua (só o que os scripts usam).

---

### Problema 2: pandas.tests inflando o exe (+18 MB comprimido)
**Causa:** `--follow-import-to=pandas` faz o Nuitka seguir TODOS os imports
de pandas, incluindo `pandas.tests` (suíte de testes com milhares de arquivos).
Isso aumentou o launcher.dll de 73 MB para 139 MB não comprimidos.

**Sintoma no log do Nuitka:**
```
WARNING: anti-bloat: Undesirable import of 'pydoc' in 'pandas.tests.series.test_api'
```
1915 arquivos C compilados em vez de ~800.

**Solução:** flags `--nofollow-import-to` explícitos no build:
```powershell
--nofollow-import-to=pandas.tests
--nofollow-import-to=pandas.io.tests
--nofollow-import-to=numpy.testing
--nofollow-import-to=numpy.tests
--nofollow-import-to=numpy.distutils
--nofollow-import-to=doctest
--nofollow-import-to=unittest
```

**Resultado:** 1915 → 799 arquivos C, exe de 46.7 MB → 28.5 MB.

`pydoc` saiu da lista em 2026-11-19: `pyarrow.compute` o importa, e com pyarrow no exe o
`import pandas` quebrava ("Module 'pydoc' was actively excluded"). É pequeno; quem inflava
era o `pandas.tests`. Para conferir antes de compilar:
`venv_build\Scripts\python -X importtime -c "import worker_imports"` e procurar módulos excluídos.

---

### Problema 3: numpy<2.0 é PIOR que numpy 2.0
**Causa:** intuição errada de que numpy 1.x seria menor.
Na prática, numpy 1.26.4 tem OpenBLAS de **37 MB** no Windows,
enquanto numpy 2.0.2 tem **32 MB**. Numpy 2.x usa uma versão otimizada menor.

**Solução:** não pinnar numpy<2.0 no requirements_build.txt. Deixar o pandas
resolver a versão (que será numpy 2.x).

---

### Problema 4: --lto=yes aumenta o tamanho no Windows/MSVC
**Causa:** LTO (Link Time Optimization) no MSVC otimiza para velocidade, não tamanho.
Com cl.exe, `--lto=yes` aumentou o exe de 46.2 MB para 48.5 MB.

**Solução:** não usar `--lto=yes` no Windows com MSVC.

---

### Referência de tamanhos (para diagnóstico futuro)

| Componente (descomprimido) | Tamanho | Pode remover? |
|---|---|---|
| launcher.dll (código compilado) | ~50 MB | Não |
| numpy.libs (OpenBLAS) | 32 MB | Não (necessário para numpy) |
| pandas (módulos) | 17 MB | Não |
| numpy (módulos) | 6.6 MB | Não |
| python39.dll | 4.3 MB | Não |
| libcrypto-1_1.dll | 3.3 MB | Não |
| pytz + tzdata (zoneinfo) | 3.5 MB | Possível (604 arquivos) |
| **pandas.tests** | **~70 MB** | **SIM — `--nofollow-import-to=pandas.tests`** |
| pyarrow (arrow.dll etc.) | ~47 MB | Não desde 2026-11-19 (rotina semanal no exe) |
| lxml | 6.6 MB | Não desde 2026-11-19 (parser XML no exe) |

---

### Regra geral para builds Nuitka com pandas

Sempre adicionar ao comando Nuitka quando incluir pandas:
```powershell
--nofollow-import-to=pandas.tests
--nofollow-import-to=numpy.testing
--nofollow-import-to=numpy.tests
--nofollow-import-to=doctest
--nofollow-import-to=unittest
```
(`pydoc` só pode ser excluído se nenhuma lib embutida o importar — o pyarrow importa.)

E sempre usar uma **venv de build separada e mínima** (não a venv de dev).
