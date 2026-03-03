# CLAUDE.md — Guia de desenvolvimento do Downloader

## Estrutura do projeto

```
Downloader/
├── server_downloader.py      # Servidor Flask (porta 8765) — entry point principal
├── web-tool/                 # Frontend estático (index.html, app.js, file-viewer.js, styles.css)
├── dump_multiple_enms.py     # Script subprocess — dump ENM
├── parquet_to_txt.py         # Script subprocess — converte parquet → txt
├── xml_to_parquet.py         # Script subprocess — converte XML → parquet
├── extract_dump.py           # Script subprocess — extrai ZIPs
├── post_process_4_camilo.py  # Script subprocess — enriquecimento LTE FDD
├── post_process_5_tdd.py     # Script subprocess — enriquecimento TDD/FDD
├── post_process_6_5g.py      # Script subprocess — enriquecimento 5G NR
├── requirements.txt          # Dependências de desenvolvimento (inclui pyarrow, lxml, etc.)
├── requirements_build.txt    # Dependências do BUILD Nuitka (apenas o que o server usa)
├── build_nuitka.ps1          # Script de build Nuitka
├── venv/                     # venv de desenvolvimento (completa, com pyarrow/lxml/etc.)
├── venv_build/               # venv de build Nuitka (mínima — NÃO tem pyarrow/lxml)
└── dist_nuitka/              # Output do build — Downloader.exe
```

## Arquitetura: server vs subprocessos

O `server_downloader.py` é um servidor Flask que **não executa** os dumps diretamente.
Ele inicia subprocessos via `subprocess.Popen`, que rodam com um Python separado.

**A função `get_python_for_dump()`** resolve qual Python usar para os subprocessos:
1. `python_embed/python.exe` (pasta ao lado do .exe — distribuição portátil)
2. `venv/Scripts/python.exe`
3. Python do sistema (`shutil.which("python")`)
4. `sys.executable` (fallback)

**Consequência:** os scripts subprocess (`dump_multiple_enms.py`, etc.) **NÃO precisam**
estar compilados no exe. Eles são incluídos como data files e executados pelo Python do sistema.

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
1. Cria/usa `venv_build` (venv limpa, sem pyarrow/lxml)
2. Instala apenas `requirements_build.txt` (flask, pandas, openpyxl)
3. Verifica que pyarrow NÃO está na venv_build (sanity check)
4. Cria `launcher.py` temporário
5. Compila com Nuitka → `dist_nuitka/Downloader.exe`
6. Limpa launcher.py temporário

### Output
- `dist_nuitka/Downloader.exe` (~28 MB)
- Atalho no Start Menu criado automaticamente

---

## ⚠️ LIÇÕES APRENDIDAS — problemas de tamanho do exe

### Problema 1: pyarrow inflando o exe (+16 MB)
**Causa:** pyarrow estava na `venv` de dev. O Nuitka o incluía porque pandas
faz imports opcionais de pyarrow. Como pyarrow inclui DLLs Arrow (21 MB),
arrow_compute (9.9 MB), parquet (6 MB), etc., o exe ficava com 62 MB.

**Solução:** usar `venv_build` separada com apenas `requirements_build.txt`
(sem pyarrow, lxml, xlsxwriter). Nuitka só vê o que está na venv ativa.

**Nunca usar a `venv` completa para o build Nuitka.**

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
--nofollow-import-to=pydoc
--nofollow-import-to=doctest
--nofollow-import-to=unittest
```

**Resultado:** 1915 → 799 arquivos C, exe de 46.7 MB → 28.5 MB.

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
| **pyarrow (arrow.dll etc.)** | **~47 MB** | **SIM — usar venv_build sem pyarrow** |
| **lxml** | **6.6 MB** | **SIM — usar venv_build sem lxml** |

---

### Regra geral para builds Nuitka com pandas

Sempre adicionar ao comando Nuitka quando incluir pandas:
```powershell
--nofollow-import-to=pandas.tests
--nofollow-import-to=numpy.testing
--nofollow-import-to=numpy.tests
--nofollow-import-to=pydoc
--nofollow-import-to=doctest
--nofollow-import-to=unittest
```

E sempre usar uma **venv de build separada e mínima** (não a venv de dev).
