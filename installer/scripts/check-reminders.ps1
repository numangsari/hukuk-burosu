<# Uygulama çalışırken WhatsApp hatırlatmalarını gönderir; bakım sırasında veritabanına dokunmaz. #>
param([string]$ToolsDir = $PSScriptRoot)
$ErrorActionPreference = "Stop"
$appService = Get-Service -Name "OzkurtHukukApp" -ErrorAction SilentlyContinue
if ($null -eq $appService -or $appService.Status -ne "Running") { exit 0 }
& (Join-Path $ToolsDir "manage.cmd") send_whatsapp
exit $LASTEXITCODE
