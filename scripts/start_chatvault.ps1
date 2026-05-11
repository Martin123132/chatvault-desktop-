param(
    [switch]$SkipDependencyInstall,
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

function Stop-Friendly {
    param(
        [string]$Message,
        [int]$Code = 1
    )
    Write-Host ""
    Write-Host $Message -ForegroundColor Red
    exit $Code
}

function Get-FreeSpaceGb {
    param([string]$Path)
    try {
        $drive = Get-PSDrive -Name ([System.IO.Path]::GetPathRoot($Path).Substring(0, 1)) -ErrorAction Stop
        return [math]::Round($drive.Free / 1GB, 2)
    }
    catch {
        return $null
    }
}

function Use-PythonCandidate {
    param(
        [string]$Command,
        [string[]]$BaseArgs = @()
    )

    try {
        $output = & $Command @BaseArgs --version 2>&1
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
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
        try {
            $resolved = (Resolve-Path -LiteralPath $PythonExe -ErrorAction Stop).Path
            if ($resolved) {
                Write-Host "Trying Python from $resolved"
                if (Use-PythonCandidate -Command $resolved) {
                    return
                }
            }
        }
        catch {
        }
    }

    if ($env:CHATVAULT_PYTHON -and (Use-PythonCandidate -Command $env:CHATVAULT_PYTHON)) {
        return
    }

    if (Use-PythonCandidate -Command "py" -BaseArgs @("-3")) {
        return
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python -and (Use-PythonCandidate -Command $python.Source)) {
        return
    }

    $python3 = Get-Command python3 -ErrorAction SilentlyContinue
    if ($python3 -and (Use-PythonCandidate -Command $python3.Source)) {
        return
    }

    Write-Host "No usable Python 3.10+ install was found." -ForegroundColor Yellow
    Write-Host "Opening the Python for Windows download page now."
    Start-Process "https://www.python.org/downloads/windows/"
    Stop-Friendly "Install Python 3.10 or newer, tick 'Add python.exe to PATH' during setup, then double-click START_HERE_WINDOWS.bat again. If Python is already installed, set CHATVAULT_PYTHON to the full path of python.exe and run this starter again."
}

function Invoke-HostPython {
    $combinedArgs = @()
    $combinedArgs += $script:PythonBaseArgs
    $combinedArgs += $Args
    & $script:PythonCommand @combinedArgs
}

function Repair-MovedVenv {
    param([string]$VenvRoot)

    if (!(Test-Path -LiteralPath $VenvRoot)) {
        return
    }

    $metadataFiles = @(
        (Join-Path $VenvRoot "pyvenv.cfg"),
        (Join-Path $VenvRoot "Scripts\activate"),
        (Join-Path $VenvRoot "Scripts\activate.bat"),
        (Join-Path $VenvRoot "Scripts\activate.fish"),
        (Join-Path $VenvRoot "Scripts\Activate.ps1")
    )

    $currentVenvRoot = (Resolve-Path -LiteralPath $VenvRoot).Path
    $pathPattern = "[A-Za-z]:\\[^`r`n""'<>|]*?\.venv"
    $changed = $false

    foreach ($file in $metadataFiles) {
        if (!(Test-Path -LiteralPath $file)) {
            continue
        }

        $text = Get-Content -LiteralPath $file -Raw
        $updated = $text
        $matches = [regex]::Matches($text, $pathPattern)
        foreach ($match in $matches) {
            if ($match.Value -ne $currentVenvRoot) {
                $updated = $updated.Replace($match.Value, $currentVenvRoot)
            }
        }

        if ($updated -ne $text) {
            Set-Content -LiteralPath $file -Value $updated -Encoding ascii
            $changed = $true
        }
    }

    if ($changed) {
        Write-Section "Repaired moved private environment paths"
        Write-Host "Updated .venv metadata to use $currentVenvRoot"
    }
}

try {
    Write-Host "ChatVault one-click starter"
    Write-Host "Folder: $script:RepoRoot"

    Write-Section "Checking Python"
    Find-Python
    Write-Host "Using Python $script:PythonVersion"

    $venvPython = Join-Path $script:RepoRoot ".venv\Scripts\python.exe"
    $venvRoot = Join-Path $script:RepoRoot ".venv"
    if ((Test-Path -LiteralPath $venvRoot) -and !(Test-Path -LiteralPath $venvPython)) {
        Write-Section "Repairing incomplete private environment"
        $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
        $backup = Join-Path $script:RepoRoot ".venv.broken-$stamp"
        Move-Item -LiteralPath $venvRoot -Destination $backup
        Write-Host "Moved broken .venv to $backup"
    }

    if (!(Test-Path -LiteralPath $venvPython)) {
        Write-Section "Creating a private Python environment"
        $freeGb = Get-FreeSpaceGb -Path $script:RepoRoot
        if ($null -ne $freeGb -and $freeGb -lt 2) {
            Write-Host "Warning: only $freeGb GB is free on this drive. Dependency installs may fail if the drive fills up." -ForegroundColor Yellow
        }
        Invoke-HostPython -m venv ".venv"
        if ($LASTEXITCODE -ne 0) {
            Stop-Friendly "Python could not create the .venv environment in $script:RepoRoot. Check that this folder is writable and that the drive has free space, then run START_HERE_WINDOWS.bat again."
        }
    }

    Repair-MovedVenv -VenvRoot $venvRoot

    if (!(Test-Path -LiteralPath $venvPython)) {
        Stop-Friendly "The private environment is still missing its Python executable: $venvPython. Delete the .venv folder and run START_HERE_WINDOWS.bat again, or set CHATVAULT_PYTHON to a working python.exe path."
    }

    if (-not $SkipDependencyInstall) {
        $requirements = Join-Path $script:RepoRoot "requirements.txt"
        $marker = Join-Path $script:RepoRoot ".venv\.requirements.sha256"
        $wantedHash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
        $currentHash = ""
        if (Test-Path -LiteralPath $marker) {
            $currentHash = (Get-Content -LiteralPath $marker -Raw).Trim()
        }

        if ($currentHash -ne $wantedHash) {
            Write-Section "Installing ChatVault dependencies"
            Write-Host "First run can take several minutes, especially on slower connections."
            $freeGb = Get-FreeSpaceGb -Path $script:RepoRoot
            if ($null -ne $freeGb -and $freeGb -lt 3) {
                Write-Host "Warning: only $freeGb GB is free on this drive. If install fails, move the repo to a roomier drive and rerun this starter." -ForegroundColor Yellow
            }
            & $venvPython -m pip install --upgrade pip
            if ($LASTEXITCODE -ne 0) {
                Stop-Friendly "Pip could not be upgraded. Check your internet connection, antivirus prompts, and free disk space, then run START_HERE_WINDOWS.bat again."
            }

            & $venvPython -m pip install -r $requirements
            if ($LASTEXITCODE -ne 0) {
                Stop-Friendly "Dependency installation failed while running: $venvPython -m pip install -r $requirements. Check your internet connection and free disk space, then run START_HERE_WINDOWS.bat again."
            }

            Set-Content -LiteralPath $marker -Value $wantedHash -Encoding ascii
        }
        else {
            Write-Section "Dependencies already installed"
        }
    }

    Write-Section "Launching ChatVault"
    Write-Host "Your browser should open automatically."
    Write-Host "Keep this window open while using ChatVault. Close it to stop the local app."
    Write-Host ""

    $env:PYTHONUTF8 = "1"
    $env:PYTHONPATH = $script:RepoRoot
    & $venvPython (Join-Path $script:RepoRoot "desktop_app.py")
    if ($LASTEXITCODE -ne 0) {
        Stop-Friendly "ChatVault exited with code $LASTEXITCODE."
    }
}
catch {
    Stop-Friendly "Unexpected setup error: $($_.Exception.Message)"
}
