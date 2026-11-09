"""Planejamento de NRPCI para os sites com PCI repetido perto (Ericsson 5G).

Le o resultado do Audit_Nearest_NRPCI.py e sugere um grupo novo de 3 PCIs
para os sites que precisam mudar.

Base: C:/Users/leocc/Huawei/NRPCI_Planning.ipynb (celula 6). Mantido:

- Grupos de 3 PCIs x, x+8, x+16 (blocos de 24), o mesmo padrao da rede:
  setor 1 = x, setor 2 = x+8, setor 3 = x+16, repetido em todas as bandas.
- Sugestao_1 e Sugestao_2 na faixa 0-503 (grupos 1-168, a faixa usada na
  rede) e Sugestao_NR na faixa 504-1007 (grupos 169-336, quase livre).
- Criterio: melhor grupo = reuso mais distante, isto e, a maior distancia
  ate a celula mais proxima que ja usa algum dos 3 PCIs (todas as bandas).
  Grupo sem nenhum PCI em uso = LIVRE.
- Dois sites planejados a menos de 10 km nunca recebem o mesmo grupo.

Corrigido:

0. A unidade do planejamento e o LOCAL (no + coordenada), nao o no. Num
   Hotel de BTS o no atende varios sites fisicos (ex.: MAPS2_MG = BH Centro
   1, 2 e 3), e planejar pelo no dava o mesmo PCI a celulas a 150 m.
1. Muda so um local de cada par em conflito. Escolha: o local com mais
   conflitos; empate = o que nao precisa de revisao manual, depois o que tem
   menos celulas, depois ordem alfabetica. Antes os dois lados mudavam.
2. A regra dos 10 km vale para as tres sugestoes. Antes valia so para a
   Sugestao_1, e todos os sites recebiam o mesmo grupo LIVRE na Sugestao_NR.
3. Um grupo sugerido a um site a mais de 10 km nao fica bloqueado. Antes o
   bloqueio valia para o pais inteiro, apesar do comentario dizer "proximos".
4. Cada sugestao feita entra na conta das proximas, como se ja estivesse na
   rede, e as celulas do proprio local nao contam (o PCI delas vai mudar).
5. Grupo com parte dos PCIs livres entra na disputa (antes era descartado).

Saida: aba Por_site (sugestoes, PCIs de cada grupo e com quem o site
conflita) e aba Por_celula (PCI atual e PCI novo de cada celula).
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_AUDIT_FILE = Path(
    "C:/Vivo Reports/5G/5G Mobilidade/Nearest_NRPCI_MG_BASE_N.xlsx"
)
DEFAULT_CELLREF_FILE = Path("C:/Camilo/cellref_5g.xlsx")
DEFAULT_OUTPUT_FILE = Path(
    "C:/Vivo Reports/5G/5G Mobilidade/Audit_NRPCI_Planning_ERICSSON.xlsx"
)
DEFAULT_MAX_KM = 5.0

DIST_MIN_KM = 10.0  # sites planejados mais perto que isso nao repetem grupo
EARTH_RADIUS_KM = 6371.0
MAX_PCI = 1007
ULTIMO_GRUPO_FAIXA_0_503 = 168
POSICAO_DO_SETOR = {"1": 0, "2": 1, "3": 2}  # setor -> x, x+8, x+16


def pci_groups() -> dict[int, tuple[int, ...]]:
    """Grupo -> 3 PCIs (x, x+8, x+16), mesma numeracao do notebook."""
    groups: dict[int, list[int]] = {}
    for pci in range(MAX_PCI + 1):
        grupo = (pci % 8) + 1 + (pci // 24) * 8
        groups.setdefault(grupo, []).append(pci)
    return {grupo: tuple(pcis) for grupo, pcis in groups.items()}


def haversine_km(lat: float, lon: float, lats, lons) -> np.ndarray:
    lat, lon, lats, lons = map(np.radians, (lat, lon, np.asarray(lats), np.asarray(lons)))
    a = (
        np.sin((lats - lat) / 2) ** 2
        + np.cos(lat) * np.cos(lats) * np.sin((lons - lon) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def local_key(site, lat, lon) -> pd.Series:
    """Chave do local fisico: no + coordenada (6 casas, ~10 cm)."""
    return (
        pd.Series(site).astype(str).to_numpy()
        + "|" + pd.Series(lat).astype(float).round(6).astype(str).to_numpy()
        + "|" + pd.Series(lon).astype(float).round(6).astype(str).to_numpy()
    )


def read_cells(path: Path) -> pd.DataFrame:
    cells = pd.read_excel(path)
    cells = cells.dropna(subset=["SiteID", "Cellname", "Latitude", "Longitude", "NR_PCI"])
    cells["NR_PCI"] = cells["NR_PCI"].astype(int)
    cells["Setor"] = cells["Cellname"].astype(str).str[-1]
    cells["Local"] = local_key(cells["SiteID"], cells["Latitude"], cells["Longitude"])

    # Nome do local para leitura: o no, e o Site_Name quando o no tem mais de um.
    locais_por_no = cells.groupby("SiteID")["Local"].nunique()
    varios = cells["SiteID"].map(locais_por_no) > 1
    cells["Local_nome"] = cells["SiteID"].where(
        ~varios, cells["SiteID"] + " (" + cells["Site_Name"].astype(str) + ")"
    )
    return cells.reset_index(drop=True)


def manual_review_reason(local_cells: pd.DataFrame) -> str:
    """Motivo para revisar o local na mao, ou texto vazio."""
    reasons = []
    fora = local_cells.loc[~local_cells["Setor"].isin(POSICAO_DO_SETOR), "Cellname"]
    if not fora.empty:
        reasons.append("setor fora de 1/2/3: " + ", ".join(sorted(fora)))
    repetido = local_cells.groupby(["Band", "Setor"]).size()
    if repetido.gt(1).any():
        reasons.append("mais de uma celula no mesmo setor e banda")
    return "; ".join(reasons)


def choose_locals(audit: pd.DataFrame, cells: pd.DataFrame) -> pd.DataFrame:
    """Escolhe o menor grupo de locais que, mudando, resolve todos os pares."""
    src = local_key(audit["SiteID_src"], audit["Latitude_src"], audit["Longitude_src"])
    tgt = local_key(audit["SiteID_tgt"], audit["Latitude_tgt"], audit["Longitude_tgt"])
    edges: dict[tuple[str, str], float] = {}
    for a, b, dist in zip(src, tgt, audit["Distancia_km"]):
        key = tuple(sorted((a, b)))
        edges[key] = min(dist, edges.get(key, np.inf))

    por_local = cells.groupby("Local")
    n_cells = por_local.size()
    nome = por_local["Local_nome"].first()
    envolvidos = {s for pair in edges for s in pair}
    faltando = envolvidos - set(n_cells.index)
    if faltando:
        raise ValueError(f"Locais do audit que nao estao no cellref: {sorted(faltando)}")
    review = {loc: manual_review_reason(por_local.get_group(loc)) for loc in envolvidos}

    pending = set(edges)
    chosen = []
    while pending:
        degree = Counter(s for pair in pending for s in set(pair))
        loc = min(
            degree,
            key=lambda s: (-degree[s], review[s] != "", n_cells[s], nome[s]),
        )
        chosen.append(loc)
        pending = {pair for pair in pending if loc not in pair}

    rows = []
    for loc in chosen:
        mine = {pair: d for pair, d in edges.items() if loc in pair}
        partners = sorted({nome[s] for pair in mine for s in pair if s != loc}) or [nome[loc]]
        rows.append(
            {
                "Local": loc,
                "Conflito_com": ", ".join(partners),
                "Dist_conflito_km": round(min(mine.values()), 2),
                "Obs": review[loc],
            }
        )
    # Conflito mais grave escolhe primeiro.
    return pd.DataFrame(rows).sort_values("Dist_conflito_km").reset_index(drop=True)


def plan(cells: pd.DataFrame, chosen: pd.DataFrame) -> pd.DataFrame:
    """Sugere os grupos de cada site, um site por vez."""
    groups = pci_groups()
    faixa_baixa = [g for g in groups if g <= ULTIMO_GRUPO_FAIXA_0_503]
    faixa_alta = [g for g in groups if g > ULTIMO_GRUPO_FAIXA_0_503]

    lat = cells["Latitude"].to_numpy(float)
    lon = cells["Longitude"].to_numpy(float)
    pci = cells["NR_PCI"].to_numpy(int)
    local_of = cells["Local"].to_numpy()
    local_pos = cells.groupby("Local")[["Latitude", "Longitude"]].first()

    # Sugestoes ja feitas, tratadas como se ja estivessem na rede.
    sug_lat: list[float] = []
    sug_lon: list[float] = []
    sug_pci: list[int] = []
    planned: list[tuple[float, float, set[int]]] = []

    rows = []
    for loc in chosen["Local"]:
        s_lat, s_lon = local_pos.loc[loc, ["Latitude", "Longitude"]]

        nearest_by_pci = np.full(MAX_PCI + 1, np.inf)
        dist = haversine_km(s_lat, s_lon, lat, lon)
        dist[local_of == loc] = np.inf
        np.minimum.at(nearest_by_pci, pci, dist)
        if sug_pci:
            dist_sug = haversine_km(s_lat, s_lon, sug_lat, sug_lon)
            np.minimum.at(nearest_by_pci, np.array(sug_pci), dist_sug)

        blocked: set[int] = set()
        for p_lat, p_lon, p_groups in planned:
            if haversine_km(s_lat, s_lon, [p_lat], [p_lon])[0] < DIST_MIN_KM:
                blocked |= p_groups

        def ranking(candidates: list[int]) -> list[tuple[int, float]]:
            scored = [
                (g, float(nearest_by_pci[list(groups[g])].min()))
                for g in candidates
                if g not in blocked
            ]
            return sorted(scored, key=lambda item: (-item[1], item[0]))

        baixa = ranking(faixa_baixa)
        alta = ranking(faixa_alta)
        picks = {
            "Sugestao_1": baixa[0] if len(baixa) > 0 else None,
            "Sugestao_2": baixa[1] if len(baixa) > 1 else None,
            "Sugestao_NR": alta[0] if len(alta) > 0 else None,
        }

        row = {"Local": loc}
        new_groups = set()
        for name, pick in picks.items():
            if pick is None:
                row.update({name: None, f"PCIs_{name}": "", f"Dist_{name}": None})
                continue
            grupo, score = pick
            new_groups.add(grupo)
            row[name] = grupo
            row[f"PCIs_{name}"] = " / ".join(str(p) for p in groups[grupo])
            row[f"Dist_{name}"] = "LIVRE" if np.isinf(score) else round(score, 2)
        rows.append(row)

        planned.append((s_lat, s_lon, new_groups))
        for grupo in new_groups:
            for p in groups[grupo]:
                sug_lat.append(s_lat)
                sug_lon.append(s_lon)
                sug_pci.append(p)

    return pd.DataFrame(rows)


def per_cell(cells: pd.DataFrame, por_local: pd.DataFrame) -> pd.DataFrame:
    """PCI atual e PCI novo de cada celula dos locais que vao mudar."""
    groups = pci_groups()
    locais = por_local.set_index("Local")
    local_cells = cells[cells["Local"].isin(locais.index)].copy()
    repetido = local_cells.duplicated(["Local", "Band", "Setor"], keep=False)

    rows = []
    for cell, rep in zip(
        local_cells.itertuples(), repetido.to_numpy()
    ):
        info = locais.loc[cell.Local]
        pos = POSICAO_DO_SETOR.get(cell.Setor)
        if pos is None:
            obs = "setor fora de 1/2/3: escolher PCI na mao"
        elif rep:
            obs = "mais de uma celula no mesmo setor e banda: escolher PCI na mao"
        else:
            obs = ""
        row = {
            "REGION": cell.REGION,
            "UF": cell.UF,
            "SiteID": cell.SiteID,
            "Site_Name": cell.Site_Name,
            "Cellname": cell.Cellname,
            "Band": cell.Band,
            "Setor": cell.Setor,
            "cellState": cell.cellState,
            "PCI_atual": cell.NR_PCI,
        }
        for name in ["Sugestao_1", "Sugestao_2", "Sugestao_NR"]:
            grupo = info[name]
            ok = obs == "" and pd.notna(grupo)
            row[f"PCI_{name}"] = groups[int(grupo)][pos] if ok else None
        row["Obs"] = obs
        rows.append(row)
    result = pd.DataFrame(rows)
    return result.sort_values(["REGION", "SiteID", "Site_Name", "Band", "Cellname"])


def run(audit_file: Path, cellref_file: Path, output_file: Path, max_km: float) -> None:
    cells = read_cells(cellref_file)
    audit = pd.read_excel(audit_file)
    audit = audit[audit["Distancia_km"] <= max_km]

    chosen = choose_locals(audit, cells)
    sugestoes = plan(cells, chosen)
    info = cells.groupby("Local")[
        ["REGION", "UF", "SiteID", "Local_nome", "Latitude", "Longitude"]
    ].first()
    atuais = (
        cells.sort_values("NR_PCI")
        .groupby("Local")["NR_PCI"]
        .apply(lambda s: " / ".join(str(p) for p in s.unique()))
        .rename("PCIs_atuais")
    )

    por_local = (
        chosen.merge(sugestoes, on="Local")
        .join(info, on="Local")
        .join(atuais, on="Local")
        .rename(columns={"SiteID": "SiteID_src"})
    )
    # Em area densa a faixa 0-503 pode nao ter grupo longe o bastante.
    fraco = pd.to_numeric(por_local["Dist_Sugestao_1"], errors="coerce") < max_km
    aviso = (
        f"nenhum grupo da faixa 0-503 fica a mais de {max_km:g} km: "
        "preferir a Sugestao_NR"
    )
    por_local["Obs"] = np.where(
        fraco,
        np.where(por_local["Obs"] == "", aviso, por_local["Obs"] + "; " + aviso),
        por_local["Obs"],
    )

    por_celula = per_cell(cells, por_local)
    colunas = [
        "REGION", "UF", "SiteID_src", "Local_nome", "Latitude", "Longitude",
        "Conflito_com", "Dist_conflito_km", "PCIs_atuais",
        "Sugestao_1", "PCIs_Sugestao_1", "Dist_Sugestao_1",
        "Sugestao_2", "PCIs_Sugestao_2", "Dist_Sugestao_2",
        "Sugestao_NR", "PCIs_Sugestao_NR", "Dist_Sugestao_NR",
        "Obs",
    ]
    por_site = por_local[colunas].rename(columns={"Local_nome": "Local"})

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(output_file) as writer:
        por_site.to_excel(writer, sheet_name="Por_site", index=False)
        por_celula.to_excel(writer, sheet_name="Por_celula", index=False)

    src = local_key(audit["SiteID_src"], audit["Latitude_src"], audit["Longitude_src"])
    tgt = local_key(audit["SiteID_tgt"], audit["Latitude_tgt"], audit["Longitude_tgt"])
    print(f"Locais com PCI repetido ate {max_km:g} km: {len(set(src) | set(tgt))}")
    print(f"Locais que precisam mudar (um por par):  {len(por_site)}")
    revisar = por_site["Obs"].str.contains("na mao|fora de 1/2/3|mesmo setor").sum()
    if revisar:
        print(f"Locais para revisar na mao (ver coluna Obs): {revisar}")
    if fraco.any():
        print(f"Locais onde a Sugestao_NR e a melhor opcao (ver coluna Obs): {int(fraco.sum())}")
    print(f"\nArquivo: {output_file}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT_FILE)
    parser.add_argument("--cellref", type=Path, default=DEFAULT_CELLREF_FILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_FILE)
    parser.add_argument(
        "--max-km",
        type=float,
        default=DEFAULT_MAX_KM,
        help="planeja os PCIs repetidos ate esta distancia (padrao: 5 km)",
    )
    args = parser.parse_args()
    run(args.audit, args.cellref, args.output, args.max_km)


if __name__ == "__main__":
    main()
