"""Which Python runs the dump/parser/cellref scripts inside the Nuitka .exe.

Nuitka onefile (4.3.5) does not set sys.frozen and points sys.executable to a
python.exe in the temp extraction folder that does not exist: every
subprocess failed with WinError 2. The real exe folder comes from
__compiled__.containing_dir / sys.argv[0].
"""
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import server_downloader as server


class PythonForDumpTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.temp_extract = base / "onefile_123"          # where the exe unpacks itself
        self.temp_extract.mkdir()
        self.exe_dir = base / "Downloader"                # where Downloader.exe really is
        self.exe_dir.mkdir()
        self.fake_python = str(self.temp_extract / "python.exe")  # does not exist

    def tearDown(self):
        self._tmp.cleanup()

    def _compiled(self, argv0=None):
        compiled = types.SimpleNamespace(containing_dir=str(self.exe_dir),
                                         original_argv0=str(self.exe_dir / "Downloader.exe"))
        return [patch.dict(server.__dict__, {"__compiled__": compiled}),
                patch.object(server, "SCRIPT_DIR", str(self.temp_extract)),
                patch.object(server.sys, "executable", self.fake_python),
                patch.object(server.sys, "argv", [argv0 or str(self.temp_extract / "Downloader.exe")])]

    def _run(self, patches, **which):
        for p in patches:
            p.start()
        try:
            with patch.object(server.shutil, "which", lambda name: which.get(name)):
                return server.get_python_for_dump()
        finally:
            for p in reversed(patches):
                p.stop()

    def test_python_embed_next_to_the_real_exe(self):
        embed = self.exe_dir / "python_embed" / "python.exe"
        embed.parent.mkdir()
        embed.write_text("")
        self.assertEqual(self._run(self._compiled()), os.path.normpath(str(embed)))

    def test_compiled_without_embed_uses_system_python_never_the_missing_one(self):
        self.assertTrue(server._is_compiled() is False)  # tests run from source
        result = self._run(self._compiled(), python="C:/Python39/python.exe")
        self.assertEqual(result, "C:/Python39/python.exe")
        self.assertNotEqual(result, self.fake_python)

    def test_exe_folder_also_found_from_argv0(self):
        embed = self.exe_dir / "python_embed" / "python.exe"
        embed.parent.mkdir()
        embed.write_text("")
        patches = self._compiled(argv0=str(self.exe_dir / "Downloader.exe"))
        patches[0] = patch.dict(server.__dict__, {"__compiled__": types.SimpleNamespace()})
        self.assertEqual(self._run(patches), os.path.normpath(str(embed)))


if __name__ == "__main__":
    unittest.main()
