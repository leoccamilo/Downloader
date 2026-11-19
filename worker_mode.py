"""Downloader.exe as its own Python: runs the subprocess scripts with the embedded interpreter.

The server starts every heavy step (dump, XML -> TXT, Process MOs, cellref,
weekly notebooks, audits) as a separate process, so it can be cancelled and
its log streamed. From source that process is ``python [-u] script.py args``.
Inside the .exe there is no python.exe on the machine to call, so the server
calls the .exe itself with the same arguments and this module runs the script
exactly like python.exe would (sys.argv, sys.path[0], __main__, exit code).
Same idea as the MoB Tool Box: Python and libraries travel inside the .exe.

Nuitka only packs modules it sees imported. The scripts are data files, so
everything they import is listed in ``worker_imports.py`` (imported only in
worker mode, to keep the server start fast); tests/test_worker_mode.py fails
when a script imports something that is not listed.
"""
from __future__ import annotations

import os
import runpy
import sys
import traceback
import types


def worker_args(argv):
    """[script, args...] when argv is a python-like call (``[-u] <existing .py> ...``), else None."""
    args = list(argv[1:])
    unbuffered = bool(args) and args[0] == "-u"
    if unbuffered:
        args = args[1:]
    if args and args[0].lower().endswith(".py") and os.path.isfile(args[0]):
        return args, unbuffered
    return None


def install_enmscripting_shim():
    """Neutralise ``enmscripting.private.overrides`` (same fix as the MoB Tool Box).

    The decorator reads the caller's source line with ``inspect.stack()`` at
    import time; a compiled .exe has no source lines, so ``import enmscripting``
    crashes. A no-op module registered first is picked up by the library's own
    ``from .overrides import overrides``.
    """
    name = "enmscripting.private.overrides"
    if name not in sys.modules:
        shim = types.ModuleType(name)
        shim.overrides = lambda method: method
        sys.modules[name] = shim


def run_script(script, args, unbuffered=False, real_exe=None) -> int:
    """Run ``script`` as __main__ with ``args``; return the exit code python.exe would return."""
    if unbuffered:
        for stream in (sys.stdout, sys.stderr):
            if stream is not None and hasattr(stream, "reconfigure"):
                stream.reconfigure(line_buffering=True)
    script = os.path.abspath(script)
    sys.argv = [script] + list(args)
    sys.path.insert(0, os.path.dirname(script))
    if real_exe:
        # Inside the .exe sys.executable points to a python.exe that does not exist.
        sys.executable = real_exe
    install_enmscripting_shim()
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as exc:
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        print(code, file=sys.stderr)
        return 1
    except BaseException:
        traceback.print_exc()
        return 1
    finally:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except Exception:
                pass
    return 0


def maybe_run_worker(argv=None) -> None:
    """Called first by the .exe launcher: run the script and exit, or return to start the server."""
    argv = sys.argv if argv is None else argv
    parsed = worker_args(argv)
    if parsed is None:
        return
    (script, *args), unbuffered = parsed
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
    import worker_imports  # noqa: F401  (makes Nuitka pack every library the scripts use)
    real_exe = os.path.abspath(argv[0]) if argv and argv[0] else None
    sys.exit(run_script(script, args, unbuffered=unbuffered, real_exe=real_exe))
