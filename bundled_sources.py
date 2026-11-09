"""Locations of the scripts shipped as part of Downloader."""
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parent / 'bundled_scripts'
WEEKLY_SCRIPTS = SCRIPT_ROOT / 'weekly'
CELLREF_SCRIPTS = SCRIPT_ROOT / 'cellrefs'
AUDIT_SCRIPTS = SCRIPT_ROOT / 'audits'


def use_bundled_scripts(config):
    """UI/API jobs always execute application-owned code, never a source folder."""
    config['notebook_dir'] = str(WEEKLY_SCRIPTS)
    options = config.get('cellref')
    if not isinstance(options, dict):
        options = config['cellref'] = {}
    options['scripts_dir'] = str(CELLREF_SCRIPTS)
    return config
