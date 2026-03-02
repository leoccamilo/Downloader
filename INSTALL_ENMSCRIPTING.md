# Install enmscripting (required for Execute Dump)

The dump script needs the **enmscripting** module from Ericsson. It is not on PyPI, so you install it from a **.whl** file.

## Where to put the wheel

The installer looks for `enm_client_scripting-*.whl` in this order:

1. **`C:\Tools\`** – if your company keeps the wheel there, no need to copy it; just run **INSTALL_ENMSCRIPTING.bat**.
2. **This folder** – same folder as `START_DOWNLOADER.bat` and `INSTALL_ENMSCRIPTING.bat`.
3. **`wheels\`** – subfolder inside the Downloader folder.

## Steps

1. **Get the wheel** (e.g. `enm_client_scripting-1.22.2-py2.py3-none-any.whl`) from your company share, or use the one in `C:\Tools` if available.
2. **Run START_DOWNLOADER.bat once** (to create the venv) if you haven't already.
3. **Run INSTALL_ENMSCRIPTING.bat** – it will find and install the wheel from `C:\Tools`, this folder, or `wheels\`.
4. Use **START_DOWNLOADER.bat** and **Execute Dump** as usual.

## Why the wheel is not inside the ZIP

The Ericsson wheel is proprietary; including it in the ZIP would be redistributing it (license). The ZIP is built from the project folder and has no access to `C:\Tools` on your machine. On a VM, copy the wheel to the Downloader folder (or to `C:\Tools` on the VM) and run **INSTALL_ENMSCRIPTING.bat** once.

## Important: install in the Downloader venv, not global Python

The dump runs with the **venv inside the Downloader folder** (`venv\Scripts\python.exe`). If you run `pip install` from a normal Command Prompt (without activating that venv), the wheel is installed in your global Python and **Execute Dump will still say "No module named 'enmscripting'"**.

- **Correct:** Run **INSTALL_ENMSCRIPTING.bat** (it uses `venv\Scripts\pip.exe` so the wheel is installed in the right place).
- **Or manually:** Open Command Prompt, `cd` to the Downloader folder, then run:
  ```batch
  venv\Scripts\pip.exe install enm_client_scripting-1.22.2-py2.py3-none-any.whl
  ```
  Then run **START_DOWNLOADER.bat** and use **Execute Dump**.
