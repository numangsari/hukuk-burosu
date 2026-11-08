; Hukuk Bürosu Otomasyonu — Inno Setup betiği
; Dosya UTF-8 (BOM'lu) kalmalı; Türkçe karakterler aksi halde bozulur.
; AppId, kurulum klasörü, servis ve görev adları eski kurulumların güncellenmesi için değişmez.
; Derleme: installer\build.ps1 (BuildDir ve AppVersion parametrelerini verir)

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef BuildDir
  #define BuildDir "build"
#endif

[Setup]
AppId={{8C1D2B5E-3F4A-4E7B-9A61-0D2C5B7E4F10}
AppName=Hukuk Bürosu Otomasyonu
AppVersion={#AppVersion}
AppPublisher=Hukuk Bürosu Otomasyonu
DefaultDirName=C:\HukukBurosu
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=HukukBurosuOtomasyonu-Kurulum-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=Hukuk Bürosu Otomasyonu
VersionInfoVersion={#AppVersion}
VersionInfoProductName=Hukuk Bürosu Otomasyonu
SetupLogging=yes

[Languages]
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"

[Dirs]
; Veri klasörleri kaldırmada SİLİNMEZ (uninsneveruninstall)
Name: "{app}\data"; Flags: uninsneveruninstall
Name: "{app}\data\media"; Flags: uninsneveruninstall
Name: "{app}\data\backups"; Flags: uninsneveruninstall
Name: "{app}\logs"; Flags: uninsneveruninstall

[Files]
Source: "{#BuildDir}\python\*"; DestDir: "{app}\python"; Flags: recursesubdirs ignoreversion
Source: "{#BuildDir}\pgsql\*"; DestDir: "{app}\pgsql"; Flags: recursesubdirs ignoreversion
Source: "{#BuildDir}\app\*"; DestDir: "{app}\app"; Excludes: ".env"; Flags: recursesubdirs ignoreversion
Source: "{#BuildDir}\tools\*"; DestDir: "{app}\tools"; Flags: recursesubdirs ignoreversion
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
  PinPage: TInputQueryWizardPage;
  PostInstallFailed: Boolean;
  VcRestartNeeded: Boolean;

function IsFirstInstall(): Boolean;
begin
  Result := not FileExists(ExpandConstant('{app}\app\.env'));
end;

procedure InitializeWizard();
begin
  PinPage := CreateInputQueryPage(wpSelectDir,
    'Kullanıcı PIN''i', 'Ofis kullanıcılarının ilk PIN kodu',
    'Tüm kullanıcılar bu 4 haneli PIN ile ilk girişi yapar. Her kullanıcının ilk girişten sonra Ayarlar > PIN değiştir''den kendi PIN''ini belirlemesi önerilir.');
  PinPage.Add('Varsayılan PIN (4 rakam):', True);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = PinPage.ID) and not IsFirstInstall();
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Pin: String;
  I: Integer;
begin
  Result := True;
  if CurPageID = PinPage.ID then begin
    Pin := PinPage.Values[0];
    if Length(Pin) <> 4 then Result := False;
    for I := 1 to Length(Pin) do
      if (Pin[I] < '0') or (Pin[I] > '9') then Result := False;
    if not Result then MsgBox('PIN tam 4 rakam olmalı.', mbError, MB_OK);
  end;
end;

function GetPin(Param: String): String;
begin
  if IsFirstInstall() then Result := PinPage.Values[0] else Result := '';
end;

function PostInstallSucceeded(): Boolean;
begin
  Result := not PostInstallFailed;
end;

function NeedRestart(): Boolean;
begin
  Result := VcRestartNeeded;
end;

procedure ReportPostInstallError(Msg: String);
begin
  PostInstallFailed := True;
  Log(Msg);
  if not WizardSilent() then
    MsgBox(Msg + #13#10#13#10 + 'Ayrıntı: ' + ExpandConstant('{app}\logs\kurulum.log'), mbCriticalError, MB_OK);
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
              '" -InstallDir "' + ExpandConstant('{app}') + '" -Pin "' + GetPin('') + '"',
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
    if Code <> 0 then
      if MsgBox('Güncelleme öncesi yedek alınamadı. Yine de devam edilsin mi?', mbConfirmation, MB_YESNO) = IDNO then begin
        Result := 'Güncelleme iptal edildi; yedek alınamadı.';
        exit;
      end;
    if FileExists(ExpandConstant('{app}\tools\HukukBuroApp.exe')) then
      Exec(ExpandConstant('{app}\tools\HukukBuroApp.exe'), 'stop', '', SW_HIDE, ewWaitUntilTerminated, Code)
    else
      Exec(ExpandConstant('{app}\tools\OzkurtHukukApp.exe'), 'stop', '', SW_HIDE, ewWaitUntilTerminated, Code);
  end;
end;
