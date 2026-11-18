"""Export the legacy LOCKED and DISABLED TermPoint reports."""
from pathlib import Path

import pandas as pd


CAMILO = Path("C:/Camilo")
OUTPUT = Path("C:/Vivo Reports/5G/5G Mobilidade")


def read_tsv(filename):
    path = CAMILO / filename
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(path, sep="\t", encoding=encoding, low_memory=False)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not read {path}")


def keep(frame, columns):
    return frame.reindex(columns=[column for column in columns if column in frame.columns])


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    gnodeb = read_tsv("5G_TermPointToGNodeB.txt")
    gnb = read_tsv("5G_TermPointToGNB.txt")
    locked_gnodeb = gnodeb.loc[gnodeb["administrativeState"].astype(str).str.strip().eq("LOCKED")]
    locked_gnb = gnb.loc[gnb["administrativeState"].astype(str).str.strip().eq("LOCKED")]
    disabled_gnb = gnb.loc[gnb["operationalState"].astype(str).str.strip().eq("DISABLED")]
    locked_gnodeb = keep(locked_gnodeb, ["Regional", "UF", "MUNICIPIO", "gNB", "termPointToGNodeB", "Ancora", "administrativeState", "usedIpAddress"])
    gnb_columns = ["Regional", "UF", "MUNICIPIO", "eNB", "Ancora", "administrativeState", "operationalState", "termPointToGNBId", "usedIpAddress"]
    with pd.ExcelWriter(OUTPUT / "Termpoint_LOCKED.xlsx", engine="openpyxl") as writer:
        locked_gnodeb.to_excel(writer, sheet_name="TermPointToGnodeB", index=False)
        keep(locked_gnb, gnb_columns).to_excel(writer, sheet_name="TermPointToGNB", index=False)
    keep(disabled_gnb, gnb_columns).to_excel(OUTPUT / "TermpointToGNB_DISABLED.xlsx", index=False)
    print(f"TermPointToGNodeB LOCKED: {len(locked_gnodeb)}")
    print(f"TermPointToGNB LOCKED: {len(locked_gnb)}")
    print(f"TermPointToGNB DISABLED: {len(disabled_gnb)}")


if __name__ == "__main__":
    main()
