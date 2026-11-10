# Builds the portable app folder, checks it, and compiles the installer.
#   powershell -ExecutionPolicy Bypass -File installer\build.ps1
#   ... -SkipTests      skip pytest
#   ... -NoInstaller    stop after dist\Vox and the portable zip

[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$NoInstaller
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$dist = Join-Path $root 'dist\Vox'
$output = Join-Path $PSScriptRoot 'Output'

# Local builds use the project's virtual environment. CI runs with whatever
# interpreter setup-python installed, and has no .venv at all.
$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    $onPath = Get-Command python -ErrorAction SilentlyContinue
    if ($onPath) {
        $py = $onPath.Source
    }
}

function Step([string]$Text) {
    Write-Host ''
    Write-Host "== $Text" -ForegroundColor Cyan
}

if (-not (Test-Path $py)) {
    throw "No virtual environment found. Create it first:`n  py -3.11 -m venv .venv`n  .\.venv\Scripts\python -m pip install -r requirements-dev.txt"
}

Push-Location $root
try {
    Step 'Versions'
    $initText = Get-Content 'voxapp\__init__.py' -Raw
    if ($initText -notmatch '__version__\s*=\s*"([^"]+)"') {
        throw 'Could not read __version__ from voxapp\__init__.py'
    }
    $version = $Matches[1]
    $issText = Get-Content 'installer\version.iss' -Raw
    if ($issText -notmatch '#define AppVersion "([^"]+)"') {
        throw 'Could not read AppVersion from installer\version.iss'
    }
    if ($Matches[1] -ne $version) {
        throw "Version mismatch: voxapp is $version, installer is $($Matches[1]). Update both."
    }
    $numeric = (($version.Split('.') + @('0', '0', '0'))[0..3]) -join '.'
    $infoText = Get-Content 'installer\version_info.txt' -Raw
    if ($infoText -notmatch [regex]::Escape("'$numeric'")) {
        throw "installer\version_info.txt does not contain version $numeric."
    }
    Write-Host "Vox $version ($numeric)"

    Step 'Model files'
    $needed = @('enroll.onnx', 'enroll_fp16.onnx', 'chunk_int8.onnx', 'chunk_fp16.onnx', 'config.yaml', 'LICENSE', 'NOTICE')
    $missing = $needed | Where-Object { -not (Test-Path (Join-Path $root "models\$_")) }
    if ($missing) {
        Write-Host "Missing: $($missing -join ', '). Downloading the pinned revision..."
        & $py 'tools\fetch_models.py'
        if ($LASTEXITCODE -ne 0) { throw 'tools\fetch_models.py failed.' }
    } else {
        Write-Host 'Models present.'
    }

    Step 'voxlock'
    & $py -c 'import voxlock' 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host 'Installing voxlock without its onnxruntime dependency...'
        & $py -m pip install --no-deps 'voxlock==1.3.0'
        if ($LASTEXITCODE -ne 0) { throw 'Could not install voxlock.' }
    } else {
        Write-Host 'voxlock present.'
    }

    if (-not $SkipTests) {
        Step 'Tests'
        & $py -m pytest -q
        if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
    }

    Step 'PyInstaller'
    & $py -m PyInstaller --noconfirm --clean 'vox.spec'
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
    if (-not (Test-Path (Join-Path $dist 'Vox.exe'))) { throw 'dist\Vox\Vox.exe was not created.' }

    Step 'Frozen self-test'
    $resultPath = Join-Path $env:TEMP "vox-selftest-$PID.json"
    Remove-Item $resultPath -ErrorAction SilentlyContinue
    $proc = Start-Process -FilePath (Join-Path $dist 'Vox.exe') `
        -ArgumentList @('--selftest', '--mode', 'cpu', '--result', "`"$resultPath`"") `
        -Wait -PassThru
    if ($proc.ExitCode -ne 0) { throw "Vox.exe --selftest exited with $($proc.ExitCode)." }
    $result = Get-Content $resultPath -Raw | ConvertFrom-Json
    if (-not $result.ok) { throw "Self-test reported failure: $($result.error)" }
    Write-Host ("ok: {0} ms blocks, RTF {1}, {2} s audio in {3} s" -f `
        $result.block_ms, $result.rtf, $result.seconds_processed, $result.seconds_taken)

    $gpu = (& $py -c 'from voxapp.engine import gpu_available; print(1 if gpu_available() else 0)' 2>$null)
    if ($gpu -and $gpu.Trim() -eq '1') {
        try {
            $gpuResult = Join-Path $env:TEMP "vox-selftest-gpu-$PID.json"
            Remove-Item $gpuResult -ErrorAction SilentlyContinue
            $gpuProc = Start-Process -FilePath (Join-Path $dist 'Vox.exe') `
                -ArgumentList @('--selftest', '--mode', 'gpu', '--result', "`"$gpuResult`"") `
                -Wait -PassThru
            if ($gpuProc.ExitCode -ne 0) { throw "Vox.exe --selftest --mode gpu exited with $($gpuProc.ExitCode)." }
            $gpuCheck = Get-Content $gpuResult -Raw | ConvertFrom-Json
            if (-not $gpuCheck.ok) { throw "GPU self-test reported failure: $($gpuCheck.error)" }
            Write-Host ("gpu ok: RTF {0}" -f $gpuCheck.rtf)
        } catch {
            # Build machines often have a software adapter with no real GPU.
            # The app still runs in CPU mode there, so keep the build going.
            if ($env:CI) {
                Write-Warning "GPU self-test skipped: $($_.Exception.Message)"
            } else {
                throw
            }
        }
    }

    Step 'Portable zip'
    New-Item -ItemType Directory -Path $output -Force | Out-Null
    $zipPath = Join-Path $output "Vox-$version-portable.zip"
    Remove-Item $zipPath -ErrorAction SilentlyContinue
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory($dist, $zipPath, 'Optimal', $false)
    Write-Host "Portable: $zipPath"

    $artifacts = @($zipPath)

    if (-not $NoInstaller) {
        Step 'Inno Setup'
        $isccCandidates = @(
            (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
            (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
        )
        $iscc = $isccCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
        if (-not $iscc) {
            $command = Get-Command iscc.exe -ErrorAction SilentlyContinue
            if ($command) { $iscc = $command.Source }
        }
        if (-not $iscc) {
            throw 'Inno Setup 6 not found. Install it from https://jrsoftware.org/isdl.php or run with -NoInstaller.'
        }
        & $iscc 'installer\Vox.iss'
        if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed.' }
        $setup = Join-Path $output "Vox-$version-setup.exe"
        if (-not (Test-Path $setup)) { throw "Installer not found at $setup" }
        $artifacts += $setup
        Write-Host "Installer: $setup"
    }

    Step 'Checksums'
    $lines = foreach ($file in $artifacts) {
        $hash = (Get-FileHash $file -Algorithm SHA256).Hash.ToLower()
        '{0}  {1}' -f $hash, (Split-Path -Leaf $file)
    }
    $lines | Set-Content (Join-Path $output 'SHA256SUMS.txt') -Encoding ascii
    Write-Host ($lines -join "`n")
}
finally {
    Pop-Location
}
