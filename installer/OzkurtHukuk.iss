; Özkurt Hukuk Büro Yönetim Sistemi — Inno Setup betiği
; Derleme: installer\build.ps1 (BuildDir ve AppVersion parametrelerini verir)

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif
#ifndef BuildDir
  #define BuildDir "build"
#endif

[Setup]
AppId={{8C1D2B5E-3F4A-4E7B-9A61-0D2C5B7E4F10}
AppName=Özkurt Hukuk Büro Yönetimi
AppVersion={#AppVersion}
AppPublisher=Özkurt Hukuk Bürosu
DefaultDirName=C:\OzkurtHukuk
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=dist
OutputBaseFilename=OzkurtHukuk-Kurulum-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=Özkurt Hukuk Büro Yönetimi
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

[Run]
Filename: "powershell.exe"; \
  Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\tools\postinstall.ps1"" -InstallDir ""{app}"" -Pin ""{code:GetPin}"""; \
  StatusMsg: "Veritabanı ve servisler hazırlanıyor (birkaç dakika sürebilir)..."; Flags: runhidden waituntilterminated
Filename: "http://localhost/"; Description: "Sistemi tarayıcıda aç"; Flags: postinstall shellexec nowait skipifsilent

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\tools\uninstall.ps1"" -InstallDir ""{app}"""; \
  Flags: runhidden waituntilterminated; RunOnceId: "OzkurtUninstall"

[Code]
var
  PinPage: TInputQueryWizardPage;

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
    Exec(ExpandConstant('{app}\tools\OzkurtHukukApp.exe'), 'stop', '', SW_HIDE, ewWaitUntilTerminated, Code);
  end;
end;
