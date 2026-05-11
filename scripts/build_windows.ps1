param(
    [switch]$SkipInstaller,
    [switch]$SkipCli,
    [string]$PythonExe
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$script:PythonCommand = $null
$script:PythonBaseArgs = @()
$script:PythonVersion = $null

Set-Location $script:RepoRoot

function Write-Section {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Use-PythonCandidate {
    param(
        [string]$Command,
        [string[]]$BaseArgs = @()
    )

    try {
        $output = & $Command @BaseArgs --version 2>&1
        if ($LASTEXITCODE -ne 0) {
            return $false
        }
        $versionLine = ($output | Select-Object -Last 1)
        if ($versionLine -match '^Python\s+(\d+)\.(\d+)\.(\d+)') {
            $major = [int]$matches[1]
            $minor = [int]$matches[2]
            if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) {
                $script:PythonCommand = $Command
                $script:PythonBaseArgs = $BaseArgs
                $script:PythonVersion = $versionLine
                return $true
            }
            Write-Host "Found Python $versionLine, but ChatVault needs Python 3.10 or newer." -ForegroundColor Yellow
        }
    }
    catch {
        return $false
    }

    return $false
}

function Find-Python {
    if ($PythonExe) {
        $resolved = (Resolve-Path -LiteralPath $PythonExe -ErrorAction Stop).Path
        if (Use-PythonCandidate -Command $resolved) {
            return
        }
    }
    if ($env:CHATVAULT_PYTHON -and (Use-PythonCandidate -Command $env:CHATVAULT_PYTHON)) {
        return
    }
    foreach ($version in @("3.13", "3.12", "3.11", "3.10")) {
        if (Use-PythonCandidate -Command "py" -BaseArgs @("-$version")) {
            return
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python -and (Use-PythonCandidate -Command $python.Source)) {
        return
    }

    throw "No usable Python 3.10+ install was found. Install Python or set CHATVAULT_PYTHON to the full python.exe path."
}

function Invoke-HostPython {
    $combinedArgs = @()
    $combinedArgs += $script:PythonBaseArgs
    $combinedArgs += $Args
    & $script:PythonCommand @combinedArgs
}

function Invoke-Checked {
    param(
        [string]$Label,
        [scriptblock]$Command
    )

    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Label failed with exit code $LASTEXITCODE."
    }
}

Write-Section "Checking Python"
Find-Python
Write-Host "Using Python $script:PythonVersion"

$venvRoot = Join-Path $script:RepoRoot ".venv"
$venvPython = Join-Path $venvRoot "Scripts\python.exe"

if (Test-Path -LiteralPath $venvPython) {
    $venvVersion = (& $venvPython --version 2>&1 | Select-Object -Last 1)
    if ($venvVersion -ne $script:PythonVersion) {
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $backup = Join-Path $script:RepoRoot ".venv.replaced-build-$stamp"
        Move-Item -LiteralPath $venvRoot -Destination $backup
        Write-Host "Moved build .venv using $venvVersion to $backup"
    }
}

if ((Test-Path -LiteralPath $venvRoot) -and !(Test-Path -LiteralPath $venvPython)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backup = Join-Path $script:RepoRoot ".venv.broken-build-$stamp"
    Move-Item -LiteralPath $venvRoot -Destination $backup
    Write-Host "Moved incomplete .venv to $backup"
}

if (!(Test-Path -LiteralPath $venvPython)) {
    Write-Section "Creating private build environment"
    Invoke-HostPython -m venv ".venv"
    if ($LASTEXITCODE -ne 0) {
        throw "Python could not create the .venv build environment."
    }
}

if (!(Test-Path -LiteralPath $venvPython)) {
    throw "The build environment was not created at $venvPython"
}

Write-Section "Installing build dependencies"
Invoke-Checked "Pip upgrade" { & $venvPython -m pip install --upgrade pip }
Invoke-Checked "Dependency install" { & $venvPython -m pip install -r requirements.txt pyinstaller }

Write-Section "Cleaning old artifacts"
if (Test-Path dist) { Remove-Item dist -Recurse -Force }
if (Test-Path build) { Remove-Item build -Recurse -Force }

$commonPyInstallerArgs = @(
    "--noconfirm",
    "--add-data", "templates;templates",
    "--add-data", "static;static",
    "--add-data", "browser_extension;browser_extension",
    "--hidden-import", "h11",
    "--hidden-import", "draughts",
    "--hidden-import", "uvicorn.logging",
    "--hidden-import", "uvicorn.loops.auto",
    "--hidden-import", "uvicorn.loops.asyncio",
    "--hidden-import", "uvicorn.protocols.http.auto",
    "--hidden-import", "uvicorn.protocols.http.h11_impl",
    "--hidden-import", "uvicorn.protocols.websockets.auto",
    "--hidden-import", "uvicorn.protocols.websockets.websockets_impl",
    "--hidden-import", "uvicorn.lifespan.on"
)

Write-Section "Building desktop app"
Invoke-Checked "Desktop build" { & $venvPython -m PyInstaller @commonPyInstallerArgs --onedir --windowed --name ChatVault desktop_app.py }

Write-Section "Building CLI"
if ($SkipCli) {
    Write-Host "Skipping CLI build because -SkipCli was set."
}
else {
    Invoke-Checked "CLI build" { & $venvPython -m PyInstaller @commonPyInstallerArgs --onefile --console --name chatvault-cli chatvault.py }
}

if (-not $SkipInstaller -and -not $SkipCli) {
    Write-Section "Building installer"
    $iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
    if (!(Test-Path $iscc)) {
        throw "Inno Setup 6 not found at '$iscc'. Install Inno Setup or run with -SkipInstaller."
    }
    Invoke-Checked "Installer build" { & $iscc "packaging/windows/chatvault.iss" }
}
elseif (-not $SkipInstaller -and $SkipCli) {
    Write-Host "Skipping installer because -SkipCli was set and the installer requires chatvault-cli.exe."
}

Write-Host ""
Write-Host "Build complete. Artifacts are in dist/."
