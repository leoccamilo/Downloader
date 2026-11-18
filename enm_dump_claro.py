# -*- coding: utf-8 -*-
"""Funcoes do `enm_dump.py` do MoB_Claro que o pos-processamento da Claro usa.

Copiadas SEM alteracao (MoB_Claro, commit b9a443e, linhas 606-956): o Downloader
nao importa nada do MoB em tempo de execucao. Sao genericas (aliases de
atributo do Ericsson e resolucao do alvo dos TermPoints pelos atributos dos
externals); UF/Regional que elas calculam no padrao da Vivo sao sobrescritos
pelo `pos_processamento_claro` com as regras da Claro.
"""

import re

# ===== Post-processing dos MOs =====
def _normalize_enm_identifier(value):
    """Return a stable textual representation for numeric ENM identifiers."""
    import pandas as pd

    if pd.isna(value):
        return ''
    text = str(value).strip()
    match = re.fullmatch(r'([+-]?\d+)(?:\.0+)?', text)
    return match.group(1) if match else text


def _find_case_alias_groups(columns):
    """List groups of distinct column names that differ only by capitalization."""
    groups = {}
    for column in columns:
        text = str(column)
        groups.setdefault(text.casefold(), []).append(text)
    return [
        tuple(groups[key])
        for key in sorted(groups)
        if len(set(groups[key])) > 1
    ]


class EnmAliasConflictError(ValueError):
    """Raised when equivalent Ericsson attributes disagree in the same row."""


def _coalesce_enm_aliases(frame, *columns):
    """Return the first populated Ericsson schema alias for each row.

    Ericsson ERBS and RadioNode schemas sometimes expose the same attribute
    with different capitalization.  The XML parser intentionally preserves
    the raw names, so consumers must coalesce the known aliases explicitly.
    Aliases with conflicting populated values are rejected explicitly.
    """
    import pandas as pd

    result = pd.Series(pd.NA, index=frame.index, dtype='object')
    for column in columns:
        if column not in frame.columns:
            continue
        candidate = frame[column]
        populated = candidate.notna() & candidate.astype(str).str.strip().ne('')
        conflicts = (
            result.notna() &
            populated &
            result.astype(str).str.strip().ne(candidate.astype(str).str.strip())
        )
        if conflicts.any():
            raise EnmAliasConflictError(
                f"Conflicting Ericsson aliases {columns}: "
                f"{int(conflicts.sum())} row(s) contain different values"
            )
        result = result.mask(result.isna() & populated, candidate)
    return result


def _canonicalize_enm_aliases(frame, canonical, *aliases):
    """Coalesce exact aliases into one canonical column and remove the others."""
    frame[canonical] = _coalesce_enm_aliases(frame, canonical, *aliases)
    redundant = [column for column in aliases if column != canonical and column in frame.columns]
    if redundant:
        frame.drop(columns=redundant, inplace=True)
    return frame[canonical]


def _process_termpoint_to_amf(termpoints):
    """Normalize TermPointToAmf for MoBot analysis and processed ENM dumps."""
    import pandas as pd

    result = termpoints.dropna(thresh=1, axis='columns').copy()
    if 'eNB' not in result.columns:
        result['eNB'] = pd.NA
    if 'ManagedElement' in result.columns:
        result['eNB'] = result['eNB'].combine_first(result['ManagedElement'])
    result['UF'] = result['eNB'].astype('string').str[-2:]
    result['termPointToAmfId'] = (
        _canonicalize_enm_aliases(result, 'termPointToAmfId', 'TermPointToAmfId')
        .fillna('').astype(str).str.strip()
    )
    result['Regional'] = result['UF'].replace(
        ['AM', 'AP', 'MA', 'PA', 'RR', 'BA', 'SE'],
        ['N', 'N', 'N', 'N', 'N', 'BASE', 'BASE'],
    )

    identity = [column for column in ('UF', 'eNB', 'termPointToAmfId') if column in result.columns]
    if identity:
        result.drop_duplicates(subset=identity, inplace=True)

    output_columns = [
        'Regional', 'MO', 'UF', 'eNB', 'administrativeState', 'amfName',
        'defaultAmf', 'ipv4Address1', 'ipv4Address2', 'ipv6Address1',
        'ipv6Address2', 'operationalState', 'pLMNIdList_mcc',
        'pLMNIdList_mnc', 'pwsRestartHandling', 'relativeCapacity',
        'servedGuamiList_amfPointer', 'servedGuamiList_amfRegionId',
        'servedGuamiList_amfSetId', 'servedGuamiList_mcc',
        'servedGuamiList_mnc', 'sNSSAIList_sd', 'sNSSAIList_sst',
        'termPointToAmfId', 'usedIpAddress',
    ]
    for column in output_columns:
        if column not in result.columns:
            result[column] = ''
    return result[output_columns]


def _process_termpoint_to_enodeb(termpoints, external_enodebs, local_enodebs):
    """Resolve 5G -> 4G TermPoints from configured ExternalENodeBFunction fields.

    The ``auto...`` identifier is an object label and has multiple naming variants in
    the live network.  It must not be parsed positionally.  The target key is built
    from the configured PLMN and eNodeBId attributes of the referenced external MO.
    """
    import pandas as pd

    result = termpoints.dropna(thresh=1, axis='columns').copy()
    if 'ManagedElement' in result.columns:
        # ManagedElement is the source node; eNB is its normalized output alias.
        result['eNB'] = result['ManagedElement']
    elif 'eNB' in result.columns:
        result['ManagedElement'] = result['eNB']
    else:
        result['ManagedElement'] = ''
        result['eNB'] = ''
    result['UF'] = result['eNB'].astype('string').str[-2:]

    result['ExternalENodeBFunction'] = (
        _canonicalize_enm_aliases(
            result, 'ExternalENodeBFunction', 'externalENodeBFunction'
        ).fillna('').astype(str).str.strip()
    )
    result['termPointToENodeBId'] = (
        _canonicalize_enm_aliases(
            result, 'termPointToENodeBId', 'TermPointToENodeBId'
        ).fillna('').astype(str).str.strip()
    )
    result['_sourceKey'] = result['ManagedElement'].fillna(result['eNB']).astype(str).str.strip()

    ext = external_enodebs.dropna(thresh=1, axis='columns').copy()
    ext['_sourceKey'] = ext.get('ManagedElement', pd.Series('', index=ext.index)).combine_first(
        ext.get('eNB', pd.Series('', index=ext.index))
    ).fillna('').astype(str).str.strip()

    ext['_externalRef'] = (
        _canonicalize_enm_aliases(
            ext, 'externalENodeBFunctionId', 'ExternalENodeBFunctionId'
        ).fillna('').astype(str).str.strip()
    )
    ext['targetMcc'] = ext.get(
        'pLMNId_mcc', pd.Series('', index=ext.index)
    ).map(_normalize_enm_identifier)
    ext['targetMnc'] = ext.get(
        'pLMNId_mnc', pd.Series('', index=ext.index)
    ).map(_normalize_enm_identifier)
    ext['targetENodeBId'] = ext.get(
        'eNodeBId', pd.Series('', index=ext.index)
    ).map(_normalize_enm_identifier)
    complete_target = ext[['targetMcc', 'targetMnc', 'targetENodeBId']].ne('').all(axis=1)
    ext['_targetKey'] = ''
    ext.loc[complete_target, '_targetKey'] = (
        ext.loc[complete_target, 'targetMcc'] +
        ext.loc[complete_target, 'targetMnc'] + '-' +
        ext.loc[complete_target, 'targetENodeBId']
    )

    ext_cols = ['_sourceKey', '_externalRef', 'targetMcc', 'targetMnc',
                'targetENodeBId', '_targetKey']
    ext_lookup = ext[ext_cols].drop_duplicates()
    ext_lookup = ext_lookup.drop_duplicates(['_sourceKey', '_externalRef'], keep='first')

    result = result.merge(
        ext_lookup,
        how='left',
        left_on=['_sourceKey', 'ExternalENodeBFunction'],
        right_on=['_sourceKey', '_externalRef'],
    )
    result['termPointToENodeBId_Aux'] = result['_targetKey'].fillna('')

    local = local_enodebs.copy()
    local['_targetKey'] = (
        local.get('eNodeBPlmnId_mcc', pd.Series('', index=local.index)).map(_normalize_enm_identifier) +
        local.get('eNodeBPlmnId_mnc', pd.Series('', index=local.index)).map(_normalize_enm_identifier) + '-' +
        local.get('eNBId', pd.Series('', index=local.index)).map(_normalize_enm_identifier)
    )
    local_lookup = (
        local.loc[local['_targetKey'].ne('-'), ['_targetKey', 'eNB']]
        .rename(columns={'eNB': 'Ancora'})
        .drop_duplicates('_targetKey', keep='first')
    )
    result = result.merge(local_lookup, how='left', on='_targetKey')

    # Deduplicate by the MO identity, never by Ancora: unresolved targets have an
    # empty Ancora and the old rule silently discarded distinct TermPoints.
    identity = [c for c in ('eNB', 'ExternalENodeBFunction', 'termPointToENodeBId') if c in result.columns]
    if identity:
        result.drop_duplicates(subset=identity, inplace=True)

    output_columns = [
        'MO', 'UF', 'eNB', 'ManagedElement', 'administrativeState',
        'availabilityStatus', 'operationalState', 'termPointToENodeBId',
        'ExternalENodeBFunction', 'termPointToENodeBId_Aux', 'Ancora',
    ]
    for column in output_columns:
        if column not in result.columns:
            result[column] = ''
    return result[output_columns]


def _process_termpoint_to_gnb(termpoints, external_gnodebs, nrcellcu):
    """Resolve 4G -> 5G TermPoints from configured ExternalGNodeBFunction fields."""
    import pandas as pd

    result = termpoints.dropna(thresh=1, axis='columns').copy()
    result['eNB'] = result['ManagedElement']
    result['UF'] = result['eNB'].astype('string').str[-2:]
    result['ExternalGNodeBFunction'] = (
        _canonicalize_enm_aliases(
            result, 'ExternalGNodeBFunction', 'externalGNodeBFunction'
        ).fillna('').astype(str).str.strip()
    )
    result['termPointToGNBId'] = (
        _canonicalize_enm_aliases(
            result, 'termPointToGNBId', 'TermPointToGNBId'
        ).fillna('').astype(str).str.strip()
    )
    result['_sourceKey'] = result['ManagedElement'].fillna('').astype(str).str.strip()

    ext = external_gnodebs.copy()
    ext['_sourceKey'] = ext['ManagedElement'].fillna('').astype(str).str.strip()
    ext['_externalRef'] = (
        _canonicalize_enm_aliases(
            ext, 'externalGNodeBFunctionId', 'ExternalGNodeBFunctionId'
        ).fillna('').astype(str).str.strip()
    )
    ext['_mcc'] = ext.get('gNodeBPlmnId_mcc', pd.Series('', index=ext.index)).map(_normalize_enm_identifier)
    ext['_mnc'] = ext.get('gNodeBPlmnId_mnc', pd.Series('', index=ext.index)).map(_normalize_enm_identifier)
    ext['_gnbId'] = ext.get('gNodeBId', pd.Series('', index=ext.index)).map(_normalize_enm_identifier)
    ext['_targetKey'] = ext['_mcc'] + ext['_mnc'] + '-' + ext['_gnbId']
    ext_lookup = (
        ext[['_sourceKey', '_externalRef', '_gnbId', '_targetKey']]
        .drop_duplicates(['_sourceKey', '_externalRef'], keep='first')
    )
    result = result.merge(
        ext_lookup,
        how='left',
        left_on=['_sourceKey', 'ExternalGNodeBFunction'],
        right_on=['_sourceKey', '_externalRef'],
        validate='many_to_one',
    )

    local = nrcellcu.copy()
    local['_targetKey'] = (
        local.get('pLMNId_mcc', pd.Series('', index=local.index)).map(_normalize_enm_identifier) +
        local.get('pLMNId_mnc', pd.Series('', index=local.index)).map(_normalize_enm_identifier) + '-' +
        local.get('gNBId', pd.Series('', index=local.index)).map(_normalize_enm_identifier)
    )
    local_lookup = (
        local[['_targetKey', 'eNB']]
        .rename(columns={'eNB': 'Ancora'})
        .drop_duplicates('_targetKey', keep='first')
    )
    result = result.merge(local_lookup, how='left', on='_targetKey', validate='many_to_one')
    result['gNBId'] = pd.to_numeric(result['_gnbId'], errors='coerce').astype('Int64')
    result['termPointToGNB'] = result['ExternalGNodeBFunction']
    result['termPointToGNB_gNBId'] = result['gNBId']

    identity = ['eNB', 'ExternalGNodeBFunction', 'termPointToGNBId']
    result.drop_duplicates(identity, inplace=True)
    preferred = [
        'MO', 'UF', 'eNB', 'Ancora', 'gNBId', 'termPointToGNBId',
        'administrativeState', 'operationalState',
    ]
    internal = {'_sourceKey', '_externalRef', '_mcc', '_mnc', '_gnbId', '_targetKey'}
    available = [c for c in preferred if c in result.columns]
    extra = [c for c in result.columns if c not in available and c not in internal]
    return result[available + extra]


def _process_termpoint_to_gnodeb(termpoints, external_gnbcucp, nrcellcu):
    """Resolve 5G -> 5G TermPoints from configured ExternalGNBCUCPFunction fields."""
    import pandas as pd

    result = termpoints.dropna(thresh=1, axis='columns').copy()
    result['gNB'] = result['ManagedElement']
    result['UF'] = result['gNB'].astype('string').str[-2:]
    result['ExternalGNBCUCPFunction'] = (
        _canonicalize_enm_aliases(
            result, 'ExternalGNBCUCPFunction', 'externalGNBCUCPFunction'
        ).fillna('').astype(str).str.strip()
    )
    result['termPointToGNodeBId'] = (
        _canonicalize_enm_aliases(
            result, 'termPointToGNodeBId', 'TermPointToGNodeBId'
        ).fillna('').astype(str).str.strip()
    )
    result['_sourceKey'] = result['ManagedElement'].fillna('').astype(str).str.strip()

    ext = external_gnbcucp.copy()
    ext['_sourceKey'] = ext['ManagedElement'].fillna('').astype(str).str.strip()
    ext['_externalRef'] = (
        _canonicalize_enm_aliases(
            ext, 'externalGNBCUCPFunctionId', 'ExternalGNBCUCPFunctionId'
        ).fillna('').astype(str).str.strip()
    )
    ext['_mcc'] = ext.get('pLMNId_mcc', pd.Series('', index=ext.index)).map(_normalize_enm_identifier)
    ext['_mnc'] = ext.get('pLMNId_mnc', pd.Series('', index=ext.index)).map(_normalize_enm_identifier)
    ext['_gnbId'] = ext.get('gNBId', pd.Series('', index=ext.index)).map(_normalize_enm_identifier)
    ext['_targetKey'] = ext['_mcc'] + ext['_mnc'] + '-' + ext['_gnbId']
    ext_lookup = (
        ext[['_sourceKey', '_externalRef', '_targetKey']]
        .drop_duplicates(['_sourceKey', '_externalRef'], keep='first')
    )
    result = result.merge(
        ext_lookup,
        how='left',
        left_on=['_sourceKey', 'ExternalGNBCUCPFunction'],
        right_on=['_sourceKey', '_externalRef'],
        validate='many_to_one',
    )
    result['termPointToGNodeB'] = result['_targetKey'].fillna('')

    local = nrcellcu.copy()
    local['_targetKey'] = (
        local.get('pLMNId_mcc', pd.Series('', index=local.index)).map(_normalize_enm_identifier) +
        local.get('pLMNId_mnc', pd.Series('', index=local.index)).map(_normalize_enm_identifier) + '-' +
        local.get('gNBId', pd.Series('', index=local.index)).map(_normalize_enm_identifier)
    )
    local_lookup = (
        local[['_targetKey', 'eNB']]
        .rename(columns={'eNB': 'Ancora'})
        .drop_duplicates('_targetKey', keep='first')
    )
    result = result.merge(local_lookup, how='left', on='_targetKey', validate='many_to_one')
    result['Regional'] = result['UF'].replace(
        ['AM', 'AP', 'MA', 'PA', 'RR', 'BA', 'SE'],
        ['N', 'N', 'N', 'N', 'N', 'BASE', 'BASE'],
    )

    identity = ['gNB', 'ExternalGNBCUCPFunction', 'termPointToGNodeBId']
    result.drop_duplicates(identity, inplace=True)
    output_columns = [
        'Regional', 'MO', 'UF', 'gNB', 'termPointToGNodeB',
        'ExternalGNBCUCPFunction', 'Ancora', 'administrativeState',
        'availabilityStatus', 'ipv4Address', 'ipv6Address', 'operationalState',
        'termPointToGNodeBId', 'usedIpAddress', 'usedPLMNId_mcc', 'usedPLMNId_mnc',
    ]
    for column in output_columns:
        if column not in result.columns:
            result[column] = ''
    return result[output_columns]
