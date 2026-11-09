<#
  Kurulum/güncelleme sonrası çalışır (Inno Setup [Run]). Tekrar çalıştırılması güvenlidir.
  - İlk kurulumda: .env (gizli anahtarlar), PostgreSQL veri klasörü ve servisi, veritabanı,
    ofis kullanıcıları ve servis ayarları.
  - Her çalıştırmada: migrate, collectstatic, uygulama servisi, güvenlik duvarı kuralı,
    zamanlanmış yedek ve hatırlatma görevleri, istemci kısayolu, sağlık kontrolü.
#>
param(
    [Parameter(Mandatory = $true)][string]$InstallDir,
    # Eski kurulum paketleriyle uyum için kabul edilir, kullanılmaz (ilk yönetici İlk Kurulum ekranında).
    [string]$Pin = "",
    # Otomatik güncelleyici (updater.ps1) kullanır: uygulama servisi başlatılmaz, port 80'deki
    # bakım sayfası açık kalır; servisi ve sağlık kontrolünü güncelleyici yapar.
    [switch]$DeferAppStart,
    # Veri kökü: veritabanı, belgeler, yedekler, güncellemeler ve kayıtlar. Varsayılan
    # C:\ProgramData\HukukBurosu; eski düzende (InstallDir\data\pgdata varsa) InstallDir\data.
    [string]$DataDir = ""
)
$ErrorActionPreference = "Stop"
if (-not $DataDir) {
    $DataDir = Join-Path $env:ProgramData "HukukBurosu"
    if (Test-Path (Join-Path $InstallDir "data\pgdata\PG_VERSION")) { $DataDir = Join-Path $InstallDir "data" }
}
$Data = $DataDir
$Legacy = $Data -eq (Join-Path $InstallDir "data")
$Logs = if ($Legacy) { Join-Path $InstallDir "logs" } else { Join-Path $Data "logs" }
$App = Join-Path $InstallDir "app"
$Env = Join-Path $App ".env"

$Admins = "*S-1-5-32-544"; $System = "*S-1-5-18"; $Users = "*S-1-5-32-545"; $NetworkService = "*S-1-5-20"
# Kökün izni değiştirilir, alt öğeler miras alır. -Recurse önce alt öğelerdeki açık izinleri siler
# (/reset). Dikkat: "/grant:r ... /T" kullanılmaz; (OI)(CI) bayraklı izinler dosyalara uygulanamaz ve
# dosyalar izinsiz (kimse açamaz) kalır.
function Set-FolderAcl([string]$Path, [string[]]$Grants, [switch]$Recurse) {
    if ($Recurse) {
        icacls $Path /reset /T /C /Q | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "İzinler sıfırlanamadı: $Path" }
    }
    $icaclsArgs = @($Path, "/inheritance:r", "/grant:r") + $Grants + @("/C", "/Q")
    icacls @icaclsArgs | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "İzinler ayarlanamadı: $Path" }
}

# 0) Veri kökü, içine hiçbir dosya (kurulum günlüğü dahil) yazılmadan önce güvenli hale getirilir.
# ProgramData'da sıradan kullanıcılar klasör açabilir; ilk kurulumdan önce açılmış bir HukukBurosu
# klasörüne (sahte veritabanı, bağlantı/junction) güvenilmez.
$movedAside = ""
if (-not $Legacy) {
    foreach ($p in @($env:ProgramData, $Data)) {
        if ((Test-Path $p) -and ((Get-Item $p -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Veri yolu bir bağlantı (reparse point), kurulum durduruldu: $p"
        }
    }
    if (-not (Test-Path $Env) -and (Test-Path $Data)) {
        # İlk kurulum (.env yok) ama veri klasörü var: silinmez, kenara alınır; sıfırdan açılır.
        $movedAside = "$Data.onceki-$(Get-Date -Format yyyyMMdd-HHmmss)"
        Rename-Item -Path $Data -NewName (Split-Path $movedAside -Leaf)
    }
    New-Item -ItemType Directory -Force $Data | Out-Null
    icacls $Data /setowner $Admins /C /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Veri klasörünün sahipliği ayarlanamadı: $Data" }
    Set-FolderAcl $Data @("$($Admins):(OI)(CI)F", "$($System):(OI)(CI)F")
    # Kök artık yalnızca yöneticilere açık; mevcut ağaç sahiplik ve açık izinlerden arındırılır.
    # pgdata'nın NetworkService izni aşağıda yeniden verilir (veritabanı servisi bu sırada durdurulmuştur).
    icacls $Data /setowner $Admins /T /C /Q | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Veri klasörünün sahipliği ayarlanamadı: $Data" }
    Set-FolderAcl $Data @("$($Admins):(OI)(CI)F", "$($System):(OI)(CI)F") -Recurse
}
New-Item -ItemType Directory -Force $Logs | Out-Null
Start-Transcript -Path (Join-Path $Logs "kurulum.log") -Append | Out-Null
if ($movedAside) { Write-Warning "Önceden var olan veri klasörü kenara alındı: $movedAside" }

$Pg = Join-Path $InstallDir "pgsql\bin"
$PgData = Join-Path $Data "pgdata"
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

foreach ($d in @($Data, "$Data\media", "$Data\backups", "$Data\updates", $Logs)) {
    New-Item -ItemType Directory -Force $d | Out-Null
}

# Program klasörü: SYSTEM olarak çalışan kod (uygulama, Python, PostgreSQL, betikler, eklenti) yalnızca
# yöneticilerce değiştirilebilir, herkes okuyabilir. Program Files zaten böyledir; eski düzendeki
# C:\HukukBurosu ise "Authenticated Users: Modify" miras aldığından açıkça daraltılır.
foreach ($d in @("app", "python", "tools", "eklenti", "pgsql")) {
    $path = Join-Path $InstallDir $d
    if (Test-Path $path) { Set-FolderAcl $path @("$($Admins):(OI)(CI)F", "$($System):(OI)(CI)F", "$($Users):(OI)(CI)RX") -Recurse }
}
# Veri kökünün izinleri yukarıda (0. adım) ayarlandı.
Set-FolderAcl "$Data\updates" @("$($Admins):(OI)(CI)F", "$($System):(OI)(CI)F") -Recurse
# .env, app klasörüne verilen okuma izninden ayrı tutulur: yalnızca Administrators ve SYSTEM.
if (Test-Path $Env) { Set-FolderAcl $Env @("$($Admins):F", "$($System):F") }

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
    $envLines = @(
        "DJANGO_SETTINGS_MODULE=config.settings.prod"
        "DJANGO_SECRET_KEY=$(New-Secret 60)"
        "DJANGO_ALLOWED_HOSTS=$allowedHosts"
        "DATABASE_URL=postgres://$($dbUser):$dbPass@127.0.0.1:$Port/$dbName"
        "DATA_DIR=$Data"
        "MEDIA_ROOT=$Data\media"
        "STATIC_ROOT=$App\staticfiles"
        "LOG_FILE=$Logs\app.log"
        "BACKUP_DIR=$Data\backups"
        "PG_DUMP=$Pg\pg_dump.exe"
        "PG_RESTORE=$Pg\pg_restore.exe"
    )
    # BOM'suz UTF-8: PowerShell 5.1'in "-Encoding utf8"i BOM ekler, .env okuyucusu ilk satırı geçersiz sayar
    [System.IO.File]::WriteAllLines($Env, [string[]]$envLines, (New-Object System.Text.UTF8Encoding $false))
    # .env yalnızca Administrators ve SYSTEM tarafından okunabilir
    Set-FolderAcl $Env @("$($Admins):F", "$($System):F")

} else {
    # Eski .env'de DATA_DIR yoksa eklenir (uygulama güncelleme durumunu buradan bulur).
    if (-not (Get-Content $Env | Where-Object { $_ -like "DATA_DIR=*" })) {
        [System.IO.File]::AppendAllText($Env, "`r`nDATA_DIR=$Data`r`n", (New-Object System.Text.UTF8Encoding $false))
    }
    $dbUrlLine = (Get-Content $Env | Where-Object { $_ -like "DATABASE_URL=*" })
    $dbPass = ($dbUrlLine -replace '^.*://[^:]+:([^@]+)@.*$', '$1')
    $dbUser = ($dbUrlLine -replace '^.*://([^:]+):.*$', '$1')
    $dbName = ($dbUrlLine -replace '^.*/([^/?]+).*$', '$1')
}

# 2) PostgreSQL veri klasörü ve servisi
if (-not (Test-Path (Join-Path $PgData "PG_VERSION"))) {
    # initdb yönetici yetkisini bırakarak (Administrators grubu devre dışı) çalışır; boş veri klasörü
    # önceden açılıp kurulumu çalıştıran hesaba açık izin verilir.
    New-Item -ItemType Directory -Force $PgData | Out-Null
    $me = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    icacls $PgData /grant "*$($me):(OI)(CI)F" "$($NetworkService):(OI)(CI)M" /C /Q | Out-Null
    $pw = Join-Path $env:TEMP "db-pw.txt"
    # Parametreler adlı verilmeli: PowerShell 5.1'de -NoNewline ile konumsal kullanımda
    # yol ve değer yer değiştirir (dosya adı parola olur, db-pw.txt oluşmaz).
    Set-Content -Encoding ascii -NoNewline -Path $pw -Value $dbPass
    try {
        Invoke-Checked "$Pg\initdb.exe" @("-D", $PgData, "-U", $dbUser, "--pwfile=$pw", "-E", "UTF8",
            "--auth=scram-sha-256", "--locale-provider=icu", "--icu-locale=tr-TR", "--locale=C")
    } finally { Remove-Item $pw -Force -ErrorAction SilentlyContinue }
    # Yalnızca bu bilgisayardan bağlantı
    Add-Content -Encoding ascii (Join-Path $PgData "postgresql.conf") "`nlisten_addresses = '127.0.0.1'`nport = $Port`n"
}
# Veritabanı servisi NetworkService hesabıyla çalışır; veri klasörü kökü ona kapalı olduğundan
# pgdata'ya açıkça yazma izni verilir.
icacls $PgData /grant "$($NetworkService):(OI)(CI)M" /C /Q | Out-Null
if ($LASTEXITCODE -ne 0) { throw "pgdata izinleri ayarlanamadı." }
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
if ($DeferAppStart) { & $svc stop | Out-Null } else { & $svc restart | Out-Null }

# 5) Güvenlik duvarı: yalnızca özel (ofis) ağdan 80 numaralı port
# Kural eklenemezse (ör. Windows Sandbox'ta güvenlik duvarı arayüzü yok) kurulum durmaz; yalnızca
# diğer bilgisayarlardan erişim için kuralın elle eklenmesi gerekir.
$fwName = "Hukuk Buro Yonetimi"
try {
    if (-not (Get-NetFirewallRule -DisplayName $fwName -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $fwName -Direction Inbound -Protocol TCP -LocalPort 80 -Action Allow -Profile Private, Domain | Out-Null
    }
} catch {
    Write-Warning "Guvenlik duvari kurali eklenemedi (port 80): $($_.Exception.Message)"
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

# Otomatik güncelleme: günde bir yeni sürüm denetlenip indirilir, açılışta kurulur (updater.ps1).
$updaterScript = Join-Path $InstallDir "tools\updater.ps1"
$updaterBase = "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$updaterScript`""
$checkAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "$updaterBase -Mode Check"
$checkSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "Hukuk Buro Guncelleme Kontrol" -Action $checkAction `
    -Trigger (New-ScheduledTaskTrigger -Daily -At "12:00") -Settings $checkSettings `
    -User "SYSTEM" -RunLevel Highest -Force | Out-Null
# Kurulumu yapan görev güncelleyici tarafından çalıştırılırken yeniden kaydedilmez.
if (-not $DeferAppStart) {
    $applyAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "$updaterBase -Mode Apply"
    $applySettings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew -Priority 4
    Register-ScheduledTask -TaskName "Hukuk Buro Guncelleme" -Action $applyAction `
        -Trigger (New-ScheduledTaskTrigger -AtStartup) -Settings $applySettings `
        -User "SYSTEM" -RunLevel Highest -Force | Out-Null
}

# 7) İstemci kısayolu (diğer PC'lerin masaüstüne kopyalanacak)
$url = "http://$($env:COMPUTERNAME)/"
$shortcut = "[InternetShortcut]`r`nURL=$url`r`n"
# Ad "Hukuk Bürosu Otomasyonu"; betik BOM'suz UTF-8 olduğundan Türkçe harfler kodla yazılır.
$shortcutName = "Hukuk B$([char]0x00FC)rosu Otomasyonu.url"
$desktop = [Environment]::GetFolderPath("CommonDesktopDirectory")
# Eski adlar; "Büroşu" eski sürümlerdeki yazım hatasıdır.
foreach ($old in @("Hukuk Buro Yonetimi.url", "Ozkurt Hukuk.url", "Hukuk B$([char]0x00FC)ro$([char]0x015F)u Otomasyonu.url")) {
    Remove-Item (Join-Path $InstallDir $old) -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $desktop $old) -ErrorAction SilentlyContinue
}
Set-Content -Encoding ascii (Join-Path $InstallDir $shortcutName) $shortcut
Set-Content -Encoding ascii (Join-Path $desktop $shortcutName) $shortcut

# 8) Sağlık kontrolü (güncelleyici çalıştırıyorsa kontrolü o yapar)
if ($DeferAppStart) {
    Write-Host "Kurulum tamamlandı; uygulama servisini güncelleyici başlatacak."
    Stop-Transcript | Out-Null
    exit 0
}
$ok = $false
for ($i = 0; $i -lt 30 -and -not $ok; $i++) {
    try { $ok = (Invoke-WebRequest "http://localhost/" -UseBasicParsing -TimeoutSec 5).StatusCode -eq 200 } catch { Start-Sleep 2 }
}
if (-not $ok) { throw "Uygulama yanıt vermiyor. Ayrıntı: $Logs" }
Write-Host "Kurulum tamamlandı. Adres: $url"
Stop-Transcript | Out-Null
