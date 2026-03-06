param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

if (!(Test-Path ".venv")) {
    py -3 -m venv .venv
}

.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt pyinstaller

if (Test-Path dist) { Remove-Item dist -Recurse -Force }
if (Test-Path build) { Remove-Item build -Recurse -Force }

.\.venv\Scripts\pyinstaller --noconfirm --clean --onefile --windowed --name ChatVault desktop_app.py --add-data "templates;templates" --add-data "static;static"
.\.venv\Scripts\pyinstaller --noconfirm --clean --onefile --console --name chatvault-cli chatvault.py --add-data "templates;templates" --add-data "static;static"

if (-not $SkipInstaller) {
    $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (!(Test-Path $iscc)) {
        throw "Inno Setup 6 not found at '$iscc'. Install Inno Setup or run with -SkipInstaller."
    }
    & $iscc "packaging/windows/chatvault.iss"
}

Write-Host "Build complete. Artifacts are in dist/."
