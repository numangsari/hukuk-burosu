<# Uygulama açıkken haciz yenileme görevlerini oluşturur ve başarısız Google Takvim
   eşitlemelerini yeniden dener. WhatsApp mesajı göndermez. #>
param([string]$ToolsDir = $PSScriptRoot)
$ErrorActionPreference = "Stop"
$appService = Get-Service -Name "HukukBuroApp" -ErrorAction SilentlyContinue
if (-not $appService) {
    $appService = Get-Service -Name "OzkurtHukukApp" -ErrorAction SilentlyContinue
}
if ($null -eq $appService -or $appService.Status -ne "Running") { exit 0 }
$manage = Join-Path $ToolsDir "manage.cmd"
& $manage create_seizure_tasks
$seizureExit = $LASTEXITCODE
& $manage create_routine_tasks
$routineExit = $LASTEXITCODE
# Google Takvim API kapalıysa komut hiçbir şey yapmadan çıkar.
& $manage retry_google_sync
if ($seizureExit -ne 0) { exit $seizureExit }
if ($routineExit -ne 0) { exit $routineExit }
exit $LASTEXITCODE
