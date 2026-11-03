<# Ofis tablolarını uygulama çalışırken düzenli günceller. #>
param([string]$ToolsDir = $PSScriptRoot)
$ErrorActionPreference = "Stop"
$appService = Get-Service -Name "OzkurtHukukApp" -ErrorAction SilentlyContinue
if ($null -eq $appService -or $appService.Status -ne "Running") { exit 0 }
& (Join-Path $ToolsDir "manage.cmd") refresh_office_lists --watch
exit $LASTEXITCODE
