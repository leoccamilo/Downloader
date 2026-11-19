"""Downloader.exe as its own Python (worker_mode.py + worker_imports.py)."""
import ast
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import worker_mode  # noqa: E402

# Scripts the server runs as subprocess (worker mode inside the exe).
SCRIPTS = ("dump_multiple_enms.py", "xml_to_txt.py", "post_process_4_camilo.py", "post_process_5_tdd.py",
           "post_process_6_5g.py", "pos_processamento_claro.py", "regras_claro.py", "enm_dump_claro.py",
           "cadastro_claro.py", "weekly_workflow.py", "cellref_workflow.py", "direct_workflow.py",
           "audit_workflow.py", "audit_exports.py", "bundled_sources.py", "operator_profiles.py")
# Imported only by a legacy notebook path that the current workflow no longer runs.
NOT_PACKED = {"fastparquet"}


def _sources(path):
    if path.suffix == ".ipynb":
        for cell in json.loads(path.read_text(encoding="utf-8-sig"))["cells"]:
            if cell.get("cell_type") == "code":
                yield "\n".join(line for line in "".join(cell.get("source", [])).splitlines()
                                if not line.lstrip().startswith(("%", "!")))
    else:
        yield path.read_text(encoding="utf-8-sig")


def _imports(path):
    names = set()
    for source in _sources(path):
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module)
    return names


class WorkerImportsTests(unittest.TestCase):
    def test_every_module_the_scripts_import_is_packed(self):
        local = {p.stem for p in ROOT.glob("*.py")}
        files = [ROOT / name for name in SCRIPTS]
        files += sorted((ROOT / "bundled_scripts").rglob("*.py")) + sorted((ROOT / "bundled_scripts").rglob("*.ipynb"))
        packed = _imports(ROOT / "worker_imports.py")
        packed_roots = {name.split(".")[0] for name in packed}
        missing = {}
        for path in files:
            for name in _imports(path):
                root = name.split(".")[0]
                if root in local or root in NOT_PACKED or root == "__future__":
                    continue
                if name not in packed and not (root in packed_roots and "." not in name):
                    missing.setdefault(name, []).append(path.name)
        self.assertEqual(missing, {}, "add these imports to worker_imports.py")


class WorkerArgsTests(unittest.TestCase):
    def test_python_like_calls_are_recognised(self):
        script = str(ROOT / "xml_to_txt.py")
        self.assertEqual(worker_mode.worker_args(["Downloader.exe", "-u", script, "a", "b"]), ([script, "a", "b"], True))
        self.assertEqual(worker_mode.worker_args(["Downloader.exe", script]), ([script], False))
        # A normal start (no arguments, or anything that is not an existing .py) starts the server.
        self.assertIsNone(worker_mode.worker_args(["Downloader.exe"]))
        self.assertIsNone(worker_mode.worker_args(["Downloader.exe", "-u", "missing.py"]))
        self.assertIsNone(worker_mode.worker_args(["Downloader.exe", "--validate"]))


class RunScriptTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        (self.dir / "helper_mod.py").write_text("VALUE = 'local import ok'\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _script(self, body):
        path = self.dir / "job.py"
        path.write_text(textwrap.dedent(body), encoding="utf-8")
        return path

    def _exe_like(self, *args):
        """Run worker mode in a fresh process, the way Downloader.exe receives `-u script args`."""
        code = ("import sys, worker_mode; "
                f"worker_mode.maybe_run_worker(['Downloader.exe', {', '.join(repr(str(a)) for a in args)}])")
        result = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True,
                                text=True, encoding="utf-8")
        return result.returncode, result.stdout, result.stderr

    def test_script_runs_as_main_with_argv_and_local_imports(self):
        script = self._script("""
            import sys
            import helper_mod
            if __name__ == "__main__":
                print(helper_mod.VALUE, sys.argv[1:], flush=True)
                sys.exit(3)
        """)
        code, out, err = self._exe_like("-u", script, "x", "y z")
        self.assertEqual(code, 3, err)
        self.assertIn("local import ok ['x', 'y z']", out)

    def test_uncaught_error_prints_traceback_and_returns_1(self):
        code, out, err = self._exe_like(self._script("raise ValueError('boom')\n"))
        self.assertEqual(code, 1)
        self.assertIn("ValueError: boom", err)

    def test_enmscripting_imports_with_the_shim(self):
        script = self._script("import enmscripting\nprint('enm ok', hasattr(enmscripting, 'open'))\n")
        code, out, err = self._exe_like("-u", script)
        self.assertEqual(code, 0, err)
        self.assertIn("enm ok True", out)


if __name__ == "__main__":
    unittest.main()
