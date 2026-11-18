# -*- coding: utf-8 -*-
"""Regras da rede Claro Puerto Rico — fonte UNICA para o resto do Tool Box.

Tudo o que no MoB da Vivo sai de fatia de nome (UF = 2 ultimos caracteres,
banda = 1a letra da celula, setor = ultimo digito, chave de site = UF +
eNB[1:4]) aqui sai destas funcoes. Medido no dump da rede inteira
(PR_mob_W42.xml, out/2026):

    no (eNB/gNB)   CAR1028_2              municipio(3) + site(4) + '_' + no do site
    celula 4G      SJU1029_B05_4_RR_A_1   site _ portadora _ 4 _ radio _ setor _ indice
    celula 5G      ABU1111_N66_5_RR_B_1   (n261 vem como '261': YAB1110_261_5_MM_A_1)

- 2.201 ENodeBFunction e 1.697 GNBCUCPFunction, todos no formato do no;
  1.572 nos sao mistos 4G+5G (mesmo nome, eNBId == gNBId).
- 14.913 celulas LTE e 5.759 NR, 100% no formato de 6 partes.
- O site da celula e SEMPRE o site do no (0 excecoes): nao existe o "Hotel de
  BTS" da Vivo. A chave de site fisico e o nome sem o sufixo do no.
- Setor e LETRA (A, B, C... ate Z em indoor). Nao ha a normalizacao 4->1 da
  Vivo: 'D' nao e repeticao de 'A'.
- Todo site NR tem LTE no mesmo site, e 5.751 de 5.759 celulas NR acham o
  mesmo (site, setor) no LTE — coordenada e co-setor do 5G vem do LTE.
- PLMN 330/110 com MNC de 3 digitos: CGI = '330110-<id>-<cell>'.

Regras gerais da operadora: skill global `claro-rede-pr`.

Copia do `mob_toolbox/app/regras_claro.py` do MoB_Claro (commit b9a443e). O
Downloader nao importa o MoB. Mudancas: o JSON de geografia vem de
`bundled_scripts/claro/` e a trava de pasta usa as pastas da Vivo do Downloader
(`operator_profiles.VIVO_ROOTS`), nao so `C:/MoB`.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

OPERADORA = "Claro PR"
MCC = "330"
MNC = "110"
MNC_LENGTH = 3
MCCMNC = MCC + MNC                      # prefixo do CGI e dos externos: 330110-...

# Comprimento do gNB ID (bits). Na Claro e 22 (1.696 de 1.697 GNBCUCPFunction e
# 3.568 de 3.570 ExternalGNodeBFunction na W42); na Vivo o .mos usava 26. Um
# External criado com o comprimento errado aponta para OUTRO gNB.
GNB_ID_LENGTH = 22

# Portadoras LTE TDD (EUtranCellTDD); o resto e FDD.
PORTADORAS_TDD = {"B41", "B46", "B48"}

_GEOGRAFIA = Path(__file__).resolve().parent / "bundled_scripts" / "claro" / "claro_pr_geography.json"

SEM_REGIAO = "Unmapped"

# <site: 3 letras + 4 digitos>_<portadora>_<tecnologia>_<radio>_<setor>_<indice>
RE_CELULA = re.compile(
    r"^(?P<site>[A-Z]{3}\d{4})_(?P<portadora>[A-Z0-9]{3})_(?P<tec>[45])_"
    r"(?P<radio>[A-Z]{2})_(?P<setor>[A-Z])_(?P<indice>\d+)$")
RE_NO = re.compile(r"^(?P<site>[A-Z]{3}\d{4})_(?P<no>\d+)$")

# Tipo de radio que so existe em indoor (Radio Dot). Os demais sao macro.
RADIOS_INDOOR = {"RD"}

# Roteador (AddressIPv4.Router) que carrega o IP de X2/Xn do no, EM ORDEM DE
# PREFERENCIA. Medido na W42 (rede inteira), pelo IP que os links usam de fato
# (usedIpAddress): 3.392 TermPointToGNB e 1.841 TermPointToGNodeB num Router=NR
# (1.695 nos). Tres nos NAO tem "NR" e usam outro nome, com os links ENABLED:
# SJU1030_1 = "NR_ESS"; PON1604_1 e SGE1332_1 = "NR_S1". Nenhum no tem dois deles.
# "NR_X2" e o da Vivo. Use `ip_x2_por_no`, nao `isin` + `drop_duplicates`.
ROTEADORES_X2 = ("NR", "NR_X2", "NR_ESS", "NR_S1")


# ---------------------------------------------------------------------------
# Nomes — versoes escalares
# ---------------------------------------------------------------------------

# Pastas da VIVO. A Claro nunca grava nem limpa nada la: o gerador de .mos do
# MoB APAGA os .mos da pasta de destino antes de gravar, e em 14/10/2026 a
# primeira versao Claro do MoB herdou caminhos da Vivo e apagou os .mos dela.
# No Downloader a lista e a mesma da trava do servidor (operator_profiles).


def ip_x2_por_no(df: pd.DataFrame, col_no: str = "eNB", col_router: str = "RouterId") -> pd.DataFrame:
    """Uma linha por no: a do roteador de X2/Xn de maior preferencia (ROTEADORES_X2).

    No sem nenhum desses roteadores fica de fora — nunca cair no IP de gerencia
    (vr_OAM) ou de S1 do LTE, que criaria um TermPoint que nao sobe.
    """
    if df is None or df.empty or col_router not in df.columns:
        return df.iloc[0:0] if df is not None else pd.DataFrame()
    ordem = {r: i for i, r in enumerate(ROTEADORES_X2)}
    d = df[df[col_router].astype(str).isin(ordem)].copy()
    d["_ordem_x2"] = d[col_router].astype(str).map(ordem)
    d = d.sort_values("_ordem_x2", kind="stable").drop_duplicates(subset=[col_no], keep="first")
    return d.drop(columns="_ordem_x2")


def eh_pasta_da_vivo(caminho) -> bool:
    import operator_profiles
    return any(operator_profiles.is_under(caminho, raiz) for raiz in operator_profiles.VIVO_ROOTS)


def exige_pasta_claro(caminho, acao: str = "write") -> None:
    """ValueError se `caminho` estiver numa pasta da Vivo. Use antes de gravar/limpar."""
    if eh_pasta_da_vivo(caminho):
        raise ValueError(f"Refusing to {acao} in a Vivo folder ({caminho}). "
                         f"Claro files stay in the Claro folders.")


def partes_celula(celula) -> dict | None:
    """{'site','portadora','tec','radio','setor','indice'} ou None se fora do padrao."""
    m = RE_CELULA.match(str(celula or "").strip())
    return m.groupdict() if m else None


def site_do_no(no) -> str:
    """CAR1028_2 -> CAR1028. Nome fora do padrao volta inteiro (nada some)."""
    s = str(no or "").strip()
    m = RE_NO.match(s)
    return m.group("site") if m else s


def site_da_celula(celula, no=None) -> str:
    """Site FISICO da celula (as 7 primeiras posicoes). Fora do padrao: site do no."""
    p = partes_celula(celula)
    if p:
        return p["site"]
    return site_do_no(no) if no is not None else str(celula or "").split("_")[0]


def setor(celula) -> str:
    """Letra do setor ('A'...'Z'); '' se o nome nao segue o padrao."""
    p = partes_celula(celula)
    return p["setor"] if p else ""


def portadora(celula) -> str:
    """Token de 3 caracteres da portadora: B04, B05, B12, B41, B46, B48, B66, N41, N66, 261."""
    p = partes_celula(celula)
    return p["portadora"] if p else ""


def tipo_lte(celula) -> str:
    """'EUtranCellFDD' ou 'EUtranCellTDD' pela portadora do nome."""
    return "EUtranCellTDD" if portadora(celula) in PORTADORAS_TDD else "EUtranCellFDD"


def portadora_rotulo(token) -> str:
    """Como mostrar na tela: '261' vira 'N261'; o resto fica igual."""
    t = str(token or "").strip()
    return "N" + t if t.isdigit() else t


def municipio(nome) -> str:
    """Codigo de 3 letras do municipio (CAR, SJU...), de no ou de celula."""
    return str(nome or "").strip()[:3].upper()


# ---------------------------------------------------------------------------
# Nomes — versoes vetoriais (pandas)
# ---------------------------------------------------------------------------

def partes_celula_serie(celulas: pd.Series) -> pd.DataFrame:
    return celulas.astype(str).str.strip().str.extract(RE_CELULA)


def site_do_no_serie(nos: pd.Series) -> pd.Series:
    s = nos.astype(str).str.strip()
    return s.str.extract(RE_NO)["site"].fillna(s)


def site_da_celula_serie(celulas: pd.Series, nos: pd.Series | None = None) -> pd.Series:
    site = partes_celula_serie(celulas)["site"]
    reserva = site_do_no_serie(nos) if nos is not None else celulas.astype(str).str.split("_").str[0]
    return site.fillna(reserva)


def setor_serie(celulas: pd.Series) -> pd.Series:
    return partes_celula_serie(celulas)["setor"].fillna("")


def portadora_serie(celulas: pd.Series) -> pd.Series:
    return partes_celula_serie(celulas)["portadora"].fillna("")


def municipio_serie(nomes: pd.Series) -> pd.Series:
    return nomes.astype(str).str.strip().str[:3].str.upper()


# ---------------------------------------------------------------------------
# Geografia: municipio -> nome e regiao operacional
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def _geografia() -> dict:
    with open(_GEOGRAFIA, encoding="utf-8") as f:
        dados = json.load(f)
    regioes = {r["id"]: r for r in dados.get("regions", [])}
    municipios = {}
    for m in dados.get("municipalities", []):
        reg = regioes.get(m.get("region_id"), {})
        municipios[m["code"].upper()] = {
            "nome": m.get("name", ""),
            "regiao": reg.get("label_en", SEM_REGIAO),
            "lat": m.get("latitude"),
            "lon": m.get("longitude"),
        }
    return municipios


def nome_municipio(codigo) -> str:
    return _geografia().get(municipio(codigo), {}).get("nome", "")


def regiao(codigo) -> str:
    """Regiao operacional (North Central, Metro East, West, South, Southeast).

    Municipio fora do cadastro cai em 'Unmapped' — nunca some do total da rede.
    """
    return _geografia().get(municipio(codigo), {}).get("regiao", SEM_REGIAO)


def regioes() -> list[str]:
    return sorted({m["regiao"] for m in _geografia().values()})


def municipios() -> dict:
    """{codigo: {'nome', 'regiao', 'lat', 'lon'}} — copia, para nao mexer no cache."""
    return {k: dict(v) for k, v in _geografia().items()}


# ---------------------------------------------------------------------------
# Bandas
# ---------------------------------------------------------------------------

# EARFCN de downlink -> banda LTE (3GPP TS 36.101). So as faixas que fazem
# sentido em Porto Rico; o nome da celula ja traz a portadora, isto e conferencia.
_FAIXAS_LTE = [
    (600, 1199, 2), (1950, 2399, 4), (2400, 2649, 5), (5010, 5179, 12),
    (5180, 5279, 13), (5730, 5849, 17), (8040, 8689, 25), (8690, 9039, 26),
    (9660, 9769, 29), (9770, 9869, 30), (39650, 41589, 41), (46790, 54539, 46),
    (55240, 56739, 48), (66436, 67335, 66), (68586, 68935, 71),
]

# NR-ARFCN (SSB/pointA de DL) -> banda NR (3GPP TS 38.104). n41 e n90 dividem a
# faixa; a Claro configura bandListManual=41 e a rede reporta bandList=90.
_FAIXAS_NR = [
    (123400, 130400, 71), (173800, 178800, 5), (386000, 398000, 2),
    (422000, 440000, 66), (499200, 537999, 41), (620000, 653333, 78),
    # n261 esta DENTRO da n257: tem de vir antes para ganhar.
    (2070833, 2084999, 261), (2054166, 2104165, 257), (2016667, 2070832, 258),
    (2229166, 2279165, 260),
]


def banda_lte(earfcn) -> int | None:
    try:
        v = int(float(earfcn))
    except (TypeError, ValueError):
        return None
    for ini, fim, banda in _FAIXAS_LTE:
        if ini <= v <= fim:
            return banda
    return None


def banda_nr(arfcn) -> int | None:
    try:
        v = int(float(arfcn))
    except (TypeError, ValueError):
        return None
    for ini, fim, banda in _FAIXAS_NR:
        if ini <= v <= fim:
            return banda
    return None


# SCS (kHz) da SSB por banda NR na Claro: e o sufixo dos ids de NRFrequency e
# GUtranSyncSignalFrequency ('424570-15', '500430-30', '2072251-120'). So
# reserva: o valor real vem do dump (ssbSubCarrierSpacing / id do MO).
SCS_PADRAO = {66: 15, 41: 30, 90: 30, 261: 120, 257: 120, 258: 120, 260: 120, 78: 30, 71: 15, 5: 15, 2: 15}


def scs_padrao(banda) -> str:
    try:
        return str(SCS_PADRAO.get(int(float(banda)), ""))
    except (TypeError, ValueError):
        return ""


def banda_da_portadora(token) -> str:
    """'B66' -> '66', 'N41' -> '41', '261' -> '261'."""
    t = str(token or "").strip().upper()
    return t[1:] if t[:1] in ("B", "N") else t


# ---------------------------------------------------------------------------
# Coordenadas do EUtranCellFDD/TDD
# ---------------------------------------------------------------------------

def decodifica_coordenadas(lat_bruta: pd.Series, lon_bruta: pd.Series) -> pd.DataFrame:
    """latitude/longitude do Ericsson -> graus decimais + a codificacao usada.

    Na rede da Claro aparecem DUAS codificacoes no mesmo atributo:

    - micrograus (o comum): 18327101 -> 18.327101;
    - 3GPP TS 23.032 (em 15 sites, algumas celulas): lat = N * 90 / 2^23,
      lon = N * 360 / 2^24. Ex.: 1721137 -> 18.4658 e -3127140 -> -67.1011,
      o mesmo ponto que as outras celulas do site dao em micrograus.

    As faixas nao se sobrepoem em Porto Rico (17,8-18,6 N): em micrograus a
    latitude fica perto de 18.000.000; em 23.032, perto de 1.700.000. Zero
    (nao configurado) e o que nao cair em nenhuma das duas vira NaN.
    """
    lat = pd.to_numeric(lat_bruta, errors="coerce")
    lon = pd.to_numeric(lon_bruta, errors="coerce")
    micro_lat, micro_lon = lat / 1e6, lon / 1e6
    g_lat, g_lon = lat * 90.0 / 2 ** 23, lon * 360.0 / 2 ** 24

    def _em_pr(la, lo):
        return la.between(17.5, 18.8) & lo.between(-68.5, -64.5)

    ok_micro = _em_pr(micro_lat, micro_lon)
    ok_3gpp = _em_pr(g_lat, g_lon) & ~ok_micro
    out = pd.DataFrame(index=lat.index)
    out["Latitude"] = np.where(ok_micro, micro_lat, np.where(ok_3gpp, g_lat, np.nan))
    out["Longitude"] = np.where(ok_micro, micro_lon, np.where(ok_3gpp, g_lon, np.nan))
    out["Coord_Codificacao"] = np.where(ok_micro, "micrograu", np.where(ok_3gpp, "3gpp_23032", ""))
    return out
