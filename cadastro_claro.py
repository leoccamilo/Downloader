# -*- coding: utf-8 -*-
"""Cadastro da Claro PR — o equivalente ao MOs_One_Drive da Vivo.

Junta as duas fontes e grava os arquivos que o resto do Tool Box le da pasta de
cadastro (`onedrive_dir`), com as MESMAS colunas do cadastro da Vivo:

    rede inteira (TXT por MO, saida do conversor_xml)   -> parametros de REDE
    MANDO (mando_cells_<data>.csv, o "cellref" da Claro) -> parametros FISICOS

Saidas:
    EUtranCell_TDD_FDD.csv / .txt   celulas 4G, rede + coordenada/azimute/altura
    cellref_5g.xlsx                 celulas 5G, idem
    EUtranCellRelation.txt          relacoes 4G->4G da rede inteira (lista de
                                    sites e vizinhas dinamicas), com o alvo resolvido
    5G_NRCellDU.txt, Slot.txt       rede inteira, para a lista de sites
    AddressIPv4_X2.txt              IP de X2/Xn (Router NR) de todos os nos, para o
                                    Audit IPAddress conferir vizinho fora do cluster
    cadastro_alertas.xlsx           celula a celula, o que veio de reserva e o que diverge
    cadastro_resumo.json            numeros da geracao

Como cada campo FISICO e preenchido (coluna `*_Fonte` diz qual valeu):

    coordenada  1) MANDO, posicao do SITE (L_Latitude/L_Longitude)
                2) XML (latitude/longitude da EUtranCell, mediana do site)
    azimute     1) MANDO, a propria celula (A_Azimuth_TN)
                2) MANDO, outra celula do mesmo site+setor (mesma tecnologia antes)
                3) estimado pelas vizinhas LTE (ver `estimar_azimutes`)
                4) padrao pela letra do setor (A=0, B=120, C=240)

Medido em 14/10/2026 (rede W42 x MANDO de 14/09): 20.449 celulas nos dois,
220 so na rede (188 herdam o azimute de uma irma do mesmo setor), 256 so no
MANDO (ficam de fora: o Tool Box trabalha sobre o que existe na rede).

A coordenada da ANTENA do MANDO (A_*) nao e usada: em ~50 celulas ela esta
claramente errada (ex.: FAJ1414 com a latitude copiada na longitude), enquanto
a do site (L_*) bate com o XML em 99,9% delas. Divergencias viram alerta.

Copia do `mob_toolbox/app/cadastro_claro.py` do MoB_Claro (commit b9a443e),
rodada pelo Downloader como subprocesso (aba Cellrefs, modo Claro). O
Downloader nao importa o MoB. Mudancas: import local (`regras_claro`), leitura
dos TXT em latin-1 (o encoding que o xml_to_txt grava) e a linha de comando no
fim (aceita a pasta do MANDO, trava contra pastas da Vivo). `construir` e o
resto ficam como no original — ao trazer correcao do MoB, comparar a saida de
novo byte a byte (ver alteracoes.md).

    python cadastro_claro.py <pasta_txt_rede> <mando.csv | pasta do MANDO> <pasta_cadastro>
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

import regras_claro as rc

# Encoding dos TXT do xml_to_txt.py (o dump da Claro e todo ASCII, mas e o contrato).
_ENCODING_TXT = 'latin-1'

PES_PARA_METROS = 0.3048
# Divergencia de posicao que vira alerta (km). Abaixo disso e arredondamento.
LIMITE_ALERTA_KM = 0.5
AZIMUTE_PADRAO = {"A": 0.0, "B": 120.0, "C": 240.0}
BEAMWIDTH_PADRAO = 65.0

COLUNAS_LTE = [
    'Regional', 'UF', 'CN', 'MUNICIPIO', 'BAIRRO', 'Site_Name', 'ENDERECO', 'eNB', 'eNBId',
    'CELL', 'cellId', 'earfcndl', 'dlChannelBandwidth', 'tac', 'PCI', 'physicalLayerCellIdGroup',
    'physicalLayerSubCellId', 'rachRootSequence', 'catm1SupportEnabled', 'CGI', 'crsGain',
    'cellRange', 'primaryPlmnReserved', 'primaryUpperLayerInd', 'Latitude', 'Longitude',
    'Azimute', 'Altura', 'administrativeState', 'operationalState', 'SiteType', 'Tipo',
    # --- so na Claro ---
    'Site', 'Setor', 'Portadora', 'Banda', 'Radio', 'Beamwidth', 'MechanicalTilt',
    'ElectricalTilt', 'MIMO', 'AntennaType', 'Classe', 'Cluster', 'Morfologia',
    'Coord_Fonte', 'Azimute_Fonte', 'Alerta',
]

COLUNAS_NR = [
    'REGION', 'UF', 'MARKET', 'CN', 'MUNICIPIO', 'BAIRRO', 'ENDERECO', 'SiteID', 'Site_Name',
    'Cellname', 'GNodeBID', 'Longitude', 'Latitude', 'SectorID', 'Cellname.1',
    'administrativeState', 'cellState', 'NCI', 'DL_NR_ARFCN', 'NR_PCI', 'MCC', 'MNC',
    'NR_TrackingAreaCode', 'Azimuth', 'Beamwidth', 'MechanicalTilt', 'ElectricalTilt',
    'AntennaType', 'Vendor', 'Band', 'SiteType', 'EPRE', 'CableLossDL', 'Height',
    'Technology_Name', 'Category_Name',
    # --- so na Claro ---
    'Site', 'Setor', 'Portadora', 'Radio', 'MIMO', 'Classe', 'Cluster', 'Morfologia',
    'operationalState', 'cellLocalId', 'CGI', 'Coord_Fonte', 'Azimuth_Fonte', 'Alerta',
]


# ---------------------------------------------------------------------------
# Leitura da rede (TXT por MO do conversor)
# ---------------------------------------------------------------------------

def _ler(pasta: Path, mo: str, colunas: Optional[set] = None) -> pd.DataFrame:
    arq = Path(pasta) / f"{mo}.txt"
    if not arq.exists():
        raise FileNotFoundError(f"{arq} not found — run the XML converter first")
    usecols = (lambda c: c in colunas) if colunas else None
    return pd.read_csv(arq, sep="\t", dtype=str, low_memory=False, usecols=usecols,
                       encoding=_ENCODING_TXT)


def _coalesce(df: pd.DataFrame, *nomes: str) -> pd.Series:
    """Primeira coluna preenchida entre aliases (ERBS usa `EUtranCellFDDId`, RadioNode `eUtranCellFDDId`)."""
    out = pd.Series(np.nan, index=df.index, dtype=object)
    for n in nomes:
        if n in df.columns:
            out = out.fillna(df[n])
    return out


def _rede_lte(pasta: Path) -> pd.DataFrame:
    comuns = {'eNB', 'cellId', 'tac', 'physicalLayerCellIdGroup', 'physicalLayerSubCellId',
              'rachRootSequence', 'crsGain', 'cellRange', 'primaryPlmnReserved',
              'primaryUpperLayerInd', 'administrativeState', 'operationalState',
              'latitude', 'longitude'}
    fdd = _ler(pasta, "EUtranCellFDD", comuns | {'EUtranCellFDDId', 'eUtranCellFDDId',
                                                  'earfcndl', 'dlChannelBandwidth'})
    fdd['CELL'] = _coalesce(fdd, 'eUtranCellFDDId', 'EUtranCellFDDId')
    fdd['Tipo'] = 'FDD'
    tdd = _ler(pasta, "EUtranCellTDD", comuns | {'EUtranCellTDDId', 'eUtranCellTDDId',
                                                  'earfcn', 'channelBandwidth'})
    tdd['CELL'] = _coalesce(tdd, 'eUtranCellTDDId', 'EUtranCellTDDId')
    tdd = tdd.rename(columns={'earfcn': 'earfcndl', 'channelBandwidth': 'dlChannelBandwidth'})
    tdd['Tipo'] = 'TDD'
    lte = pd.concat([fdd, tdd], ignore_index=True)
    lte = lte.dropna(subset=['CELL']).drop_duplicates(subset=['eNB', 'CELL'])

    enb = _ler(pasta, "ENodeBFunction", {'eNB', 'eNBId', 'eNodeBPlmnId_mcc', 'eNodeBPlmnId_mnc'})
    enb = enb.drop_duplicates(subset=['eNB'])
    lte = lte.merge(enb, on='eNB', how='left')

    grupo = pd.to_numeric(lte['physicalLayerCellIdGroup'], errors='coerce')
    sub = pd.to_numeric(lte['physicalLayerSubCellId'], errors='coerce')
    lte['PCI'] = (grupo * 3 + sub).astype('Int64')
    mcc = lte['eNodeBPlmnId_mcc'].fillna(rc.MCC)
    mnc = lte['eNodeBPlmnId_mnc'].fillna(rc.MNC)
    ok = lte['eNBId'].notna() & lte['cellId'].notna()
    lte['CGI'] = np.where(ok, mcc + mnc + '-' + lte['eNBId'].astype(str) + '-' + lte['cellId'].astype(str), '')

    xy = rc.decodifica_coordenadas(lte['latitude'], lte['longitude'])
    lte['lat_xml'], lte['lon_xml'] = xy['Latitude'], xy['Longitude']
    return lte.drop(columns=['latitude', 'longitude'])


def _rede_nr(pasta: Path) -> pd.DataFrame:
    cu = _ler(pasta, "NRCellCU", {'eNB', 'nRCellCUId', 'cellLocalId', 'nCI', 'nRTAC',
                                  'cellState', 'serviceState', 'nRFrequencyRef'})
    du = _ler(pasta, "NRCellDU", {'eNB', 'nRCellDUId', 'nRPCI', 'ssbFrequency',
                                  'ssbFrequencyAutoSelected', 'bandList', 'bandListManual',
                                  'ssbSubCarrierSpacing', 'administrativeState',
                                  'operationalState', 'nRTAC'})
    gnb = _ler(pasta, "GNBCUCPFunction", {'eNB', 'gNBId', 'gNBIdLength', 'pLMNId_mcc', 'pLMNId_mnc'})
    cu = cu.dropna(subset=['nRCellCUId']).drop_duplicates(subset=['eNB', 'nRCellCUId'])
    du = du.dropna(subset=['nRCellDUId']).drop_duplicates(subset=['eNB', 'nRCellDUId'])
    du = du.rename(columns={'nRCellDUId': 'nRCellCUId', 'nRTAC': 'nRTAC_du'})
    nr = cu.merge(du, on=['eNB', 'nRCellCUId'], how='outer')
    nr = nr.merge(gnb.drop_duplicates(subset=['eNB']), on='eNB', how='left')
    nr['nRTAC'] = nr['nRTAC'].fillna(nr['nRTAC_du'])
    # ssbFrequency = 0 quer dizer "escolhida pelo no": o valor real fica no AutoSelected.
    ssb = pd.to_numeric(nr['ssbFrequency'], errors='coerce')
    auto = pd.to_numeric(nr['ssbFrequencyAutoSelected'], errors='coerce')
    nr['ssb_real'] = ssb.where(ssb > 0, auto).astype('Int64')
    return nr


def _relacoes_lte(pasta: Path, lte: pd.DataFrame) -> pd.DataFrame:
    """EUtranCellRelation 4G->4G da rede inteira, com a celula alvo resolvida.

    O alvo sai do `neighborCellRef` (a autoridade, mesma regra da Vivo):
    interna -> `...,vsDataEUtranCellFDD=<celula>`; externa -> o id do
    ExternalEUtranCell, que na Claro e `330110-<eNBId>-<cellId>` (ANR) ou o
    proprio nome da celula. Relacoes de NRCellCU (5G->4G) ficam de fora: nao
    tem EUtranCell de origem.
    """
    rel = _ler(pasta, "EUtranCellRelation", {'eNB', 'EUtranCell', 'eUtranCellRelationId',
                                             'EUtranCellRelationId', 'EUtranFreqRelation',
                                             'neighborCellRef', 'isHoAllowed'})
    rel = rel.dropna(subset=['EUtranCell'])
    rel['EUtranCellRelationId'] = _coalesce(rel, 'eUtranCellRelationId', 'EUtranCellRelationId')
    ref = rel['neighborCellRef'].fillna('').astype(str)
    interna = ref.str.extract(r',vsDataEUtranCell(?:FDD|TDD)=([^,]+)$', expand=False)
    externa = ref.str.extract(r',vsDataExternalEUtranCell(?:FDD|TDD)?=([^,]+)$', expand=False)
    ids = externa.str.extract(r'^(\d+)-(\d+)-(\d+)$')

    chave = lte[['eNBId', 'cellId', 'CELL']].copy()
    chave['_e'] = pd.to_numeric(chave['eNBId'], errors='coerce')
    chave['_c'] = pd.to_numeric(chave['cellId'], errors='coerce')
    chave = chave.dropna(subset=['_e', '_c']).drop_duplicates(subset=['_e', '_c'])
    por_id = pd.DataFrame({'_e': pd.to_numeric(ids[1], errors='coerce'),
                           '_c': pd.to_numeric(ids[2], errors='coerce')}, index=rel.index)
    por_id = por_id.reset_index().merge(chave[['_e', '_c', 'CELL']], on=['_e', '_c'], how='left'
                                        ).set_index('index')['CELL']
    nome_ext = externa.where(ids[0].isna())
    rel['CELL_tgt'] = interna.fillna(por_id).fillna(nome_ext)
    no_da_celula = lte.drop_duplicates(subset=['CELL']).set_index('CELL')['eNB']
    rel['eNB_tgt'] = rel['CELL_tgt'].map(no_da_celula)
    rel = rel.rename(columns={'EUtranCell': 'CELL', 'EUtranFreqRelation': 'Freq_tgt'})
    rel['UF'] = rc.municipio_serie(rel['eNB'])
    rel['MO'] = 'EUtranCellRelation'
    return rel[['MO', 'UF', 'eNB', 'CELL', 'EUtranCellRelationId', 'Freq_tgt', 'isHoAllowed',
                'neighborCellRef', 'CELL_tgt', 'eNB_tgt']]


# ---------------------------------------------------------------------------
# MANDO
# ---------------------------------------------------------------------------

def ler_mando(arquivo: Path) -> pd.DataFrame:
    """Uma linha por celula, com os campos fisicos ja em unidade do Tool Box."""
    m = pd.read_csv(arquivo, dtype=str, encoding="utf-8-sig", low_memory=False)
    m = m.rename(columns=lambda c: c.strip())
    m['cell'] = m['C_UTRANCell_Name'].astype(str).str.strip()
    # Celula repetida no export (CUL1003 e ORO1263 vieram em dobro): fica a que
    # esta no ar; empate fica a primeira.
    m['_no_ar'] = m['C_Status'].astype(str).str.strip().str.lower().eq('on air')
    m = m.sort_values('_no_ar', ascending=False, kind='stable').drop_duplicates(subset=['cell'])

    def num(c):
        return pd.to_numeric(m[c], errors='coerce') if c in m.columns else pd.Series(np.nan, index=m.index)

    out = pd.DataFrame({
        'cell': m['cell'],
        'no_mando': m.get('CC_NodebID'),
        'face_mando': m.get('C_Face'),
        'tec_mando': m.get('C_Tech'),
        'status_mando': m.get('C_Status'),
        'site_name': m.get('CS_Name'),
        'cidade': m.get('T_Town_Name'),
        'lat_site': num('L_Latitude'),
        'lon_site': num('L_Longitude'),
        'lat_antena': num('A_Latitude'),
        'lon_antena': num('A_Longitude'),
        'azimute': num('A_Azimuth_TN') % 360,
        'tilt_mec': num('A_Mechanical_Tilt'),
        'tilt_ele': num('C_Electrical_Tilt'),
        'altura_m': (num('A_Height_AGL_Ft') * PES_PARA_METROS).round(1),
        'beamwidth': num('AC_H_Beam_Width_Deg'),
        'antena': m.get('AC_Model'),
        'mimo': m.get('C_MIMO_Type'),
        'cobertura': m.get('A_Coverage'),
        'classe': m.get('CS_Class'),
        'cluster': m.get('CS_Op_Cluster'),
        'morfologia': m.get('CS_Morphology'),
    })
    indoor = (out['cobertura'].astype(str).str.strip().str.lower().eq('indoor')
              | out['classe'].astype(str).str.strip().str.lower().eq('indoor'))
    out['site_type'] = np.where(indoor, 'Indoor', 'Outdoor')
    p = rc.partes_celula_serie(out['cell'])
    out['site'] = p['site']
    out['setor'] = p['setor']
    out['tec'] = p['tec']
    return out.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Azimute estimado pelas vizinhas (reserva)
# ---------------------------------------------------------------------------

def _rumo_e_distancia(lat1, lon1, lat2, lon2):
    la1, lo1, la2, lo2 = map(np.radians, (lat1, lon1, lat2, lon2))
    dl = lo2 - lo1
    rumo = (np.degrees(np.arctan2(np.sin(dl) * np.cos(la2),
                                  np.cos(la1) * np.sin(la2) - np.sin(la1) * np.cos(la2) * np.cos(dl))) + 360) % 360
    a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin(dl / 2) ** 2
    return rumo, 2 * 6371.0 * np.arcsin(np.sqrt(a))


def _media_circular(graus: pd.Series, pesos: Optional[pd.Series] = None, por=None):
    r = np.radians(graus)
    w = pesos if pesos is not None else pd.Series(1.0, index=graus.index)
    s = (np.sin(r) * w).groupby(por).sum() if por is not None else (np.sin(r) * w).sum()
    c = (np.cos(r) * w).groupby(por).sum() if por is not None else (np.cos(r) * w).sum()
    return (np.degrees(np.arctan2(s, c)) + 360) % 360


def estimar_azimutes(rel: pd.DataFrame, site_xy: pd.DataFrame) -> pd.Series:
    """(site, setor) -> azimute estimado pela direcao das vizinhas LTE.

    O ANR cria a relacao com quem o UE da celula enxerga, e o UE fica na FRENTE
    da antena: a media circular dos rumos ate os sites vizinhos aponta para o
    azimute. Peso = n * pref^2, onde n e quantas relacoes o setor tem com o site
    alvo e pref = n / (relacoes do site inteiro com aquele alvo): o vizinho que
    so ESTE setor enxerga e o que diz para onde ele aponta.

    Sites com exatamente A, B e C sao ajustados juntos (offset unico + 0/120/240,
    sentido horario — 94% dos sites do MANDO seguem esse sentido).

    Validado contra o MANDO (3.069 setores): erro mediano 16 graus, 75% ate 30
    e 89% ate 45. Por setor isolado seria 22 graus / 75% ate 45. E reserva: so
    vale onde o MANDO nao tem a celula nem outra do mesmo setor.
    """
    r = rel.dropna(subset=['CELL_tgt']).copy()
    r['site'] = rc.site_da_celula_serie(r['CELL'], r['eNB'])
    r['setor'] = rc.setor_serie(r['CELL'])
    r['site_t'] = rc.site_da_celula_serie(r['CELL_tgt'])
    g = r.groupby(['site', 'setor', 'site_t']).size().rename('n').reset_index()
    g = g[(g['site'] != g['site_t']) & (g['setor'] != '')]
    g = g.join(site_xy, on='site').join(site_xy.rename(columns={'lat': 'lat_t', 'lon': 'lon_t'}), on='site_t')
    g = g.dropna(subset=['lat', 'lon', 'lat_t', 'lon_t'])
    if g.empty:
        return pd.Series(dtype=float)
    g['rumo'], g['dist'] = _rumo_e_distancia(g['lat'], g['lon'], g['lat_t'], g['lon_t'])
    g = g[(g['dist'] > 0.05) & (g['dist'] < 15)]
    g['pref'] = g['n'] / g.groupby(['site', 'site_t'])['n'].transform('sum')
    peso = g['pref'] ** 2 * g['n']
    est = _media_circular(g['rumo'], peso, por=[g['site'], g['setor']])

    e = est.rename('az').reset_index()
    abc = e[e['setor'].isin(['A', 'B', 'C'])].copy()
    completos = abc.groupby('site')['setor'].transform('nunique') == 3
    abc = abc[completos]
    if not abc.empty:
        k = abc['setor'].map({'A': 0, 'B': 1, 'C': 2})
        off = (abc['az'] - 120 * k) % 360
        theta = _media_circular(off, por=abc['site'])
        ajustado = (abc['site'].map(theta) + 120 * k) % 360
        est.loc[list(zip(abc['site'], abc['setor']))] = ajustado.values
    return est


# ---------------------------------------------------------------------------
# Montagem do cadastro
# ---------------------------------------------------------------------------

def _distancia_km(lat1, lon1, lat2, lon2):
    return _rumo_e_distancia(lat1, lon1, lat2, lon2)[1]


def _fisico(rede: pd.DataFrame, mando: pd.DataFrame, rel: Optional[pd.DataFrame],
            log: Callable[[str], None]) -> pd.DataFrame:
    """Campos fisicos para cada celula da rede (LTE e NR juntas).

    `rede`: colunas cell, no, tec, lat_xml, lon_xml (NR sem coordenada propria).
    """
    df = rede.copy()
    df['site'] = rc.site_da_celula_serie(df['cell'], df['no'])
    df['setor'] = rc.setor_serie(df['cell'])
    m = mando.set_index('cell')
    em_mando = df['cell'].isin(m.index)

    # ---------- coordenada: por SITE ----------
    xy_mando = mando.dropna(subset=['lat_site', 'lon_site']).groupby('site')[['lat_site', 'lon_site']].median()
    xy_rede = df.dropna(subset=['lat_xml', 'lon_xml']).groupby('site')[['lat_xml', 'lon_xml']].median()
    df['Latitude'] = df['site'].map(xy_mando['lat_site'])
    df['Longitude'] = df['site'].map(xy_mando['lon_site'])
    df['Coord_Fonte'] = np.where(df['Latitude'].notna(), 'mando', '')
    falta = df['Latitude'].isna()
    df.loc[falta, 'Latitude'] = df.loc[falta, 'site'].map(xy_rede['lat_xml'])
    df.loc[falta, 'Longitude'] = df.loc[falta, 'site'].map(xy_rede['lon_xml'])
    df.loc[falta & df['Latitude'].notna(), 'Coord_Fonte'] = 'rede'

    alertas = {i: [] for i in df.index}

    def alerta(mask, texto):
        for i in df.index[mask.fillna(False)]:
            alertas[i].append(texto)

    # MANDO x rede, no nivel do site
    comp = xy_mando.join(xy_rede, how='inner')
    comp['km'] = _distancia_km(comp['lat_site'], comp['lon_site'], comp['lat_xml'], comp['lon_xml'])
    longe = set(comp.index[comp['km'] > LIMITE_ALERTA_KM])
    alerta(df['site'].isin(longe), f'site position in MANDO more than {LIMITE_ALERTA_KM} km away from the ENM position')
    # antena x site, no proprio MANDO
    ant = mando.dropna(subset=['lat_antena', 'lat_site']).copy()
    ant['km'] = _distancia_km(ant['lat_site'], ant['lon_site'], ant['lat_antena'], ant['lon_antena'])
    ant_longe = set(ant.loc[ant['km'] > LIMITE_ALERTA_KM, 'cell'])
    alerta(df['cell'].isin(ant_longe), 'MANDO antenna far from the site (antenna coordinates ignored)')

    # ---------- campos da propria celula no MANDO ----------
    for col in ['azimute', 'tilt_mec', 'tilt_ele', 'altura_m', 'beamwidth', 'antena', 'mimo',
                'site_type', 'site_name', 'classe', 'cluster', 'morfologia', 'no_mando', 'face_mando']:
        df[col] = df['cell'].map(m[col])
    df['Azimute_Fonte'] = np.where(df['azimute'].notna(), 'mando', '')

    alerta(~em_mando, 'cell not in MANDO')
    alerta(em_mando & df['no_mando'].notna() & (df['no_mando'] != df['no']),
           'node in MANDO differs from the node in the network')
    alerta(em_mando & df['face_mando'].notna() & (df['face_mando'] != df['setor']),
           'MANDO sector (C_Face) differs from the letter in the cell name')

    # ---------- irmas do mesmo setor (mesma tecnologia antes, depois qualquer) ----------
    num = ['tilt_mec', 'tilt_ele', 'altura_m', 'beamwidth']
    for chave in (['site', 'setor', 'tec'], ['site', 'setor']):
        base = mando.dropna(subset=['azimute'])
        if base.empty:
            break
        az = _media_circular(base['azimute'], por=[base[c] for c in chave])
        az.index.names = chave
        outros = base.groupby(chave)[num].median()
        texto = base.groupby(chave)[['antena', 'mimo', 'site_type']].agg(
            lambda s: s.mode().iloc[0] if not s.mode().empty else np.nan)
        idx = pd.MultiIndex.from_frame(df[chave])
        falta = df['azimute'].isna()
        df.loc[falta, 'azimute'] = az.reindex(idx).values[falta.values]
        df.loc[falta & df['azimute'].notna(), 'Azimute_Fonte'] = 'mando_setor'
        for c in num:
            f = df[c].isna()
            df.loc[f, c] = outros[c].reindex(idx).values[f.values]
        for c in ['antena', 'mimo', 'site_type']:
            f = df[c].isna()
            df.loc[f, c] = texto[c].reindex(idx).values[f.values]

    # nome do site e dados de site: qualquer celula do site no MANDO
    por_site = mando.groupby('site')[['site_name', 'classe', 'cluster', 'morfologia']].agg(
        lambda s: s.dropna().mode().iloc[0] if not s.dropna().mode().empty else np.nan)
    for c in ['site_name', 'classe', 'cluster', 'morfologia']:
        f = df[c].isna()
        df.loc[f, c] = df.loc[f, 'site'].map(por_site[c])

    # ---------- estimativa pelas vizinhas LTE ----------
    falta = df['azimute'].isna()
    if falta.any() and rel is not None and not rel.empty:
        site_xy = df.dropna(subset=['Latitude']).groupby('site')[['Latitude', 'Longitude']].median()
        site_xy.columns = ['lat', 'lon']
        est = estimar_azimutes(rel, site_xy)
        idx = pd.MultiIndex.from_frame(df[['site', 'setor']])
        df.loc[falta, 'azimute'] = est.reindex(idx).values[falta.values]
        df.loc[falta & df['azimute'].notna(), 'Azimute_Fonte'] = 'estimado_vizinhas'
        # NR do mesmo setor herda o que o LTE estimou
        falta = df['azimute'].isna()
        if falta.any():
            lte_setor = _media_circular(df.loc[df['Azimute_Fonte'] == 'estimado_vizinhas', 'azimute'],
                                        por=[df.loc[df['Azimute_Fonte'] == 'estimado_vizinhas', 'site'],
                                             df.loc[df['Azimute_Fonte'] == 'estimado_vizinhas', 'setor']])
            if len(lte_setor):
                df.loc[falta, 'azimute'] = lte_setor.reindex(idx).values[falta.values]
                df.loc[falta & df['azimute'].notna(), 'Azimute_Fonte'] = 'estimado_vizinhas'

    # ---------- padrao pela letra ----------
    falta = df['azimute'].isna()
    df.loc[falta, 'azimute'] = df.loc[falta, 'setor'].map(AZIMUTE_PADRAO).fillna(0.0)
    df.loc[falta, 'Azimute_Fonte'] = 'padrao_setor'
    alerta(df['Azimute_Fonte'].isin(['estimado_vizinhas', 'padrao_setor']),
           'azimuth not taken from MANDO (see Azimute_Fonte)')
    alerta(df['Latitude'].isna(), 'no coordinates (neither MANDO nor ENM) — left off the map')

    df['beamwidth'] = df['beamwidth'].fillna(BEAMWIDTH_PADRAO)
    df['site_type'] = df['site_type'].fillna('Outdoor')
    df['Alerta'] = [' | '.join(alertas[i]) for i in df.index]
    df['azimute'] = df['azimute'].round(1)
    return df


def _geografia(df: pd.DataFrame, col_no: str) -> pd.DataFrame:
    cod = rc.municipio_serie(df[col_no])
    mun = rc.municipios()
    nome = cod.map({k: v['nome'] for k, v in mun.items()})
    reg = cod.map({k: v['regiao'] for k, v in mun.items()}).fillna(rc.SEM_REGIAO)
    return pd.DataFrame({'UF': cod, 'MUNICIPIO': nome, 'Regional': reg}, index=df.index)


def construir(pasta_rede, arquivo_mando, pasta_saida,
              log: Optional[Callable[[str], None]] = None) -> dict:
    """Gera o cadastro Claro. Devolve o resumo (tambem gravado em cadastro_resumo.json)."""
    log = log or print
    t0 = time.time()
    pasta_rede, pasta_saida = Path(pasta_rede), Path(pasta_saida)
    pasta_saida.mkdir(parents=True, exist_ok=True)

    log("Reading the network (4G)...")
    lte = _rede_lte(pasta_rede)
    log(f"  {len(lte):,} LTE cells")
    log("Reading the network (5G)...")
    nr = _rede_nr(pasta_rede)
    log(f"  {len(nr):,} NR cells")
    log("Reading 4G->4G relations...")
    rel = _relacoes_lte(pasta_rede, lte)
    log(f"  {len(rel):,} relations, target resolved for {rel['CELL_tgt'].notna().mean():.1%}")
    log(f"Reading MANDO ({Path(arquivo_mando).name})...")
    mando = ler_mando(Path(arquivo_mando))
    log(f"  {len(mando):,} cells in MANDO")

    rede = pd.concat([
        pd.DataFrame({'cell': lte['CELL'], 'no': lte['eNB'], 'tec': '4',
                      'lat_xml': lte['lat_xml'], 'lon_xml': lte['lon_xml']}),
        pd.DataFrame({'cell': nr['nRCellCUId'], 'no': nr['eNB'], 'tec': '5',
                      'lat_xml': np.nan, 'lon_xml': np.nan}),
    ], ignore_index=True)
    fis = _fisico(rede, mando, rel, log)
    fis_lte = fis[fis['tec'] == '4'].drop_duplicates(subset=['no', 'cell']).set_index(['no', 'cell'])
    fis_nr = fis[fis['tec'] == '5'].drop_duplicates(subset=['no', 'cell']).set_index(['no', 'cell'])

    # ---------------- EUtranCell_TDD_FDD ----------------
    out = lte.copy()
    out = pd.concat([out, _geografia(out, 'eNB')], axis=1)
    f = fis_lte.reindex(pd.MultiIndex.from_frame(out[['eNB', 'CELL']]))
    p = rc.partes_celula_serie(out['CELL'])
    out['CN'] = ''
    out['BAIRRO'] = ''
    out['ENDERECO'] = ''
    out['catm1SupportEnabled'] = ''
    out['Site_Name'] = f['site_name'].values
    out['Latitude'] = f['Latitude'].values
    out['Longitude'] = f['Longitude'].values
    out['Azimute'] = f['azimute'].values
    out['Altura'] = f['altura_m'].values
    out['SiteType'] = f['site_type'].values
    out['Site'] = rc.site_da_celula_serie(out['CELL'], out['eNB'])
    out['Setor'] = p['setor'].fillna('')
    out['Portadora'] = p['portadora'].fillna('')
    out['Banda'] = out['earfcndl'].map(rc.banda_lte).astype('Int64')
    out['Radio'] = p['radio'].fillna('')
    out['Beamwidth'] = f['beamwidth'].values
    out['MechanicalTilt'] = f['tilt_mec'].values
    out['ElectricalTilt'] = f['tilt_ele'].values
    out['MIMO'] = f['mimo'].values
    out['AntennaType'] = f['antena'].values
    out['Classe'] = f['classe'].values
    out['Cluster'] = f['cluster'].values
    out['Morfologia'] = f['morfologia'].values
    out['Coord_Fonte'] = f['Coord_Fonte'].values
    out['Azimute_Fonte'] = f['Azimute_Fonte'].values
    out['Alerta'] = f['Alerta'].values
    out = out[COLUNAS_LTE].sort_values(['UF', 'eNB', 'CELL'])
    out.to_csv(pasta_saida / 'EUtranCell_TDD_FDD.csv', index=False, encoding='ISO-8859-1', errors='replace')
    out.to_csv(pasta_saida / 'EUtranCell_TDD_FDD.txt', sep='\t', index=False, encoding='ISO-8859-1', errors='replace')
    log(f"EUtranCell_TDD_FDD: {len(out):,} cells")

    # ---------------- cellref_5g ----------------
    n5 = nr.copy()
    geo = _geografia(n5, 'eNB')
    f = fis_nr.reindex(pd.MultiIndex.from_frame(n5[['eNB', 'nRCellCUId']]))
    p = rc.partes_celula_serie(n5['nRCellCUId'])
    c5 = pd.DataFrame(index=n5.index)
    c5['REGION'] = geo['Regional']
    c5['UF'] = geo['UF']
    c5['MARKET'] = 'CLARO'
    c5['CN'] = ''
    c5['MUNICIPIO'] = geo['MUNICIPIO']
    c5['BAIRRO'] = ''
    c5['ENDERECO'] = ''
    c5['SiteID'] = n5['eNB']
    c5['Site_Name'] = f['site_name'].values
    c5['Cellname'] = n5['nRCellCUId']
    c5['GNodeBID'] = n5['gNBId']
    c5['Longitude'] = f['Longitude'].values
    c5['Latitude'] = f['Latitude'].values
    c5['SectorID'] = n5['nRCellCUId']
    c5['Cellname.1'] = n5['nRCellCUId']
    c5['administrativeState'] = n5['administrativeState']
    c5['cellState'] = n5['cellState']
    c5['NCI'] = n5['nCI']
    c5['DL_NR_ARFCN'] = n5['ssb_real']
    c5['NR_PCI'] = n5['nRPCI']
    c5['MCC'] = n5['pLMNId_mcc'].fillna(rc.MCC)
    c5['MNC'] = n5['pLMNId_mnc'].fillna(rc.MNC)
    c5['NR_TrackingAreaCode'] = n5['nRTAC']
    c5['Azimuth'] = f['azimute'].values
    c5['Beamwidth'] = f['beamwidth'].values
    c5['MechanicalTilt'] = f['tilt_mec'].values
    c5['ElectricalTilt'] = f['tilt_ele'].values
    c5['AntennaType'] = f['antena'].values
    c5['Vendor'] = 'ERICSSON'
    # Band: a PORTADORA (N41, N66, N261) — e o que o filtro de portadoras do
    # Viewer mostra. Na Vivo e a frequencia em MHz.
    c5['Band'] = p['portadora'].map(rc.portadora_rotulo)
    c5['SiteType'] = f['site_type'].values
    c5['EPRE'] = np.nan
    c5['CableLossDL'] = np.nan
    c5['Height'] = f['altura_m'].values
    c5['Technology_Name'] = '5G NR'
    c5['Category_Name'] = 'NR_' + c5['Band'].fillna('')
    c5['Site'] = rc.site_da_celula_serie(n5['nRCellCUId'], n5['eNB'])
    c5['Setor'] = p['setor'].fillna('')
    c5['Portadora'] = p['portadora'].fillna('')
    c5['Radio'] = p['radio'].fillna('')
    c5['MIMO'] = f['mimo'].values
    c5['Classe'] = f['classe'].values
    c5['Cluster'] = f['cluster'].values
    c5['Morfologia'] = f['morfologia'].values
    c5['operationalState'] = n5['operationalState']
    # CGI do alvo (mcc+mnc-gNBId-cellLocalId): e por ele que o pos-processamento
    # resolve vizinha 5G FORA do cluster, onde so ha o external.
    c5['cellLocalId'] = pd.to_numeric(n5['cellLocalId'], errors='coerce').astype('Int64')
    ok = n5['gNBId'].notna() & n5['cellLocalId'].notna()
    c5['CGI'] = np.where(ok, c5['MCC'].astype(str) + c5['MNC'].astype(str) + '-' + n5['gNBId'].astype(str)
                         + '-' + n5['cellLocalId'].astype(str), '')
    c5['Coord_Fonte'] = f['Coord_Fonte'].values
    c5['Azimuth_Fonte'] = f['Azimute_Fonte'].values
    c5['Alerta'] = f['Alerta'].values
    c5 = c5[COLUNAS_NR].sort_values(['UF', 'SiteID', 'Cellname'])
    for col in ['GNodeBID', 'NCI', 'DL_NR_ARFCN', 'NR_PCI', 'MCC', 'MNC', 'NR_TrackingAreaCode']:
        c5[col] = pd.to_numeric(c5[col], errors='coerce').astype('Int64')
    c5.to_excel(pasta_saida / 'cellref_5g.xlsx', index=False)
    log(f"cellref_5g: {len(c5):,} cells")

    # ---------------- arquivos da rede inteira ----------------
    rel.to_csv(pasta_saida / 'EUtranCellRelation.txt', sep='\t', index=False)
    log(f"EUtranCellRelation (whole network): {len(rel):,} relations")
    du = _ler(pasta_rede, "NRCellDU")
    du.insert(0, 'UF', rc.municipio_serie(du['eNB']))
    du.to_csv(pasta_saida / '5G_NRCellDU.txt', sep='\t', index=False)
    try:
        _ler(pasta_rede, "Slot").to_csv(pasta_saida / 'Slot.txt', sep='\t', index=False)
    except FileNotFoundError:
        pass
    # IP de X2/Xn (Router NR) de TODOS os nos: o Audit IPAddress confere por ele o
    # TermPoint cujo vizinho esta fora do cluster (Guaynabo: 65 de 576
    # TermPointToGNB ficavam sem conferencia).
    try:
        ip = _ler(pasta_rede, "AddressIPv4")
        ip['IP_address'] = ip['usedAddress'].astype(str).str.extract(r'([^/]+)', expand=False)
        ip = ip[~ip['IP_address'].isin(['', 'nan', '0.0.0.0'])]
        ip = rc.ip_x2_por_no(ip, col_router='Router')[['eNB', 'Router', 'IP_address']]
        ip.insert(0, 'UF', rc.municipio_serie(ip['eNB']))
        ip.to_csv(pasta_saida / 'AddressIPv4_X2.txt', sep='\t', index=False)
        log(f"AddressIPv4_X2 (whole network): {len(ip):,} nodes")
    except (FileNotFoundError, KeyError) as e:
        log(f"[WARN] AddressIPv4_X2 not written: {e}")

    # ---------------- alertas e resumo ----------------
    al_lte = out[out['Alerta'] != ''][['Regional', 'UF', 'eNB', 'CELL', 'Coord_Fonte', 'Azimute_Fonte', 'Alerta']]
    al_lte = al_lte.rename(columns={'CELL': 'Celula', 'eNB': 'No', 'Azimute_Fonte': 'Azimute_Fonte'})
    al_nr = c5[c5['Alerta'] != ''][['REGION', 'UF', 'SiteID', 'Cellname', 'Coord_Fonte', 'Azimuth_Fonte', 'Alerta']]
    al_nr = al_nr.rename(columns={'REGION': 'Regional', 'SiteID': 'No', 'Cellname': 'Celula',
                                  'Azimuth_Fonte': 'Azimute_Fonte'})
    alertas = pd.concat([al_lte.assign(Tecnologia='4G'), al_nr.assign(Tecnologia='5G')], ignore_index=True)
    alertas.to_excel(pasta_saida / 'cadastro_alertas.xlsx', index=False)

    so_mando = sorted(set(mando['cell']) - set(fis['cell']))
    resumo = {
        'gerado_em': datetime.now().isoformat(timespec='seconds'),
        'rede': str(pasta_rede),
        'mando': str(arquivo_mando),
        'celulas_lte': int(len(out)),
        'celulas_nr': int(len(c5)),
        'relacoes_lte': int(len(rel)),
        'relacoes_alvo_resolvido': float(round(rel['CELL_tgt'].notna().mean(), 4)),
        'celulas_fora_do_mando': int((~fis['cell'].isin(mando['cell'])).sum()),
        'celulas_so_no_mando': len(so_mando),
        'azimute_fonte': fis['Azimute_Fonte'].value_counts().to_dict(),
        'coordenada_fonte': fis['Coord_Fonte'].replace('', 'sem').value_counts().to_dict(),
        'celulas_com_alerta': int((fis['Alerta'] != '').sum()),
        'segundos': round(time.time() - t0, 1),
    }
    with open(pasta_saida / 'cadastro_resumo.json', 'w', encoding='utf-8') as fjs:
        json.dump(resumo, fjs, indent=2, ensure_ascii=False)
    log(f"Cellref ready in {resumo['segundos']} s: {pasta_saida}")
    return resumo


_RE_MANDO = re.compile(r'^mando_cells_(\d{4}-\d{2}-\d{2})\.csv(\.zip)?$', re.I)


def achar_mando(caminho) -> Path:
    """Arquivo do MANDO a usar: o proprio arquivo, ou o mais novo da pasta.

    Na pasta vale `mando_cells_<AAAA-MM-DD>.csv` (ou `.csv.zip`, como vem do
    portal); o mais novo e o da maior data no nome e, na mesma data, o `.csv`.
    """
    p = Path(caminho)
    if p.is_file():
        return p
    if not p.is_dir():
        raise FileNotFoundError(f"MANDO not found: {p}")
    achados = []
    for arq in p.iterdir():
        m = _RE_MANDO.match(arq.name)
        if m and arq.is_file():
            achados.append((m.group(1), m.group(2) is None, arq))
    if not achados:
        raise FileNotFoundError(f"No mando_cells_<YYYY-MM-DD>.csv (or .csv.zip) in {p}")
    return max(achados, key=lambda t: (t[0], t[1]))[2]


def _main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: python cadastro_claro.py <pasta_txt_rede> <mando.csv | pasta> <pasta_cadastro>")
        return 2
    pasta_rede, mando, pasta_saida = argv[0], argv[1], argv[2]
    if not Path(pasta_rede).is_dir():
        print(f"ERROR: network TXT folder not found: {pasta_rede}")
        return 1
    # A saida grava EUtranCellRelation.txt, Slot.txt e 5G_NRCellDU.txt: na pasta
    # do parser trocaria o TXT da rede pelo do cadastro.
    if Path(pasta_saida).resolve() == Path(pasta_rede).resolve():
        print(f"ERROR: the cellref folder must be different from the network TXT folder ({pasta_rede}).")
        return 1
    try:
        rc.exige_pasta_claro(pasta_saida)
        mando = achar_mando(mando)
        resumo = construir(pasta_rede, mando, pasta_saida)
    except (ValueError, FileNotFoundError) as e:
        print(f"ERROR: {e}")
        return 1
    print(json.dumps(resumo, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
