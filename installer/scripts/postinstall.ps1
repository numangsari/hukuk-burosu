<#
  Kurulum/güncelleme sonrası çalışır (Inno Setup [Run]). Tekrar çalıştırılması güvenlidir.
  - İlk kurulumda: .env (gizli anahtarlar), PostgreSQL veri klasörü ve servisi, veritabanı,
    ofis kullanıcıları, yedek parolası dosyası.
  - Her çalıştırmada: migrate, collectstatic, uygulama servisi, güvenlik duvarı kuralı,
    zamanlanmış yedek görevi, istemci kısayolu, sağlık kontrolü.
#>
param(
    [Parameter(Mandatory = $true)][string]$InstallDir,
    [string]$Pin = ""
)
$ErrorActionPreference = "Stop"
$log = Join-Path $InstallDir "logs\kurulum.log"
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
Start-Transcript -Path $log -Append | Out-Null

$App = Join-Path $InstallDir "app"
$Pg = Join-Path $InstallDir "pgsql\bin"
$Data = Join-Path $InstallDir "data"
$PgData = Join-Path $Data "pgdata"
$Env = Join-Path $App ".env"
$Manage = Join-Path $InstallDir "tools\manage.cmd"
$PgService = "OzkurtHukukDB"
$Port = 5432

function New-Secret([int]$Length = 40) {
    $chars = [char[]]"ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    $bytes = New-Object byte[] $Length
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}

function Invoke-Checked([string]$File, [string[]]$Arguments) {
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Komut başarısız ($LASTEXITCODE): $File $($Arguments -join ' ')" }
}

foreach ($d in @($Data, "$Data\media", "$Data\backups", (Join-Path $InstallDir "logs"))) {
    New-Item -ItemType Directory -Force $d | Out-Null
}

# 1) .env — yalnızca ilk kurulumda üretilir, güncellemede korunur
$firstInstall = -not (Test-Path $Env)
if ($firstInstall) {
    $dbPass = New-Secret 32
    $backupPass = New-Secret 24
    @(
        "DJANGO_SETTINGS_MODULE=config.settings.prod"
        "DJANGO_SECRET_KEY=$(New-Secret 60)"
        "DJANGO_ALLOWED_HOSTS=*"
        "DATABASE_URL=postgres://ozkurt:$dbPass@127.0.0.1:$Port/ozkurt"
        "MEDIA_ROOT=$Data\media"
        "STATIC_ROOT=$App\staticfiles"
        "LOG_FILE=$InstallDir\logs\app.log"
        "BACKUP_PASSWORD=$backupPass"
        "BACKUP_DIR=$Data\backups"
        "PG_DUMP=$Pg\pg_dump.exe"
        "PG_RESTORE=$Pg\pg_restore.exe"
    ) | Set-Content -Encoding utf8 $Env
    # .env yalnızca Administrators ve SYSTEM tarafından okunabilir
    icacls $Env /inheritance:r /grant:r "*S-1-5-32-544:F" "*S-1-5-18:F" | Out-Null

    # Yedek parolası kullanıcıya bir kez gösterilir; güvenli yerde saklanıp dosya silinmeli.
    $note = Join-Path ([Environment]::GetFolderPath("CommonDesktopDirectory")) "Ozkurt Hukuk - YEDEK PAROLASI.txt"
    @(
        "Özkurt Hukuk yedek dosyalarının şifresi:"
        ""
        "    $backupPass"
        ""
        "Bu parola olmadan yedekler AÇILAMAZ. Parolayı kâğıda yazıp kasada veya bir parola"
        "yöneticisinde saklayın, ardından BU DOSYAYI SİLİN."
    ) | Set-Content -Encoding utf8 $note
} else {
    $dbPass = ((Get-Content $Env | Where-Object { $_ -like "DATABASE_URL=*" }) -replace '^.*://ozkurt:([^@]+)@.*$', '$1')
}

# 2) PostgreSQL veri klasörü ve servisi
if (-not (Test-Path (Join-Path $PgData "PG_VERSION"))) {
    $pw = Join-Path $env:TEMP "ozk-pw.txt"
    Set-Content -Encoding ascii -NoNewline $pw $dbPass
    try {
        Invoke-Checked "$Pg\initdb.exe" @("-D", $PgData, "-U", "ozkurt", "--pwfile=$pw", "-E", "UTF8",
            "--auth=scram-sha-256", "--locale-provider=icu", "--icu-locale=tr-TR", "--locale=C")
    } finally { Remove-Item $pw -Force -ErrorAction SilentlyContinue }
    # Yalnızca bu bilgisayardan bağlantı
    Add-Content -Encoding ascii (Join-Path $PgData "postgresql.conf") "`nlisten_addresses = '127.0.0.1'`nport = $Port`n"
}
if (-not (Get-Service $PgService -ErrorAction SilentlyContinue)) {
    Invoke-Checked "$Pg\pg_ctl.exe" @("register", "-N", $PgService, "-D", $PgData, "-S", "auto")
}
Start-Service $PgService
for ($i = 0; $i -lt 30; $i++) {
    & "$Pg\pg_isready.exe" -h 127.0.0.1 -p $Port | Out-Null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 1
}
$env:PGPASSWORD = $dbPass
$exists = & "$Pg\psql.exe" -h 127.0.0.1 -p $Port -U ozkurt -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='ozkurt'"
if ($exists -ne "1") { Invoke-Checked "$Pg\createdb.exe" @("-h", "127.0.0.1", "-p", "$Port", "-U", "ozkurt", "ozkurt") }
Remove-Item Env:\PGPASSWORD

# 3) Veritabanı şeması, statik dosyalar, kullanıcılar
Invoke-Checked $Manage @("migrate", "--noinput")
Invoke-Checked $Manage @("collectstatic", "--noinput")
if ($firstInstall -and $Pin) { Invoke-Checked $Manage @("setup_office_users", "--pin", $Pin) }

# 4) Uygulama servisi (WinSW)
$svc = Join-Path $InstallDir "tools\OzkurtHukukApp.exe"
if (-not (Get-Service "OzkurtHukukApp" -ErrorAction SilentlyContinue)) { Invoke-Checked $svc @("install") }
& $svc restart | Out-Null

# 5) Güvenlik duvarı: yalnızca özel (ofis) ağdan 80 numaralı port
if (-not (Get-NetFirewallRule -DisplayName "Ozkurt Hukuk" -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName "Ozkurt Hukuk" -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow -Profile Private, Domain | Out-Null
}

# 6) Yedek görevi: 30 dakikada bir kontrol eder, ayarlanan saatte (veya PC açılınca) günde bir kez yedekler
$action = New-ScheduledTaskAction -Execute $Manage -Argument "backup --scheduled"
$triggers = @(
    (New-ScheduledTaskTrigger -AtStartup),
    (New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 30))
)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName "Ozkurt Hukuk Yedek" -Action $action -Trigger $triggers -Settings $settings `
    -User "SYSTEM" -RunLevel Highest -Force | Out-Null

# 7) İstemci kısayolu (diğer PC'lerin masaüstüne kopyalanacak)
$url = "http://$($env:COMPUTERNAME)/"
$shortcut = "[InternetShortcut]`r`nURL=$url`r`n"
Set-Content -Encoding ascii (Join-Path $InstallDir "Ozkurt Hukuk.url") $shortcut
Set-Content -Encoding ascii (Join-Path ([Environment]::GetFolderPath("CommonDesktopDirectory")) "Ozkurt Hukuk.url") $shortcut

# 8) Sağlık kontrolü
$ok = $false
for ($i = 0; $i -lt 30 -and -not $ok; $i++) {
    try { $ok = (Invoke-WebRequest "http://localhost/hesap/giris/" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200 } catch { Start-Sleep 2 }
}
if (-not $ok) { throw "Uygulama yanıt vermiyor. Ayrıntı: $InstallDir\logs" }
Write-Host "Kurulum tamamlandı. Adres: $url"
Stop-Transcript | Out-Null
