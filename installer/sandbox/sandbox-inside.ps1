<#
  Windows Sandbox icinde calisir (run-sandbox-test.ps1 baslatir). Senaryo:
    A) <Eski> surumu temiz ve sessiz kurulur, /saglik/ dogrulanir, isaret kullanicisi eklenir.
    B) Sahte releases API'sinde <Yeni> yayinlanir; updater Check + Apply ile guncellenir.
    C) Ayni paket daha yuksek surum numarasiyla yayinlanir: kurulum calisir ama saglik kontrolu
       beklenen surumu goremez -> geri donus. Onceki surum ve veri (isaret) korunmali, surum
       bad-versions.txt'ye yazilmali.
    D) Check tekrar calisir: hatali surum indirilmez.
  Sonuclar C:\work\sonuc\ altina yazilir; ozet sonuc.txt, bitis isareti BITTI.txt.
#>
param([string]$Old = "1.2.0", [string]$New = "1.2.1", [string]$Bad = "1.2.2")
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Work = "C:\work"
$Out = Join-Path $Work "sonuc"
$Install = "C:\Program Files\HukukBurosu"
$DataRoot = "C:\ProgramData\HukukBurosu"
$Api = Join-Path $Work "api"
$Port = 8765
$Prefix = "HukukBurosuOtomasyonu-Kurulum-"
New-Item -ItemType Directory -Force $Out | Out-Null
$Summary = Join-Path $Out "sonuc.txt"
Remove-Item $Summary, (Join-Path $Out "BITTI.txt") -ErrorAction SilentlyContinue

function Note([string]$Text) { Add-Content -Path $Summary -Value "$(Get-Date -Format HH:mm:ss) $Text" }
function Check([string]$Name, [bool]$Ok, [string]$Detail = "") {
    Note ("{0} {1} {2}" -f ($(if ($Ok) { "GECTI " } else { "KALDI " })), $Name, $Detail)
}
function Health {
    try { return Invoke-RestMethod "http://127.0.0.1/saglik/" -TimeoutSec 10 } catch { return $null }
}
function Manage([string]$Code) {
    $env:DJANGO_SETTINGS_MODULE = "config.settings.prod"
    Push-Location (Join-Path $Install "app")
    try { return (& (Join-Path $Install "python\python.exe") manage.py shell -c $Code 2>&1 | Out-String).Trim() }
    finally { Pop-Location }
}
function Publish([string]$Version, [string]$SourceExe) {
    $dl = Join-Path $Api "dl"
    New-Item -ItemType Directory -Force $dl, (Join-Path $Api "repos\test\rel\releases") | Out-Null
    $name = "$Prefix$Version.exe"
    Copy-Item -Force $SourceExe (Join-Path $dl $name)
    $hash = (Get-FileHash -Algorithm SHA256 (Join-Path $dl $name)).Hash.ToLowerInvariant()
    [IO.File]::WriteAllText((Join-Path $dl "$name.sha256"), "$hash  $name`n")
    $release = @{ tag_name = "v$Version"; assets = @(
        @{ name = $name; browser_download_url = "http://127.0.0.1:$Port/dl/$name" },
        @{ name = "$name.sha256"; browser_download_url = "http://127.0.0.1:$Port/dl/$name.sha256" }
    ) }
    [IO.File]::WriteAllText((Join-Path $Api "repos\test\rel\releases\latest"), ($release | ConvertTo-Json -Depth 4))
}
function Updater([string]$Mode) {
    # Start-Process argumanlari tirnaklamaz; "Program Files" yolu tirnak icinde verilmeli.
    $updaterArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$(Join-Path $Install 'tools\updater.ps1')`"",
        "-Mode", $Mode, "-Repo", "test/rel", "-ApiBase", "http://127.0.0.1:$Port", "-Relaunched")
    $p = Start-Process powershell.exe -ArgumentList $updaterArgs -Wait -PassThru -WindowStyle Hidden
    return $p.ExitCode
}
function Get-SidRights([string]$Path, [string]$Sid) {
    @((Get-Acl $Path).Access | Where-Object {
        try { $_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value -eq $Sid } catch { $false }
    } | ForEach-Object { $_.FileSystemRights.ToString() })
}
function Read-Status {
    $f = Join-Path $DataRoot "updates\status.json"
    if (Test-Path $f) { return (Get-Content $f -Raw | ConvertFrom-Json) } return $null
}

try {
    Note "Sandbox testi basladi: $Old -> $New, hatali $Bad"

    # A) Temiz kurulum. Once biri veri klasorunu onceden acmis gibi yapilir: ilk kurulum ona
    # guvenmemeli, klasoru kenara alip sifirdan acmali.
    New-Item -ItemType Directory -Force "$DataRoot\pgdata" | Out-Null
    Set-Content "$DataRoot\pgdata\sahte.txt" "onceden konmus"
    $setup =Start-Process (Join-Path $Work "pkg\$Prefix$Old.exe") -Wait -PassThru `
        -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/LOG=`"$Out\A-kurulum.log`"")
    Check "A kurulum cikis kodu 0" ($setup.ExitCode -eq 0) "kod=$($setup.ExitCode)"
    $aside = @(Get-ChildItem "C:\ProgramData" -Directory -Filter "HukukBurosu.onceki-*")
    Check "A onceden var olan veri klasoru kenara alindi" ($aside.Count -eq 1 -and (Test-Path "$($aside[0].FullName)\pgdata\sahte.txt") -and -not (Test-Path "$DataRoot\pgdata\sahte.txt")) (($aside | ForEach-Object Name) -join ",")
    $h = Health
    Check "A saglik $Old" ($h -and $h.status -eq "ok" -and $h.version -eq $Old) ($h | ConvertTo-Json -Compress)
    foreach ($svc in "HukukBuroApp", "HukukBuroDB") {
        Check "A servis $svc calisiyor" ((Get-Service $svc).Status -eq "Running")
    }
    foreach ($task in "Hukuk Buro Guncelleme", "Hukuk Buro Guncelleme Kontrol") {
        Check "A gorev '$task' var" ([bool](Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue))
    }
    $desktop = [Environment]::GetFolderPath("CommonDesktopDirectory")
    $links = @(Get-ChildItem $desktop -Filter "Hukuk*.url" | ForEach-Object { $_.Name })
    Check "A masaustu kisayolu dogru adla" ($links -contains "Hukuk B$([char]0x00FC)rosu Otomasyonu.url" -and $links.Count -eq 1) ($links -join ", ")
    # Izinler (SID ile; Windows dili hesap adlarini degistirir): Users = S-1-5-32-545,
    # Authenticated Users = S-1-5-11. Program klasoru salt okunur, veriler kapali.
    $usersTools = (Get-SidRights "$Install\tools" "S-1-5-32-545") -join ","
    Check "A tools: Users yalnizca okur" ($usersTools -match "ReadAndExecute" -and $usersTools -notmatch "Modify|Write|FullControl" -and -not (Get-SidRights "$Install\tools" "S-1-5-11")) $usersTools
    Check "A media: Users erisemez" (-not (Get-SidRights "$DataRoot\media" "S-1-5-32-545") -and -not (Get-SidRights "$DataRoot\media" "S-1-5-11"))
    Check "A .env: Users erisemez" (-not (Get-SidRights "$Install\app\.env" "S-1-5-32-545"))
    $marker = Manage "from apps.accounts.models import User; User.objects.create_user(username='sandbox.isaret', first_name='Isaret'); print(User.objects.filter(username='sandbox.isaret').count())"
    Check "A isaret kullanicisi eklendi" ($marker -match '1$') $marker

    # Sahte API: kurulumla gelen Python'un KOPYASIYLA (kurulum, programin Python dosyalarini kullanan
    # surecleri kapatir). Not: PowerShell degisken adlari buyuk/kucuk harf ayirmaz; $Api ile cakismamali.
    robocopy (Join-Path $Install "python") "C:\fakepy" /MIR /NFL /NDL /NJH /NJS /NP | Out-Null
    $apiServer = Start-Process "C:\fakepy\python.exe" -WindowStyle Hidden -PassThru `
        -ArgumentList @("-I", "`"$Work\fakeapi.py`"", "`"$Api`"", "$Port")
    Start-Sleep 2

    # B) Basarili guncelleme
    Publish $New (Join-Path $Work "pkg\$Prefix$New.exe")
    $code = Updater "Check"
    $s = Read-Status
    Check "B Check indirdi" ($code -eq 0 -and $s.result -eq "downloaded" -and $s.version -eq $New) "kod=$code sonuc=$($s.result)"
    $code = Updater "Apply"
    $s = Read-Status
    $h = Health
    Check "B Apply sonucu ok" ($code -eq 0 -and $s.result -eq "ok") "kod=$code sonuc=$($s.result) $($s.message)"
    Check "B saglik $New" ($h -and $h.version -eq $New) ($h | ConvertTo-Json -Compress)
    Check "B anlik kopya temizlendi" (-not (Test-Path "$DataRoot\updates\rollback"))
    Check "B isaret korundu" ((Manage "from apps.accounts.models import User; print(User.objects.filter(username='sandbox.isaret').count())") -match '1$')

    # C) Hatali surum -> geri donus
    Publish $Bad (Join-Path $Work "pkg\$Prefix$New.exe")
    $code = Updater "Check"
    Check "C Check indirdi" ($code -eq 0 -and (Read-Status).result -eq "downloaded")
    $code = Updater "Apply"
    $s = Read-Status
    $h = Health
    Check "C sonuc rolled_back" ($s.result -eq "rolled_back") "kod=$code sonuc=$($s.result) $($s.message)"
    Check "C onceki surum calisiyor ($New)" ($h -and $h.status -eq "ok" -and $h.version -eq $New) ($h | ConvertTo-Json -Compress)
    Check "C isaret korundu (veritabani geri yuklendi)" ((Manage "from apps.accounts.models import User; print(User.objects.filter(username='sandbox.isaret').count())") -match '1$')
    Check "C bad-versions.txt $Bad iceriyor" ((Get-Content "$DataRoot\updates\bad-versions.txt" -ErrorAction SilentlyContinue) -contains $Bad)
    Check "C gorevler yeniden etkin" ((Get-ScheduledTask -TaskName "Hukuk Buro Yedek").State -ne "Disabled")

    # D) Hatali surum tekrar indirilmez
    $code = Updater "Check"
    Check "D hatali surum atlandi" ($code -eq 0 -and -not (Test-Path "$DataRoot\updates\pending.json"))

    Stop-Process -Id $apiServer.Id -Force -ErrorAction SilentlyContinue
} catch {
    Note "BEKLENMEYEN HATA: $($_.Exception.Message) @ $($_.InvocationInfo.ScriptLineNumber)"
} finally {
    Copy-Item "$DataRoot\logs\*" $Out -ErrorAction SilentlyContinue
    Copy-Item "$DataRoot\updates\status.json" $Out -ErrorAction SilentlyContinue
    Set-Content (Join-Path $Out "BITTI.txt") "bitti"
}
