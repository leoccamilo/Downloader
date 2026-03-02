# NR Neighbor Viewer - Data Model Rules

## 1. Nomenclatura de Sites e Células

### 1.1. Site 4G (eNB)
- **Formato**: `{Prefixo}{SiteCode}{Número}_{UF}`
- **Prefixos válidos**: `T` ou `M` (nunca `S`)
- **Exemplos**:
  - `M1741_AM` (Prefixo=M, SiteCode=1741, UF=AM)
  - `MFJI2_AM` (Prefixo=M, SiteCode=FJI2, UF=AM)
  - `TFJI1_AM` (Prefixo=T, SiteCode=FJI1, UF=AM)
  - `TOTM1_PA` (Prefixo=T, SiteCode=OTM1, UF=PA)
- **Nota**: Múltiplos eNBs podem existir no mesmo local físico (ex: MFJI2_AM e TFJI1_AM)
- **Nota**: Sites 4G NUNCA começam com `S` (diferente de 5G)

### 1.2. Site 5G (gNB)
- **Formato**: `{Prefixo}{SiteCode}{Número}_{UF}` (igual ao 4G)
- **Prefixos válidos**: `M` ou `S` (nunca `T`)
- **Exemplos**:
  - `MAAT1_AM` (gNB com células 5SAAT11, 5SAAT12, 5SAAT13)
  - `MFJI2_AM` (gNB com células 5SFJI21, 5SFJI22, 5SFJI23)
  - `SINM1_AM` (gNB com células 5SINM11, 5SINM12, 5SINM13) ← **Prefixo S**
- **Coluna no arquivo**: `eNB` (mesmo nome para 4G e 5G nos dumps)
- **Nota**: Sites 5G NUNCA começam com `T` (diferente de 4G)

### 1.3. Célula 4G (EUtranCell)
- **Formato**: `{BandPrefix}{SiteCode}{Setor}`
- **BandPrefix indica a frequência**:
  - `T` = LTE 2600 TDD
  - `Q` = LTE 2600 TDD
  - `U` = LTE 2100 FDD
  - `V` = LTE 1800 FDD
  - `Z` = LTE 700 FDD
  - `P` = LTE 2600 TDD
  - `Y` = LTE 850 FDD
  - `C` = LTE 1800 FDD
  - `O` = LTE 2300 TDD
  - `L` = LTE 2300 TDD
- **Exemplos**:
  - `T17411` = Band T, Site 1741, Setor 1
  - `ZFJI11` = Band Z, Site FJI1, Setor 1
  - `UFJI12` = Band U, Site FJI1, Setor 2
- **Setor**: Último dígito (1, 2, 3). Setores 4-9 mapeiam para 1-3.

### 1.4. Célula 5G (NRCellCU/NRCellDU)
- **Formato**: `{FreqPrefix}{SiteCode}{Setor}`
- **Prefixos válidos** (associados à frequência DL_NR_ARFCN):
  - `5S` = NR n78 (3.5 GHz) - **principal no Brasil**
  - `5O` = NR n78 (outra configuração)
- **Prefixos DSS (descartados - não ativados na rede)**:
  - `5R`, `5U`, `5Z` = Dynamic Spectrum Sharing (filtrados)
- **Filtro no código**:
  ```python
  # Expurgar DSS
  NRCellDU = NRCellDU[~NRCellDU['nRCellDUId'].str[0:2].isin(['5R', '5U', '5Z'])]
  ```
- **Exemplos válidos**:
  - `5SAAT13` = Site AAT1, Setor 3
  - `5SFJI21` = Site FJI2, Setor 1
  - `5SINM11` = Site INM1, Setor 1 (gNB = SINM1_AM)
- **Setor**: Último dígito (sempre 1, 2 ou 3 para células 5G)

## 2. Site Key (Chave de Co-site)

### 2.1. Fórmula
```
site_key = UF + eNB[1:4]
```
- **UF**: Últimos 2 caracteres após o `_` (ex: AM, PA, SP)
- **eNB[1:4]**: Caracteres nas posições 1, 2, 3 do nome do site (índices Python: `eNB[1:4]`)

### 2.2. Exemplos
| Site (eNB/gNB) | UF  | eNB[1:4] | site_key |
|----------------|-----|----------|----------|
| M1741_AM       | AM  | 174      | AM174    |
| MFJI2_AM       | AM  | FJI      | AMFJI    |
| TFJI1_AM       | AM  | FJI      | AMFJI    |
| MARB2_AM       | AM  | ARB      | AMARB    |
| TOTM1_PA       | PA  | OTM      | PAOTM    |
| SINM1_AM       | AM  | INM      | AMINM    |

### 2.3. Co-sites
Sites com o **mesmo site_key** estão no mesmo local físico:
- `MFJI2_AM` e `TFJI1_AM` → ambos têm site_key `AMFJI`
- Isso significa que são eNBs diferentes no mesmo site

### 2.4. Merge entre DataFrames 4G e 5G
**REGRA CRÍTICA**: Para fazer merge entre dataframes 4G e 5G, usar:
```python
# Criar site_key em ambos os dataframes
df_4g['site_key'] = df_4g['UF'] + df_4g['eNB'].str[1:4]
df_5g['site_key'] = df_5g['UF'] + df_5g['eNB'].str[1:4]

# Merge por site_key (e setor normalizado para co-setores)
merged = pd.merge(df_4g, df_5g, on=['site_key', 'setor_normalizado'])
```

**NÃO usar**:
- ❌ `eNB` diretamente (diferentes prefixos: T/M para 4G, M/S para 5G)
- ❌ `Cellname` (nomenclaturas diferentes)

**Usar**:
- ✅ `site_key` = UF + eNB[1:4]
- ✅ `setor_normalizado` para match de direção física

## 3. Regra de Setores e Normalização

### 3.1. Extração do Setor
O setor é **sempre** o último caractere do nome da célula:
```
Setor = RIGHT(CELL, 1)
```

### 3.2. Normalização de Setores
Células 4G podem ter setores de 1 a 9, mas representam apenas 3 direções físicas.
A normalização mapeia para o setor físico real:

| Setor Raw | Setor Normalizado | Fórmula |
|-----------|-------------------|---------|
| 1         | 1                 | - |
| 2         | 2                 | - |
| 3         | 3                 | - |
| 4         | 1                 | 4 - 3 = 1 |
| 5         | 2                 | 5 - 3 = 2 |
| 6         | 3                 | 6 - 3 = 3 |
| 7         | 1                 | 7 - 6 = 1 |
| 8         | 2                 | 8 - 6 = 2 |
| 9         | 3                 | 9 - 6 = 3 |

**Código Python**:
```python
def get_setor(cell_name: str) -> int:
    setor = int(cell_name[-1])
    if setor in [4, 5, 6]:
        return setor - 3
    elif setor in [7, 8, 9]:
        return setor - 6
    return setor
```

### 3.3. Exemplo Prático - Site TOTM1_PA

| eNB | CELL | Setor Raw | Setor Normalizado | Banda |
|-----|------|-----------|-------------------|-------|
| TOTM1_PA | UOTM11 | 1 | 1 | U (2100 FDD) |
| TOTM1_PA | UOTM12 | 2 | 2 | U (2100 FDD) |
| TOTM1_PA | UOTM13 | 3 | 3 | U (2100 FDD) |
| TOTM1_PA | UOTM14 | 4 | **1** | U (2100 FDD) |
| TOTM1_PA | UOTM15 | 5 | **2** | U (2100 FDD) |
| TOTM1_PA | UOTM16 | 6 | **3** | U (2100 FDD) |
| TOTM1_PA | VOTM11 | 1 | 1 | V (1800 FDD) |
| TOTM1_PA | VOTM12 | 2 | 2 | V (1800 FDD) |
| TOTM1_PA | VOTM13 | 3 | 3 | V (1800 FDD) |
| TOTM1_PA | VOTM14 | 4 | **1** | V (1800 FDD) |
| TOTM1_PA | VOTM15 | 5 | **2** | V (1800 FDD) |
| TOTM1_PA | VOTM16 | 6 | **3** | V (1800 FDD) |

**Observação**: Células como `UOTM14` e `VOTM14` são **co-setores** - mesma direção física (setor 1), bandas diferentes.

### 3.4. Células 5G - Setores Sempre 1, 2 ou 3
Células 5G **sempre** têm setor raw = 1, 2 ou 3 (não há setores 4-9 em 5G):
- `5SOTM11` = Setor 1
- `5SOTM12` = Setor 2
- `5SOTM13` = Setor 3

### 3.5. Regra de Co-setor 4G ↔ 5G
Uma célula 4G é **co-setor** de uma célula 5G quando:
1. Mesmo `site_key` (UF + eNB[1:4])
2. Mesmo `setor normalizado`

**Exemplo**:
- `UOTM16` (4G): site_key=`PAOTM`, setor_normalizado=**3**
- `5SOTM13` (5G): site_key=`PAOTM`, setor=**3**
- ✅ São co-setores!

**IMPORTANTE**: Múltiplas células 4G podem ser co-setor da mesma célula 5G (bandas diferentes):
- `UOTM13`, `UOTM16`, `VOTM13`, `VOTM16` → todas co-setor de `5SOTM13`

## 4. Mapeamento Co-site 4G ↔ 5G

### 4.1. Lookup por (site_key, setor_normalizado)
```python
# Para encontrar célula 5G do co-setor:
site_setor_to_5g[(site_key, setor_normalizado)] → nRCellCUId (única)

# Para encontrar células 4G do co-setor (múltiplas por bandas):
site_setor_to_4g[(site_key, setor_normalizado)] → [lista de Cellname_4G]
```

**IMPORTANTE**: O lookup deve usar `setor_normalizado` (não raw) para garantir match correto.

### 4.2. Exemplo para site AMFJI
| site_key | setor | 4G (várias bandas)          | 5G            |
|----------|-------|-----------------------------| --------------|
| AMFJI    | 1     | ZFJI11, TFJI11, UFJI11, VFJI11, ZFJI14, TFJI14, UFJI14, VFJI14 | 5SFJI21 |
| AMFJI    | 2     | ZFJI12, TFJI12, UFJI12, VFJI12, ZFJI15, TFJI15, UFJI15, VFJI15 | 5SFJI22 |
| AMFJI    | 3     | ZFJI13, TFJI13, UFJI13, VFJI13, ZFJI16, TFJI16, UFJI16, VFJI16 | 5SFJI23 |

**Nota**: Células com setor raw 4, 5, 6 também pertencem aos setores normalizados 1, 2, 3.

### 4.3. LTE Only (Regra por SITE, não por setor)
Um site 4G é **LTE Only** quando o **SITE** não tem **NENHUM** setor 5G:
- Verificação: `site_key not in sites_with_5g`
- Se o site tem **pelo menos 1 setor 5G**, **NENHUMA** célula desse site é LTE Only

**IMPORTANTE**: NÃO existe "setor LTE Only". A regra é por SITE completo.

**Exemplo CORRETO**:
| site_key | Setores 5G | Célula 4G | LTE Only? |
|----------|------------|-----------|-----------|
| AMVDB    | 1, 2       | VVDB11    | ❌ Não (site tem 5G) |
| AMVDB    | 1, 2       | VVDB13    | ❌ Não (site tem 5G, mesmo sem 5G no setor 3) |
| AMVDB    | 1, 2       | VVDB14    | ❌ Não (site tem 5G) |
| AMXYZ    | (nenhum)   | VXYZ11    | ✅ Sim (site não tem 5G) |

**Código**:
```python
# LTE Only = o SITE não tem NENHUM setor 5G
lte_only = site_key not in sites_with_5g
```

### 4.4. Implementação do Lookup (Correção v1.2.0)
```python
def build_cosite_lookups(cells_4g_df, nrcelldu_df):
    # IMPORTANTE: Usar setor NORMALIZADO, não raw
    site_setor_to_4g = defaultdict(list)  # Lista para múltiplas bandas
    site_setor_to_5g = {}                 # Única célula 5G por setor

    # 4G cells
    for _, row in cells_4g_df.iterrows():
        site_key = get_cosite_key_vivo(row['eNB'], row['UF'])
        setor = get_setor(row['CELL'])  # ← NORMALIZADO!
        site_setor_to_4g[(site_key, setor)].append(row['CELL'])

    # 5G cells
    for _, row in nrcelldu_df.iterrows():
        site_key = get_cosite_key_vivo(row['eNB'], row['UF'])
        setor = get_setor(row['nRCellDUId'])  # ← Sempre 1, 2 ou 3
        site_setor_to_5g[(site_key, setor)] = row['nRCellDUId']

    return site_setor_to_4g, site_setor_to_5g
```

## 5. Arquivos de Dados

### 5.1. Dumps do OSS (C:\MoB\Dumps_txt\)
| Arquivo | Conteúdo | Colunas Principais |
|---------|----------|-------------------|
| 5G_NRCellCU.txt | Células 5G | eNB (gNB), nRCellCUId, gNBId, nRFrequency, cellLocalId, nCI |
| 5G_NRCellDU.txt | Dados RF 5G | nRCellDUId, nRPCI, ssbFrequency |
| 5G_NRCellRelation.txt | Vizinhas 5G-5G existentes | nRCellCUId, neighborCellRef |
| 5G_GUtranCellRelation.txt | Vizinhas 4G-5G existentes | EUtranCellTDD/FDD, nRCellRef |
| 5G_TermPointToGNodeB.txt | TermPoints 5G-5G | gNBId_src, gNBId_tgt |
| 5G_TermPointToGNB.txt | TermPoints 4G-5G | eNB, gNBId_tgt |
| EUtranCell_TDD_FDD.csv | Células 4G (cluster) | eNB, CELL |
| AddressIPv4.txt | IPs X2 | Site, IP_Address |

### 5.2. Coordenadas (C:\MoB\MOs_One_Drive\)
| Arquivo | Conteúdo | Colunas Principais |
|---------|----------|-------------------|
| cellref_5g.xlsx | Coordenadas 5G | SiteID (gNB), Cellname, Latitude, Longitude, Azimuth |
| EUtranCell_TDD_FDD.csv | Coordenadas 4G | eNB, CELL, Latitude, Longitude, Azimute, Tipo (FDD/TDD) |

### 5.3. Outputs do MoB (C:\MoB\Outputs\)
| Arquivo | Conteúdo |
|---------|----------|
| Missing_NRCellRelation.xlsx | Vizinhas 5G-5G a criar |
| NRCellRelation_deletar.xlsx | Vizinhas 5G-5G a deletar |
| Missing_GUtranCellRelation.xlsx | Vizinhas 4G-5G a criar |
| GUtranCellRelation_deletar.xlsx | Vizinhas 4G-5G a deletar |

## 6. Relações de Vizinhança

### 6.1. GUtranCellRelation (4G → 5G)
- **Source**: Célula 4G (EUtranCell) - ex: `TRTT12`
- **Target**: Célula 5G (NRCellCU) - ex: `5SARB21`
- **Direção**: **UNIDIRECIONAL** (apenas 4G → 5G)
- **TermPoint**: TermPointToGNB (eNB → gNB)
- **Nota**: A volta (5G → 4G) seria EUtranCellRelation, que é outro MO (não implementado ainda)

### 6.2. NRCellRelation (5G → 5G)
- **Source**: Célula 5G (NRCellCU) - ex: `5SAAT11`
- **Target**: Célula 5G (NRCellCU) - ex: `5SFJI21`
- **Direção**: **BIDIRECIONAL** (cria A→B e B→A)
- **TermPoint**: TermPointToGNodeB (gNB → gNB)

### 6.3. Verificação de Pares Existentes (v1.2.0)
Antes de criar um par Missing, o sistema verifica no arquivo TXT correspondente se já existe:

| Tipo de Relação | Arquivo TXT Verificado | Variável no Código | Direção |
|-----------------|------------------------|-------------------|---------|
| GUtranCellRelation | `5G_GUtranCellRelation.txt` | `gutrancell_neighbor_index` | 4G→5G (unidirecional) |
| TermPointToGNB | `5G_TermPointToGNB.txt` | `existing_termpoints_to_gnb` | eNB→gNB (unidirecional) |
| NRCellRelation | `5G_NRCellRelation.txt` | `neighbor_index` | 5G↔5G (bidirecional) |
| TermPointToGNodeB | `5G_TermPointToGNodeB.txt` | `existing_termpoints` | gNB↔gNB (bidirecional) |

**Fluxo de Verificação**:
```python
# GUtranCellRelation (4G→5G) - UNIDIRECIONAL
src_neighbors = gutrancell_neighbor_index.get(src_4g, set())
if tgt_5g not in src_neighbors:
    # Criar par (não existe)

# NRCellRelation (5G→5G) - BIDIRECIONAL
# Verifica IDA
src_neighbors = neighbor_index.get(src_5g, set())
if tgt_5g not in src_neighbors:
    # Criar IDA
# Verifica VOLTA
tgt_neighbors = neighbor_index.get(tgt_5g, set())
if src_5g not in tgt_neighbors:
    # Criar VOLTA
```

## 7. Formato do Export GUtranCellRelation

### 7.1. Colunas Obrigatórias
| Coluna | Origem | Exemplo |
|--------|--------|---------|
| UF | eNB[-2:] | AM |
| MUNICIPIO | EUtranCell_TDD_FDD.csv | MANAUS |
| eNB | Source 4G site | M1741_AM |
| CELL | Source 4G cell | T17411 |
| Ancora | gNB do target | MARB2_AM |
| Tipo | "inter_site" ou "intra_site" | inter_site |
| gNB_tgt | Target 5G site | MARB2_AM |
| GUtranSyncSignalFrequency | ssbFrequency + "-30" | 627360-30 |
| ssbFrequency | NRCellDU | 627360 |
| band | 78 (n78) | 78 |
| gNBId_tgt | NRCellCU | 5321854 |
| nRCellCUId_tgt | Target 5G cell | 5SARB21 |
| cellLocalId | NRCellCU | 591 |
| nRPCI | NRCellDU | 288 |
| physicalLayerCellIdGroup | nRPCI // 3 | 96 |
| physicalLayerSubCellId | nRPCI % 3 | 0 |
| pLMNId_mcc | 724 (Brasil) | 724 |
| pLMNId_mnc | 11 (Vivo) | 11 |
| administrativeState | UNLOCKED | UNLOCKED |
| ExternalGNodeBFunction | "{mcc}{mnc}-{gNBId}" | 72411-5321854 |
| GUtranFreqRelationId | "NR_{ssbFrequency}" | NR_627360 |
| Regional | EUtranCell_TDD_FDD.csv | N |
| Tipo_Freq | Source 4G Tipo | FDD |
| Distance | Calculada | 3.43 |
| Status | "adicionar" | adicionar |

### 7.2. Lookup de Dados 5G (cell_5g_lookup)
Chave: `nRCellCUId` (ex: 5SARB21)
```python
cell_5g_lookup[nRCellCUId] = {
    'gNBId': '5321854',          # de NRCellCU
    'gNB': 'MARB2_AM',           # de NRCellCU.eNB
    'nRFrequency': '627360',     # de NRCellCU
    'cellLocalId': '591',        # de NRCellCU
    'nCI': '...',                # de NRCellCU
    'ssbFrequency': '627360',    # de NRCellDU
    'nRPCI': '288',              # de NRCellDU
    'physicalLayerCellIdGroup': '96',   # nRPCI // 3
    'physicalLayerSubCellId': '0',      # nRPCI % 3
    'pLMNId_mcc': '724',
    'pLMNId_mnc': '11',
    'site_key': 'AMARB',
    'setor': 1
}
```

### 7.3. Lookup de Dados 4G (cell_4g_lookup)
Chave: `Cellname` (ex: T17411)
```python
cell_4g_lookup[Cellname] = {
    'eNB': 'M1741_AM',
    'Tipo': 'FDD',              # ou TDD
    'Regional': 'N',
    'MUNICIPIO': 'MANAUS',
    'earfcndl': '1300'
}
```

## 8. Fluxo do Viewer para Export 4G-5G

1. Usuário seleciona SOURCE (célula 4G): `TRTT12`
2. Usuário clica em TARGET (pétala 4G no mapa): `ZFJI11`
3. Viewer encontra co-site 5G do target:
   - site_key de ZFJI11 = `AMFJI`, setor = 1
   - Busca em `site_setor_to_5g[('AMFJI', 1)]` = `5SFJI21`
4. Viewer cria par: SOURCE=TRTT12, TARGET=5SFJI21
5. No export, busca dados em:
   - `cell_4g_lookup['TRTT12']` para Tipo_Freq, Regional, MUNICIPIO
   - `cell_5g_lookup['5SFJI21']` para gNBId, ssbFrequency, nRPCI, etc.

## 9. Valores PLMN (Brasil - Vivo)
- MCC: 724
- MNC: 11
- PLMN String: "mcc=724,mnc=11,mncLength=2"

## 10. Band 5G (n78 - Correção v1.1.0)

### 10.1. Parsing de Band
**Correção realizada em v1.1.0**: Função `_parse_band_from_list()` agora trata corretamente valores float.

**Origem dos dados**:
- Arquivo: `5G_NRCellDU.txt`
- Coluna: `bandList`
- Valor típico: `78.0` (float)

**Processamento**:
```python
# Antes (INCORRETO):
_parse_band_from_list(78.0)
→ re.findall(r'\d+', "78.0") → ['78', '0']
→ numbers[-1] → "0"  ❌ ERRADO!

# Depois (CORRETO - v1.1.0):
_parse_band_from_list(78.0)
→ int(78.0) → 78
→ str(78) → "78"  ✅ CORRETO!
```

### 10.2. Valores de Band
- **Band n78 (SA)**: 3.5 GHz, padrão no Brasil para 5G
- **Valor no Export**: `band: 78`
- **Verificação**: 733 de 735 células têm band=78 (99.7%)
- **2 exceções**: 5SUM441, 5SUM442 usam default 78 na exportação

### 10.3. Tabela de Bands Suportadas
| Band | Frequência | Status |
|------|-----------|--------|
| n78 | 3.5 GHz | ✅ Principal (Brasil) |
| n79 | 4.5 GHz | Possível futuro |

## 11. Highlighting de Células (Correção v1.1.0)

### 11.1. Cores por Modo

**Modo 5G-5G**:
- Source: Azul (`#0066FF`) - Peso 3
- Target: Verde (`#00FF00`) - Peso 4, borda tracejada
- Vizinhos sugeridos: Cores do Analysis Mode
- Outras: Branco/transparente

**Modo 4G-5G** (Correção v1.1.0):
- Source (4G): Azul (`#0066FF`) - Peso 3
- Target (4G co-site 5G): Verde (`#00FF00`) - Peso 4, borda tracejada
- Vizinhos sugeridos: Cores do Analysis Mode
- LTE Only (sem 5G): Laranja/cinza

### 11.2. Lógica de Matching em 4G-5G
Antes (INCORRETO):
```javascript
// Tentava fazer match direto
addedTargets.has(layer.cellname)  // layer.cellname = 4G
// Mas targets eram 5G: '5SFJI21'
```

Depois (CORRETO - v1.1.0):
```javascript
// Itera cellsMap para encontrar célula 4G co-site
for (let cellname in cellsMap) {
    const cell = cellsMap[cellname];
    if (cell.cosite_5g === targetCell5G) {
        addedTargets.add(cellname);  // Adiciona célula 4G
    }
}
```

### 11.3. Estados Visuais Esperados
1. Clique em célula 4G (SOURCE) → Pétala **AZUL**
2. Clique em célula 4G com co-site 5G (TARGET) → Pétala **VERDE**
3. Múltiplos targets selecionados → Múltiplas pétalas **VERDES**
4. Vizinhos sugeridos → Cores conforme Analysis Mode (existing/missing/delete)

## 12. Histórico de Alterações

### v1.3.0 - 04/02/2026
- ✅ ENM Dump end-to-end: download + ZIP extraction + XML parsing + post-processing
- ✅ XML Parser usando `lxml.etree.iterparse` (tag VsDataContainer, namespaces genericNrm/EricssonSpecific)
- ✅ Post-processing de 16 MOs com pandas (ENodeBFunction, EUtranCellFDD/TDD, NRCellCU, NRCellRelation, etc.)
- ✅ Pastas locais: `ENM_Outputs/` (TXTs brutos) e `Dumps_txt/` (TXTs processados) sob nr_neighbor_viewer/
- ✅ `MOB_DUMPS_DIR` desacoplado: agora aponta para `Dumps_txt/` local
- ✅ `clean_dumps_folder()` remove subdiretorios (nao apenas arquivos)
- ✅ `selected_mos` enviado do frontend no request de execute dump
- ✅ Pipeline com 8 etapas numeradas e logs detalhados no modal
- ✅ Dependencia `lxml` adicionada para parsing XML

### v1.2.0 - 03/02/2026
- ✅ Documentação: Sites 5G podem ter prefixo `S` (ex: SINM1_AM)
- ✅ Documentação: Clarificada regra de merge 4G↔5G usando `site_key = UF + eNB[1:4]`
- ✅ Documentação: Adicionada seção 3 detalhando normalização de setores
- ✅ Documentação: Células 5G usam prefixos `5S`/`5O` (DSS `5R`/`5U`/`5Z` descartados)
- ✅ Documentação: Adicionada seção 6.3 - Verificação de Pares Existentes
- ✅ CORRIGIDO: `build_cosite_lookups()` agora usa `get_setor()` (normalizado)
- ✅ CORRIGIDO: `site_setor_to_4g` agora armazena LISTA de células (múltiplas bandas/eNBs por setor)
- ✅ CORRIGIDO: `get_cells_4g()` agora envia `setor_normalizado` para o frontend
- ✅ CORRIGIDO: Frontend usa `setor_normalizado` para agrupar co-setores no `createSourceGroup`
- ✅ CORRIGIDO: LTE Only agora é por SITE (não por setor) - usa `sites_with_5g`
- ✅ CONFIRMADO: GUtranCellRelation é unidirecional (4G→5G), volta seria EUtranCellRelation

### v1.1.0 - 30/01/2026
- ✅ Corrigido parsing de band (78.0 → "78")
- ✅ Implementado highlighting verde para 4G-5G
- ✅ Validado band em 733/735 células 5G

### v1.0.0 - Baseline
- Implementação inicial do Neighbor Viewer 4G-5G
- Support para visualização e seleção
- Export para MoB