<#
  Kaldırmada servisleri, zamanlanmış görevi ve güvenlik duvarı kuralını siler.
  VERİLER (data\pgdata, data\media, data\backups) ve .env SİLİNMEZ.
#>
param([Parameter(Mandatory = $true)][string]$InstallDir)
$ErrorActionPreference = "Continue"

foreach ($exeName in @("HukukBuroApp.exe", "OzkurtHukukApp.exe")) {
    $svc = Join-Path $InstallDir "tools\$exeName"
    if (Test-Path $svc) { & $svc stop; & $svc uninstall }
}

$pg = Join-Path $InstallDir "pgsql\bin\pg_ctl.exe"
foreach ($dbSvc in @("HukukBuroDB", "OzkurtHukukDB")) {
    if (Get-Service $dbSvc -ErrorAction SilentlyContinue) {
        Stop-Service $dbSvc -Force
        if (Test-Path $pg) { & $pg unregister -N $dbSvc }
    }
}

foreach ($taskName in @(
    "Hukuk Buro Listeler", "Hukuk Buro Yedek", "Hukuk Buro Hatirlatma", "Hukuk Buro Haciz Takibi",
    "Ozkurt Hukuk Listeler", "Ozkurt Hukuk Yedek", "Ozkurt Hukuk Hatirlatma", "Ozkurt Hukuk Haciz Takibi"
)) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
}

Remove-NetFirewallRule -DisplayName "Hukuk Buro Yonetimi" -ErrorAction SilentlyContinue
$desktop = [Environment]::GetFolderPath("CommonDesktopDirectory")
foreach ($name in @("Hukuk B$([char]0x00FC)ro$([char]0x015F)u Otomasyonu.url", "Hukuk Buro Yonetimi.url", "Ozkurt Hukuk.url")) {
    Remove-Item (Join-Path $desktop $name) -ErrorAction SilentlyContinue
}
Remove-NetFirewallRule -DisplayName "Ozkurt Hukuk" -ErrorAction SilentlyContinue
