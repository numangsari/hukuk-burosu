# Yalnızca bu projenin geliştirme veritabanından listeleri yeniler.
$ErrorActionPreference = "Stop"
$mutex = New-Object System.Threading.Mutex($false, "Local\OzkurtHukukDevOfficeLists")
$locked = $false
try {
    $locked = $mutex.WaitOne(0)
    if (-not $locked) { exit 0 }
    $projectPath = Split-Path -Parent $PSScriptRoot
    $pythonPath = Join-Path $projectPath ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $pythonPath)) { exit 1 }
    Set-Location -LiteralPath $projectPath
    $env:DJANGO_SETTINGS_MODULE = "config.settings.dev"
    & $pythonPath -c "import django; django.setup(); from django.db import connection; d=connection.settings_dict; assert d['NAME']=='ozkurt' and d['USER']=='ozkurt' and d['HOST'] in ('localhost','127.0.0.1') and str(d['PORT'])=='5434'"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $pythonPath manage.py refresh_office_lists --watch
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
