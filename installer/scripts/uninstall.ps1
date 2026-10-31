<#
  Kaldırmada servisleri, zamanlanmış görevi ve güvenlik duvarı kuralını siler.
  VERİLER (data\pgdata, data\media, data\backups) ve .env SİLİNMEZ.
#>
param([Parameter(Mandatory = $true)][string]$InstallDir)
$ErrorActionPreference = "Continue"
$svc = Join-Path $InstallDir "tools\OzkurtHukukApp.exe"
if (Test-Path $svc) { & $svc stop; & $svc uninstall }
$pg = Join-Path $InstallDir "pgsql\bin\pg_ctl.exe"
if (Get-Service "OzkurtHukukDB" -ErrorAction SilentlyContinue) {
    Stop-Service "OzkurtHukukDB" -Force
    if (Test-Path $pg) { & $pg unregister -N OzkurtHukukDB }
}
Unregister-ScheduledTask -TaskName "Ozkurt Hukuk Yedek" -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "Ozkurt Hukuk Hatirlatma" -Confirm:$false -ErrorAction SilentlyContinue
Remove-NetFirewallRule -DisplayName "Ozkurt Hukuk" -ErrorAction SilentlyContinue
