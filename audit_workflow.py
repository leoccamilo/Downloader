"""Run registered audit notebooks and Python scripts with their original rules."""
import argparse
import ast
from datetime import datetime
import gc
from importlib.util import find_spec
import json
from pathlib import Path
import re
import sys
import traceback
from bundled_sources import AUDIT_SCRIPTS
import operator_profiles

# Classic Vivo folders, hard-coded in the audit notebooks/scripts.
CAMILO = Path('C:/Camilo')
PROCESSED = Path('C:/Dumps/LTE_Total')
RAW = Path('C:/Dumps/todos_enms')
VIVO = Path('C:/Vivo Reports')

# Hard-coded prefix in the notebooks -> folder role (operator_profiles.vivo_folders).
_CLASSIC_PREFIXES = (('C:/Dumps/todos_enms', 'raw'), ('C:/Dumps/LTE_Total', 'processed'),
                     ('C:/Vivo Reports', 'reports'), ('C:/Camilao', 'extras'), ('C:/Camilo', 'references'))


class VivoPaths:
    """Translate the classic paths of the audits to the Vivo folders in use.

    Same rule as weekly_workflow.AdaptNotebook: prefix match by folder, case
    insensitive (the notebooks write both LTE_Total and LTE_total), and with a
    Vivo root an absolute path that is not one of the classic folders stops the
    audit instead of writing somewhere unexpected. Classic folders = no change.
    """

    def __init__(self, folders=None):
        self.folders = dict(folders or operator_profiles.VIVO_CLASSIC_FOLDERS)
        self.classic = all(str(self.folders.get(role, '')).lower() == path.lower()
                           for role, path in operator_profiles.VIVO_CLASSIC_FOLDERS.items())

    def folder(self, role):
        return Path(self.folders[role])

    def translate(self, text):
        """Translated path text, the same text when it is not a classic Vivo path, or ValueError."""
        normalized = text.replace('\\', '/')
        lowered = normalized.lower()
        for prefix, role in _CLASSIC_PREFIXES:
            low = prefix.lower()
            if lowered == low or lowered.startswith(low + '/'):
                if self.classic:
                    return text
                suffix = normalized[len(prefix):].lstrip('/')
                translated = str(self.folders[role]).replace('\\', '/').rstrip('/')
                if suffix:
                    translated += '/' + suffix
                if normalized.endswith('/') and not translated.endswith('/'):
                    translated += '/'
                return translated
        if not self.classic and re.match(r'^[A-Za-z]:[/\\]', text):
            raise ValueError(f'Caminho absoluto sem pasta Vivo correspondente no audit: {text}')
        return text

    def path(self, path):
        return Path(self.translate(str(path).replace('\\', '/')))


def audit(identifier, title, folder, notebook, inputs, outputs, note=''):
    return dict(id=identifier, title=title, path=str(AUDIT_SCRIPTS / notebook),
                inputs=inputs, outputs=outputs, note=note)


AUDITS = [
    audit('missing-termpoint-enb', 'Missing TermpointToENB 4G → 4G', 'Audits',
          'Missing_TermpointToENB_4G_4G.ipynb',
          ['Camilo/EUtranCell_TDD_FDD.txt', 'Camilo/TermPointToENB_{week}.txt', 'Dumps/LTE_Total/AddressIPv4.txt'],
          ['Vivo Reports/LTE/LTE Mobilidade/Missing_TermPointToENB_4G_4G.xlsx']),
    audit('capacity-state', 'CapacityState', 'ChatGPT', 'Audit_CapacityState.ipynb',
          ['Dumps/LTE_Total/CapacityState.txt', 'Camilo/EUtranCell_TDD_FDD_{week}.txt'],
          ['Vivo Reports/LTE/LTE Parametros/Audit_CapacityState.xlsx']),
    audit('cell-subscription-capacity', 'Cell Subscription Capacity', 'ChatGPT',
          'Audit_Cellsubscriptioncapacity.ipynb', ['Dumps/LTE_Total/EUtranCellFDD.txt'],
          ['Vivo Reports/LTE/LTE Parametros/Cellsubscriptioncapacity.xlsx']),
    audit('termpoint-gnb-distance', 'TermpointToGNB — distância', 'Audits',
          'TermpointToGNB_Distancia.ipynb',
          ['Camilo/5G_TermPointToGNB.txt', 'Camilo/cellref.xlsx', 'Camilo/cellref_5g.xlsx'],
          ['Vivo Reports/5G/5G Mobilidade/TermPointToGNB_Distancia.xlsx']),
    audit('termpoint-status', 'Termpoints LOCKED e DISABLED', 'Audits',
          'Audit_Termpoint_Status.py',
          ['Camilo/5G_TermPointToGNodeB.txt', 'Camilo/5G_TermPointToGNB.txt'],
          ['Vivo Reports/5G/5G Mobilidade/Termpoint_LOCKED.xlsx',
           'Vivo Reports/5G/5G Mobilidade/TermpointToGNB_DISABLED.xlsx'],
          'Relatorios operacionais dos TermPoints LOCKED e DISABLED.'),
    audit('ip-address', 'Audit IP Address', 'Audits', 'Audit_IPAddress.py',
          ['Dumps/LTE_Total/AddressIPv4.txt', 'Camilo/5G_TermPointToGNodeB.txt',
           'Camilo/5G_TermPointToGNB.txt'],
          ['Vivo Reports/5G/5G Mobilidade/Audit_IPAddress.xlsx'],
          'Compara os IPv4 dos TermPoints com as referencias NR_X2 de AddressIPv4.'),
    audit('new-sites', 'Sites Novos 4G / 5G', 'Audits', 'Sites_Novos_4G_5G.ipynb', [],
          ['Vivo Reports/Sites Novos/Sites_Novos_{week}.xlsx',
           'Vivo Reports/Historico Ativação/Historico_Ativação.xlsx'],
          'Compara as semanas disponíveis em C:/Camilo e atualiza também o histórico de ativações, como no notebook.'),
    audit('nrpci-neighbor', 'NRPCI Neighbor', 'Audits', 'Audit_NRPCI_Neighbor.ipynb',
          ['Dumps/LTE_Total/5G_ExternalNRCellCU.txt', 'Camilo/5G_NRCellDU_{week}.txt', 'Camilo/5G_NRCellCU_{week}.txt'],
          ['Vivo Reports/5G/5G Mobilidade/Audit_NRPCI_ExternalNRCellCU.xlsx']),
    audit('pscell-endc', 'PSCell ENDC', 'Audits', 'Audit_PSCell_Endc.ipynb',
          ['Dumps/LTE_Total/ENodeBFunction.txt', 'Camilo/5G_GUtranCellRelation_{week}.txt'],
          ['Vivo Reports/5G/5G Mobilidade/Audit_PSCell_Endc.xlsx'],
          'Requer GNBCUUPFunction bruto em C:/Dumps/todos_enms (TXT ou os Parquets originais).'),
    audit('pscell-change-v10', 'PSCell Change', 'Novos_Audits', 'Audit_PSCellChange_v10.ipynb',
          ['Camilo/5G_TermPointToGNodeB_{week}.txt', 'Camilo/EUtranCell_TDD_FDD.csv',
           'Camilo/5G_TermPointToGNB_{week}.txt', 'Camilo/5G_NRCellRelation_{week}.txt',
           'Camilo/5G_GUtranCellRelation_{week}.txt', 'Camilo/5G_NRCellCU_{week}.txt',
           'Camilo/5G_NRCellDU_{week}.txt', 'Camilo/GUtranFreqRelation_{week}.txt',
           'Camilo/5G_EUtranCellRelation_{week}.txt', 'Camilo/5G_TermPointToENodeB_{week}.txt',
           'Camilo/5G_ExternalENodeBFunction.txt', 'Dumps/LTE_Total/5G_ExternalGUtranCell.txt',
           'Dumps/LTE_Total/AddressIPv4.txt', 'Camilo/cellref_5g.xlsx'],
          ['Vivo Reports/5G/5G Mobilidade/Missing_TermPointToGNB_PSCellChange.xlsx',
           'Vivo Reports/5G/5G Mobilidade/Missing_GUtranCellRelation_PSCellChange.csv',
           'Vivo Reports/5G/5G Mobilidade/Missing_EUtranCellRelation_5g_4g_PSCellChange.xlsx',
           'Camilao/missing_TermpointToENodeB_PSCellChange.xlsx',
           'Camilao/Missing_GUtranCellRelation_volta.xlsx'],
          'PSCell alinhado ao MoB: site físico, setor normalizado, frequência por célula e distância. Mantém os dois relatórios adicionais em C:/Camilao.'),
]


def cellref_audit(identifier, title, filename, inputs, outputs, note=''):
    return dict(id=identifier, title=title, path=str(AUDIT_SCRIPTS / filename),
                inputs=inputs, outputs=outputs, note=note)


AUDITS.extend([
    cellref_audit('scell-candidate', 'sCellCandidate', 'Audit_sCellCandidate.ipynb',
                  ['Dumps/LTE_Total/EUtranCellRelation.txt', 'Camilo/EUtranCell_TDD_FDD.csv'],
                  ['Vivo Reports/LTE/LTE Mobilidade/Audit_sCellCandidate.xlsx']),
    cellref_audit('missing-eutranfreq-cosite', 'Missing EUtranFreqRelation 4G → 4G (co-site)',
                  'Missing_EUtranFreqRelation_4G_4G.ipynb',
                  ['Camilo/EUtranCell_TDD_FDD_{week}.txt', 'Dumps/LTE_Total/EUtranFreqRelation.txt', 'Dumps/LTE_Total/EUtranFrequency.txt'],
                  ['Vivo Reports/LTE/LTE Mobilidade/Missing EUtranFreqRelation_cosite_4G_4G.xlsx']),
    cellref_audit('missing-neighbor-city', 'Missing Neighbor 4G → 4G (cidade)', 'Missing_Neighbor_4G_4G.py',
                  ['Camilo/EUtranCell_TDD_FDD.csv', 'Dumps/LTE_Total/EUtranFreqRelation.txt', 'Dumps/LTE_Total/EUtranFrequency.txt'],
                  ['Vivo Reports/LTE/LTE Mobilidade/Missing Neighbor 4G_4G Cidade.xlsx'],
                  'Mantém o limite original: penetração municipal maior que 30%.'),
    cellref_audit('nearest-nrpci', 'Nearest NRPCI', 'Audit_Nearest_NRPCI.py',
                  ['Camilo/cellref_5g.xlsx'], ['Vivo Reports/5G/5G Mobilidade/Nearest_NRPCI_MG_BASE_N.xlsx'],
                  'Mantém o limite original de 5 km e a comparação por PCI e frequência.'),
    dict(cellref_audit('nrpci-planning', 'NRPCI Planning', 'NRPCI_Planning.py',
                  ['Camilo/cellref_5g.xlsx', 'Vivo Reports/5G/5G Mobilidade/Nearest_NRPCI_MG_BASE_N.xlsx'],
                  ['Vivo Reports/5G/5G Mobilidade/Audit_NRPCI_Planning_ERICSSON.xlsx'],
                  'Ao selecionar Planning, Nearest NRPCI é executado antes automaticamente. Mantém o limite original de 5 km.'),
         depends_on=['nearest-nrpci']),
    cellref_audit('nrpci-neighbor-script', 'NRPCI Neighbor — script Cellref', 'Audit_NRPCI_Neighbor.py',
                  ['Dumps/LTE_Total/5G_ExternalNRCellCU.txt', 'Camilo/5G_NRCellDU_{week}.txt', 'Camilo/5G_NRCellCU_{week}.txt'],
                  ['Vivo Reports/5G/5G Mobilidade/Audit_NRPCI_ExternalNRCellCU.xlsx'],
                  'Versão Python integrada. Usa o mesmo destino do NRPCI Neighbor em notebook; se executar os dois, o último atualiza o arquivo.'),
])


def resolved_files(item, key, week, paths=None):
    paths = paths or VivoPaths()
    return [paths.path(Path('C:/') / value.format(week=week)) for value in item[key]]


def notebook_cells(path):
    if Path(path).suffix.lower() == '.py':
        yield 0, Path(path).read_text(encoding='utf-8-sig')
        return
    document = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    for index, cell in enumerate(document['cells']):
        if cell.get('cell_type') != 'code':
            continue
        source = ''.join(cell.get('source', []))
        lines = []
        for line in source.splitlines():
            if line.strip() in ('%%time', '%time'):
                continue
            if line.lstrip().startswith(('%', '!')):
                raise ValueError(f'Comando interativo não suportado: célula {index}: {line}')
            lines.append(line)
        source = '\n'.join(lines)
        if source.strip():
            yield index, source


def check_audit(item, week, available_outputs=(), paths=None):
    paths = paths or VivoPaths()
    references, raw = paths.folder('references'), paths.folder('raw')
    problems = []
    path = Path(item['path'])
    if not path.is_file():
        return [f'Arquivo do audit ausente: {path}']
    imports = {'pandas', 'numpy', 'openpyxl'}
    try:
        for index, source in notebook_cells(path):
            tree = ast.parse(source, filename=f'{path.name}:cell_{index}')
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name.split('.')[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module.split('.')[0])
    except (ValueError, SyntaxError, KeyError) as exc:
        problems.append(str(exc))
    for name in sorted(imports):
        if find_spec(name) is None:
            problems.append(f'Dependência ausente: {name}')
    for filename in resolved_files(item, 'inputs', week, paths):
        if not filename.is_file() and filename not in available_outputs:
            problems.append(f'Entrada ausente: {filename}')
    if item['id'] == 'new-sites':
        for prefix in ('EUtranCell_TDD_FDD', '5G_NRCellDU'):
            if len(list(references.glob(prefix + '_[0-9]*.txt'))) < 2:
                problems.append(f'Histórico insuficiente: {references}/{prefix}_<semana>.txt (mínimo 2 semanas)')
    if item['id'] == 'pscell-endc':
        if not (raw / 'GNBCUUPFunction.txt').is_file() and not list(raw.glob('GNBCUUPFunction_*_part*.parquet')):
            problems.append(f'Entrada bruta ausente: {raw}/GNBCUUPFunction.txt ou GNBCUUPFunction_*_part*.parquet')
    return problems


def catalog(folders=None):
    paths = VivoPaths(folders)
    week = int(datetime.today().strftime('%U')) + 1
    entries = []
    for item in AUDITS:
        dependencies = [entry for entry in entries if entry['id'] in item.get('depends_on', [])]
        available = [Path(output) for entry in dependencies if entry['ready'] for output in entry['outputs']]
        problems = check_audit(item, week, available, paths)
        for dependency in dependencies:
            if not dependency['ready']:
                problems.append(f"Audit necessário pendente: {dependency['title']}")
        entries.append(dict(item, path=Path(item['path']).name, embedded=True, inputs=[str(p) for p in resolved_files(item, 'inputs', week, paths)],
                            outputs=[str(p) for p in resolved_files(item, 'outputs', week, paths)],
                            ready=not problems, problems=problems))
    return dict(week=week, audits=entries, folders=paths.folders)


def selected_audits(identifiers):
    if not isinstance(identifiers, list) or not identifiers or not all(isinstance(i, str) for i in identifiers):
        raise ValueError('Selecione pelo menos um audit.')
    known = {item['id'] for item in AUDITS}
    if set(identifiers) - known:
        raise ValueError('Audit desconhecido: ' + ', '.join(sorted(set(identifiers) - known)))
    selection = set(identifiers)
    for item in reversed(AUDITS):
        if item['id'] in selection:
            selection.update(item.get('depends_on', []))
    return [item for item in AUDITS if item['id'] in selection]


def emit(item, status, **details):
    print('AUDIT_EVENT=' + json.dumps(dict(id=item['id'], status=status, **details), ensure_ascii=False), flush=True)


def execute_audit(item, week, output_mapper=None, paths=None):
    """Execute original code with its paths translated to the Vivo folders in use.

    output_mapper is used only by isolated validation (classic folders, reports elsewhere).
    """
    import pandas as pd
    from audit_exports import write_audit_excel
    paths = paths or VivoPaths()
    raw = paths.folder('raw')
    outputs = resolved_files(item, 'outputs', week, paths)
    before = {}
    for target in outputs:
        actual = output_mapper(target) if output_mapper else target
        before[str(actual)] = (actual.stat().st_mtime_ns, actual.stat().st_size) if actual.is_file() else None
        actual.parent.mkdir(parents=True, exist_ok=True)
    namespace = {'__name__': '__main__', '__file__': item['path']}
    namespace['write_audit_excel'] = write_audit_excel
    for index, source in notebook_cells(item['path']):
        emit(item, 'running', cell=index)
        tree = ast.parse(source)
        if item['id'] == 'pscell-change-v10':
            class AuditExcel(ast.NodeTransformer):
                def visit_Call(self, node):
                    self.generic_visit(node)
                    if isinstance(node.func, ast.Attribute) and node.func.attr == 'to_excel':
                        return ast.copy_location(ast.Call(func=ast.Name(id='write_audit_excel', ctx=ast.Load()),
                                                          args=[node.func.value] + node.args, keywords=node.keywords), node)
                    return node
            tree = AuditExcel().visit(tree)
            ast.fix_missing_locations(tree)
        if output_mapper:
            # Remap absolute paths during tests without editing source notebooks.
            class MapPaths(ast.NodeTransformer):
                def visit_Constant(self, node):
                    if isinstance(node.value, str) and node.value.replace('\\', '/').startswith(('C:/Vivo Reports', 'C:/Camilao')):
                        translated = str(output_mapper(Path(node.value)))
                        if node.value.endswith(('/', '\\')):
                            translated = translated.rstrip('/\\') + '/'
                        return ast.copy_location(ast.Constant(translated), node)
                    return node
            tree = MapPaths().visit(tree)
            ast.fix_missing_locations(tree)
        elif not paths.classic:
            # The notebooks keep their classic paths; point them at the Vivo root in use.
            class VivoFolders(ast.NodeTransformer):
                def visit_Constant(self, node):
                    if isinstance(node.value, str):
                        translated = paths.translate(node.value)
                        if translated != node.value:
                            return ast.copy_location(ast.Constant(translated), node)
                    return node
            try:
                tree = VivoFolders().visit(tree)
            except ValueError as exc:
                raise RuntimeError(f"{Path(item['path']).name}, célula {index}: {exc}") from exc
            ast.fix_missing_locations(tree)
        try:
            old_argv, old_path = sys.argv, sys.path[:]
            try:
                if Path(item['path']).suffix.lower() == '.py':
                    sys.argv = [item['path']]
                    sys.path.insert(0, str(Path(item['path']).parent))
                exec(compile(tree, f"{Path(item['path']).name}:cell_{index}", 'exec'), namespace)
            except SystemExit as exc:
                if exc.code not in (None, 0):
                    raise RuntimeError(f'Script encerrou com código {exc.code}') from exc
            finally:
                sys.argv, sys.path[:] = old_argv, old_path
            # ENDC's original loader consumes Parquet. A TXT raw MO can supply
            # exactly the same dataframe without creating intermediate files.
            if item['id'] == 'pscell-endc' and 'def load_parquet' in source and (raw / 'GNBCUUPFunction.txt').is_file():
                def load_raw_txt(pattern, columns=None):
                    if 'GNBCUUPFunction_' not in pattern:
                        raise ValueError(f'Padrão bruto não suportado: {pattern}')
                    filename = raw / 'GNBCUUPFunction.txt'
                    for encoding in ('utf-8-sig', 'latin-1'):
                        try:
                            return pd.read_csv(filename, sep='\t', usecols=columns, encoding=encoding, low_memory=False)
                        except UnicodeDecodeError:
                            pass
                namespace['load_parquet'] = load_raw_txt
        except Exception as exc:
            raise RuntimeError(f"{Path(item['path']).name}, célula {index}: {exc}") from exc
    for target in outputs:
        actual = output_mapper(target) if output_mapper else target
        if not actual.is_file() or actual.stat().st_size == 0:
            raise RuntimeError(f'Relatório não foi gerado: {actual}')
        if before[str(actual)] == (actual.stat().st_mtime_ns, actual.stat().st_size):
            raise RuntimeError(f'Relatório existente não foi atualizado: {actual}')
        print(f'Saved: {actual}', flush=True)
    return [str(p) for p in outputs]


def run_audits(identifiers, folders=None):
    paths = VivoPaths(folders)
    items = selected_audits(identifiers)
    week = int(datetime.today().strftime('%U')) + 1
    # Check the entire selection before any report is overwritten.
    invalid = False
    available_outputs = []
    for item in items:
        problems = check_audit(item, week, available_outputs, paths)
        if problems:
            invalid = True
            emit(item, 'blocked', message='; '.join(problems))
        else:
            available_outputs.extend(resolved_files(item, 'outputs', week, paths))
    if invalid:
        raise ValueError('Verificação falhou. Nenhum audit foi iniciado.')
    print(f'Audits: {len(items)} | Semana dos notebooks: {week}', flush=True)
    if not paths.classic:
        print(f"Pastas Vivo: referências {paths.folder('references')} | relatórios {paths.folder('reports')}", flush=True)
    for item in items:
        print(f"\nAudit: {item['title']}\nArquivo: {item['path']}", flush=True)
        try:
            outputs = execute_audit(item, week, paths=paths)
        except Exception as exc:
            emit(item, 'failed', message=str(exc))
            raise
        emit(item, 'completed', outputs=outputs)
        gc.collect()
    print('AUDITS COMPLETED.', flush=True)


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('config')
    args = parser.parse_args()
    try:
        config = json.loads(Path(args.config).read_text(encoding='utf-8'))
        run_audits(config.get('audit_ids'), config.get('folders'))
    except Exception:
        traceback.print_exc()
        print('AUDITS FAILED.', flush=True)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
