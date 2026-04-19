$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

$wrapperExe = Join-Path $PSScriptRoot 'CapsWriterService.exe'

if (-not (Test-IsAdmin)) {
    throw "Uninstalling the Windows service requires an elevated PowerShell session. Re-run this script as Administrator."
}

if (-not (Test-Path -LiteralPath $wrapperExe)) {
    throw "Missing service wrapper executable: $wrapperExe. Run the install script once first so the wrapper is downloaded."
}

& $wrapperExe stop | Out-Null
& $wrapperExe uninstall

if ($LASTEXITCODE -ne 0) {
    throw "WinSW uninstall failed with exit code $LASTEXITCODE"
}

Write-Output "CapsWriter Windows service removed."
