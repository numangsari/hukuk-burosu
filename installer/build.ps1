<#
.SYNOPSIS
  Özkurt Hukuk kurulum paketini (Setup.exe) üretir. Geliştirici makinesinde çalıştırılır.

.DESCRIPTION
  1. Gömülü Python'u indirir ve bağımlılıkları kurar.
  2. PostgreSQL Windows binary'lerini indirir (yalnızca sunucu için gerekenler).
  3. WinSW servis sarmalayıcısını indirir.
  4. Uygulama kodunu kopyalar, statik dosyaları toplar.
  5. Inno Setup (ISCC.exe) ile installer\dist\OzkurtHukuk-Kurulum-<sürüm>.exe üretir.

  Gereken: Inno Setup 6 (winget install JRSoftware.InnoSetup), uv, internet bağlantısı.
  İndirilen dosyaların SHA256 değerleri build\indirilenler.txt dosyasına yazılır.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File installer\build.ps1 -Version 1.0.0
#>
param(
    [string]$Version = "1.0.0",
    [string]$PythonVersion = "3.13.15",
    [string]$PostgresVersion = "17.6-1",
    [string]$WinSWVersion = "v2.12.0"
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Invoke-WebRequest/Expand-Archive ilerleme çubuğu çok yavaşlatır
$Root = Split-Path -Parent $PSScriptRoot
$Build = Join-Path $PSScriptRoot "build"
$Cache = Join-Path $PSScriptRoot "cache"
New-Item -ItemType Directory -Force $Cache | Out-Null
if (Test-Path $Build) { Remove-Item -Recurse -Force $Build }
New-Item -ItemType Directory -Force $Build | Out-Null
$hashes = @()

function Get-Cached([string]$Url, [string]$Name) {
    $target = Join-Path $Cache $Name
    if (-not (Test-Path $target)) {
        Write-Host "İndiriliyor: $Url"
        Invoke-WebRequest -Uri $Url -OutFile $target -UseBasicParsing
    }
    $script:hashes += "{0}  {1}  {2}" -f (Get-FileHash $target -Algorithm SHA256).Hash, $Name, $Url
    return $target
}

# 1) Gömülü Python + bağımlılıklar
$pyZip = Get-Cached "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" "python-$PythonVersion-embed-amd64.zip"
$py = Join-Path $Build "python"
Expand-Archive $pyZip $py
$pth = Get-ChildItem $py -Filter "python*._pth" | Select-Object -First 1
# site-packages ve uygulama klasörü yola eklenir
@("python$($PythonVersion.Split('.')[0..1] -join '').zip", ".", "Lib\site-packages", "..\app", "import site") |
    Set-Content -Encoding ascii $pth.FullName
$getPip = Get-Cached "https://bootstrap.pypa.io/get-pip.py" "get-pip.py"
& "$py\python.exe" $getPip --no-warn-script-location
$req = Join-Path $Build "requirements.txt"
Push-Location $Root
uv export --no-dev --no-hashes --format requirements-txt -o $req | Out-Null
Pop-Location
& "$py\python.exe" -m pip install --no-warn-script-location -r $req
if ($LASTEXITCODE -ne 0) { throw "Python bağımlılıkları kurulamadı." }

# 2) PostgreSQL (yalnızca sunucu bileşenleri)
$pgZip = Get-Cached "https://get.enterprisedb.com/postgresql/postgresql-$PostgresVersion-windows-x64-binaries.zip" "postgresql-$PostgresVersion-windows-x64-binaries.zip"
$pgTmp = Join-Path $Build "pgtmp"
New-Item -ItemType Directory -Force $pgTmp | Out-Null
tar -xf $pgZip -C $pgTmp  # Windows'un yerleşik tar'ı Expand-Archive'den çok daha hızlı
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL arşivi açılamadı." }
Move-Item (Join-Path $pgTmp "pgsql") (Join-Path $Build "pgsql")
Remove-Item -Recurse -Force $pgTmp
foreach ($junk in @("pgAdmin 4", "doc", "StackBuilder", "symbols", "include")) {
    $p = Join-Path $Build "pgsql\$junk"
    if (Test-Path $p) { Remove-Item -Recurse -Force $p }
}

# 3) WinSW (Windows servis sarmalayıcı)
$tools = Join-Path $Build "tools"
New-Item -ItemType Directory -Force $tools | Out-Null
$winsw = Get-Cached "https://github.com/winsw/winsw/releases/download/$WinSWVersion/WinSW-x64.exe" "WinSW-x64-$WinSWVersion.exe"
Copy-Item $winsw (Join-Path $tools "OzkurtHukukApp.exe")
Copy-Item (Join-Path $PSScriptRoot "scripts\*") $tools

# 4) Uygulama kodu
$app = Join-Path $Build "app"
New-Item -ItemType Directory -Force $app | Out-Null
foreach ($item in @("apps", "config", "templates", "static", "manage.py", "pyproject.toml")) {
    Copy-Item -Recurse (Join-Path $Root $item) $app
}
Get-ChildItem $app -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Set-Content -Encoding utf8 (Join-Path $app "VERSION") $Version
# Statik dosyaları topla (geçici değerlerle; gerçek .env kurulumda yazılır)
$env:DJANGO_SETTINGS_MODULE = "config.settings.prod"
$env:DJANGO_SECRET_KEY = "build-only"
$env:DATABASE_URL = "postgres://build:build@127.0.0.1:1/build"
$env:STATIC_ROOT = (Join-Path $app "staticfiles")
& "$py\python.exe" (Join-Path $app "manage.py") collectstatic --noinput | Out-Null
if ($LASTEXITCODE -ne 0) { throw "collectstatic başarısız." }
Remove-Item Env:\DATABASE_URL, Env:\DJANGO_SECRET_KEY, Env:\STATIC_ROOT

$hashes | Set-Content -Encoding utf8 (Join-Path $Build "indirilenler.txt")

# 5) Inno Setup
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
          "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 bulunamadı. Kurmak için: winget install JRSoftware.InnoSetup" }
& $iscc "/DAppVersion=$Version" "/DBuildDir=$Build" (Join-Path $PSScriptRoot "OzkurtHukuk.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup derlemesi başarısız." }
Write-Host "Hazır: $(Join-Path $PSScriptRoot "dist\OzkurtHukuk-Kurulum-$Version.exe")"
