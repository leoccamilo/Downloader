$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Downloader - Build with Nuitka" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# -------------------------------------------------------
# Usa venv_build (limpa, so libs do server) para garantir
# que pyarrow/lxml/xlsxwriter nao entrem no exe.
# A venv normal (venv) continua intacta para desenvolvimento.
# -------------------------------------------------------

# Criar venv_build se nao existir
if (-not (Test-Path ".\venv_build\Scripts\python.exe")) {
    Write-Host "`nCreating clean build venv (venv_build)..." -ForegroundColor Yellow
    python -m venv venv_build
    Write-Host "venv_build created" -ForegroundColor Green
}

Write-Host "`nActivating build venv..." -ForegroundColor Yellow
& .\venv_build\Scripts\Activate.ps1

# Instala apenas as libs que o server_downloader.py usa diretamente
Write-Host "`nInstalling minimal server dependencies into venv_build..." -ForegroundColor Yellow
python -m pip install --upgrade pip --quiet
python -m pip install --upgrade -r requirements_build.txt
python -m pip install --upgrade nuitka zstandard ordered-set

# Clean previous builds
Write-Host "`nCleaning previous builds..." -ForegroundColor Yellow
# Kill any running Downloader.exe before trying to delete
$ErrorActionPreference = "Continue"
taskkill /f /im Downloader.exe 2>$null | Out-Null
Start-Sleep -Seconds 1
$ErrorActionPreference = "Stop"
if (Test-Path ".\dist_nuitka") {
    cmd /c "rmdir /s /q .\dist_nuitka 2>nul || taskkill /f /im python.exe 2>nul & rmdir /s /q .\dist_nuitka"
    Write-Host "Removed ./dist_nuitka" -ForegroundColor Green
}
if (Test-Path ".\launcher.py") {
    Remove-Item ".\launcher.py" -Force -ErrorAction SilentlyContinue
    Write-Host "Removed ./launcher.py" -ForegroundColor Green
}

# Ensure placeholder dirs exist
foreach ($dir in @("arquivos", "cellref", "data")) {
    if (-not (Test-Path ".\$dir")) {
        New-Item -ItemType Directory -Path ".\$dir" | Out-Null
    }
    if (-not (Test-Path ".\$dir\.gitkeep")) {
        "" | Out-File -FilePath ".\$dir\.gitkeep" -Encoding ASCII
    }
}

# Create launcher script (write as ASCII to avoid BOM issues)
Write-Host "`nCreating launcher script..." -ForegroundColor Yellow
$launcher = @"
import os
import sys
import webbrowser
import time
import traceback
from threading import Thread

def open_browser():
    time.sleep(3)
    try:
        webbrowser.open('http://127.0.0.1:8765')
    except Exception as e:
        print(f"Could not open browser: {e}")

if __name__ == "__main__":
    app_dir = os.path.dirname(os.path.abspath(__file__))
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)

    try:
        # Direct import so Nuitka can trace the dependency
        from server_downloader import app as flask_app

        browser_thread = Thread(target=open_browser, daemon=True)
        browser_thread.start()

        print("Starting Downloader server on http://127.0.0.1:8765 ...")
        flask_app.run(host='127.0.0.1', port=8765, threaded=True)
    except KeyboardInterrupt:
        print("\nServer stopped.")
        sys.exit(0)
    except Exception as e:
        # Write error to file next to exe for debugging
        err_path = os.path.join(app_dir, "downloader_error.log")
        with open(err_path, "w", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        sys.exit(1)
"@
# Use .NET to write without BOM
[System.IO.File]::WriteAllText(
    (Join-Path $PWD "launcher.py"),
    $launcher,
    [System.Text.UTF8Encoding]::new($false)
)
Write-Host "Launcher script created" -ForegroundColor Green

# Verify launcher.py can be imported
Write-Host "`nVerifying launcher imports..." -ForegroundColor Yellow
python -c "from server_downloader import app; print('server_downloader imported OK')"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Cannot import server_downloader. Check that all dependencies are installed." -ForegroundColor Red
    exit 1
}
Write-Host "Import verification passed" -ForegroundColor Green

# Confirm pyarrow is NOT in venv_build (sanity check)
$ErrorActionPreference = "Continue"
python -c "import pyarrow" 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "WARNING: pyarrow found in venv_build - it should not be here!" -ForegroundColor Red
    Write-Host "Run: venv_build\Scripts\pip uninstall pyarrow -y" -ForegroundColor Yellow
    $ErrorActionPreference = "Stop"
    exit 1
} else {
    Write-Host "OK: pyarrow not in venv_build (will not be included in exe)" -ForegroundColor Green
}
$ErrorActionPreference = "Stop"

# Run Nuitka compilation
Write-Host "`nStarting Nuitka compilation..." -ForegroundColor Yellow
Write-Host "This may take 10-20 minutes depending on your system..." -ForegroundColor Cyan

# NOTAS SOBRE OS FLAGS ABAIXO (nao remover sem ler o CLAUDE.md):
#
# --nofollow-import-to=pandas.tests / numpy.tests / pydoc / doctest / unittest
#   CRITICO: --follow-import-to=pandas puxa pandas.tests por transitividade,
#   inflando o launcher.dll de ~50MB para 139MB (exe de 28MB para 46MB+).
#   Esses flags bloqueiam isso. Sem eles, o exe dobra de tamanho.
#   Sintoma do problema: warning "Undesirable import of 'pydoc' in pandas.tests.series.test_api"
#
# venv_build (usada acima em vez da venv de dev):
#   pyarrow/lxml/xlsxwriter estao na venv dev mas NAO na venv_build.
#   Se o Nuitka os enxergar, inclui as DLLs do Arrow (~47MB) automaticamente.
#   Por isso usamos venv_build com apenas flask+pandas+openpyxl.
#
# numpy 2.x (NAO pinnar numpy<2.0):
#   numpy 1.26 tem OpenBLAS de 37MB; numpy 2.0 tem 32MB. 2.x e menor.
#
# --lto=yes NAO usar no Windows/MSVC:
#   Com cl.exe, LTO otimiza velocidade, nao tamanho. Aumenta o exe.

python -m nuitka `
    --onefile `
    --standalone `
    --windows-console-mode=disable `
    --assume-yes-for-downloads `
    --follow-import-to=flask `
    --follow-import-to=werkzeug `
    --follow-import-to=jinja2 `
    --follow-import-to=click `
    --follow-import-to=itsdangerous `
    --follow-import-to=markupsafe `
    --follow-import-to=pandas `
    --follow-import-to=openpyxl `
    --follow-import-to=server_downloader `
    --nofollow-import-to=pandas.tests `
    --nofollow-import-to=pandas.io.tests `
    --nofollow-import-to=numpy.testing `
    --nofollow-import-to=numpy.tests `
    --nofollow-import-to=numpy.distutils `
    --nofollow-import-to=pydoc `
    --nofollow-import-to=doctest `
    --nofollow-import-to=unittest `
    --include-package=flask `
    --include-package=werkzeug `
    --include-package=jinja2 `
    --include-package=click `
    --include-package=itsdangerous `
    --include-package=markupsafe `
    --include-package=pandas `
    --include-package=openpyxl `
    --include-data-dir=web-tool=web-tool `
    --include-data-files=dump_multiple_enms.py=dump_multiple_enms.py `
    --include-data-files=parquet_to_txt.py=parquet_to_txt.py `
    --include-data-files=xml_to_parquet.py=xml_to_parquet.py `
    --include-data-files=extract_dump.py=extract_dump.py `
    --include-data-files=post_process_4_camilo.py=post_process_4_camilo.py `
    --include-data-files=post_process_5_tdd.py=post_process_5_tdd.py `
    --include-data-files=post_process_6_5g.py=post_process_6_5g.py `
    --output-dir=dist_nuitka `
    --output-filename=Downloader.exe `
    launcher.py

# Check if build was successful
if ($LASTEXITCODE -eq 0) {
    Write-Host "`n========================================" -ForegroundColor Green
    Write-Host "BUILD SUCCESSFUL!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green

    $exeSize = (Get-Item ".\dist_nuitka\Downloader.exe").Length / 1MB
    Write-Host ("`nExecutable size: {0:N1} MB" -f $exeSize) -ForegroundColor Cyan
    Write-Host "  .\dist_nuitka\Downloader.exe" -ForegroundColor Yellow

    Write-Host "`nThe application will:" -ForegroundColor Green
    Write-Host "  - Start the Flask server on http://127.0.0.1:8765" -ForegroundColor White
    Write-Host "  - Automatically open in your default browser" -ForegroundColor White
    Write-Host "`nNOTE: Console window is hidden (--windows-console-mode=disable)." -ForegroundColor Yellow
    Write-Host "Startup errors are written to downloader_error.log next to the exe." -ForegroundColor Yellow

    Write-Host "`nIMPORTANT: The subprocess scripts (dump, parquet, xml, etc.) are embedded" -ForegroundColor Cyan
    Write-Host "inside the .exe and extracted at runtime. They require Python to be installed" -ForegroundColor Cyan
    Write-Host "on the machine (or place a python_embed folder next to the .exe)." -ForegroundColor Cyan

    # Create desktop shortcut
    Write-Host "`nCreating desktop shortcut..." -ForegroundColor Yellow
    $targetPath = (Resolve-Path ".\dist_nuitka\Downloader.exe").Path
    $shortcutPath = "$env:USERPROFILE\Desktop\Downloader.lnk"
    try {
        $shell = New-Object -COM WScript.Shell
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $targetPath
        $shortcut.WorkingDirectory = (Resolve-Path ".\dist_nuitka").Path
        $shortcut.Description = "Downloader - ENM Web Tool"
        $shortcut.Save()
        Write-Host "Desktop shortcut created: Downloader.lnk" -ForegroundColor Green
    } catch {
        Write-Host "Could not create desktop shortcut: $_" -ForegroundColor Yellow
    }

    # Create Start Menu shortcut
    Write-Host "`nCreating Start Menu shortcut..." -ForegroundColor Yellow
    try {
        $startMenuPath = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Downloader.lnk"
        $shell2 = New-Object -COM WScript.Shell
        $startShortcut = $shell2.CreateShortcut($startMenuPath)
        $startShortcut.TargetPath = $targetPath
        $startShortcut.WorkingDirectory = (Resolve-Path ".\dist_nuitka").Path
        $startShortcut.Description = "Downloader - ENM Web Tool"
        $startShortcut.Save()
        Write-Host "Start Menu shortcut created: Downloader (searchable via Windows Search)" -ForegroundColor Green
    } catch {
        Write-Host "Could not create Start Menu shortcut: $_" -ForegroundColor Yellow
    }

    # Clean up launcher script
    Write-Host "`nCleaning up temporary files..." -ForegroundColor Yellow
    Remove-Item ".\launcher.py" -Force -ErrorAction SilentlyContinue
    Write-Host "Temporary files removed" -ForegroundColor Green
} else {
    Write-Host "`n========================================" -ForegroundColor Red
    Write-Host "BUILD FAILED" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "`nPlease check the error messages above." -ForegroundColor Yellow
    exit 1
}

Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "Build process completed!" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
