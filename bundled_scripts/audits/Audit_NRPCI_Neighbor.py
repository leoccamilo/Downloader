"""Audit de NRPCI errado na ExternalNRCellCU (Ericsson 5G).

Compara o nRPCI que cada no guarda da celula vizinha (ExternalNRCellCU) com o
nRPCI real da celula (NRCellDU). Diferenca = vizinha cadastrada com PCI
desatualizado, o que atrapalha o handover.

Copia fiel de C:/Users/leocc/Audits/Audit_NRPCI_Neighbor.ipynb, o notebook que
roda toda segunda no Roda_MOs_e_Audits.ipynb. Mesmas regras e mesmas colunas:

1. Junta NRCellCU e NRCellDU da semana por UF + no + nome da celula.
2. Casa a External com a celula real pelo CGI.
3. Fica so onde o nRPCI da External e diferente do nRPCI real.
4. Fica so se o no que tem a External tiver pelo menos uma celula ENABLED.

Unica mudanca: a semana. O notebook usa a semana do calendario + 1, que
quebra no domingo (pede o arquivo de segunda, que ainda nao existe). Aqui a
semana padrao e a do 5G_NRCellDU_<semana>.txt mais recente (--semana muda).
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd


DEFAULT_EXTERNAL_FILE = Path("C:/Dumps/LTE_total/5G_ExternalNRCellCU.txt")
DEFAULT_WEEKLY_DIR = Path("C:/Camilo")
DEFAULT_OUTPUT_FILE = Path(
    "C:/Vivo Reports/5G/5G Mobilidade/Audit_NRPCI_ExternalNRCellCU.xlsx"
)

REGIONAL = {"AM": "N", "AP": "N", "MA": "N", "PA": "N", "RR": "N", "BA": "BASE", "SE": "BASE"}


def latest_week(weekly_dir: Path) -> int:
    """Semana do 5G_NRCellDU_<semana>.txt gravado por ultimo."""
    files = list(weekly_dir.glob("5G_NRCellDU_*.txt"))
    if not files:
        raise FileNotFoundError(f"Nenhum 5G_NRCellDU_*.txt em {weekly_dir}")
    newest = max(files, key=lambda f: f.stat().st_mtime)
    return int(re.search(r"_(\d+)\.txt$", newest.name).group(1))


def run(external_file: Path, weekly_dir: Path, week: int, output_file: Path) -> pd.DataFrame:
    external = pd.read_csv(
        external_file,
        sep="\t",
        usecols=["UF", "gNB", "CGI", "nRPCI", "externalNRCellCUId"],
        low_memory=False,
    )

    du = pd.read_csv(
        weekly_dir / f"5G_NRCellDU_{week}.txt",
        sep="\t",
        encoding="ISO-8859-1",
        usecols=["UF", "eNB", "nRCellDUId", "nRPCI", "operationalState"],
        low_memory=False,
    ).rename(columns={"nRCellDUId": "nRCell"})
    cu = pd.read_csv(
        weekly_dir / f"5G_NRCellCU_{week}.txt",
        sep="\t",
        encoding="ISO-8859-1",
        usecols=["UF", "eNB", "nRCellCUId", "CGI"],
        low_memory=False,
    ).rename(columns={"nRCellCUId": "nRCell"})

    nrcell = pd.merge(cu, du, on=["UF", "eNB", "nRCell"], how="inner").rename(
        columns={
            "eNB": "gNB_tgt",
            "nRCell": "nRCellCUId_tgt",
            "CGI": "CGI_tgt",
            "nRPCI": "nRPCI_nRCell",
            "UF": "UF_NRCell",
        }
    )

    audit = pd.merge(external, nrcell, left_on=["CGI"], right_on=["CGI_tgt"], how="inner")
    audit = audit[audit["nRPCI"] != audit["nRPCI_nRCell"]]
    audit.insert(0, "Regional", audit["UF"].replace(REGIONAL))

    # No que tem a External precisa ter pelo menos uma celula ENABLED.
    nos_ativos = (
        nrcell[["gNB_tgt", "operationalState"]]
        .drop_duplicates()
        .query("operationalState == 'ENABLED'")
        .rename(columns={"operationalState": "operationalState_src"})
    )
    audit = pd.merge(audit, nos_ativos, left_on="gNB", right_on="gNB_tgt", how="inner")
    audit = audit.rename(
        columns={"gNB_tgt_x": "gNB_tgt", "operationalState": "operationalState_tgt"}
    ).drop(columns="gNB_tgt_y")

    output_file.parent.mkdir(parents=True, exist_ok=True)
    audit.to_excel(output_file, index=False)

    print(f"Semana dos MOs: {week}")
    print(f"Externals com nRPCI diferente do real: {len(audit):,}")
    if len(audit):
        print(audit.groupby("Regional").size().to_string())
    print(f"\nArquivo: {output_file}")
    return audit


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--external", type=Path, default=DEFAULT_EXTERNAL_FILE)
    parser.add_argument("--pasta-semanal", type=Path, default=DEFAULT_WEEKLY_DIR)
    parser.add_argument("--semana", type=int, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_FILE)
    args = parser.parse_args()
    week = args.semana if args.semana is not None else latest_week(args.pasta_semanal)
    run(args.external, args.pasta_semanal, week, args.output)


if __name__ == "__main__":
    main()
