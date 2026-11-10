# Downloads the VB-CABLE driver pack and starts its installer elevated.
# The vendor's setup is interactive: the user clicks "Install Driver".
# Vox is not affiliated with VB-Audio; the cable is a separate product.

[CmdletBinding()]
param(
    [switch]$NoLaunch
)

$ErrorActionPreference = 'Stop'
$page = 'https://vb-audio.com/Cable/'
$zipUrl = 'https://download.vb-audio.com/Download_CABLE/VBCABLE_Driver_Pack45.zip'
$work = Join-Path $env:TEMP 'VoxVB-Cable'

function Open-DownloadPage {
    try {
        Start-Process $page | Out-Null
    } catch {
        Write-Warning "Could not open $page"
    }
}

try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    if (Test-Path $work) {
        Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Path $work -Force | Out-Null

    $zip = Join-Path $work 'VBCABLE_Driver_Pack45.zip'
    Write-Host 'Downloading VB-CABLE...'
    Invoke-WebRequest -Uri $zipUrl -OutFile $zip -UseBasicParsing -TimeoutSec 120
    Expand-Archive -Path $zip -DestinationPath $work -Force

    $setup = Get-ChildItem -Path $work -Filter 'VBCABLE_Setup_x64.exe' -Recurse |
        Select-Object -First 1
    if (-not $setup) {
        throw 'The downloaded package does not contain VBCABLE_Setup_x64.exe.'
    }

    if ($NoLaunch) {
        Write-Host "Extracted to $($setup.FullName)"
        exit 0
    }

    Write-Host "Starting $($setup.FullName)"
    Start-Process -FilePath $setup.FullName -Verb RunAs
    Write-Host 'Follow the VB-CABLE installer, then reboot if it asks.'
    exit 0
}
catch {
    Write-Warning "VB-CABLE download failed: $($_.Exception.Message)"
    Open-DownloadPage
    exit 0
}
