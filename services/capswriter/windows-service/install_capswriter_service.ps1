param(
    [switch]$StartService
)

$ErrorActionPreference = "Stop"

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-RepoRoot {
    return [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..'))
}

function Resolve-CapsWriterAppDir {
    param(
        [string]$RepoRoot
    )

    $candidates = @()

    if ($env:CAPSWRITER_APP_DIR) {
        $candidates += $env:CAPSWRITER_APP_DIR
    }

    $candidates += (Join-Path $RepoRoot 'services\capswriter\runtime\CapsWriter-Offline')
    $candidates += (Join-Path $RepoRoot 'backups\vendor\capswriter\app\CapsWriter-Offline')

    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate)) {
            $exe = Join-Path $candidate 'start_server.exe'
            if (Test-Path -LiteralPath $exe) {
                return [System.IO.Path]::GetFullPath($candidate)
            }
        }
    }

    throw "Could not locate CapsWriter-Offline. Set CAPSWRITER_APP_DIR or place the runtime under services\\capswriter\\runtime\\CapsWriter-Offline."
}

function Ensure-WinSW {
    param(
        [string]$WrapperExe
    )

    if (Test-Path -LiteralPath $WrapperExe) {
        return
    }

    $releaseUrl = 'https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW.NET4.exe'
    Invoke-WebRequest -Uri $releaseUrl -OutFile $WrapperExe
}

function Render-ServiceConfig {
    param(
        [string]$TemplatePath,
        [string]$OutputPath,
        [string]$ExecutablePath,
        [string]$WorkingDirectory,
        [string]$LogPath
    )

    $content = Get-Content -LiteralPath $TemplatePath -Raw
    $content = $content.Replace('__CAPSWRITER_EXE__', $ExecutablePath)
    $content = $content.Replace('__CAPSWRITER_WORKDIR__', $WorkingDirectory)
    $content = $content.Replace('__CAPSWRITER_LOGPATH__', $LogPath)
    Set-Content -LiteralPath $OutputPath -Value $content -Encoding ASCII
}

function Stop-CapsWriterProcessTree {
    param(
        [string]$ExecutablePath
    )

    $procs = Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -eq $ExecutablePath
    }

    foreach ($proc in $procs | Sort-Object ProcessId -Descending) {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Test-ServicePresent {
    param(
        [string]$Name
    )

    $service = Get-Service -Name $Name -ErrorAction SilentlyContinue
    $registryKey = Get-Item -LiteralPath "HKLM:\SYSTEM\CurrentControlSet\Services\$Name" -ErrorAction SilentlyContinue
    return [bool]$service -or [bool]$registryKey
}

function Remove-ServiceRegistration {
    param(
        [string]$Name,
        [string]$WrapperExe
    )

    $service = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if ($service) {
        Stop-Service -Name $Name -Force -ErrorAction SilentlyContinue
    }

    & $WrapperExe stop | Out-Null
    & $WrapperExe uninstall | Out-Null

    if (Test-ServicePresent -Name $Name) {
        sc.exe delete $Name | Out-Null
    }
}

function Wait-ServiceRemoval {
    param(
        [string]$Name,
        [int]$TimeoutSeconds = 30
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (-not (Test-ServicePresent -Name $Name)) {
            return $true
        }
        Start-Sleep -Seconds 1
    }

    return (-not (Test-ServicePresent -Name $Name))
}

$repoRoot = Get-RepoRoot
$serviceDir = $PSScriptRoot
$templatePath = Join-Path $serviceDir 'CapsWriterService.xml.template'
$wrapperExe = Join-Path $serviceDir 'CapsWriterService.exe'
$wrapperXml = Join-Path $serviceDir 'CapsWriterService.xml'
$logsDir = Join-Path $serviceDir 'logs'
$serviceName = 'CapsWriterService'
$appDir = Resolve-CapsWriterAppDir -RepoRoot $repoRoot
$appExe = Join-Path $appDir 'start_server.exe'

if (-not (Test-IsAdmin)) {
    throw "Installing a real Windows service requires an elevated PowerShell session. Re-run this script as Administrator."
}

if (-not (Test-Path -LiteralPath $templatePath)) {
    throw "Missing service wrapper template: $templatePath"
}

if (-not (Test-Path -LiteralPath $appExe)) {
    throw "Missing CapsWriter executable: $appExe"
}

New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
Ensure-WinSW -WrapperExe $wrapperExe
Render-ServiceConfig -TemplatePath $templatePath -OutputPath $wrapperXml -ExecutablePath $appExe -WorkingDirectory $appDir -LogPath $logsDir

Remove-ServiceRegistration -Name $serviceName -WrapperExe $wrapperExe

if (-not (Wait-ServiceRemoval -Name $serviceName -TimeoutSeconds 30)) {
    throw "Service $serviceName is still pending removal after 30 seconds."
}

& $wrapperExe install

if ($LASTEXITCODE -eq 1073) {
    if (Wait-ServiceRemoval -Name $serviceName -TimeoutSeconds 30) {
        & $wrapperExe install
    }
}

if ($LASTEXITCODE -ne 0) {
    throw "WinSW install failed with exit code $LASTEXITCODE"
}

if ($StartService) {
    Stop-CapsWriterProcessTree -ExecutablePath $appExe
    & $wrapperExe start
    if ($LASTEXITCODE -ne 0) {
        throw "WinSW start failed with exit code $LASTEXITCODE"
    }
}

Write-Output "CapsWriter Windows service installed."
Write-Output "CapsWriter app dir: $appDir"
if ($StartService) {
    Write-Output "CapsWriter Windows service started."
}
