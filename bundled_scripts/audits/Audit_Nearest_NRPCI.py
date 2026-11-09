"""Audit de NRPCI repetido proximo (Ericsson 5G).

Para cada celula NR do cellref_5g, encontra a celula mais proxima que usa o
mesmo NR_PCI na mesma frequencia (DL_NR_ARFCN) e informa a distancia em km.
Quanto menor a distancia, maior o risco de colisao/confusao de PCI.

Base: C:/Users/leocc/Audits/Audit_Nearest_NRPCI.ipynb (celula com BallTree,
ultima saida conhecida em 02/03/2026). Mudancas em relacao a ele:

1. Compara apenas celulas na mesma frequencia. PCI igual em frequencias
   diferentes (ex.: 3500 x 2100) nao gera conflito, e o audit antigo podia
   apontar como "mais proxima" uma celula de outra banda.
2. Como a frequencia ja separa as bandas do mesmo site, celulas com a mesma
   coordenada deixam de ser descartadas: mesmo PCI + mesma frequencia no
   mesmo ponto (ex.: Hotel de BTS) e conflito real e aparece com distancia 0.
3. Calculo exato entre todas as celulas do grupo PCI + frequencia, sem o
   limite de 5 vizinhos do BallTree. Nao precisa de scikit-learn.
4. Le MUNICIPIO (sem acento), nome atual da coluna no cellref_5g, e a UF da
   coluna UF (antes era tirada do fim do SiteID).
5. Mantem so os PCIs repetidos a ate 5 km (--max-km muda o limite). O audit
   antigo nao filtrava e listava repeticoes a ate 2.600 km; o corte de 5 km
   ficava no NRPCI_Planning (Distancia_km < 5.01).

DL_NR_ARFCN e o ssbFrequency do NRCellDU. Na Ericsson, ssbFrequency = 0 quer
dizer que o no escolhe a frequencia sozinho (o valor fica em
ssbFrequencyAutoSelected, que o dump semanal nao traz). Nesses casos o audit
usa o ARFCN mais comum da mesma Band e registra isso na coluna Obs.

Saida: mesmo arquivo e mesmas colunas do audit antigo (o NRPCI_Planning le
este arquivo), com colunas extras no fim.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


DEFAULT_CELLREF_FILE = Path("C:/Camilo/cellref_5g.xlsx")
DEFAULT_OUTPUT_FILE = Path(
    "C:/Vivo Reports/5G/5G Mobilidade/Nearest_NRPCI_MG_BASE_N.xlsx"
)

EARTH_RADIUS_KM = 6371.0
DEFAULT_MAX_KM = 5.0

# Colunas do audit antigo, na mesma ordem.
BASE_COLUMNS = [
    "REGION",
    "UF",
    "CN",
    "MUNICIPIO",
    "SiteID",
    "Cellname",
    "Longitude",
    "Latitude",
    "NR_PCI",
    "Height",
]
EXTRA_COLUMNS = ["Band", "DL_NR_ARFCN", "administrativeState", "cellState", "Vendor"]


def read_cells(path: Path) -> pd.DataFrame:
    """Le o cellref_5g e devolve uma linha por celula com PCI e coordenada."""
    cells = pd.read_excel(path)
    missing = [c for c in BASE_COLUMNS + EXTRA_COLUMNS if c not in cells.columns]
    if missing:
        raise ValueError(f"Colunas ausentes no cellref: {missing}")

    cells = cells[BASE_COLUMNS + EXTRA_COLUMNS].copy()
    cells = cells.dropna(subset=["SiteID", "Cellname", "Latitude", "Longitude", "NR_PCI"])
    # Mesmo filtro do audit antigo: SiteID iniciado por T fica fora.
    cells = cells[cells["SiteID"].astype(str).str[0] != "T"]
    cells["NR_PCI"] = cells["NR_PCI"].astype(int)

    # Frequencia usada na comparacao. Zero = frequencia automatica no no.
    arfcn = pd.to_numeric(cells["DL_NR_ARFCN"], errors="coerce")
    arfcn = arfcn.where(arfcn > 0)
    band_mode = arfcn.groupby(cells["Band"].astype(str)).agg(
        lambda s: s.mode().iloc[0] if s.notna().any() else np.nan
    )
    inferred = arfcn.isna()
    arfcn = arfcn.fillna(cells["Band"].astype(str).map(band_mode))
    cells["Freq"] = arfcn
    cells["Obs"] = np.where(
        inferred, "ssbFrequency = 0 (automatico); usado o ARFCN da Band", ""
    )

    sem_freq = cells["Freq"].isna()
    if sem_freq.any():
        print(f"Aviso: {int(sem_freq.sum())} celulas sem frequencia ficaram fora do audit.")
        cells = cells[~sem_freq]
    if inferred.any():
        lista = ", ".join(cells.loc[inferred.reindex(cells.index, fill_value=False), "Cellname"])
        print(f"Aviso: ssbFrequency = 0 (automatico), usado o ARFCN da Band: {lista}")

    return cells.reset_index(drop=True)


def nearest_same_pci(cells: pd.DataFrame) -> pd.DataFrame:
    """Para cada celula, acha a celula mais proxima com mesmo PCI e frequencia."""
    lat = np.radians(cells["Latitude"].to_numpy(float))
    lon = np.radians(cells["Longitude"].to_numpy(float))
    cell_key = (cells["SiteID"].astype(str) + "|" + cells["Cellname"].astype(str)).to_numpy()

    src_pos, tgt_pos, dist_km = [], [], []
    for pos in cells.groupby(["NR_PCI", "Freq"]).indices.values():
        if len(pos) < 2:
            continue
        la, lo = lat[pos], lon[pos]
        a = (
            np.sin((la[:, None] - la[None, :]) / 2) ** 2
            + np.cos(la)[:, None] * np.cos(la)[None, :]
            * np.sin((lo[:, None] - lo[None, :]) / 2) ** 2
        )
        d = 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))
        # A propria celula (ou a mesma celula repetida no cellref) nao conta.
        keys = cell_key[pos]
        d[keys[:, None] == keys[None, :]] = np.inf

        best = d.argmin(axis=1)
        best_dist = d[np.arange(len(pos)), best]
        ok = np.isfinite(best_dist)
        src_pos.extend(pos[ok])
        tgt_pos.extend(pos[best[ok]])
        dist_km.extend(best_dist[ok])

    src = cells.iloc[src_pos].reset_index(drop=True)
    tgt = cells.iloc[tgt_pos].reset_index(drop=True)

    result = pd.concat(
        [src[BASE_COLUMNS].add_suffix("_src"), tgt[BASE_COLUMNS].add_suffix("_tgt")],
        axis=1,
    )
    result["Distancia_km"] = dist_km
    for column in EXTRA_COLUMNS:
        result[f"{column}_src"] = src[column]
        result[f"{column}_tgt"] = tgt[column]
    obs = src["Obs"].where(src["Obs"] != "", tgt["Obs"])
    result["Obs"] = obs

    return result.sort_values(["REGION_src", "Distancia_km"]).reset_index(drop=True)


def print_summary(result: pd.DataFrame, max_km: float) -> None:
    """Mostra quantas celulas tem PCI repetido perto, por regional."""
    limites = sorted({x for x in (1, 3, 5, 10) if x < max_km} | {max_km})
    resumo = pd.DataFrame(
        {
            f"ate {limite:g} km": result[result["Distancia_km"] <= limite]
            .groupby("REGION_src")
            .size()
            for limite in limites
        }
    ).fillna(0).astype(int)
    resumo.loc["TOTAL"] = resumo.sum()
    print("\nCelulas com o mesmo PCI + frequencia ate X km:")
    print(resumo.to_string())


def run(cellref_file: Path, output_file: Path, max_km: float) -> pd.DataFrame:
    cells = read_cells(cellref_file)
    result = nearest_same_pci(cells)
    result = result[result["Distancia_km"] <= max_km].reset_index(drop=True)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    result.to_excel(output_file, index=False)

    print(f"Celulas no cellref: {len(cells):,}")
    print(f"Linhas no audit (ate {max_km:g} km): {len(result):,}")
    print_summary(result, max_km)
    print(f"\nArquivo: {output_file}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cellref", type=Path, default=DEFAULT_CELLREF_FILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_FILE)
    parser.add_argument(
        "--max-km",
        type=float,
        default=DEFAULT_MAX_KM,
        help="distancia maxima para listar o PCI repetido (padrao: 5 km)",
    )
    args = parser.parse_args()
    run(cellref_file=args.cellref, output_file=args.output, max_km=args.max_km)


if __name__ == "__main__":
    main()
