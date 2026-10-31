<#
  Seçilen yedeği geri yükler: servis durdurulur, geri yüklenir, servis başlatılır.
  Yönetici olarak çalıştırın (sağ tık > PowerShell ile çalıştır > Evet).
#>
$ErrorActionPreference = "Stop"
$tools = $PSScriptRoot
Add-Type -AssemblyName System.Windows.Forms
$dlg = New-Object System.Windows.Forms.OpenFileDialog
$dlg.Title = "Geri yüklenecek yedeği seçin"
$dlg.Filter = "Özkurt yedekleri (ozkurt-yedek-*.zip)|ozkurt-yedek-*.zip"
$dlg.InitialDirectory = Join-Path (Split-Path $tools) "data\backups"
if ($dlg.ShowDialog() -ne "OK") { exit 0 }
$answer = [System.Windows.Forms.MessageBox]::Show(
    "$($dlg.SafeFileName) geri yüklenecek. Mevcut veriler bu yedekteki hâliyle değiştirilecek.`n`nGeri yüklemeden önce mevcut durumun da yedeği alınacak. Devam edilsin mi?",
    "Yedekten geri yükle", "YesNo", "Warning")
if ($answer -ne "Yes") { exit 0 }
& (Join-Path $tools "manage.cmd") backup --update
& (Join-Path $tools "OzkurtHukukApp.exe") stop
try {
    & (Join-Path $tools "manage.cmd") restore $dlg.FileName --yes
    if ($LASTEXITCODE -ne 0) { throw "Geri yükleme başarısız." }
    [System.Windows.Forms.MessageBox]::Show("Geri yükleme tamamlandı.", "Yedekten geri yükle") | Out-Null
} finally {
    & (Join-Path $tools "OzkurtHukukApp.exe") start
}
