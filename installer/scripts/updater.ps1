<#
  Otomatik guncelleyici.

  -Mode Check  (gunde bir, "Hukuk Buro Guncelleme Kontrol" gorevi):
      Ayri public releases reposunda son surume bakar. Kurulu surumden yeniyse ve daha once
      basarisiz olmadiysa kurulum dosyasini indirir, SHA256 ile dogrular, data\updates\pending.json
      yazar. Kurulum yapmaz.

  -Mode Apply  (bilgisayar acilisinda, "Hukuk Buro Guncelleme" gorevi):
      Bekleyen surum varsa: uygulama servisini durdurur, app/python/tools klasorlerinin ve
      veritabaninin anlik kopyasini alir, port 80'de "Guncelleniyor" sayfasi acar, kurulumu sessiz
      calistirir, servisi baslatip /saglik/ ile yeni surumu dogrular. Herhangi bir adim basarisiz
      olursa klasorleri ve veritabanini anlik kopyadan geri yukler, onceki surumle devam eder ve
      surumu bad-versions.txt'ye yazar (daha yeni surum cikana kadar tekrar denenmez).

  Sonuc data\updates\status.json'a yazilir (Ayarlar > Hakkinda), ayrinti logs\guncelleme.log.
  Betik BOM'suz UTF-8'dir; PowerShell 5.1 uyumu icin metinler ASCII yazilir.
#>
param(
    [Parameter(Mandatory = $true)][ValidateSet("Check", "Apply")][string]$Mode,
    [string]$InstallDir = (Split-Path $PSScriptRoot -Parent),
    [string]$Repo = "numangsari/hukuk-burosu-releases",
    [string]$ApiBase = "https://api.github.com",
    [int]$HealthTimeoutSec = 240,
    [switch]$Relaunched
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Updates = Join-Path $InstallDir "data\updates"
$PendingFile = Join-Path $Updates "pending.json"
$StatusFile = Join-Path $Updates "status.json"
$BadFile = Join-Path $Updates "bad-versions.txt"
$LockFile = Join-Path $Updates "applying.lock"
$Snapshot = Join-Path $Updates "rollback"
$DownloadDir = Join-Path $Updates "indirilen"
$LogFile = Join-Path $InstallDir "logs\guncelleme.log"
$Pg = Join-Path $InstallDir "pgsql\bin"
$AssetPrefix = "HukukBurosuOtomasyonu-Kurulum-"
$UserAgent = @{ "User-Agent" = "HukukBurosuUpdater" }
# Guncelleme sirasinda veritabanina dokunan zamanlanmis gorevler durdurulur.
$QuietTasks = @(
    "Hukuk Buro Yedek", "Hukuk Buro Haciz Takibi", "Hukuk Buro Listeler",
    "Ozkurt Hukuk Yedek", "Ozkurt Hukuk Haciz Takibi", "Ozkurt Hukuk Listeler"
)
$SnapshotDirs = @("app", "python", "tools")

function Write-Log([string]$Message) {
    New-Item -ItemType Directory -Force (Split-Path $LogFile) | Out-Null
    Add-Content -Path $LogFile -Value "$(Get-Date -Format s) [$Mode] $Message" -Encoding utf8
}

function Write-TextNoBom([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding $false))
}

function Initialize-UpdateDir {
    if (-not (Test-Path $Updates)) {
        New-Item -ItemType Directory -Force $Updates | Out-Null
        # Anlik kopya .env ve tum veritabanini icerir: yalnizca Administrators ve SYSTEM.
        if ([Security.Principal.WindowsIdentity]::GetCurrent().IsSystem) {
            icacls $Updates /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" | Out-Null
        }
    }
}

function Save-Status([string]$Result, [string]$Version, [string]$FromVersion, [string]$Message = "") {
    $status = [ordered]@{
        result       = $Result
        version      = $Version
        from_version = $FromVersion
        at           = (Get-Date).ToString("o")
        message      = $Message
    }
    Write-TextNoBom $StatusFile ($status | ConvertTo-Json)
}

function ConvertTo-AppVersion([string]$Text) {
    $parsed = $null
    if ([version]::TryParse("$Text".Trim().TrimStart("v", "V"), [ref]$parsed)) { return $parsed }
    return $null
}

function Get-InstalledVersion {
    $file = Join-Path $InstallDir "app\VERSION"
    if (Test-Path $file) {
        $parsed = ConvertTo-AppVersion (Get-Content $file -Raw)
        if ($parsed) { return $parsed }
    }
    return [version]"0.0.0"
}

function Test-BadVersion([string]$Version) {
    return (Test-Path $BadFile) -and (@(Get-Content $BadFile) -contains $Version)
}

function Add-BadVersion([string]$Version) {
    if (-not (Test-BadVersion $Version)) { Add-Content -Path $BadFile -Value $Version -Encoding ascii }
}

function Get-Sha256([string]$Path) {
    return (Get-FileHash -Algorithm SHA256 -Path $Path).Hash.ToLowerInvariant()
}

function Read-Pending {
    if (-not (Test-Path $PendingFile)) { return $null }
    try { return (Get-Content $PendingFile -Raw | ConvertFrom-Json) } catch { return $null }
}

function Test-PendingValid($Pending) {
    return $Pending -and $Pending.file -and (Test-Path $Pending.file) -and
        ((Get-Sha256 $Pending.file) -eq $Pending.sha256)
}

function Remove-Pending {
    $pending = Read-Pending
    if ($pending -and $pending.file) { Remove-Item $pending.file -Force -ErrorAction SilentlyContinue }
    Remove-Item $PendingFile -Force -ErrorAction SilentlyContinue
}

# ---------------------------------------------------------------- Check

function Invoke-Check {
    if (Test-Path $LockFile) { Write-Log "Kurulum suruyor; kontrol atlandi."; return }
    $current = Get-InstalledVersion
    $release = Invoke-RestMethod -Uri "$ApiBase/repos/$Repo/releases/latest" -Headers $UserAgent -TimeoutSec 30
    $latest = ConvertTo-AppVersion $release.tag_name
    if (-not $latest) { throw "Gecersiz surum etiketi: $($release.tag_name)" }
    $version = $latest.ToString()
    if ($latest -le $current) { Write-Log "Guncel (kurulu $current, son $version)."; return }
    if (Test-BadVersion $version) { Write-Log "$version daha once basarisiz oldu; atlandi."; return }
    $pending = Read-Pending
    if ($pending -and $pending.version -eq $version -and (Test-PendingValid $pending)) {
        Write-Log "$version zaten indirilmis; acilista kurulacak."
        return
    }

    $exeName = "$AssetPrefix$version.exe"
    $exeAsset = @($release.assets | Where-Object { $_.name -eq $exeName })[0]
    $shaAsset = @($release.assets | Where-Object { $_.name -eq "$exeName.sha256" })[0]
    if (-not $exeAsset -or -not $shaAsset) { throw "Surumde $exeName veya .sha256 dosyasi yok." }

    New-Item -ItemType Directory -Force $DownloadDir | Out-Null
    $shaPath = Join-Path $DownloadDir "$exeName.sha256"
    $partPath = Join-Path $DownloadDir "$exeName.part"
    $exePath = Join-Path $DownloadDir $exeName
    Invoke-WebRequest -Uri $shaAsset.browser_download_url -Headers $UserAgent -OutFile $shaPath -UseBasicParsing -TimeoutSec 60
    $expected = ((Get-Content $shaPath -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
    if ($expected -notmatch '^[0-9a-f]{64}$') { throw "Gecersiz SHA256 dosyasi." }
    Invoke-WebRequest -Uri $exeAsset.browser_download_url -Headers $UserAgent -OutFile $partPath -UseBasicParsing -TimeoutSec 1800
    if ((Get-Sha256 $partPath) -ne $expected) {
        Remove-Item $partPath, $shaPath -Force
        throw "SHA256 uyusmuyor; indirilen dosya silindi."
    }
    Remove-Pending
    Get-ChildItem $DownloadDir -Filter "*.exe" | Remove-Item -Force
    Move-Item -Force $partPath $exePath
    Remove-Item $shaPath -Force
    $pendingData = [ordered]@{ version = $version; file = $exePath; sha256 = $expected }
    Write-TextNoBom $PendingFile ($pendingData | ConvertTo-Json)
    Save-Status "downloaded" $version $current.ToString()
    Write-Log "$version indirildi ve dogrulandi; sonraki acilista kurulacak."
}

# ---------------------------------------------------------------- Apply

function Get-ServiceName([string[]]$Names) {
    foreach ($name in $Names) { if (Get-Service $name -ErrorAction SilentlyContinue) { return $name } }
    return $Names[0]
}

function Get-DbSettings {
    $line = Get-Content (Join-Path $InstallDir "app\.env") | Where-Object { $_ -like "DATABASE_URL=*" } | Select-Object -First 1
    if ($line -notmatch '^DATABASE_URL=\w+://([^:]+):([^@]+)@([^:/]+):(\d+)/([^/?]+)') {
        throw "DATABASE_URL okunamadi."
    }
    return @{ User = $Matches[1]; Password = [uri]::UnescapeDataString($Matches[2]); Host = $Matches[3]; Port = $Matches[4]; Name = $Matches[5] }
}

function Invoke-Pg([string]$Tool, [string[]]$Arguments, $Db) {
    $env:PGPASSWORD = $Db.Password
    try {
        & (Join-Path $Pg $Tool) -h $Db.Host -p $Db.Port -U $Db.User @Arguments
        if ($LASTEXITCODE -ne 0) { throw "$Tool basarisiz ($LASTEXITCODE)." }
    } finally { Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue }
}

function Copy-Mirror([string]$From, [string]$To) {
    # /SEC: .env'nin kisitli izinleri kopyada da korunur.
    robocopy $From $To /MIR /SEC /R:2 /W:2 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "Kopyalama basarisiz ($LASTEXITCODE): $From -> $To" }
}

function Wait-Url([string]$Url, [string]$ExpectVersion) {
    $deadline = (Get-Date).AddSeconds($HealthTimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            if ($ExpectVersion) {
                $health = Invoke-RestMethod -Uri $Url -TimeoutSec 10
                if ($health.status -eq "ok" -and $health.version -eq $ExpectVersion) { return $true }
            } else {
                Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 10 | Out-Null
                return $true
            }
        } catch {}
        Start-Sleep -Seconds 3
    }
    return $false
}

function Start-Maintenance {
    $python = Join-Path $Snapshot "python\python.exe"
    $script = Join-Path $Snapshot "tools\maintenance.py"
    if (-not ((Test-Path $python) -and (Test-Path $script))) { return $null }
    return Start-Process -FilePath $python -ArgumentList @("-I", "`"$script`"", "80") -WindowStyle Hidden -PassThru
}

function Stop-Maintenance($Process) {
    if ($Process -and -not $Process.HasExited) {
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        $Process.WaitForExit(10000) | Out-Null
    }
}

function Invoke-Apply {
    $pending = Read-Pending
    if (-not $pending) { return }
    $current = Get-InstalledVersion
    $target = ConvertTo-AppVersion $pending.version
    if (-not $target -or $target -le $current -or (Test-BadVersion $pending.version) -or -not (Test-PendingValid $pending)) {
        Write-Log "Bekleyen surum gecersiz veya gereksiz ($($pending.version)); silindi."
        Remove-Pending
        return
    }
    $version = $target.ToString()
    $from = $current.ToString()
    $appService = Get-ServiceName @("HukukBuroApp", "OzkurtHukukApp")
    $dbService = Get-ServiceName @("HukukBuroDB", "OzkurtHukukDB")
    $db = Get-DbSettings
    $dump = Join-Path $Snapshot "db.dump"
    $installerStarted = $false
    $maintenance = $null
    $disabled = @()

    Write-Log "$from -> $version kurulumu basliyor."
    New-Item -ItemType File -Force $LockFile | Out-Null
    try {
        foreach ($task in $QuietTasks) {
            $t = Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
            if ($t -and $t.State -ne "Disabled") {
                Stop-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
                Disable-ScheduledTask -TaskName $task | Out-Null
                $disabled += $task
            }
        }
        try {
            Stop-Service $appService -Force -ErrorAction SilentlyContinue
            Start-Service $dbService

            # 1) Anlik kopya: klasorler ve veritabani
            New-Item -ItemType Directory -Force $Snapshot | Out-Null
            foreach ($dir in $SnapshotDirs) { Copy-Mirror (Join-Path $InstallDir $dir) (Join-Path $Snapshot $dir) }
            Remove-Item $dump -Force -ErrorAction SilentlyContinue
            Invoke-Pg "pg_dump.exe" @("-Fc", "-f", $dump, $db.Name) $db
            Write-Log "Anlik kopya alindi."

            # 2) Bakim sayfasi ve sessiz kurulum (uygulama servisini kurulum degil biz baslatiriz)
            $maintenance = Start-Maintenance
            $installerStarted = $true
            $setupLog = Join-Path $InstallDir "logs\guncelleme-kurulum-$version.log"
            $setup = Start-Process -FilePath $pending.file -Wait -PassThru -ArgumentList @(
                "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/DEFERSTART=1", "/LOG=`"$setupLog`""
            )
            if ($setup.ExitCode -ne 0) { throw "Kurulum basarisiz (cikis kodu $($setup.ExitCode)). Ayrinti: $setupLog" }

            # 3) Yeni surumu baslat ve dogrula
            Stop-Maintenance $maintenance
            Start-Service $appService
            if (-not (Wait-Url "http://127.0.0.1/saglik/" $version)) { throw "Yeni surum saglik kontrolunu gecemedi." }

            Save-Status "ok" $version $from
            Write-Log "$version kuruldu ve dogrulandi."
            Remove-Pending
            Remove-Item $Snapshot -Recurse -Force -ErrorAction SilentlyContinue
        } catch {
            $reason = $_.Exception.Message
            Write-Log "HATA: $reason"
            if (-not $installerStarted) {
                # Kuruluma gecilmedi; hicbir sey degismedi. Bekleyen surum sonraki acilista denenir.
                Start-Service $appService -ErrorAction SilentlyContinue
                Save-Status "rolled_back" $version $from $reason
                return
            }
            Add-BadVersion $version
            Remove-Pending
            try {
                if (-not $maintenance -or $maintenance.HasExited) { $maintenance = Start-Maintenance }
                Stop-Service $appService -Force -ErrorAction SilentlyContinue
                foreach ($dir in $SnapshotDirs) { Copy-Mirror (Join-Path $Snapshot $dir) (Join-Path $InstallDir $dir) }
                Start-Service $dbService
                Invoke-Pg "dropdb.exe" @("--force", "--if-exists", "--maintenance-db=postgres", $db.Name) $db
                Invoke-Pg "createdb.exe" @($db.Name) $db
                Invoke-Pg "pg_restore.exe" @("--no-owner", "-d", $db.Name, $dump) $db
                Stop-Maintenance $maintenance
                Start-Service $appService
                if (-not (Wait-Url "http://127.0.0.1/" "")) { throw "Onceki surum de yanit vermiyor." }
                Save-Status "rolled_back" $version $from $reason
                Write-Log "Onceki surume ($from) donuldu."
            } catch {
                Save-Status "rollback_failed" $version $from "$reason / $($_.Exception.Message)"
                Write-Log "GERI DONUS BASARISIZ: $($_.Exception.Message). Anlik kopya korunuyor: $Snapshot"
                Start-Service $appService -ErrorAction SilentlyContinue
            }
        }
    } finally {
        Stop-Maintenance $maintenance
        foreach ($task in $disabled) { Enable-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue | Out-Null }
        Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
    }
}

# ---------------------------------------------------------------- Giris

try {
    Initialize-UpdateDir
    if ($Mode -eq "Apply" -and -not $Relaunched) {
        # Kurulum tools\ klasorunu yeniler; betik kendi kopyasindan calisir.
        $copy = Join-Path $Updates "updater-run.ps1"
        Copy-Item -Force $PSCommandPath $copy
        & powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $copy `
            -Mode Apply -InstallDir $InstallDir -Repo $Repo -ApiBase $ApiBase `
            -HealthTimeoutSec $HealthTimeoutSec -Relaunched
        exit $LASTEXITCODE
    }
    if ($Mode -eq "Check") { Invoke-Check } else { Invoke-Apply }
    exit 0
} catch {
    Write-Log "HATA: $($_.Exception.Message)"
    exit 1
}
