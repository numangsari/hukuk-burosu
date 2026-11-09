<#
.SYNOPSIS
  Derlenmiş kurulum paketini public releases reposunda yayınlar; otomatik güncelleyici oradan alır.

.DESCRIPTION
  installer\dist\HukukBurosuOtomasyonu-Kurulum-<sürüm>.exe ve .sha256 dosyasını
  "v<sürüm>" etiketli GitHub release olarak yükler. Kaynak kod yüklenmez; ana repo private kalır.
  Yayınlanan sürüm, sunucularda en geç ertesi gün indirilir ve bir sonraki açılışta kurulur.
  Önce installer\build.ps1 çalıştırılmalıdır. Gereken: gh (oturum açık).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File installer\publish-release.ps1 -Notes "Hakkında bölümü eklendi"
#>
param(
    [string]$Version = "",
    [string]$Notes = "",
    [string]$Repo = "numangsari/hukuk-burosu-releases"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Version) {
    $Version = (Select-String -Path (Join-Path $Root "pyproject.toml") -Pattern '^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
}
$exe = Join-Path $PSScriptRoot "dist\HukukBurosuOtomasyonu-Kurulum-$Version.exe"
$sha = "$exe.sha256"
if (-not (Test-Path $exe) -or -not (Test-Path $sha)) { throw "Paket bulunamadı; önce build.ps1 çalıştırın: $exe" }
$expected = ((Get-Content $sha -Raw).Trim() -split '\s+')[0]
if ((Get-FileHash -Algorithm SHA256 $exe).Hash.ToLowerInvariant() -ne $expected) { throw "SHA256 dosyası pakete uymuyor." }

if (-not $Notes) { $Notes = "Sürüm $Version" }
& gh release create "v$Version" $exe $sha --repo $Repo --title "Sürüm $Version" --notes $Notes
if ($LASTEXITCODE -ne 0) { throw "Yayınlama başarısız." }
Write-Host "Yayınlandı: https://github.com/$Repo/releases/tag/v$Version"
