<# Uygulama açıkken haciz yenileme görevlerini oluşturur. WhatsApp mesajı göndermez. #>
param([string]$ToolsDir = $PSScriptRoot)
$ErrorActionPreference = "Stop"
$appService = Get-Service -Name "HukukBuroApp" -ErrorAction SilentlyContinue
if (-not $appService) {
    $appService = Get-Service -Name "OzkurtHukukApp" -ErrorAction SilentlyContinue
}
if ($null -eq $appService -or $appService.Status -ne "Running") { exit 0 }
& (Join-Path $ToolsDir "manage.cmd") create_seizure_tasks
exit $LASTEXITCODE
