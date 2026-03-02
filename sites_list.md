# Sites List – Correlação UF ↔ Município

## Objetivo

O Downloader possui um mecanismo de escopo de sites baseado em um arquivo `sites_list.txt`. A partir dele, o usuário pode filtrar a lista de sites por **UF** e, dentro daquela UF, por **Município**, com autocomplete. A correlação é dinâmica: ao selecionar uma UF, apenas os municípios daquela UF aparecem.

---

## 1. Formato do `sites_list.txt`

Arquivo TSV (tab-separated), encoding **UTF-8**, com header obrigatório:

```
Regional\tUF\tMUNICIPIO\tSiteID\tTech
```

| Coluna     | Descrição                                     | Exemplo          |
|------------|-----------------------------------------------|------------------|
| Regional   | Nome da regional                               | BASE             |
| UF         | Sigla do estado (uppercase)                    | BA               |
| MUNICIPIO  | Nome do município                              | SALVADOR         |
| SiteID     | Identificador do site (eNB para LTE)           | TPPF1_BA         |
| Tech       | Tecnologia: `LTE` ou `NR`                     | LTE              |

Gerado por `update_site_list.py` a partir de `cellref/EUtranCell_TDD_FDD.csv` (LTE) e `cellref/Cellref_5G*.csv` (NR). Também pode ser gerado pela própria UI (botão "Select folder and update").

---

## 2. Carregamento no Frontend

Existem duas formas de popular a variável global `siteListData` (array de objetos):

### a) Load de arquivo existente (`loadSiteListFile`)

```javascript
// web-tool/app.js – linha ~269
function loadSiteListFile() {
  const file = document.getElementById('site-list-file').files[0];
  const reader = new FileReader();
  reader.onload = function () {
    siteListData = parseSiteListTSV(reader.result);
    // Popula o dropdown de UF
    const ufSelect = document.getElementById('scope-uf-select');
    const ufs = [...new Set(siteListData.map(r => r.UF.toUpperCase()).filter(Boolean))].sort();
    ufSelect.innerHTML = '<option value="">-- UF --</option>'
      + ufs.map(u => `<option value="${u}">${u}</option>`).join('');
  };
  reader.readAsText(file, 'UTF-8');
}
```

### b) Build a partir de pasta (`updateSiteListFromFolder`)

Lê CSVs da pasta selecionada, constrói `siteListData` em memória e popula o dropdown de UF da mesma forma.

### Parser TSV

```javascript
// web-tool/app.js – linha ~254
function parseSiteListTSV(text) {
  const lines = text.replace(/^\uFEFF/, '').trim().split(/\r?\n/).filter(l => l.trim());
  const header = lines[0].split('\t').map(h => h.trim());
  const rows = [];
  for (let i = 1; i < lines.length; i++) {
    const cells = lines[i].split('\t');
    const row = {};
    header.forEach((h, j) => { row[h] = (cells[j] || '').trim(); });
    rows.push(row);
  }
  return rows; // Array de { Regional, UF, MUNICIPIO, SiteID, Tech }
}
```

---

## 3. Correlação UF → Município (lógica principal)

### HTML (index.html – Scope card, ~165–188)

Quando o radio "By Municipality" está selecionado, aparece:

- **`#scope-uf-select`**: dropdown de UFs (populado no load do site list)
- **`#scope-municipality-input`**: campo texto com `<datalist>` para autocomplete
- **`#municipality-datalist`**: datalist preenchido dinamicamente
- Checkboxes **LTE** e **NR** para filtrar por tecnologia
- **`#scope-municipality-count`**: contador de sites selecionados

### Evento: ao mudar a UF ou digitar município

```javascript
// web-tool/app.js – linha ~1128–1136
scopeUfSelect.addEventListener('change', updateMunicipalityDatalist);
scopeMunInput.addEventListener('input', updateMunicipalityDatalist);
scopeMunInput.addEventListener('change', updateMunicipalityCount);
```

### `updateMunicipalityDatalist()` – Filtra municípios pela UF

```javascript
// web-tool/app.js – linha ~343
function updateMunicipalityDatalist() {
  const uf = document.getElementById('scope-uf-select').value.trim().toUpperCase();
  const q = document.getElementById('scope-municipality-input').value.trim().toUpperCase();
  const list = document.getElementById('municipality-datalist');
  list.innerHTML = '';
  if (!uf || siteListData.length === 0) return;

  // Filtra siteListData: só registros da UF selecionada que contenham o texto digitado
  const matches = [...new Set(
    siteListData
      .filter(r => r.UF.toUpperCase() === uf && r.MUNICIPIO.toUpperCase().includes(q))
      .map(r => r.MUNICIPIO.trim())
      .filter(Boolean)
  )].sort();

  // Popula o datalist (máx 100 opções)
  matches.slice(0, 100).forEach(m => {
    const opt = document.createElement('option');
    opt.value = m;
    list.appendChild(opt);
  });
  updateMunicipalityCount();
}
```

### `getSitesString()` – Gera a string de sites para o scope "municipality"

```javascript
// web-tool/app.js – linha ~308
if (scope === 'municipality') {
  const uf = document.getElementById('scope-uf-select').value.trim().toUpperCase();
  const mun = document.getElementById('scope-municipality-input').value.trim();
  const lte = document.getElementById('scope-tech-lte').checked;
  const nr = document.getElementById('scope-tech-nr').checked;
  if (!uf || !mun) return '';

  const filtered = siteListData.filter(r => {
    if (r.UF.toUpperCase() !== uf) return false;
    if (!r.MUNICIPIO.toUpperCase().includes(mun.toUpperCase())) return false;
    const tech = r.Tech.toUpperCase();
    if (tech === 'LTE' && !lte) return false;
    if (tech === 'NR' && !nr) return false;
    return true;
  });

  return [...new Set(filtered.map(r => r.SiteID.trim()).filter(Boolean))].join(';');
}
```

---

## 4. Fluxo Completo

```
sites_list.txt (TSV)
        │
        ▼
  parseSiteListTSV()  →  siteListData = [{ Regional, UF, MUNICIPIO, SiteID, Tech }, ...]
        │
        ├─ Popula #scope-uf-select  →  UFs únicas ordenadas
        │
        ▼
  Usuário seleciona UF  →  change event  →  updateMunicipalityDatalist()
        │
        ├─ Filtra siteListData por UF selecionada
        ├─ Extrai municípios únicos (com filtro de texto digitado)
        └─ Popula #municipality-datalist (autocomplete)
                │
                ▼
  Usuário seleciona município  →  getSitesString()
        │
        ├─ Filtra siteListData por UF + MUNICIPIO + Tech (LTE/NR)
        ├─ Extrai SiteIDs únicos
        └─ Retorna "SITE1;SITE2;SITE3;..."
                │
                ▼
  generateEnmCommand()  →  cmedit -n <sites_string> ...
```

---

## 5. Estrutura de Arquivos

| Arquivo | Papel |
|---------|-------|
| `cellref/sites_list.txt` | Dados TSV com Regional/UF/MUNICIPIO/SiteID/Tech |
| `update_site_list.py` | Gera `sites_list.txt` a partir de CSVs do cellref |
| `web-tool/index.html` | UI: cards "Site List" e "Scope" com dropdowns e datalist |
| `web-tool/app.js` | Lógica: parse TSV, correlação UF→Município, geração de sites_string |
| `server_downloader.py` | Recebe config com `sites_string` pronto; não faz filtragem |

---

## 6. Regras Importantes

- A correlação UF ↔ Município vem **exclusivamente** do `siteListData` (dados do `sites_list.txt`).
- O dropdown de UF (`#scope-uf-select`) é populado com as UFs **presentes no arquivo**, não de uma lista fixa.
- O datalist de municípios é **refeito a cada mudança** de UF ou de texto digitado.
- O filtro de município usa `.includes()` (busca parcial, case-insensitive).
- `getSitesString()` retorna SiteIDs separados por `;` para montar o comando cmedit.
- O servidor (`server_downloader.py`) **não** participa da filtragem; recebe a string de sites já montada.
