"""Audit de EUtranFreqRelation ausente por relevancia de frequencia na cidade.

Regra reconstruida do audit historico:

1. Considerar apenas celulas UNLOCKED e ENABLED.
2. Representar o eNB logico pela chave UF + MID(CELL, 2, 3), equivalente a
   UF + CELL.str[1:4] em Python.
3. Para cada UF/municipio/frequencia, contar em quantas chaves de eNB a
   frequencia esta presente e dividir pelo total de chaves do municipio.
4. Frequencias com percentual estritamente maior que o limite (30% por
   padrao) sao esperadas em todas as celulas ativas daquele municipio,
   inclusive quando a frequencia esperada e a propria frequencia da celula.
5. Confrontar a lista esperada com as EUtranFreqRelation existentes.

Premissa operacional: criar uma EUtranFreqRelation excedente nao causa impacto
relevante na rede. Por isso o audit usa penetracao municipal acima de 30%, e
nao distancia geografica. A regra e intencionalmente abrangente: e preferivel
gerar uma relacao potencialmente desnecessaria a deixar ausente uma relacao
que possa ser necessaria para mobilidade.

O EARFCN real de uma relacao nao e inferido de EUtranFreqRelationId. O script
extrai EUtranFrequencyId de eutranFrequencyRef e busca arfcnValueEUtranDl no
MO EUtranFrequency. Isso trata corretamente nomes como LTE e LTE_700J.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


DEFAULT_CELL_FILE = Path("C:/Camilo/EUtranCell_TDD_FDD.csv")
DEFAULT_RELATION_FILE = Path("C:/Dumps/LTE_total/EUtranFreqRelation.txt")
DEFAULT_FREQUENCY_FILE = Path("C:/Dumps/LTE_total/EUtranFrequency.txt")
DEFAULT_OUTPUT_FILE = Path(
    "C:/Vivo Reports/LTE/LTE Mobilidade/Missing Neighbor 4G_4G Cidade.xlsx"
)

CITY_KEYS = ["Regional", "UF", "MUNICIPIO"]
RELATION_KEYS = ["UF", "eNB", "CELL", "earfcndl_raw"]


def read_active_cells(path: Path) -> pd.DataFrame:
    """Le o inventario e retorna uma linha por celula LTE ativa."""
    columns = [
        "Regional",
        "UF",
        "MUNICIPIO",
        "eNB",
        "CELL",
        "earfcndl",
        "administrativeState",
        "operationalState",
    ]
    cells = pd.read_csv(path, usecols=columns, encoding="ISO-8859-1")
    cells = cells.loc[
        cells["administrativeState"].eq("UNLOCKED")
        & cells["operationalState"].eq("ENABLED")
    ].copy()

    for column in ["Regional", "UF", "MUNICIPIO", "eNB", "CELL"]:
        cells[column] = cells[column].astype("string").str.strip()
    cells["earfcndl"] = pd.to_numeric(cells["earfcndl"], errors="coerce").astype(
        "Int64"
    )
    cells = cells.dropna(subset=CITY_KEYS + ["eNB", "CELL", "earfcndl"])
    invalid_cell_name = cells["CELL"].str.len().lt(4)
    if invalid_cell_name.any():
        raise ValueError(
            f"{int(invalid_cell_name.sum())} celulas nao permitem calcular MID(CELL, 2, 3)"
        )
    # Chave historica usada para contar eNBs no percentual municipal.
    cells["eNB_contagem"] = cells["UF"] + cells["CELL"].str[1:4]

    # Duplicidade da mesma CELL tornaria a lista virtual e o output instaveis.
    conflicts = (
        cells.groupby(["UF", "eNB", "CELL"], dropna=False)["earfcndl"]
        .nunique()
        .gt(1)
    )
    if conflicts.any():
        raise ValueError(
            f"{int(conflicts.sum())} celulas possuem mais de um earfcndl no inventario"
        )

    return cells.drop_duplicates(
        subset=CITY_KEYS + ["eNB", "CELL", "earfcndl"]
    )


def calculate_city_frequencies(
    cells: pd.DataFrame, threshold: float
) -> pd.DataFrame:
    """Calcula penetracao por eNB e mantem frequencias acima do limite."""
    total_enbs = (
        cells.groupby(CITY_KEYS, dropna=False)["eNB_contagem"]
        .nunique()
        .rename("count_eNB")
        .reset_index()
    )
    frequency_enbs = (
        cells.groupby(CITY_KEYS + ["earfcndl"], dropna=False)["eNB_contagem"]
        .nunique()
        .rename("conta_earfcndl")
        .reset_index()
        .rename(columns={"earfcndl": "earfcndl_raw"})
    )
    frequency_enbs = frequency_enbs.merge(
        total_enbs, on=CITY_KEYS, how="left", validate="m:1"
    )
    percentual_exato = (
        frequency_enbs["conta_earfcndl"]
        .div(frequency_enbs["count_eNB"])
        .mul(100)
    )
    frequency_enbs["Percentual"] = percentual_exato.round(2)
    return frequency_enbs.loc[percentual_exato.gt(threshold)].copy()


def build_expected_relations(
    cells: pd.DataFrame, city_frequencies: pd.DataFrame
) -> pd.DataFrame:
    """Combina cada celula com as frequencias relevantes do municipio."""
    cell_keys = cells[CITY_KEYS + ["eNB", "CELL"]].drop_duplicates()
    expected = cell_keys.merge(
        city_frequencies,
        on=CITY_KEYS,
        how="inner",
        validate="m:m",
    )
    # A rede possui EUtranFreqRelation tambem para a propria frequencia da CELL.
    return expected.drop_duplicates(
        subset=RELATION_KEYS + ["MUNICIPIO", "Regional"]
    )


def read_frequency_objects(path: Path) -> pd.DataFrame:
    """Le os objetos que traduzem ID de frequencia para EARFCN efetivo."""
    frequencies = pd.read_csv(
        path,
        sep="\t",
        usecols=[
            "eNB",
            "ManagedElement",
            "EUtranFrequencyId",
            "arfcnValueEUtranDl",
        ],
        dtype="string",
        low_memory=False,
    )
    frequencies["eNB"] = frequencies["eNB"].fillna(
        frequencies["ManagedElement"]
    )
    frequencies["arfcnValueEUtranDl"] = pd.to_numeric(
        frequencies["arfcnValueEUtranDl"], errors="coerce"
    ).astype("Int64")
    frequencies = frequencies.dropna(
        subset=["eNB", "EUtranFrequencyId", "arfcnValueEUtranDl"]
    ).drop_duplicates()

    conflicts = (
        frequencies.groupby(["eNB", "EUtranFrequencyId"])[
            "arfcnValueEUtranDl"
        ]
        .nunique()
        .gt(1)
    )
    if conflicts.any():
        raise ValueError(
            f"{int(conflicts.sum())} objetos EUtranFrequencyId apontam para mais de um EARFCN"
        )
    return frequencies


def read_existing_relations(
    relation_path: Path,
    frequency_objects: pd.DataFrame,
    chunk_size: int = 100_000,
) -> pd.DataFrame:
    """Resolve o EARFCN efetivo de todas as EUtranFreqRelation."""
    usecols = [
        "UF",
        "eNB",
        "CELL",
        "EUtranFreqRelationId",
        "eutranFrequencyRef",
        "ManagedElement",
    ]
    chunks: list[pd.DataFrame] = []
    for chunk in pd.read_csv(
        relation_path,
        sep="\t",
        usecols=usecols,
        dtype="string",
        chunksize=chunk_size,
        low_memory=False,
    ):
        # Alguns registros do parser trazem eNB/UF vazios, mas preservam o
        # eNB de origem em ManagedElement.
        chunk["eNB"] = chunk["eNB"].fillna(chunk["ManagedElement"])
        chunk["UF"] = chunk["UF"].fillna(chunk["eNB"].str[-2:])
        chunk["EUtranFrequencyId_ref"] = chunk["eutranFrequencyRef"].str.extract(
            r"vsDataEUtranFrequency=([^,]+)", expand=False
        )
        chunks.append(chunk)
    relations = pd.concat(chunks, ignore_index=True)

    relation_frequency_map = frequency_objects.drop_duplicates(
        subset=["eNB", "EUtranFrequencyId"]
    )
    relations = relations.merge(
        relation_frequency_map,
        left_on=["eNB", "EUtranFrequencyId_ref"],
        right_on=["eNB", "EUtranFrequencyId"],
        how="left",
        validate="m:1",
    ).rename(columns={"arfcnValueEUtranDl": "earfcndl_raw"})

    unresolved = relations["earfcndl_raw"].isna()
    if unresolved.any():
        sample = relations.loc[
            unresolved, ["UF", "eNB", "CELL", "EUtranFreqRelationId"]
        ].head(10)
        raise ValueError(
            f"{int(unresolved.sum())} relacoes sem EARFCN resolvido. Amostra:\n"
            f"{sample.to_string(index=False)}"
        )

    return relations[RELATION_KEYS].drop_duplicates()


def find_missing(
    expected: pd.DataFrame, existing: pd.DataFrame
) -> pd.DataFrame:
    """Executa anti-join entre lista virtual e relacoes existentes."""
    compared = expected.merge(
        existing.assign(_relation_exists=True),
        on=RELATION_KEYS,
        how="left",
        validate="m:1",
    )
    return compared.loc[compared["_relation_exists"].isna()].drop(
        columns="_relation_exists"
    )


def add_frequency_labels(
    missing: pd.DataFrame, frequency_objects: pd.DataFrame
) -> pd.DataFrame:
    """Reproduz frequency_aux: usa o ID local, ou o EARFCN como fallback."""
    local_labels = frequency_objects.rename(
        columns={"arfcnValueEUtranDl": "earfcndl_raw"}
    )[["eNB", "earfcndl_raw", "EUtranFrequencyId"]].drop_duplicates()
    result = missing.merge(
        local_labels,
        on=["eNB", "earfcndl_raw"],
        how="left",
        validate="m:m",
    )
    valid_id = result["EUtranFrequencyId"].fillna("").str.strip().ne("")
    result["earfcndl"] = result["earfcndl_raw"].astype(object)
    result.loc[valid_id, "earfcndl"] = result.loc[valid_id, "EUtranFrequencyId"]

    output_columns = [
        "Regional",
        "MUNICIPIO",
        "UF",
        "eNB",
        "CELL",
        "earfcndl",
        "conta_earfcndl",
        "count_eNB",
        "Percentual",
        "earfcndl_raw",
        "EUtranFrequencyId",
    ]
    result = result[output_columns].drop_duplicates()
    return result.sort_values(
        ["Regional", "MUNICIPIO", "UF", "CELL", "earfcndl_raw"],
        kind="stable",
    ).reset_index(drop=True)


def run_audit(
    cell_file: Path,
    relation_file: Path,
    frequency_file: Path,
    output_file: Path,
    threshold: float,
) -> pd.DataFrame:
    cells = read_active_cells(cell_file)
    city_frequencies = calculate_city_frequencies(cells, threshold)
    expected = build_expected_relations(cells, city_frequencies)
    frequency_objects = read_frequency_objects(frequency_file)
    existing = read_existing_relations(relation_file, frequency_objects)
    missing = find_missing(expected, existing)
    result = add_frequency_labels(missing, frequency_objects)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    result.to_excel(output_file, index=False)

    print(f"Celulas ativas: {len(cells):,}")
    print(f"Frequencias cidade acima de {threshold:g}%: {len(city_frequencies):,}")
    print(f"Relacoes esperadas: {len(expected):,}")
    print(f"Missing neighbors: {len(result):,}")
    print(f"Arquivo: {output_file}")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit de Missing Neighbor 4G-4G por frequencia relevante na cidade"
    )
    parser.add_argument("--cell-file", type=Path, default=DEFAULT_CELL_FILE)
    parser.add_argument("--relation-file", type=Path, default=DEFAULT_RELATION_FILE)
    parser.add_argument("--frequency-file", type=Path, default=DEFAULT_FREQUENCY_FILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_FILE)
    parser.add_argument(
        "--threshold",
        type=float,
        default=30.0,
        help="Percentual minimo exclusivo; 30 significa Percentual > 30",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_audit(
        cell_file=args.cell_file,
        relation_file=args.relation_file,
        frequency_file=args.frequency_file,
        output_file=args.output,
        threshold=args.threshold,
    )
