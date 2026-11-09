<#
  Seçilen yedeği geri yükler: servis durdurulur, geri yüklenir, servis başlatılır.
  Yönetici olarak çalıştırın (sağ tık > PowerShell ile çalıştır > Evet).
#>
$ErrorActionPreference = "Stop"
$tools = $PSScriptRoot
Add-Type -AssemblyName System.Windows.Forms
$dlg = New-Object System.Windows.Forms.OpenFileDialog
$dlg.Title = "Geri yüklenecek yedeği seçin"
$dlg.Filter = "Yedek arşivleri (*-yedek-*.zip;*.zip)|*-yedek-*.zip;*.zip"
# Yedek klasörü .env'deki BACKUP_DIR'dır (yeni düzende C:\ProgramData\HukukBurosu\backups).
$backupLine = Get-Content (Join-Path (Split-Path $tools) "app\.env") -ErrorAction SilentlyContinue |
    Where-Object { $_ -like "BACKUP_DIR=*" } | Select-Object -First 1
$dlg.InitialDirectory = if ($backupLine) { $backupLine.Substring("BACKUP_DIR=".Length).Trim() } else { Join-Path (Split-Path $tools) "data\backups" }
if ($dlg.ShowDialog() -ne "OK") { exit 0 }
$answer = [System.Windows.Forms.MessageBox]::Show(
    "$($dlg.SafeFileName) geri yüklenecek. Mevcut veriler bu yedekteki hâliyle değiştirilecek.`n`nGeri yüklemeden önce mevcut durumun da yedeği alınacak. Devam edilsin mi?",
    "Yedekten geri yükle", "YesNo", "Warning")
if ($answer -ne "Yes") { exit 0 }
& (Join-Path $tools "manage.cmd") backup --update
if ($LASTEXITCODE -ne 0) {
    [System.Windows.Forms.MessageBox]::Show("Güvenlik yedeği alınamadı. Geri yükleme başlatılmadı.", "Yedekten geri yükle", "OK", "Error") | Out-Null
    exit 1
}

$appExe = Join-Path $tools "HukukBuroApp.exe"
if (-not (Test-Path $appExe)) { $appExe = Join-Path $tools "OzkurtHukukApp.exe" }

& $appExe stop
if ($LASTEXITCODE -ne 0) {
    [System.Windows.Forms.MessageBox]::Show("Uygulama durdurulamadı. Geri yükleme başlatılmadı.", "Yedekten geri yükle", "OK", "Error") | Out-Null
    exit 1
}
Stop-ScheduledTask -TaskName "Hukuk Buro Hatirlatma" -ErrorAction SilentlyContinue
Stop-ScheduledTask -TaskName "Hukuk Buro Haciz Takibi" -ErrorAction SilentlyContinue
Stop-ScheduledTask -TaskName "Ozkurt Hukuk Hatirlatma" -ErrorAction SilentlyContinue
Stop-ScheduledTask -TaskName "Ozkurt Hukuk Haciz Takibi" -ErrorAction SilentlyContinue

try {
    & (Join-Path $tools "manage.cmd") restore $dlg.FileName --yes
    if ($LASTEXITCODE -ne 0) { throw "Geri yükleme başarısız." }
    & $appExe start
    if ($LASTEXITCODE -ne 0) { throw "Veriler geri yüklendi, ancak uygulama başlatılamadı." }
    [System.Windows.Forms.MessageBox]::Show("Geri yükleme tamamlandı.", "Yedekten geri yükle") | Out-Null
} catch {
    [System.Windows.Forms.MessageBox]::Show("$($_.Exception.Message)`nUygulama kapalı tutuluyor. Sorun giderilmeden yeniden başlatmayın.", "Yedekten geri yükle", "OK", "Error") | Out-Null
    exit 1
}
