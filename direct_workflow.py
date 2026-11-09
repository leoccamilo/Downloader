"""Weekly execution in the original folders, using direct XML-to-TXT inputs."""
from contextlib import ExitStack
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
from bundled_sources import CELLREF_SCRIPTS


def report_directories(config, stack):
    """Only disabled exports need transient report scratch space; no dump copies."""
    enriched = Path(config['enriched_dir'])
    vivo = Path(config.get('vivo_dir') or 'C:/Vivo Reports')
    if not config.get('create_weekly', True):
        enriched = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='downloader_reports_')))
    if not config.get('transfer_vivo', True):
        vivo = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='downloader_reports_')))
    for directory in (enriched, vivo / 'LTE/LTE MOs', vivo / '5G/5G MOs', vivo / 'MoB_IMP'):
        directory.mkdir(parents=True, exist_ok=True)
    return enriched, vivo


def run_direct_workflow(config):
    from weekly_workflow import preflight, execute_notebook, NOTEBOOKS, publish_mob_imports
    from xml_to_txt import parse_ericsson_xmls
    preflight(config)
    raw = Path(config['raw_txt_dir']).resolve()
    processed = Path(config['output_dir']).resolve()
    references = Path(config['reference_dir']).resolve()
    for target in (processed, references, Path(config['enriched_dir']).resolve(), Path(config['notebook_dir']).resolve()):
        if raw == target or raw in target.parents:
            raise ValueError(f'A pasta dos TXT brutos deve ser separada de {target}')
    inputs = config.get('input_files') or [config.get('input_dir')]
    if not all(inputs):
        raise ValueError('Informe a pasta ou os arquivos ZIP/XML de entrada.')
    raw.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    date = datetime.fromisoformat(config['run_date']) if config.get('run_date') else datetime.now()
    week = int(date.strftime('%U')) + 1
    warnings = []
    manifest = dict(status='running', week=week, notebooks=[], warnings=warnings,
                    raw_txt_dir=str(raw), output_dir=str(processed), enriched_dir=config['enriched_dir'])
    manifest_path = raw / 'downloader_manifest.json'
    try:
        print(f'STEP 2/6: XML/ZIP → TXT em {raw} (sem extração dos ZIPs e sem Parquet)', flush=True)
        written = parse_ericsson_xmls(inputs, str(raw), clear_existing=False, strict=True, include_nr_relations=True)
        if not written:
            raise ValueError('Nenhum MO foi convertido para TXT.')
        with ExitStack() as stack:
            enriched, vivo = report_directories(config, stack)
            roots = [('C:/Camilo/SCIENCE.xlsx', references / 'SCIENCE.xlsx'),
                     ('C:/Camilo/cellref.xlsx', references / 'cellref.xlsx'),
                     ('C:/Dumps/todos_enms', raw), ('C:/Dumps/LTE_Total', processed),
                     ('C:/Camilo', enriched), ('C:/Vivo Reports', vivo)]
            for step, name in enumerate(NOTEBOOKS[1:], 3):
                path = Path(config['notebook_dir']) / name
                manifest['notebooks'].append(dict(name=name, sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
                print(f'\nSTEP {step}/6: {name}', flush=True)
                execute_notebook(path, roots, week, warnings, txt_mode=True)
            if (config.get('cellref') or {}).get('enabled'):
                generate_direct_cellrefs(config, raw, processed, enriched, vivo, week, warnings)
            publish_report_options(config, enriched, week)
            publish_mob_imports(config, enriched)
        manifest['status'] = 'completed'
        print('PIPELINE COMPLETED.', flush=True)
    except Exception as exc:
        manifest.update(status='failed', error=str(exc))
        raise
    finally:
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
        print(f'Manifest: {manifest_path}', flush=True)


def publish_report_options(config, enriched, week):
    """Custom history destinations and disabled history retain the previous options."""
    from weekly_workflow import publish_file
    suffix = re.compile(r'_' + str(week) + r'(?=\.[^.]+$)')
    current = Path(config['enriched_dir'])
    history = Path(config.get('history_dir') or config['enriched_dir'])
    for source in enriched.iterdir():
        if not source.is_file():
            continue
        if not config.get('create_weekly', True):
            publish_file(source, current / suffix.sub('', source.name), [])
        elif suffix.search(source.name) and source.resolve().parent != history.resolve():
            publish_file(source, history / source.name, [])


def generate_direct_cellrefs(config, raw, processed, enriched, vivo, week, warnings, parameters=None):
    """Use original portal and output folders, without copying datasets."""
    import pandas as pd
    from cellref_workflow import preflight_cellrefs, LTE_NOTEBOOK, NR_NOTEBOOK, science_from_cellref
    from weekly_workflow import execute_notebook, NOTEBOOKS, publish_file
    preflight_cellrefs(config, require_parameters=False)
    options = config.get('cellref') or {}
    lte = Path(options.get('lte_output_dir') or 'C:/Cellref/LTE')
    nr = Path(options.get('nr_output_dir') or 'C:/Cellref/NR')
    for directory in (lte, nr):
        directory.mkdir(parents=True, exist_ok=True)
    roots = [('C:/cellref/LTE_dump', Path(options.get('lte_input_dir') or 'C:/Cellref/LTE_dump')),
             ('C:/cellref/NR_dump', Path(options.get('nr_input_dir') or 'C:/Cellref/NR_dump')),
             ('C:/cellref/LTE', lte), ('C:/cellref/NR', nr),
             ('C:/Vivo Reports/LTE/LTE MOs/SectorCarrier.csv', processed / 'SectorCarrier.txt'),
             ('C:/Camilo', parameters or enriched), ('C:/Dumps/todos_enms', raw)]
    for name in (LTE_NOTEBOOK, NR_NOTEBOOK):
        print(f'CELLREF: {name}', flush=True)
        execute_notebook(Path(options.get('scripts_dir') or CELLREF_SCRIPTS) / name,
                         roots, week, warnings, txt_mode=True)
    references = Path(config['reference_dir'])
    for source in (lte / 'cellref.xlsx', nr / 'cellref_5g.xlsx'):
        frame = pd.read_excel(source)
        required = {'eNB', 'CELL', 'Latitude', 'Longitude', 'Azimuth', 'Height'} if source.name == 'cellref.xlsx' else {'SiteID', 'SectorID', 'Latitude', 'Longitude', 'Azimuth', 'Height'}
        if frame.empty or required - set(frame):
            raise ValueError(f'Cellref inválido: {source}; colunas ausentes: {sorted(required - set(frame))}')
        latitude = pd.to_numeric(frame['Latitude'], errors='coerce')
        longitude = pd.to_numeric(frame['Longitude'], errors='coerce')
        if (latitude.dropna().abs() > 90).any() or (longitude.dropna().abs() > 180).any():
            raise ValueError(f'Coordenadas inválidas: {source}')
        missing = int((latitude.isna() | longitude.isna()).sum())
        if missing:
            message = f'{source.name}: {missing} de {len(frame)} células sem coordenadas completas.'
            warnings.append(message)
            print('WARNING: ' + message, flush=True)
    if options.get('refresh_reports', True):
        roots = [('C:/Camilo/cellref.xlsx', lte / 'cellref.xlsx'),
                 ('C:/Dumps/todos_enms', raw), ('C:/Dumps/LTE_Total', processed),
                 ('C:/Camilo', enriched), ('C:/Vivo Reports', vivo)]
        geography = science_from_cellref(lte / 'cellref.xlsx')
        cache = {str(enriched / 'SCIENCE.xlsx'): geography}
        for name in NOTEBOOKS[2:4]:
            print(f'REFRESH: {name}', flush=True)
            execute_notebook(Path(config['notebook_dir']) / name, roots, week, warnings,
                             reference_cache=cache, skip_missing_auxiliary=True, txt_mode=True)
    for source in (lte / 'cellref.xlsx', nr / 'cellref_5g.xlsx'):
        publish_file(source, references / source.name, [])


def run_direct_cellrefs(config):
    import pandas as pd
    from cellref_workflow import preflight_cellrefs, find_parameter
    from weekly_workflow import publish_mob_imports
    preflight_cellrefs(config)
    raw = Path(config['raw_txt_dir'])
    if (config.get('cellref') or {}).get('refresh_reports', True) and not (raw / 'EUtranCellFDD.txt').is_file():
        raise ValueError(f'Faltam os TXT brutos em {raw}; execute a conversão XML → TXT antes de reaplicar os passos 4 e 5.')
    if (config.get('cellref') or {}).get('refresh_reports', True):
        parameters = Path((config.get('cellref') or {}).get('parameter_dir') or config['enriched_dir'])
        inventory = pd.read_csv(find_parameter(parameters, 'EUtranCell_TDD_FDD.txt'), sep='\t', encoding='latin-1')
        if 'Tipo' in inventory and inventory['Tipo'].eq('TDD').any() and not (raw / 'EUtranCellTDD.txt').is_file():
            raise ValueError('O inventário contém TDD, mas faltam seus TXT brutos. Execute a conversão antes de reaplicar os relatórios.')
    week = int(datetime.now().strftime('%U')) + 1
    with ExitStack() as stack:
        enriched, vivo = report_directories(config, stack)
        parameters = Path((config.get('cellref') or {}).get('parameter_dir') or config['enriched_dir'])
        generate_direct_cellrefs(config, raw, Path(config['output_dir']), enriched, vivo, week, [], parameters=parameters)
        publish_report_options(config, enriched, week)
        publish_mob_imports(config, enriched)
    print('PIPELINE COMPLETED.', flush=True)
