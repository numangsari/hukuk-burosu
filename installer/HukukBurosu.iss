; Hukuk Bürosu Otomasyonu — Inno Setup betiği
; Dosya UTF-8 (BOM'lu) kalmalı; Türkçe karakterler aksi halde bozulur.
; AppId, servis ve görev adları eski kurulumların güncellenmesi için değişmez.
; Program: C:\Program Files\HukukBurosu (yalnızca yöneticiler yazar). Veri: C:\ProgramData\HukukBurosu
; (veritabanı, belgeler, yedekler, güncellemeler, kayıtlar; postinstall.ps1 oluşturur, kaldırmada silinmez).
; Eski düzende (C:\HukukBurosu\data) kurulu sistem güncellenirse aynı klasörde kalır.
; Derleme: installer\build.ps1 (BuildDir ve AppVersion parametrelerini verir)

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef BuildDir
  #define BuildDir "build"
#endif
; build.ps1 -Fast sıkıştırmayı kapatır (yalnızca test paketi; dosya büyük ama derleme hızlı).
#ifndef Compression
  #define Compression "lzma2/max"
#endif

[Setup]
AppId={{8C1D2B5E-3F4A-4E7B-9A61-0D2C5B7E4F10}
AppName=Hukuk Bürosu Otomasyonu
AppVersion={#AppVersion}
AppPublisher=Hukuk Bürosu Otomasyonu
DefaultDirName={commonpf64}\HukukBurosu
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=HukukBurosuOtomasyonu-Kurulum-{#AppVersion}
Compression={#Compression}
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=Hukuk Bürosu Otomasyonu
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Hukuk Bürosu Otomasyonu
SetupLogging=yes

[Languages]
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"

[Files]
Source: "{#BuildDir}\python\*"; DestDir: "{app}\python"; Flags: recursesubdirs ignoreversion
Source: "{#BuildDir}\pgsql\*"; DestDir: "{app}\pgsql"; Flags: recursesubdirs ignoreversion
Source: "{#BuildDir}\app\*"; DestDir: "{app}\app"; Excludes: ".env"; Flags: recursesubdirs ignoreversion
Source: "{#BuildDir}\tools\*"; DestDir: "{app}\tools"; Flags: recursesubdirs ignoreversion
Source: "{#BuildDir}\eklenti\*"; DestDir: "{app}\eklenti"; Flags: recursesubdirs ignoreversion
Source: "{#BuildDir}\redist\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

; Visual C++ kütüphanesi ve postinstall.ps1 [Code] içindeki CurStepChanged ile çalışır;
; böylece çıkış kodları denetlenir ve hata kullanıcıya gösterilir.
[Run]
Filename: "http://localhost/"; Description: "Sistemi tarayıcıda aç"; Flags: postinstall shellexec nowait skipifsilent; \
  Check: PostInstallSucceeded

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\tools\uninstall.ps1"" -InstallDir ""{app}"""; \
  Flags: runhidden waituntilterminated; RunOnceId: "HukukBuroUninstall"

[Code]
var
  PostInstallFailed: Boolean;
  VcRestartNeeded: Boolean;

// İlk yönetici ve PIN'i kurulumdan sonra tarayıcıdaki İlk Kurulum ekranında belirlenir.
function IsFirstInstall(): Boolean;
begin
  Result := not FileExists(ExpandConstant('{app}\app\.env'));
end;

function PostInstallSucceeded(): Boolean;
begin
  Result := not PostInstallFailed;
end;

function NeedRestart(): Boolean;
begin
  Result := VcRestartNeeded;
end;

// Otomatik güncelleyici /DEFERSTART=1 verir: uygulama servisini kurulum değil güncelleyici başlatır.
function DeferArg(Param: String): String;
begin
  if ExpandConstant('{param:DEFERSTART|0}') = '1' then Result := ' -DeferAppStart' else Result := '';
end;

// Sessiz kurulumda hata çıkış koduyla bildirilir (güncelleyici buna bakarak geri döner).
function GetCustomSetupExitCode(): Integer;
begin
  if PostInstallFailed then Result := 9 else Result := 0;
end;

function LogDir(): String;
begin
  if DirExists(ExpandConstant('{app}\data\pgdata')) then Result := ExpandConstant('{app}\logs')
  else Result := ExpandConstant('{commonappdata}\HukukBurosu\logs');
end;

procedure ReportPostInstallError(Msg: String);
begin
  PostInstallFailed := True;
  Log(Msg);
  if not WizardSilent() then
    MsgBox(Msg + #13#10#13#10 + 'Ayrıntı: ' + LogDir() + '\kurulum.log', mbCriticalError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Code: Integer;
begin
  if CurStep <> ssPostInstall then exit;

  // 0: kuruldu, 1638: aynı/yeni sürüm zaten yüklü, 3010: yeniden başlatma gerekiyor
  WizardForm.StatusLabel.Caption := 'Visual C++ çalışma kütüphanesi kuruluyor...';
  if not Exec(ExpandConstant('{tmp}\vc_redist.x64.exe'), '/install /quiet /norestart', '',
              SW_HIDE, ewWaitUntilTerminated, Code) then begin
    ReportPostInstallError('Visual C++ çalışma kütüphanesi kurulumu başlatılamadı.');
    exit;
  end;
  if Code = 3010 then VcRestartNeeded := True
  else if (Code <> 0) and (Code <> 1638) then begin
    ReportPostInstallError('Visual C++ çalışma kütüphanesi kurulamadı (kod ' + IntToStr(Code) + ').');
    exit;
  end;

  WizardForm.StatusLabel.Caption := 'Veritabanı ve servisler hazırlanıyor (birkaç dakika sürebilir)...';
  if not Exec('powershell.exe',
              '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\tools\postinstall.ps1') +
              '" -InstallDir "' + ExpandConstant('{app}') + '"' + DeferArg(''),
              '', SW_HIDE, ewWaitUntilTerminated, Code) or (Code <> 0) then
    ReportPostInstallError('Veritabanı ve servisler hazırlanamadı; sistem çalışmıyor.');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  Result := '';
  // Güncellemede: önce yedek al, sonra uygulama servisini durdur.
  if not IsFirstInstall() then begin
    Exec(ExpandConstant('{app}\tools\manage.cmd'), 'backup --update', '', SW_HIDE, ewWaitUntilTerminated, Code);
    if Code <> 0 then begin
      // Sessiz kurulumda soru sorulamaz; yedeksiz devam edilmez.
      if WizardSilent() or
         (MsgBox('Güncelleme öncesi yedek alınamadı. Yine de devam edilsin mi?', mbConfirmation, MB_YESNO) = IDNO) then begin
        Result := 'Güncelleme iptal edildi; yedek alınamadı.';
        exit;
      end;
    end;
    if FileExists(ExpandConstant('{app}\tools\HukukBuroApp.exe')) then
      Exec(ExpandConstant('{app}\tools\HukukBuroApp.exe'), 'stop', '', SW_HIDE, ewWaitUntilTerminated, Code)
    else
      Exec(ExpandConstant('{app}\tools\OzkurtHukukApp.exe'), 'stop', '', SW_HIDE, ewWaitUntilTerminated, Code);
    // PostgreSQL dosyaları çalışırken değiştirilemez; postinstall.ps1 servisi yeniden başlatır.
    Exec(ExpandConstant('{sys}\net.exe'), 'stop HukukBuroDB', '', SW_HIDE, ewWaitUntilTerminated, Code);
    Exec(ExpandConstant('{sys}\net.exe'), 'stop OzkurtHukukDB', '', SW_HIDE, ewWaitUntilTerminated, Code);
  end;
end;
