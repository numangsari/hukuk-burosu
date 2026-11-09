<#
.SYNOPSIS
  Kurulum, otomatik güncelleme ve geri dönüşü Windows Sandbox'ta uçtan uca dener.

.DESCRIPTION
  installer\dist altındaki iki paketi (eski ve yeni sürüm) çalışma klasörüne kopyalar, Sandbox'ı
  açar; içeride sandbox-inside.ps1 temiz kurulum, güncelleme ve bilerek bozulan güncellemede geri
  dönüşü sınar. Sonuç: <çalışma klasörü>\sonuc\sonuc.txt (her satır GECTI/KALDI).
  Gereken: Windows Sandbox özelliği açık; paketler build.ps1 ile derlenmiş olmalı. Test için
  "build.ps1 -Fast" (sıkıştırmasız, çok daha hızlı) yeterlidir.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File installer\sandbox\run-sandbox-test.ps1 -Old 1.2.0 -New 1.2.1
#>
param(
    [Parameter(Mandatory = $true)][string]$Old,
    [Parameter(Mandatory = $true)][string]$New,
    [string]$Work = (Join-Path $env:TEMP "hukuk-sandbox-test")
)
$ErrorActionPreference = "Stop"
$dist = Join-Path (Split-Path $PSScriptRoot -Parent) "dist"
$bad = ([version]$New)
$bad = "{0}.{1}.{2}" -f $bad.Major, $bad.Minor, ($bad.Build + 1)

if (Test-Path $Work) { Remove-Item $Work -Recurse -Force }
New-Item -ItemType Directory -Force (Join-Path $Work "pkg"), (Join-Path $Work "sonuc") | Out-Null
foreach ($v in $Old, $New) {
    $exe = Join-Path $dist "HukukBurosuOtomasyonu-Kurulum-$v.exe"
    if (-not (Test-Path $exe)) { throw "Paket yok: $exe" }
    Copy-Item $exe (Join-Path $Work "pkg")
}
Copy-Item (Join-Path $PSScriptRoot "sandbox-inside.ps1"), (Join-Path $PSScriptRoot "fakeapi.py") $Work

$wsb = Join-Path $Work "test.wsb"
@"
<Configuration>
  <MappedFolders>
    <MappedFolder><HostFolder>$Work</HostFolder><SandboxFolder>C:\work</SandboxFolder><ReadOnly>false</ReadOnly></MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\work\sandbox-inside.ps1 -Old $Old -New $New -Bad $bad</Command>
  </LogonCommand>
</Configuration>
"@ | Set-Content -Encoding utf8 $wsb
Start-Process $wsb
Write-Host "Sandbox açıldı. Sonuç: $(Join-Path $Work 'sonuc\sonuc.txt') (bitince BITTI.txt oluşur)"
