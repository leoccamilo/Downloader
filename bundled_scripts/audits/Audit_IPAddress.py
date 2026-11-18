"""Audit TermPoint IPv4 addresses against AddressIPv4 NR_X2 references."""
from pathlib import Path

import pandas as pd


CAMILO = Path("C:/Camilo")
PROCESSED = Path("C:/Dumps/LTE_Total")
OUTPUT = Path("C:/Vivo Reports/5G/5G Mobilidade")


def read_tsv(path):
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            return pd.read_csv(path, sep="\t", encoding=encoding, low_memory=False)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Could not read {path}")


def keep(frame, columns):
    return frame.reindex(columns=[column for column in columns if column in frame.columns]).drop_duplicates()


def incorrect(frame, references, node_column, ip_column):
    joined = frame.merge(references, left_on=["UF", node_column], right_on=["UF", "eNB"], how="inner")
    return joined.loc[joined[ip_column].fillna("").astype(str).ne(joined["IP_address"].fillna("").astype(str))].copy()


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    addresses = read_tsv(PROCESSED / "AddressIPv4.txt")
    required = {"UF", "eNB", "IP_address", "Router"}
    if absent := required.difference(addresses.columns):
        raise ValueError("AddressIPv4 missing columns: " + ", ".join(sorted(absent)))
    references = addresses.loc[addresses["Router"].astype(str).str.strip().eq("NR_X2"), ["UF", "eNB", "IP_address"]]
    gnodeb = read_tsv(CAMILO / "5G_TermPointToGNodeB.txt")
    gnb = read_tsv(CAMILO / "5G_TermPointToGNB.txt").rename(columns={"ipAddress": "ipv4Address"})
    bad_gnodeb = incorrect(gnodeb, references, "Ancora", "ipv4Address").rename(columns={"ipv4Address": "ipv4Address_atual", "IP_address": "ipv4Address_sugerido"})
    bad_gnb = incorrect(gnb, references, "Ancora", "ipv4Address").rename(columns={"ipv4Address": "ipv4Address_atual", "IP_address": "ipv4Address_sugerido", "eNB_x": "eNB"})
    gnodeb_columns = ["Regional", "MO", "UF", "gNB", "termPointToGNodeB", "ExternalGNBCUCPFunction", "Ancora", "administrativeState", "availabilityStatus", "ipv4Address_atual", "ipv6Address", "operationalState", "termPointToGNodeBId", "usedIpAddress", "usedPLMNId_mcc", "usedPLMNId_mnc", "eNB", "ipv4Address_sugerido"]
    gnb_columns = ["UF", "eNB", "Ancora", "administrativeState", "availabilityStatus", "operationalState", "createdBy", "termPointToGNBId", "ipv4Address_atual", "ipv4Address_sugerido"]
    with pd.ExcelWriter(OUTPUT / "Audit_IPAddress.xlsx", engine="openpyxl") as writer:
        keep(bad_gnodeb, gnodeb_columns).to_excel(writer, sheet_name="TermpointToGNodeB", index=False)
        keep(bad_gnb, gnb_columns).to_excel(writer, sheet_name="TermpointToGNB", index=False)
    print(f"TermPointToGNodeB incorrect IPs: {len(bad_gnodeb)}")
    print(f"TermPointToGNB incorrect IPs: {len(bad_gnb)}")


if __name__ == "__main__":
    main()
