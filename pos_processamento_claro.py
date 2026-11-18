# -*- coding: utf-8 -*-
"""Pos-processamento do dump (passo "Process MOs") com as regras da Claro PR.

Grava os MESMOS arquivos do `enm_dump.post_process_mos` da Vivo (o Viewer, o
workflow e os audits leem estes nomes e colunas), trocando o que la e regra
da Vivo:

    Vivo                                   Claro (regras_claro)
    UF = eNB[-2:]                          UF = municipio (3 letras do no)
    Regional = mapa de UF                  Regional = regiao operacional
    SITE = eNB[1:4] + '_' + UF             Site = no sem o sufixo (CAR1028)
    Setor = ultimo digito (4..9 -> 1..3)   Setor = letra do nome (A, B, C...)
    band = 78 se SSB comeca com '6'        band pela faixa de NR-ARFCN (n66, n41, n261)
    CGI com MCC/MNC de 5 digitos (72411)   MCC/MNC de 6 digitos (330110)

e o ALVO das relacoes 5G: na Vivo ele sai do texto do `nRCellRelationId`
(nome comecando com '5' = mesmo no; '724_...' = CGI; 'auto...' = NCI). Na
Claro o id e o NOME da celula em 85% das relacoes, inclusive das EXTERNAS,
entao o alvo sai da autoridade: o `nRCellRef` / `neighborCellRef` aponta o MO
(interno = nome da celula no mesmo no; externo = External*Cell, cujo CGI vem
dos ATRIBUTOS do external — gNBId + cellLocalId — e nao do rotulo, mesma
regra que o Tool Box ja segue para os TermPoints).

Cascata do alvo: 1) celula do dump do cluster pelo CGI; 2) cadastro da rede
inteira (cellref_5g.xlsx da pasta de cadastro) pelo CGI; 3) o nome do external,
quando ele segue o padrao de nome de celula. A coluna `Fonte_alvo` diz qual valeu.

Copia do `mob_toolbox/app/pos_processamento_claro.py` do MoB_Claro (commit
b9a443e), rodada pelo Downloader como subprocesso ("Process MOs" da Claro).
Mudancas: imports locais (`regras_claro`, `enm_dump_claro`), leitura dos TXT em
latin-1 (o encoding que o xml_to_txt grava) e a linha de comando no fim.

    python pos_processamento_claro.py <pasta_txt> <pasta_saida> [pasta_cadastro]
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import regras_claro as rc
import enm_dump_claro as ed

# Encoding dos TXT do xml_to_txt.py (o dump da Claro e todo ASCII, mas e o contrato).
_ENCODING_TXT = 'latin-1'

GERADOS = (
    'ENodeBFunction.txt', 'EUtranCellFDD.txt', '5G_GNBCUCPFunction.txt', '5G_NRCellCU.txt',
    '5G_NRCellDU.txt', 'EUtranCell_TDD_FDD.csv', 'EUtranCell_TDD_FDD.txt', '5G_NRCellRelation.txt',
    '5G_GUtranCellRelation.txt', 'GUtranFreqRelation.txt', 'AddressIPv4.txt',
    '5G_TermPointToGNodeB.txt', '5G_TermPointToGNB.txt', '5G_TermPointToENodeB.txt',
    '5G_TermPointToAmf.txt', '5G_ExternalGUtranCell.txt', '5G_ExternalNRCellCU.txt', 'NRCell.csv',
    '5G_EUtranCellRelation.txt', '5G_ExternalENodeBFunction.txt',
)


# ---------------------------------------------------------------------------
# Utilitarios
# ---------------------------------------------------------------------------

def _uf(nos: pd.Series) -> pd.Series:
    return rc.municipio_serie(nos.fillna(''))


def _regional(uf: pd.Series) -> pd.Series:
    mapa = {k: v['regiao'] for k, v in rc.municipios().items()}
    return uf.map(mapa).fillna(rc.SEM_REGIAO)


def _id(s: pd.Series) -> pd.Series:
    """Identificador numerico como texto estavel ('771101.0' -> '771101'; vazio -> '')."""
    return s.map(ed._normalize_enm_identifier)


def _cgi(mcc: pd.Series, mnc: pd.Series, no_id: pd.Series, cel_id: pd.Series) -> pd.Series:
    a, b, c, d = _id(mcc), _id(mnc), _id(no_id), _id(cel_id)
    ok = a.ne('') & b.ne('') & c.ne('') & d.ne('')
    return (a + b + '-' + c + '-' + d).where(ok, '')


def _cgi_do_rotulo(rotulo: pd.Series) -> pd.Series:
    """'330110-0000000000771102-581' / '330110-771101-511' -> '330110-771102-581'.

    So reserva: o CGI de verdade vem dos atributos do external.
    """
    p = rotulo.fillna('').astype(str).str.extract(r'^(\d{5,6})[-_](\d+)[-_](\d+)$')
    ok = p[0].notna()
    return (p[0] + '-' + p[1].str.lstrip('0').replace('', '0') + '-' + p[2]).where(ok, '')


def _colunas_na_frente(df: pd.DataFrame, primeiras: list) -> pd.DataFrame:
    frente = [c for c in primeiras if c in df.columns]
    return df[frente + [c for c in df.columns if c not in frente]]


def _nci(gnb_id: pd.Series, cel_id: pd.Series, gnb_len: pd.Series) -> pd.Series:
    """NCI = gNBId * 2^(36 - gNBIdLength) + cellLocalId (TS 38.413)."""
    g = pd.to_numeric(gnb_id, errors='coerce')
    c = pd.to_numeric(cel_id, errors='coerce')
    n = pd.to_numeric(gnb_len, errors='coerce').fillna(22)
    out = g * np.power(2.0, 36 - n) + c
    return out.round().astype('Int64')


def _cadastro_5g(cadastro_dir) -> Optional[pd.DataFrame]:
    """CGI -> (Cellname, SiteID) da rede inteira, para alvo fora do cluster."""
    if not cadastro_dir:
        return None
    arq = Path(cadastro_dir) / 'cellref_5g.xlsx'
    if not arq.exists():
        return None
    try:
        df = pd.read_excel(arq, dtype=str, usecols=lambda c: c in {'Cellname', 'SiteID', 'CGI', 'NCI', 'GNodeBID'})
    except Exception:
        return None
    if 'CGI' not in df.columns:
        return None
    return df[df['CGI'].fillna('') != ''].drop_duplicates(subset=['CGI'])


def _cadastro_4g(cadastro_dir) -> Optional[pd.DataFrame]:
    """CGI -> (CELL, eNB, earfcndl) da rede inteira, para alvo 4G fora do cluster."""
    if not cadastro_dir:
        return None
    arq = Path(cadastro_dir) / 'EUtranCell_TDD_FDD.csv'
    if not arq.exists():
        return None
    try:
        df = pd.read_csv(arq, dtype=str, encoding='ISO-8859-1',
                         usecols=lambda c: c in {'eNB', 'eNBId', 'CELL', 'CGI', 'earfcndl'})
    except Exception:
        return None
    if 'CGI' not in df.columns:
        return None
    return df[df['CGI'].fillna('') != ''].drop_duplicates(subset=['CGI'])


# ---------------------------------------------------------------------------
# Processamento
# ---------------------------------------------------------------------------

def processar(dumps_dir, output_dir, task=None, cadastro_dir=None) -> None:
    src = Path(dumps_dir)
    dst = Path(output_dir)
    dst.mkdir(parents=True, exist_ok=True)

    def log(msg):
        if task:
            task.log(msg)
        else:
            print(msg)

    def invalida():
        for nome in GERADOS:
            (dst / nome).unlink(missing_ok=True)

    def ler(nome):
        arq = src / nome
        if not arq.exists():
            log(f"File not found (skipping): {nome}")
            return None
        try:
            return pd.read_csv(arq, sep='\t', dtype=str, low_memory=False,
                               encoding=_ENCODING_TXT, encoding_errors='replace')
        except Exception as e:
            log(f"Error reading {nome}: {e}")
            return None

    def grava(df, nome, **kw):
        df.to_csv(dst / nome, sep=kw.pop('sep', '\t'), index=False, **kw)

    def ler_filtrado(nome, coluna):
        """So as linhas com `coluna` preenchida, lendo em blocos.

        O EUtranCellRelation.txt traz a 4G->4G (1,1 milhao de linhas na rede
        W42) e a 5G->4G (91 mil, as que tem NRCell) no mesmo arquivo.
        """
        arq = src / nome
        if not arq.exists():
            log(f"File not found (skipping): {nome}")
            return None
        partes = []
        try:
            for bloco in pd.read_csv(arq, sep='\t', dtype=str, chunksize=200_000,
                                     encoding=_ENCODING_TXT, encoding_errors='replace'):
                if coluna in bloco.columns:
                    partes.append(bloco[bloco[coluna].notna()])
        except Exception as e:
            log(f"Error reading {nome}: {e}")
            return None
        return pd.concat(partes, ignore_index=True) if partes else None

    cadastro = _cadastro_5g(cadastro_dir)
    if cadastro is not None:
        log(f"5G cellref for targets outside the cluster: {len(cadastro):,} cells")
    cadastro4 = _cadastro_4g(cadastro_dir)

    try:
        # ===== 1. ENodeBFunction =====
        enb = ler('ENodeBFunction.txt')
        if enb is not None:
            enb['UF'] = _uf(enb['eNB'])
            enb['eNodeBFunctionId'] = _id(ed._canonicalize_enm_aliases(enb, 'eNodeBFunctionId', 'ENodeBFunctionId'))
            enb = enb.dropna(how='all', axis='columns')
            enb = _colunas_na_frente(enb, ['MO', 'UF', 'eNB'])
            grava(enb, 'ENodeBFunction.txt')
            log("ENodeBFunction OK")

        # ===== 2/3. EUtranCellFDD e TDD =====
        def celulas_lte(nome, tipo):
            df = ler(nome)
            if df is None:
                return None
            ids = [c for c in df.columns if c.lower() == f'eutrancell{tipo.lower()}id']
            df['CELL'] = df[ids].bfill(axis=1).iloc[:, 0] if ids else np.nan
            if tipo == 'TDD':
                df = df.rename(columns={'earfcn': 'earfcndl', 'channelBandwidth': 'dlChannelBandwidth'})
            grupo = pd.to_numeric(df.get('physicalLayerCellIdGroup'), errors='coerce')
            sub = pd.to_numeric(df.get('physicalLayerSubCellId'), errors='coerce')
            df['PCI'] = (grupo * 3 + sub).astype('Int64')
            df['UF'] = _uf(df['eNB'])
            df['Tipo'] = tipo
            if enb is not None:
                cols = [c for c in ['eNB', 'eNBId', 'eNodeBPlmnId_mcc', 'eNodeBPlmnId_mnc'] if c in enb.columns]
                df = df.merge(enb[cols].drop_duplicates(subset=['eNB']), on='eNB', how='left')
            df['CGI'] = _cgi(df.get('eNodeBPlmnId_mcc', pd.Series(rc.MCC, index=df.index)).fillna(rc.MCC),
                             df.get('eNodeBPlmnId_mnc', pd.Series(rc.MNC, index=df.index)).fillna(rc.MNC),
                             df.get('eNBId', pd.Series('', index=df.index)), df['cellId'])
            df = df.dropna(subset=['CELL']).drop_duplicates(subset=['eNB', 'CELL'])
            df['SITE'] = rc.site_da_celula_serie(df['CELL'], df['eNB'])
            p = rc.partes_celula_serie(df['CELL'])
            df['Setor'] = p['setor'].fillna('')
            df['Portadora'] = p['portadora'].fillna('')
            return df

        sel = ['UF', 'eNB', 'eNBId', 'CELL', 'cellId', 'earfcndl', 'dlChannelBandwidth', 'tac', 'PCI',
               'physicalLayerCellIdGroup', 'physicalLayerSubCellId', 'CGI', 'crsGain', 'cellRange',
               'primaryPlmnReserved', 'primaryUpperLayerInd', 'administrativeState', 'operationalState',
               'Tipo', 'SITE', 'Setor', 'Portadora']
        fdd = celulas_lte('EUtranCellFDD.txt', 'FDD')
        tdd = celulas_lte('EUtranCellTDD.txt', 'TDD')
        if fdd is not None:
            grava(fdd[[c for c in sel if c in fdd.columns]], 'EUtranCellFDD.txt',
                  encoding='ISO-8859-1', errors='replace')
            log("EUtranCellFDD OK")
        lte = pd.concat([x for x in (fdd, tdd) if x is not None], ignore_index=True) if (fdd is not None or tdd is not None) else None
        if lte is not None:
            cols = [c for c in sel if c in lte.columns and c != 'SITE']
            tf = lte[cols].copy()
            tf.insert(0, 'Regional', _regional(tf['UF']))
            tf['Site'] = lte['SITE']
            tf.to_csv(dst / 'EUtranCell_TDD_FDD.csv', index=False, encoding='ISO-8859-1', errors='replace')
            grava(tf, 'EUtranCell_TDD_FDD.txt', encoding='ISO-8859-1', errors='replace')
            log(f"EUtranCell_TDD_FDD OK ({len(tf)} cells)")

        # ===== 4. GNBCUCPFunction =====
        gnb = ler('GNBCUCPFunction.txt')
        if gnb is not None:
            shutil.copy2(src / 'GNBCUCPFunction.txt', dst / '5G_GNBCUCPFunction.txt')
            log("GNBCUCPFunction OK")

        # ===== 5/7. NRCellCU (enriquecido com o GNBCUCPFunction) =====
        nrc = ler('NRCellCU.txt')
        if nrc is not None:
            nrc['UF'] = _uf(nrc['eNB'])
            nrc = nrc.dropna(subset=['nRCellCUId']).drop_duplicates(subset=['eNB', 'nRCellCUId'])
            nrc = nrc.drop(columns=[c for c in ('pLMNIdList_mcc', 'pLMNIdList_mnc') if c in nrc.columns])
            if gnb is not None:
                g1 = gnb[[c for c in ['eNB', 'pLMNId_mcc', 'pLMNId_mnc', 'gNBId', 'gNBIdLength'] if c in gnb.columns]]
                g1 = g1.drop_duplicates(subset=['eNB']).rename(columns={'eNB': 'NR_Site'})
                nrc = nrc.merge(g1, left_on='eNB', right_on='NR_Site', how='left')
            nrc['CGI'] = _cgi(nrc.get('pLMNId_mcc', pd.Series(rc.MCC, index=nrc.index)).fillna(rc.MCC),
                              nrc.get('pLMNId_mnc', pd.Series(rc.MNC, index=nrc.index)).fillna(rc.MNC),
                              nrc.get('gNBId', pd.Series('', index=nrc.index)), nrc['cellLocalId'])
            if 'nRFrequencyRef' in nrc.columns:
                nrc['nRFrequency'] = nrc['nRFrequencyRef'].str.extract(r'NRFrequency=(\w+)', expand=False)
                # id COMPLETO do MO NRFrequency ('424570-15'): o sufixo e o SCS e muda
                # por portadora (n66=15, n41=30, n261=120). E o que o .mos referencia.
                nrc['nRFrequencyId'] = nrc['nRFrequencyRef'].str.extract(r'NRFrequency=([^,]+)$', expand=False)
            nrc = _colunas_na_frente(nrc, ['MO', 'UF', 'eNB', 'nRCellCUId', 'cellLocalId', 'nCI', 'gNBId', 'nRFrequency'])
            grava(nrc, '5G_NRCellCU.txt')
            log(f"NRCellCU OK ({len(nrc)} cells)")

        # ===== 6. NRCellDU =====
        nrd = ler('NRCellDU.txt')
        if nrd is not None:
            nrd['UF'] = _uf(nrd['eNB'])
            nrd = nrd.dropna(subset=['nRCellDUId']).drop_duplicates(subset=['eNB', 'nRCellDUId'])
            # ssbFrequency = 0 e "o no escolhe": o valor em uso esta no AutoSelected.
            # Quem consome (GUtranSyncSignalFrequency, banda, .mos) precisa do valor real.
            if 'ssbFrequency' in nrd.columns:
                nrd['ssbFrequency_configurado'] = nrd['ssbFrequency']
                ssb = pd.to_numeric(nrd['ssbFrequency'], errors='coerce')
                auto = pd.to_numeric(nrd.get('ssbFrequencyAutoSelected'), errors='coerce')
                nrd['ssbFrequency'] = ssb.where(ssb > 0, auto).astype('Int64')
            nrd = _colunas_na_frente(nrd, ['MO', 'UF', 'eNB', 'nRCellDUId', 'cellLocalId', 'nCI', 'nRPCI', 'nRTAC'])
            grava(nrd, '5G_NRCellDU.txt')
            log(f"NRCellDU OK ({len(nrd)} cells)")

        # tabela de alvo 5G do cluster: CGI -> celula/no/ids
        alvo5 = None
        if nrc is not None:
            alvo5 = nrc[['eNB', 'nRCellCUId', 'CGI', 'nCI', 'gNBId', 'UF']].copy()
            alvo5 = alvo5[alvo5['CGI'] != ''].drop_duplicates(subset=['CGI'])

        # gNBs conhecidos (cluster + rede inteira pelo cadastro): para separar "o gNB
        # alvo nao existe" de "o gNB existe mas a CELULA alvo nao existe nele".
        gnbs_conhecidos = set(alvo5['gNBId'].dropna().astype(str)) if alvo5 is not None else set()
        if cadastro is not None and 'GNodeBID' in cadastro.columns:
            gnbs_conhecidos |= set(cadastro['GNodeBID'].dropna().astype(str).str.replace(r'\.0$', '', regex=True))

        def resolve_por_cgi(cgi: pd.Series, rotulo: pd.Series) -> pd.DataFrame:
            """Para cada CGI: (celula, no, origem).

            Cluster -> cadastro -> 'celula_inexistente' (o gNB do CGI existe, mas sem
            aquele cellLocalId: a relacao aponta para celula que nao existe — lixo,
            medido na rede inteira W42: 60 GUtranCellRelation) -> nome do external
            (so quando nem o gNB e conhecido, ex.: sem cadastro).
            """
            out = pd.DataFrame({'cel': '', 'no': '', 'origem': ''}, index=cgi.index)
            if alvo5 is not None:
                m = alvo5.set_index('CGI')
                cel = cgi.map(m['nRCellCUId'])
                ok = cel.notna()
                out.loc[ok, 'cel'] = cel[ok]
                out.loc[ok, 'no'] = cgi[ok].map(m['eNB'])
                out.loc[ok, 'origem'] = 'cluster'
            if cadastro is not None:
                m = cadastro.set_index('CGI')
                falta = out['origem'].eq('') & cgi.ne('')
                cel = cgi[falta].map(m['Cellname'])
                ok = cel.notna()
                idx = cel[ok].index
                out.loc[idx, 'cel'] = cel[ok]
                out.loc[idx, 'no'] = cgi[idx].map(m['SiteID'])
                out.loc[idx, 'origem'] = 'cadastro'
            falta = out['origem'].eq('') & cgi.ne('')
            gnb_do_cgi = cgi.str.split('-').str[1].fillna('')
            m = falta & gnb_do_cgi.isin(gnbs_conhecidos)
            out.loc[m, 'origem'] = 'celula_inexistente'
            # O NOME do external so serve quando nao ha cadastro da rede inteira para
            # conferir. Com o cadastro, CGI que nao bate e lixo: a rede roteia pelo
            # CGI, e o rotulo pode citar celula que nem existe mais (W42: 9
            # NRCellRelation com rotulo LAR1279_N41_5_MM_B_1 / ARR1006_N41_5_MM_*,
            # celulas desativadas, que pareciam intra-site com distancia 0).
            if cadastro is not None:
                return out
            falta = out['origem'].eq('')
            nome_ok = rotulo.fillna('').astype(str).str.match(rc.RE_CELULA.pattern)
            idx = out.index[falta & nome_ok]
            out.loc[idx, 'cel'] = rotulo[idx]
            out.loc[idx, 'origem'] = 'nome_external'
            return out

        # ===== 9. NRCellRelation =====
        rel = ler('NRCellRelation.txt')
        if rel is not None and nrc is not None:
            rel = rel.rename(columns={'NRCell': 'NRCellCU'})
            rel['eNB_src'] = rel['eNB']
            rel['UF_src'] = _uf(rel['eNB'])
            if 'nRFreqRelationRef' in rel.columns:
                rel['NRFreqRelation'] = rel['nRFreqRelationRef'].str.extract(r'NRFreqRelation=([^,]+)$', expand=False)
            ref = rel['nRCellRef'].fillna('').astype(str)
            interna = ref.str.extract(r',vsDataNRCellCU=([^,]+)$', expand=False)
            ext = ref.str.extract(r',vsDataExternalGNBCUCPFunction=([^,]+),vsDataExternalNRCellCU=([^,]+)$')
            rel['_extF'], rel['_extC'] = ext[0], ext[1]

            # CGI dos externals pelos ATRIBUTOS (gNBId do ExternalGNBCUCPFunction + cellLocalId do ExternalNRCellCU)
            xg = ler('ExternalGNBCUCPFunction.txt')
            xc = ler('ExternalNRCellCU.txt')
            rel['_cgi_ext'] = ''
            rel['_gnb_ext'] = ''
            rel['_nci_ext'] = pd.array([pd.NA] * len(rel), dtype='Int64')
            if xg is not None and xc is not None:
                xg['_ref'] = ed._coalesce_enm_aliases(xg, 'externalGNBCUCPFunctionId', 'ExternalGNBCUCPFunctionId').fillna('')
                xc['_ref'] = xc['externalNRCellCUId'].fillna('')
                cel = xc[['eNB', 'ExternalGNBCUCPFunction', '_ref', 'cellLocalId']].merge(
                    xg[['eNB', '_ref', 'gNBId', 'gNBIdLength', 'pLMNId_mcc', 'pLMNId_mnc']].rename(columns={'_ref': 'ExternalGNBCUCPFunction'}),
                    on=['eNB', 'ExternalGNBCUCPFunction'], how='left')
                cel['_cgi_ext'] = _cgi(cel['pLMNId_mcc'], cel['pLMNId_mnc'], cel['gNBId'], cel['cellLocalId'])
                cel['_nci_ext'] = _nci(cel['gNBId'], cel['cellLocalId'], cel['gNBIdLength'])
                cel = cel.drop_duplicates(subset=['eNB', 'ExternalGNBCUCPFunction', '_ref'])
                j = rel[['eNB', '_extF', '_extC']].reset_index().merge(
                    cel[['eNB', 'ExternalGNBCUCPFunction', '_ref', '_cgi_ext', '_nci_ext', 'gNBId']],
                    left_on=['eNB', '_extF', '_extC'], right_on=['eNB', 'ExternalGNBCUCPFunction', '_ref'],
                    how='left').set_index('index')
                rel['_cgi_ext'] = j['_cgi_ext'].fillna('')
                rel['_gnb_ext'] = _id(j['gNBId'])
                rel['_nci_ext'] = j['_nci_ext']
            # reserva: CGI pelo rotulo (external ou id da relacao no formato CGI)
            sem = rel['_cgi_ext'].eq('') & rel['_extF'].notna()
            rel.loc[sem, '_cgi_ext'] = _cgi_do_rotulo(rel.loc[sem, '_extC'])
            sem = rel['_cgi_ext'].eq('') & rel['_extF'].notna()
            rel.loc[sem, '_cgi_ext'] = _cgi_do_rotulo(rel.loc[sem, 'nRCellRelationId'])

            # interno: celula do mesmo no
            m_int = nrc.set_index(['eNB', 'nRCellCUId'])
            chave_int = pd.MultiIndex.from_arrays([rel['eNB'], interna.fillna('')])
            eh_int = interna.notna()
            rel['nRCellCUId'] = np.where(eh_int, interna, '')
            rel['eNB_tgt'] = np.where(eh_int, rel['eNB'], '')
            rel['Fonte_alvo'] = np.where(eh_int, 'cluster', '')
            rel['CGI'] = np.where(eh_int, m_int['CGI'].reindex(chave_int).fillna('').values, rel['_cgi_ext'])
            rel['nCI'] = np.where(eh_int, m_int['nCI'].reindex(chave_int).values, rel['_nci_ext'].astype('object'))
            rel['gNBId'] = np.where(eh_int, m_int['gNBId'].reindex(chave_int).values, rel['_gnb_ext'])
            # externo: cascata pelo CGI
            ix = rel.index[~eh_int]
            alvo = resolve_por_cgi(rel.loc[ix, 'CGI'].fillna(''), rel.loc[ix, '_extC'])
            rel.loc[ix, 'nRCellCUId'] = alvo['cel']
            rel.loc[ix, 'eNB_tgt'] = alvo['no']
            rel.loc[ix, 'Fonte_alvo'] = alvo['origem']
            rel['UF_tgt'] = np.where(rel['eNB_tgt'] != '', _uf(rel['eNB_tgt']), _uf(rel['nRCellCUId']))
            rel['UF_tgt'] = pd.Series(rel['UF_tgt'], index=rel.index).where(rel['nRCellCUId'] != '', '')
            rel['Regional'] = _regional(rel['UF_src'])
            colunas = ['Regional', 'MO', 'UF_src', 'eNB_src', 'NRCellCU', 'UF_tgt', 'eNB_tgt', 'nRCellCUId',
                       'NRFreqRelation', 'gNBId', 'CGI', 'nCI', 'sCellCandidate', 'cellIndividualOffsetNR',
                       'coverageIndicator', 'includeInSIB', 'isHoAllowed', 'isRemoveAllowed', 'caStatusActive',
                       'caStatusInfo', 'coordinationType', 'nRCellRef', 'nRCellRelationId', 'nRFreqRelationRef',
                       'Fonte_alvo']
            out = rel.reindex(columns=colunas)
            grava(out, '5G_NRCellRelation.txt')
            log(f"NRCellRelation OK ({len(out)} relations; target: "
                f"{out['Fonte_alvo'].replace('', 'unresolved').value_counts().to_dict()})")

        # ===== 10. GUtranCellRelation =====
        gut = ler('GUtranCellRelation.txt')
        xgn = ler('ExternalGNodeBFunction.txt')
        xgc = ler('ExternalGUtranCell.txt')
        cel_gut = None
        if xgn is not None and xgc is not None:
            xgn['_ref'] = ed._coalesce_enm_aliases(xgn, 'externalGNodeBFunctionId', 'ExternalGNodeBFunctionId').fillna('')
            xgc['ExternalGUtranCellId'] = ed._coalesce_enm_aliases(xgc, 'ExternalGUtranCellId', 'externalGUtranCellId').fillna('')
            cel_gut = xgc.merge(
                xgn[['eNB', '_ref', 'gNodeBId', 'gNodeBIdLength', 'gNodeBPlmnId_mcc', 'gNodeBPlmnId_mnc']].rename(columns={'_ref': 'ExternalGNodeBFunction'}),
                on=['eNB', 'ExternalGNodeBFunction'], how='left')
            cel_gut['CGI_tgt'] = _cgi(cel_gut['gNodeBPlmnId_mcc'], cel_gut['gNodeBPlmnId_mnc'],
                                      cel_gut['gNodeBId'], cel_gut['localCellId'])
            sem = cel_gut['CGI_tgt'].eq('')
            cel_gut.loc[sem, 'CGI_tgt'] = _cgi_do_rotulo(cel_gut.loc[sem, 'ExternalGUtranCellId'])
        if gut is not None:
            gut['UF'] = _uf(gut['eNB'])
            ref = gut['neighborCellRef'].fillna('').astype(str)
            ext = ref.str.extract(r',vsDataExternalGNodeBFunction=([^,]+),vsDataExternalGUtranCell=([^,]+)$')
            gut['ExternalGNodeBFunction'] = ext[0]
            gut['ExternalGUtranCell'] = ext[1]
            gut['CGI'] = ''
            gut['gNBId_tgt'] = ''
            if cel_gut is not None:
                j = gut[['eNB', 'ExternalGNodeBFunction', 'ExternalGUtranCell']].reset_index().merge(
                    cel_gut[['eNB', 'ExternalGNodeBFunction', 'ExternalGUtranCellId', 'CGI_tgt', 'gNodeBId']].drop_duplicates(
                        subset=['eNB', 'ExternalGNodeBFunction', 'ExternalGUtranCellId']),
                    left_on=['eNB', 'ExternalGNodeBFunction', 'ExternalGUtranCell'],
                    right_on=['eNB', 'ExternalGNodeBFunction', 'ExternalGUtranCellId'], how='left').set_index('index')
                gut['CGI'] = j['CGI_tgt'].fillna('')
                # gNodeB ID do alvo pelo ATRIBUTO do ExternalGNodeBFunction: na
                # Claro o id dele e quase sempre o nome do no, sem o numero dentro.
                gut['gNBId_tgt'] = _id(j['gNodeBId'])
            sem = gut['CGI'].eq('')
            gut.loc[sem, 'CGI'] = _cgi_do_rotulo(gut.loc[sem, 'ExternalGUtranCell'])
            alvo = resolve_por_cgi(gut['CGI'], gut['ExternalGUtranCell'])
            gut['Neighbor'] = alvo['no']
            gut['nRCellCUId'] = alvo['cel']
            gut['Fonte_alvo'] = alvo['origem']
            gut['Regional'] = _regional(gut['UF'])
            ident = [c for c in ['eNB', 'EUtranCell', 'gUtranCellRelationId'] if c in gut.columns]
            gut = gut.drop_duplicates(subset=ident)
            gut = _colunas_na_frente(gut, ['MO', 'UF', 'eNB', 'EUtranCell', 'GUtranFreqRelation', 'gUtranCellRelationId'])
            grava(gut, '5G_GUtranCellRelation.txt')
            log(f"GUtranCellRelation OK ({len(gut)} relations; target: "
                f"{gut['Fonte_alvo'].replace('', 'unresolved').value_counts().to_dict()})")

        # ===== 11. GUtranFreqRelation =====
        gfr = ler('GUtranFreqRelation.txt')
        if gfr is not None:
            if 'gUtranSyncSignalFrequencyRef' in gfr.columns:
                gfr['GUtranSyncSignalFrequency'] = gfr['gUtranSyncSignalFrequencyRef'].str.extract(
                    r'GUtranSyncSignalFrequency=([^,]+)$', expand=False)
            gfr['GUtranFreqRelationId'] = ed._canonicalize_enm_aliases(
                gfr, 'GUtranFreqRelationId', 'gUtranFreqRelationId').fillna('').astype(str).str.strip()
            gfr = gfr.rename(columns={'EUtranCell': 'EUtranCellFDD'})
            gfr['UF'] = _uf(gfr['eNB'])
            if 'GUtranSyncSignalFrequency' in gfr.columns:
                gfr['GUtranFrequency'] = gfr['GUtranSyncSignalFrequency'].str.extract(r'([^-\s]+)', expand=False)
                gfr = gfr.drop_duplicates(subset=['eNB', 'EUtranCellFDD', 'GUtranFrequency'])
            gfr = _colunas_na_frente(gfr, ['MO', 'UF', 'eNB', 'EUtranCellFDD', 'GUtranFrequency',
                                           'GUtranSyncSignalFrequency', 'GUtranFreqRelationId'])
            grava(gfr, 'GUtranFreqRelation.txt')
            log("GUtranFreqRelation OK")

        # ===== 8. EUtranCellRelation 5G -> 4G (filha da NRCellCU) =====
        # Mesmo MO da relacao 4G->4G; a do 5G e a que tem NRCell. Alvo:
        #  - eNodeBId e PLMN pelos ATRIBUTOS do ExternalENodeBFunction do lado 5G;
        #  - a CELULA pelo rotulo, porque o ExternalEUtranCell (localCellId) nao vem
        #    no export. Rotulos medidos na W42 (91.650 relacoes): 47% CGI, 51% nome
        #    da celula e 2% fora do padrao ('71152-14832-138': o prefixo e lixo de
        #    script; o eNodeBId certo e o do external e o ultimo numero e a celula).
        xe = ler('ExternalENodeBFunction.txt')
        ext_enb5 = None
        if xe is not None and 'GNBCUCPFunction' in xe.columns:
            xe = xe[xe['GNBCUCPFunction'].notna()].copy()
            vazio = pd.Series('', index=xe.index)
            ext_enb5 = pd.DataFrame({
                'eNB': xe['eNB'],
                'ExternalENodeBFunction': ed._coalesce_enm_aliases(
                    xe, 'externalENodeBFunctionId', 'ExternalENodeBFunctionId').fillna(''),
                'eNodeBId': _id(xe.get('eNodeBId', vazio)),
                'pLMNId_mcc': _id(xe.get('pLMNId_mcc', vazio)),
                'pLMNId_mnc': _id(xe.get('pLMNId_mnc', vazio)),
            }).drop_duplicates(subset=['eNB', 'ExternalENodeBFunction'])
            s = ext_enb5.rename(columns={'eNB': 'gNB'})
            s.insert(0, 'UF', _uf(s['gNB']))
            grava(s, '5G_ExternalENodeBFunction.txt')
            log(f"ExternalENodeBFunction (5G) OK ({len(s)})")

        eur = ler_filtrado('EUtranCellRelation.txt', 'NRCell')
        if eur is not None and not eur.empty:
            eur = eur.dropna(how='all', axis='columns').rename(columns={'NRCell': 'CELL'})
            eur['UF'] = _uf(eur['eNB'])
            eur['EUtranCellRelationId'] = ed._canonicalize_enm_aliases(
                eur, 'EUtranCellRelationId', 'eUtranCellRelationId').fillna('').astype(str)
            ref = eur['neighborCellRef'].fillna('').astype(str)
            ext = ref.str.extract(r',vsDataExternalENodeBFunction=([^,]+),vsDataExternalEUtranCell=([^,]+)$')
            eur['ExternalENodeBFunction'] = ext[0].fillna('')
            eur['ExternalEUtranCell'] = ext[1].fillna('')
            vazio = pd.Series('', index=eur.index)
            enb_id, mcc, mnc = vazio, vazio, vazio
            if ext_enb5 is not None:
                j = eur[['eNB', 'ExternalENodeBFunction']].reset_index().merge(
                    ext_enb5, on=['eNB', 'ExternalENodeBFunction'], how='left').set_index('index')
                enb_id = j['eNodeBId'].fillna('')
                mcc, mnc = j['pLMNId_mcc'].fillna(''), j['pLMNId_mnc'].fillna('')
            # reserva do eNodeBId: o numero no fim do id do external ('auto330_110_3_771101')
            enb_id = enb_id.where(enb_id != '', eur['ExternalENodeBFunction'].str.extract(
                r'_(\d+)$', expand=False).fillna(''))
            mcc = mcc.where(mcc != '', rc.MCC)
            mnc = mnc.where(mnc != '', rc.MNC)
            eur['eNBId_tgt'] = enb_id

            rot = eur['ExternalEUtranCell'].where(eur['ExternalEUtranCell'] != '', eur['EUtranCellRelationId'])
            eh_nome = rot.str.match(rc.RE_CELULA.pattern)
            numerico = rot.str.match(r'^\d[\d-]*-\d+$')
            cel_id = rot.str.extract(r'-(\d+)$', expand=False).fillna('')
            eur['CGI'] = ''
            ok = numerico & enb_id.ne('') & cel_id.ne('')
            eur.loc[ok, 'CGI'] = mcc[ok] + mnc[ok] + '-' + enb_id[ok] + '-' + cel_id[ok]

            tab = []
            if lte is not None:
                tab.append(lte.reindex(columns=['eNB', 'CELL', 'CGI', 'earfcndl', 'eNBId']).assign(_f='cluster'))
            if cadastro4 is not None:
                tab.append(cadastro4.reindex(columns=['eNB', 'CELL', 'CGI', 'earfcndl', 'eNBId']).assign(_f='cadastro'))
            for c in ('eNB_tgt', 'CELL_tgt', 'earfcndl_tgt', 'Fonte_alvo'):
                eur[c] = ''
            if tab:
                a = pd.concat(tab, ignore_index=True)
                a = a[a['CGI'].fillna('') != ''].copy()
                a['eNBId'] = _id(a['eNBId'])
                # rotulo = nome da celula. O mesmo nome pode estar em dois nos (W42:
                # MOC1490_1 e MOC1490_3) — vale o do eNodeBId do external.
                m = eh_nome & eur['CGI'].eq('')
                if m.any():
                    por_nome_id = a.drop_duplicates(subset=['CELL', 'eNBId']).set_index(['CELL', 'eNBId'])['CGI']
                    por_nome = a.drop_duplicates(subset=['CELL']).set_index('CELL')['CGI']
                    chave = pd.MultiIndex.from_arrays([rot[m], enb_id[m]])
                    c1 = pd.Series(por_nome_id.reindex(chave).values, index=rot[m].index)
                    eur.loc[m, 'CGI'] = c1.fillna(rot[m].map(por_nome)).fillna('')
                # nome que nao existe mais: celula RENOMEADA (W42: CAT1653_B48_4_MR_A_3
                # virou CAT1653_B48_4_MM_A_3, trocou o tipo de radio). Casa site +
                # portadora + setor + indice no MESMO eNodeBId do external.
                renomeada = pd.Series(False, index=eur.index)
                m = eh_nome & eur['CGI'].eq('')
                if m.any():
                    def sem_radio(nomes):
                        p = rc.partes_celula_serie(nomes)
                        return p['site'] + '_' + p['portadora'] + '_' + p['setor'] + '_' + p['indice']
                    a['_sem_radio'] = sem_radio(a['CELL'])
                    tab_r = a.dropna(subset=['_sem_radio']).drop_duplicates(
                        subset=['_sem_radio', 'eNBId']).set_index(['_sem_radio', 'eNBId'])['CGI']
                    chave = pd.MultiIndex.from_arrays([sem_radio(rot[m]), enb_id[m]])
                    c = pd.Series(tab_r.reindex(chave).values, index=rot[m].index).fillna('')
                    eur.loc[m, 'CGI'] = c
                    renomeada = m & eur['CGI'].ne('')
                # CGI -> celula: cluster primeiro (vem antes no concat), depois cadastro
                por_cgi = a.drop_duplicates(subset=['CGI'], keep='first').set_index('CGI')
                t = por_cgi.reindex(eur['CGI'])
                eur['eNB_tgt'] = t['eNB'].fillna('').values
                eur['CELL_tgt'] = t['CELL'].fillna('').values
                eur['earfcndl_tgt'] = t['earfcndl'].fillna('').values
                eur['Fonte_alvo'] = t['_f'].fillna('').values
                eur.loc[renomeada & eur['Fonte_alvo'].ne(''), 'Fonte_alvo'] = 'nome_antigo'
            # Sem cadastro da rede inteira para conferir, o nome do external e o que ha
            # (mesma regra da NRCellRelation/GUtranCellRelation).
            if cadastro4 is None:
                m = eur['Fonte_alvo'].eq('') & eh_nome
                eur.loc[m, 'CELL_tgt'] = rot[m]
                eur.loc[m, 'Fonte_alvo'] = 'nome_external'
            eur['UF_tgt'] = _uf(eur['eNB_tgt'].where(eur['eNB_tgt'] != '', eur['CELL_tgt']))
            eur.loc[eur['CELL_tgt'] == '', 'UF_tgt'] = ''
            eur['Regional'] = _regional(eur['UF'])
            eur = eur.drop_duplicates(subset=['eNB', 'CELL', 'EUtranCellRelationId'])
            eur = _colunas_na_frente(eur, ['Regional', 'MO', 'UF', 'eNB', 'CELL', 'EUtranCellRelationId',
                                           'ExternalENodeBFunction', 'ExternalEUtranCell', 'eNBId_tgt', 'CGI',
                                           'UF_tgt', 'eNB_tgt', 'CELL_tgt', 'earfcndl_tgt', 'Fonte_alvo'])
            grava(eur, '5G_EUtranCellRelation.txt')
            log(f"EUtranCellRelation 5G->4G OK ({len(eur)} relations; target: "
                f"{eur['Fonte_alvo'].replace('', 'unresolved').value_counts().to_dict()})")

        # ===== 12. AddressIPv4 =====
        ip = ler('AddressIPv4.txt')
        if ip is not None:
            ip['UF'] = _uf(ip['eNB'])
            if 'Router' in ip.columns:
                ip = ip.rename(columns={'Router': 'RouterId'})
            if 'usedAddress' in ip.columns:
                ip['IP_address'] = ip['usedAddress'].str.extract(r'([^/]+)', expand=False)
            ip = _colunas_na_frente(ip, ['MO', 'UF', 'eNB', 'IP_address'])
            grava(ip, 'AddressIPv4.txt')
            log("AddressIPv4 OK")

        # ===== 13-16. TermPoints (resolvedores genericos do MoB; so UF/Regional mudam) =====
        def ajusta_uf(df, col_no):
            df['UF'] = _uf(df[col_no].astype(str))
            if 'Regional' in df.columns:
                df['Regional'] = _regional(df['UF'])
            return df

        def termpoint(nome_tp, nome_ext, saida, funcao, local, col_no):
            tp, ex = ler(nome_tp), ler(nome_ext)
            if tp is None or ex is None or local is None:
                log(f"{nome_tp[:-4]} dependencies not found (skipping)")
                return
            res = ajusta_uf(funcao(tp, ex, local), col_no)
            grava(res, saida)
            log(f"{nome_tp[:-4]} OK ({len(res)})")

        termpoint('TermPointToGNodeB.txt', 'ExternalGNBCUCPFunction.txt', '5G_TermPointToGNodeB.txt',
                  ed._process_termpoint_to_gnodeb, nrc, 'gNB')
        termpoint('TermPointToGNB.txt', 'ExternalGNodeBFunction.txt', '5G_TermPointToGNB.txt',
                  ed._process_termpoint_to_gnb, nrc, 'eNB')
        termpoint('TermPointToENodeB.txt', 'ExternalENodeBFunction.txt', '5G_TermPointToENodeB.txt',
                  ed._process_termpoint_to_enodeb, enb, 'eNB')
        amf = ler('TermPointToAmf.txt')
        if amf is not None:
            grava(ajusta_uf(ed._process_termpoint_to_amf(amf), 'eNB'), '5G_TermPointToAmf.txt')
            log("TermPointToAmf OK")

        # ===== 17. ExternalGUtranCell =====
        if cel_gut is not None:
            df = cel_gut.copy()
            df['UF'] = _uf(df['eNB'])
            if alvo5 is not None:
                a = alvo5.rename(columns={'UF': 'UF_tgt', 'eNB': 'eNB_tgt', 'nRCellCUId': 'nRCellCUId_tgt',
                                          'CGI': 'CGI_tgt'})[['UF_tgt', 'eNB_tgt', 'nRCellCUId_tgt', 'CGI_tgt']]
                if nrc is not None:
                    extra = nrc[[c for c in ['CGI', 'nRFrequency', 'cellState', 'serviceState'] if c in nrc.columns]]
                    extra = extra[extra['CGI'] != ''].drop_duplicates(subset=['CGI']).rename(columns={
                        'CGI': 'CGI_tgt', 'nRFrequency': 'nRFrequency_tgt', 'cellState': 'cellState_tgt',
                        'serviceState': 'serviceState_tgt'})
                    a = a.merge(extra, on='CGI_tgt', how='left')
                df = df.merge(a, on='CGI_tgt', how='left')
            df = df.drop(columns=[c for c in ('_ref', 'gNodeBPlmnId_mcc', 'gNodeBPlmnId_mnc', 'gNodeBIdLength') if c in df.columns])
            grava(df, '5G_ExternalGUtranCell.txt')
            log("ExternalGUtranCell OK")

        # ===== 18. ExternalNRCellCU =====
        xg = ler('ExternalGNBCUCPFunction.txt')
        xc = ler('ExternalNRCellCU.txt')
        if xc is not None and not xc.empty:
            df = xc.rename(columns={'eNB': 'gNB'})
            df['UF'] = _uf(df['gNB'])
            df['CGI'] = ''
            if xg is not None:
                xg['_ref'] = ed._coalesce_enm_aliases(xg, 'externalGNBCUCPFunctionId', 'ExternalGNBCUCPFunctionId').fillna('')
                k = xg[['eNB', '_ref', 'gNBId', 'pLMNId_mcc', 'pLMNId_mnc']].drop_duplicates(subset=['eNB', '_ref']).rename(
                    columns={'eNB': 'gNB', '_ref': 'ExternalGNBCUCPFunction', 'gNBId': '_gnb'})
                df = df.merge(k, on=['gNB', 'ExternalGNBCUCPFunction'], how='left')
                df['CGI'] = _cgi(df['pLMNId_mcc'], df['pLMNId_mnc'], df['_gnb'], df['cellLocalId'])
                df = df.drop(columns=['_gnb', 'pLMNId_mcc', 'pLMNId_mnc'])
            sem = df['CGI'].eq('')
            base = _cgi_do_rotulo(df.loc[sem, 'ExternalGNBCUCPFunction'].fillna('') + '-' + df.loc[sem, 'cellLocalId'].fillna(''))
            df.loc[sem, 'CGI'] = base
            if 'nRFrequencyRef' in df.columns:
                df['nRFrequency'] = df['nRFrequencyRef'].str.extract(r'NRFrequency=([^,]+)$', expand=False)
            grava(df, '5G_ExternalNRCellCU.txt')
            log("ExternalNRCellCU OK")

        # ===== NRCell.csv (CU + DU), entrada do Template =====
        if nrc is not None and nrd is not None:
            cu = nrc[[c for c in ['UF', 'eNB', 'nRCellCUId', 'pLMNId_mcc', 'pLMNId_mnc', 'gNBId', 'CGI', 'nCI',
                                  'nRTAC', 'cellLocalId'] if c in nrc.columns]]
            du = nrd[[c for c in ['UF', 'eNB', 'nRCellDUId', 'cellLocalId', 'administrativeState', 'nRPCI',
                                  'bandListManual', 'ssbFrequency', 'ssbSubCarrierSpacing'] if c in nrd.columns]]
            du = du.rename(columns={'nRCellDUId': 'nRCellCUId'})
            cel = cu.merge(du, on=['UF', 'eNB', 'nRCellCUId', 'cellLocalId'], how='inner')
            cel['Site'] = rc.site_da_celula_serie(cel['nRCellCUId'], cel['eNB'])
            cel['Setor'] = rc.setor_serie(cel['nRCellCUId'])
            cel = cel.rename(columns={'eNB': 'gNB'})
            cel['GUtranSyncSignalFrequency'] = cel['ssbFrequency'].astype(str) + '-' + cel['ssbSubCarrierSpacing'].astype(str)
            banda = cel['ssbFrequency'].map(rc.banda_nr)
            cel['band'] = banda.fillna(pd.to_numeric(cel.get('bandListManual'), errors='coerce')).astype('Int64')
            pci = pd.to_numeric(cel['nRPCI'], errors='coerce')
            cel['physicalLayerCellIdGroup'] = (pci // 3).astype('Int64')
            cel['physicalLayerSubCellId'] = (pci % 3).astype('Int64')
            colunas = ['UF', 'gNB', 'nRCellCUId', 'pLMNId_mcc', 'pLMNId_mnc', 'gNBId', 'CGI', 'nCI', 'nRTAC',
                       'GUtranSyncSignalFrequency', 'cellLocalId', 'administrativeState', 'nRPCI', 'band',
                       'ssbFrequency', 'physicalLayerCellIdGroup', 'physicalLayerSubCellId', 'Site', 'Setor']
            cel.reindex(columns=colunas).to_csv(dst / 'NRCell.csv', index=False)
            log("NRCell.csv OK")

    except ed.EnmAliasConflictError:
        invalida()
        raise

    log(f"Post-processing complete! Files at: {output_dir}")


def _mesma_pasta(a, b) -> bool:
    return Path(a).resolve() == Path(b).resolve()


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) not in (2, 3):
        print("Usage: python pos_processamento_claro.py <txt_dir> <output_dir> [cellref_dir]")
        return 2
    txt_dir, output_dir = args[0], args[1]
    cadastro_dir = args[2] if len(args) == 3 and args[2].strip() else None
    if not Path(txt_dir).is_dir():
        print(f"TXT folder not found: {txt_dir}")
        return 1
    # A saida reescreve ENodeBFunction.txt, EUtranCellFDD.txt, AddressIPv4.txt... com
    # o mesmo nome: na mesma pasta, o TXT do parser seria trocado pelo processado.
    if _mesma_pasta(txt_dir, output_dir):
        print("The processed MOs folder must be different from the parsed TXT folder "
              f"({txt_dir}): the processed files have the same names.")
        return 1
    try:
        rc.exige_pasta_claro(output_dir)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1
    if cadastro_dir and not Path(cadastro_dir).is_dir():
        print(f"Cellref folder not found, continuing without it: {cadastro_dir}")
        cadastro_dir = None
    if cadastro_dir is None:
        print("No Claro cellref: neighbors outside the dump are resolved by the external's name.")
    processar(txt_dir, output_dir, cadastro_dir=cadastro_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
