"""Every module the subprocess scripts and notebooks import (see worker_mode.py).

Nuitka packs only what it sees imported. The scripts run by the .exe in worker
mode (dump, xml_to_txt, post-processing, Claro, weekly notebooks, cellrefs,
audits) are data files, so their imports are listed here. Keep the list in
sync: tests/test_worker_mode.py scans the scripts and fails on a missing one.

Imported ONLY in worker mode, never by the server start.
"""
# Standard library used by the scripts / notebooks
import argparse  # noqa: F401
import ast  # noqa: F401
import collections  # noqa: F401
import concurrent.futures  # noqa: F401
import contextlib  # noqa: F401
import csv  # noqa: F401
import datetime  # noqa: F401
import functools  # noqa: F401
import gc  # noqa: F401
import glob  # noqa: F401
import gzip  # noqa: F401
import hashlib  # noqa: F401
import importlib.util  # noqa: F401
import json  # noqa: F401
import marshal  # noqa: F401
import math  # noqa: F401
import os  # noqa: F401
import pathlib  # noqa: F401
import re  # noqa: F401
import shutil  # noqa: F401
import sys  # noqa: F401
import tempfile  # noqa: F401
import time  # noqa: F401
import traceback  # noqa: F401
import types  # noqa: F401
import typing  # noqa: F401
import uuid  # noqa: F401
import zipfile  # noqa: F401

# Third-party
import numpy  # noqa: F401
import pandas  # noqa: F401
import openpyxl  # noqa: F401
import openpyxl.utils  # noqa: F401
import xlsxwriter  # noqa: F401  (pandas to_excel engine, loaded dynamically)
import lxml.etree  # noqa: F401  (xml_to_txt.py)
import pyarrow  # noqa: F401  (weekly_workflow: string[pyarrow])
import pyarrow.parquet  # noqa: F401
import haversine  # noqa: F401  (TermpointToGNB_Distancia)
import requests  # noqa: F401  (enmscripting)

# The ENM library crashes on import inside a compiled .exe unless its
# `overrides` decorator is replaced first (worker_mode.install_enmscripting_shim).
from worker_mode import install_enmscripting_shim as _shim

_shim()
import enmscripting  # noqa: F401,E402
