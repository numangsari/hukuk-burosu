<#
  Kurulum/güncelleme sonrası çalışır (Inno Setup [Run]). Tekrar çalıştırılması güvenlidir.
  - İlk kurulumda: .env (gizli anahtarlar), PostgreSQL veri klasörü ve servisi, veritabanı,
    ofis kullanıcıları ve servis ayarları.
  - Her çalıştırmada: migrate, collectstatic, uygulama servisi, güvenlik duvarı kuralı,
    zamanlanmış yedek ve hatırlatma görevleri, istemci kısayolu, sağlık kontrolü.
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
$PgService = "HukukBuroDB"
if (-not (Get-Service $PgService -ErrorAction SilentlyContinue) -and (Get-Service "OzkurtHukukDB" -ErrorAction SilentlyContinue)) {
    $PgService = "OzkurtHukukDB"
}
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
    $dbUser = "hukuk"
    $dbName = "hukuk"
    # Sunucuya girilebilecek adresler: yerel adlar, bilgisayar adı (Türkçe karakter punycode'a
    # çevrilir) ve özel ağdaki IPv4 adresleri. Sonradan Ayarlar > Erişim adreslerinden eklenir.
    $hostNames = @("localhost", "127.0.0.1")
    try { $hostNames += [System.Globalization.IdnMapping]::new().GetAscii($env:COMPUTERNAME).ToLower() } catch {}
    $hostNames += @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
        ForEach-Object { $_.IPAddress })
    $allowedHosts = ($hostNames | Select-Object -Unique) -join ","
    @(
        "DJANGO_SETTINGS_MODULE=config.settings.prod"
        "DJANGO_SECRET_KEY=$(New-Secret 60)"
        "DJANGO_ALLOWED_HOSTS=$allowedHosts"
        "DATABASE_URL=postgres://$($dbUser):$dbPass@127.0.0.1:$Port/$dbName"
        "MEDIA_ROOT=$Data\media"
        "STATIC_ROOT=$App\staticfiles"
        "LOG_FILE=$InstallDir\logs\app.log"
        "BACKUP_DIR=$Data\backups"
        "PG_DUMP=$Pg\pg_dump.exe"
        "PG_RESTORE=$Pg\pg_restore.exe"
    ) | Set-Content -Encoding utf8 $Env
    # .env yalnızca Administrators ve SYSTEM tarafından okunabilir
    icacls $Env /inheritance:r /grant:r "*S-1-5-32-544:F" "*S-1-5-18:F" | Out-Null

} else {
    $dbUrlLine = (Get-Content $Env | Where-Object { $_ -like "DATABASE_URL=*" })
    $dbPass = ($dbUrlLine -replace '^.*://[^:]+:([^@]+)@.*$', '$1')
    $dbUser = ($dbUrlLine -replace '^.*://([^:]+):.*$', '$1')
    $dbName = ($dbUrlLine -replace '^.*/([^/?]+).*$', '$1')
}

# 2) PostgreSQL veri klasörü ve servisi
if (-not (Test-Path (Join-Path $PgData "PG_VERSION"))) {
    $pw = Join-Path $env:TEMP "db-pw.txt"
    Set-Content -Encoding ascii -NoNewline $pw $dbPass
    try {
        Invoke-Checked "$Pg\initdb.exe" @("-D", $PgData, "-U", $dbUser, "--pwfile=$pw", "-E", "UTF8",
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
$exists = & "$Pg\psql.exe" -h 127.0.0.1 -p $Port -U $dbUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$dbName'"
if ($exists -ne "1") { Invoke-Checked "$Pg\createdb.exe" @("-h", "127.0.0.1", "-p", "$Port", "-U", $dbUser, $dbName) }
Remove-Item Env:\PGPASSWORD

# 3) Veritabanı şeması, statik dosyalar, kullanıcılar
Invoke-Checked $Manage @("migrate", "--noinput")
Invoke-Checked $Manage @("collectstatic", "--noinput")
# Yeni kurulumda ilk yönetici tarayıcıdaki İlk Kurulum ekranında oluşturulur.

# 4) Uygulama servisi (WinSW)
$appSvcName = "HukukBuroApp"
$svc = Join-Path $InstallDir "tools\HukukBuroApp.exe"
if (-not (Test-Path $svc)) {
    $svc = Join-Path $InstallDir "tools\OzkurtHukukApp.exe"
    $appSvcName = "OzkurtHukukApp"
}
if (-not (Get-Service $appSvcName -ErrorAction SilentlyContinue)) { Invoke-Checked $svc @("install") }
& $svc restart | Out-Null

# 5) Güvenlik duvarı: yalnızca özel (ofis) ağdan 80 numaralı port
$fwName = "Hukuk Buro Yonetimi"
if (-not (Get-NetFirewallRule -DisplayName $fwName -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -DisplayName $fwName -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow -Profile Private, Domain | Out-Null
}

# 6) Yedek görevi: 30 dakikada bir kontrol eder, ayarlanan saatte (veya PC açılınca) günde bir kez yedekler
$action = New-ScheduledTaskAction -Execute $Manage -Argument "backup --scheduled"
$triggers = @(
    (New-ScheduledTaskTrigger -AtStartup),
    (New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 30))
)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName "Hukuk Buro Yedek" -Action $action -Trigger $triggers -Settings $settings `
    -User "SYSTEM" -RunLevel Highest -Force | Out-Null

# Eski zamanlanmış görevlerin temizliği
Unregister-ScheduledTask -TaskName "Ozkurt Hukuk Yedek" -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "Ozkurt Hukuk Hatirlatma" -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "Hukuk Buro Hatirlatma" -Confirm:$false -ErrorAction SilentlyContinue

# Haciz yenileme günleri, sayfa açık olmasa da beş dakikada bir denetlenir.
$seizureScript = Join-Path $InstallDir "tools\check-reminders.ps1"
$seizureArguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$seizureScript`""
$seizureAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $seizureArguments
$seizureTriggers = @(
    (New-ScheduledTaskTrigger -AtStartup),
    (New-ScheduledTaskTrigger -Once -At (Get-Date).Date -RepetitionInterval (New-TimeSpan -Minutes 5))
)
$seizureSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "Hukuk Buro Haciz Takibi" -Action $seizureAction `
    -Trigger $seizureTriggers -Settings $seizureSettings -User "SYSTEM" -RunLevel Highest -Force | Out-Null
Unregister-ScheduledTask -TaskName "Ozkurt Hukuk Haciz Takibi" -Confirm:$false -ErrorAction SilentlyContinue

# Ofis klasöründeki görüntüleme tabloları düzenli güncellenir.
$listScript = Join-Path $InstallDir "tools\check-office-lists.ps1"
$listArguments = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$listScript`""
$listAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $listArguments
$listTriggers = @(
    (New-ScheduledTaskTrigger -AtStartup),
    (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1))
)
$listSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "Hukuk Buro Listeler" -Action $listAction `
    -Trigger $listTriggers -Settings $listSettings -User "SYSTEM" -RunLevel Highest -Force | Out-Null
Unregister-ScheduledTask -TaskName "Ozkurt Hukuk Listeler" -Confirm:$false -ErrorAction SilentlyContinue

# 7) İstemci kısayolu (diğer PC'lerin masaüstüne kopyalanacak)
$url = "http://$($env:COMPUTERNAME)/"
$shortcut = "[InternetShortcut]`r`nURL=$url`r`n"
Set-Content -Encoding ascii (Join-Path $InstallDir "Hukuk Buro Yonetimi.url") $shortcut
Set-Content -Encoding ascii (Join-Path ([Environment]::GetFolderPath("CommonDesktopDirectory")) "Hukuk Buro Yonetimi.url") $shortcut

# 8) Sağlık kontrolü
$ok = $false
for ($i = 0; $i -lt 30 -and -not $ok; $i++) {
    try { $ok = (Invoke-WebRequest "http://localhost/" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200 } catch { Start-Sleep 2 }
}
if (-not $ok) { throw "Uygulama yanıt vermiyor. Ayrıntı: $InstallDir\logs" }
Write-Host "Kurulum tamamlandı. Adres: $url"
Stop-Transcript | Out-Null
