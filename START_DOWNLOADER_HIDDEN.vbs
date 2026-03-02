' Start Downloader server in background (no CMD window) and open browser.
' Use START_DOWNLOADER.bat for first-time setup or if you need to see logs.

Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)

If Not fso.FolderExists(scriptDir & "\venv") Then
    MsgBox "Run START_DOWNLOADER.bat first to create the virtual environment and install dependencies.", 48, "Downloader"
    WScript.Quit 1
End If

' pythonw.exe = no console window; 0 = hidden, False = don't wait for exit
WshShell.CurrentDirectory = scriptDir

' Stop previous listeners on port 8765 to avoid multiple server instances.
WshShell.Run "cmd /c for /f ""tokens=5"" %p in ('netstat -ano ^| findstr "":8765"" ^| findstr ""LISTENING""') do taskkill /F /PID %p >nul 2>&1", 0, True
WScript.Sleep 1000

WshShell.Run """" & scriptDir & "\venv\Scripts\pythonw.exe"" server_downloader.py", 0, False

WScript.Sleep 2000
WshShell.Run "http://127.0.0.1:8765"
