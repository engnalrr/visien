# Visien installer for Windows 10/11 (64-bit).
# Everything goes into this folder (Python, packages, ffmpeg). No system settings are changed.
# To uninstall: delete this folder and the Visien shortcuts.

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Tools = Join-Path $Root "tools"
$Venv = Join-Path $Root ".venv"
$Py = Join-Path $Venv "Scripts\python.exe"
$PyW = Join-Path $Venv "Scripts\pythonw.exe"
$Log = Join-Path $Root "install.log"
# The full (offline) package ships its own Python with all packages in runtime\python.
$RuntimePy = Join-Path $Root "runtime\python\python.exe"
$Bundled = Test-Path $RuntimePy
if ($Bundled) { $Py = $RuntimePy; $PyW = Join-Path $Root "runtime\python\pythonw.exe" }
New-Item -ItemType Directory -Force -Path $Tools, (Join-Path $Root "engine") | Out-Null
try { Start-Transcript -Path $Log -Force | Out-Null } catch {}

$Warnings = New-Object System.Collections.Generic.List[string]
function Step([string]$Text) { Write-Host ""; Write-Host "==> $Text" -ForegroundColor Cyan }
function Info([string]$Text) { Write-Host "    $Text" }
function Warn([string]$Text) { Write-Host "    WARNING: $Text" -ForegroundColor Yellow; $Warnings.Add($Text) | Out-Null }

function Get-File([string]$Url, [string]$Target) {
    $partial = "$Target.part"
    if (Get-Command curl.exe -ErrorAction SilentlyContinue) {
        & curl.exe -L --fail --retry 3 --retry-delay 2 -o $partial $Url
        if ($LASTEXITCODE -ne 0) { throw "Download failed: $Url" }
    } else {
        Invoke-WebRequest -Uri $Url -OutFile $partial -UseBasicParsing
    }
    Move-Item -Force $partial $Target
}

function Expand-Zip([string]$Zip, [string]$Destination) {
    # .NET reader: tar.exe fails when the folder sits behind a symlink (redirected Downloads etc.)
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path $Destination) { Remove-Item $Destination -Recurse -Force }
    [System.IO.Compression.ZipFile]::ExtractToDirectory($Zip, $Destination)
}

Write-Host "Visien setup" -ForegroundColor White
Info "Folder: $Root"
# -cmatch: a case-insensitive match treats "I" as non-English on Turkish Windows (I -> dotless i).
if ($Root -cmatch "[^\x00-\x7F]") { Warn "The folder path contains non-English characters. If something fails, move Visien to a path like D:\Apps\Visien." }
# Files extracted from a downloaded zip carry Windows' "from the internet" mark; .NET then refuses to load the
# app window's libraries. Removing the mark from Visien's own files is what "Unblock" in file Properties does.
Info "Unblocking Visien's files (needed after extracting a downloaded zip)..."
Get-ChildItem -LiteralPath $Root -Recurse -File -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue

# ------------------------------------------------------------------ 1. GPU
Step "1/6  NVIDIA GPU"
$Gpu = $null
try { $Gpu = (& nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>$null | Select-Object -First 1) } catch {}
if ($Gpu) { Info "GPU: $Gpu" } else {
    $Amd = $null
    try { $Amd = (Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match "Radeon" } | Select-Object -First 1).Name } catch {}
    if ($Amd) {
        Info "GPU: $Amd (AMD)"
        Warn "No NVIDIA GPU: Visual Enhancer's DLSS and RTX cards cannot run on this PC. Visien's AI cards (SeedVR2, RIFE, Face Restore) run on AMD Radeon RX 7000/9000 with the AMD AI runtime (Settings > AI models)."
    } else {
        Warn "nvidia-smi not found. Visual Enhancer needs an NVIDIA GeForce RTX GPU with a current driver."
    }
}

# ------------------------------------------------------------------ 2-3. Python
if ($Bundled) {
    Step "2/6  Python (included in this package)"
    & $Py -c "import fastapi, uvicorn, webview; import sys; print('Python', sys.version.split()[0], '- packages OK')"
    if ($LASTEXITCODE -ne 0) { throw "The bundled Python in runtime\python is damaged. Extract the package again." }
    Step "3/6  Packages (included in this package)"
    Info "Nothing to download."
} else {
    # ------------------------------------------------------------------ 2. uv
    Step "2/6  uv (Python package manager)"
    $UvDir = Join-Path $Tools "uv"
    $Uv = Join-Path $UvDir "uv.exe"
    $NearbyUv = Join-Path (Split-Path -Parent $Root) "tools\uv\uv.exe"
    if (-not (Test-Path $Uv)) {
        New-Item -ItemType Directory -Force -Path $UvDir | Out-Null
        if (Test-Path $NearbyUv) {
            Copy-Item $NearbyUv $Uv -Force
            Info "Reused uv from $NearbyUv"
        } else {
            $zip = Join-Path $Tools "uv.zip"
            Get-File "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" $zip
            Expand-Zip $zip $UvDir
            Remove-Item $zip -Force
            $found = Get-ChildItem -Path $UvDir -Recurse -Filter "uv.exe" | Select-Object -First 1
            if ($found -and $found.FullName -ne $Uv) { Copy-Item $found.FullName $Uv -Force }
        }
    }
    & $Uv --version
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $Tools "python"
    $env:UV_CACHE_DIR = Join-Path $Tools "uv-cache"
    $env:UV_LINK_MODE = "copy"
    $env:UV_HTTP_TIMEOUT = "300"

    # ------------------------------------------------------------------ 3. Python + packages
    Step "3/6  Python 3.12 and packages"
    if (Test-Path $Py) {
        # A venv stops working when the folder is moved; rebuild it in that case.
        $ok = $false
        try { & $Py -c "import sys" 2>$null; $ok = ($LASTEXITCODE -eq 0) } catch {}
        if (-not $ok) { Info "Rebuilding the Python environment (the folder was moved)."; Remove-Item $Venv -Recurse -Force }
    }
    if (-not (Test-Path $Py)) {
        & $Uv venv $Venv --python 3.12
        if ($LASTEXITCODE -ne 0) { throw "Could not create the Python environment." }
    }
    & $Uv pip install --python $Py -r (Join-Path $Root "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Could not install the Python packages." }

}

# ------------------------------------------------------------------ 4. ffmpeg
Step "4/6  ffmpeg (previews and playback copies)"
$FfDir = Join-Path $Tools "ffmpeg"
$Ffmpeg = Join-Path $FfDir "bin\ffmpeg.exe"
$NearbyFf = Join-Path (Split-Path -Parent $Root) "tools\ffmpeg"
if (-not (Test-Path $Ffmpeg)) {
    if (Test-Path (Join-Path $NearbyFf "bin\ffmpeg.exe")) {
        Copy-Item $NearbyFf $FfDir -Recurse -Force
        Info "Reused ffmpeg from $NearbyFf"
    } else {
        $zip = Join-Path $Tools "ffmpeg.zip"
        $tmp = Join-Path $Tools "ffmpeg-extract"
        Get-File "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" $zip
        Expand-Zip $zip $tmp
        $inner = Get-ChildItem -Path $tmp -Directory | Select-Object -First 1
        if (Test-Path $FfDir) { Remove-Item $FfDir -Recurse -Force }
        Move-Item $inner.FullName $FfDir
        Remove-Item $tmp -Recurse -Force
        Remove-Item $zip -Force
    }
}
& $Ffmpeg -hide_banner -version | Select-Object -First 1

# ------------------------------------------------------------------ 5. WebView2
Step "5/6  Microsoft Edge WebView2 Runtime (the app window)"
$WebView = $null
foreach ($key in @("HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
                   "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
                   "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}")) {
    try { $v = (Get-ItemProperty -Path $key -ErrorAction Stop).pv; if ($v -and $v -ne "0.0.0.0") { $WebView = $v; break } } catch {}
}
if ($WebView) { Info "WebView2 $WebView" }
else { Warn "WebView2 Runtime not found. Install it from https://go.microsoft.com/fwlink/p/?LinkId=2124703 (Visien falls back to your browser without it)." }

# ------------------------------------------------------------------ 6. check + shortcuts
Step "6/6  Check and shortcuts"
$env:PYTHONUTF8 = "1"
Push-Location $Root
& $Py -m visien.check | Tee-Object -FilePath (Join-Path $Root "check.log")
Pop-Location

$Icon = Join-Path $Root "ui\assets\visien.ico"
function New-Shortcut([string]$Path) {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($Path)
    $lnk.TargetPath = $PyW
    $lnk.Arguments = "-m visien"
    $lnk.WorkingDirectory = $Root
    $lnk.IconLocation = "$Icon,0"
    $lnk.Description = "Visien - AI video enhancement"
    $lnk.Save()
}
try {
    $desktop = [Environment]::GetFolderPath("Desktop")
    if ($desktop -and (Test-Path $desktop)) { New-Shortcut (Join-Path $desktop "Visien.lnk"); Info "Desktop shortcut: Visien" }
    $programs = Join-Path ([Environment]::GetFolderPath("ApplicationData")) "Microsoft\Windows\Start Menu\Programs"
    if (Test-Path $programs) { New-Shortcut (Join-Path $programs "Visien.lnk"); Info "Start menu shortcut: Visien" }
} catch { Warn "Could not create the shortcuts. Start Visien with Visien.bat." }

try { & $Uv cache prune | Out-Null } catch {}

Write-Host ""
if ($Warnings.Count -gt 0) {
    Write-Host "Setup finished with warnings:" -ForegroundColor Yellow
    $Warnings | ForEach-Object { Write-Host "  - $_" -ForegroundColor Yellow }
} else {
    Write-Host "Setup finished." -ForegroundColor Green
}
Write-Host "Start Visien from the desktop shortcut or Visien.bat."
Write-Host "Log: $Log"
try { Stop-Transcript | Out-Null } catch {}
