# Oturum açıkken geliştirme yedeğini düzenli denetler; ikinci kopyayı başlatmaz.
$mutex = New-Object System.Threading.Mutex($false, "Local\OzkurtHukukDevBackup")
$locked = $false
try {
    $locked = $mutex.WaitOne(0)
    if (-not $locked) { exit 0 }
    $scriptPath = Join-Path $PSScriptRoot "dev-backup.ps1"
    while ($true) {
        try { & $scriptPath } catch { }
        Start-Sleep -Seconds 1800
    }
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
