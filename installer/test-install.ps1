# Installs the built setup silently into a throwaway folder, runs the installed
# app's self-test, then uninstalls it and checks that it is gone.
#   powershell -ExecutionPolicy Bypass -File installer\test-install.ps1
#   ... -Keep     leave the app installed for a manual look

[CmdletBinding()]
param(
    [string]$Installer,
    [switch]$Keep
)

$ErrorActionPreference = 'Stop'

if (-not $Installer) {
    $Installer = Get-ChildItem (Join-Path $PSScriptRoot 'Output') -Filter 'Vox-*-setup.exe' |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $Installer -or -not (Test-Path $Installer)) {
    throw 'No installer found. Run installer\build.ps1 first.'
}

$suffix = [guid]::NewGuid().ToString('N').Substring(0, 8)
$target = Join-Path $env:TEMP "Vox-install-test-$suffix"
$result = Join-Path $env:TEMP "vox-install-selftest-$suffix.json"

Write-Host "Installer: $Installer"
Write-Host "Target:    $target"

$install = Start-Process -FilePath $Installer -Wait -PassThru -ArgumentList @(
    '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/TASKS=""', "/DIR=`"$target`""
)
if ($install.ExitCode -ne 0) {
    throw "The installer exited with code $($install.ExitCode)."
}

$exe = Join-Path $target 'Vox.exe'
if (-not (Test-Path $exe)) {
    throw "Vox.exe is missing from $target after installation."
}
Write-Host 'Install ok.'

$run = Start-Process -FilePath $exe -Wait -PassThru -ArgumentList @(
    '--selftest', '--mode', 'cpu', '--result', "`"$result`""
)
if ($run.ExitCode -ne 0) {
    throw "The installed Vox self-test exited with code $($run.ExitCode)."
}
$check = Get-Content $result -Raw | ConvertFrom-Json
if (-not $check.ok) {
    throw "The installed Vox self-test failed: $($check.error)"
}
Write-Host ("Installed self-test ok: {0} ms blocks, RTF {1}" -f $check.block_ms, $check.rtf)

if ($Keep) {
    Write-Host "Kept for inspection: $target"
    exit 0
}

$uninstaller = Join-Path $target 'unins000.exe'
if (-not (Test-Path $uninstaller)) {
    throw 'The uninstaller is missing from the installed folder.'
}
$uninstall = Start-Process -FilePath $uninstaller -Wait -PassThru -ArgumentList @(
    '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART'
)
if ($uninstall.ExitCode -ne 0) {
    throw "The uninstaller exited with code $($uninstall.ExitCode)."
}
Start-Sleep -Seconds 2
if (Test-Path $exe) {
    throw 'Vox.exe is still present after uninstalling.'
}
Write-Host 'Uninstall ok. The test folder is gone.'
