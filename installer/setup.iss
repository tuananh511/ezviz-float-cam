; =====================================================================
; EzvizFloatCam — Inno Setup Script (Sprint 7)
; Build installer chuan Windows, dang ky Add/Remove Programs,
; tuong thich Control Panel + Revo Uninstaller.
;
; YEU CAU TRUOC KHI COMPILE:
;   1. Da chay build_exe.bat (Sprint 6) -> co san dist\EzvizFloatCam.exe
;   2. Cai Inno Setup 6 (https://jrsoftware.org/isinfo.php)
;   3. Mo file nay bang Inno Setup Compiler, bam Build > Compile
;      (hoac dong lenh: ISCC.exe installer\setup.iss)
;
; LUU Y: file .iss nay dat trong thu muc installer/, nhung tham chieu
; toi cac file khac dung {#SourcePath}\.. de tro ve goc repo, vi vay
; PHAI compile voi working directory la goc repo (Inno Setup Compiler
; tu dong xu ly dung neu mo file .iss truc tiep tu installer/).
; =====================================================================

#define MyAppName "EzvizFloatCam"
#define MyAppVersion "0.7.0"
#define MyAppPublisher "BiKipViet"
#define MyAppURL "https://github.com/tuananh511/ezviz-float-cam"
#define MyAppExeName "EzvizFloatCam.exe"
; Thu muc goc repo, tinh tu vi tri file .iss nay (installer/../)
#define RepoRoot ".."

[Setup]
; GUID rieng cho app nay - KHONG duoc doi sau khi da phat hanh ban dau,
; Windows dung ID nay de nhan dien "cung 1 app" khi update/uninstall.
AppId={{E5A1F8C2-6B3D-4F9A-9C7E-2D8B1A4F6E90}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
; Cai vao Program Files rieng cho user hien tai, khong can quyen admin
; (khop voi trai nghiem "khong ranh ky thuat" - khong bi UAC hoi quyen)
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Khong yeu cau admin - cai cho user hien tai (per-user), tranh UAC prompt
PrivilegesRequired=lowest
OutputDir={#RepoRoot}\dist_installer
OutputBaseFilename=EzvizFloatCam-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Icon rieng cho installer - dung icon mac dinh Inno neu chua co .ico rieng
; (khop ghi chu S6: app chua co file .ico rieng)
UninstallDisplayIcon={app}\{#MyAppExeName}
; Cho phep Revo Uninstaller / Control Panel doc dung dung luong da cai
VersionInfoVersion={#MyAppVersion}

[Languages]
; Luu y: Inno Setup KHONG di kem san file Vietnamese.isl (phai tai rieng
; tu ban dich cong dong, khong chinh thuc trong bo cai) - dung tam tieng
; Anh cho cac nut co san cua Inno (Next/Back/Install...). Toan bo mo ta
; rieng cua app (checkbox, thong bao xoa config...) van la tieng Viet
; vi do la text tu viet trong file .iss nay, khong phu thuoc .isl.
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
; Checkbox tuy chon "Khoi dong cung Windows" trong man hinh cai dat.
; App da tu co logic ghi HKCU Run key (Sprint 5) - task nay chi quyet
; dinh co TICH SAN vao config mac dinh hay khong, khong tu ghi registry
; tai day (tranh 2 noi cung ghi 1 registry key gay xung dot).
Name: "autostart"; Description: "Khoi dong cung Windows"; GroupDescription: "Tuy chon:"; Flags: unchecked
Name: "desktopicon"; Description: "Tao icon ngoai Desktop"; GroupDescription: "Tuy chon:"; Flags: unchecked

[Files]
; File exe chinh, build tu Sprint 6 (PyInstaller --onefile)
Source: "{#RepoRoot}\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
; README + LICENSE de nguoi dung tham khao sau khi cai
Source: "{#RepoRoot}\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
; KHONG dong goi config/default_config.json rieng - file nay da duoc
; PyInstaller bundle thang vao ben trong exe tu Sprint 6 (xem spec file),
; nen khong can copy ra ngoai, tranh trung lap gay nham lan.

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Go GitHub"; Filename: "{#MyAppURL}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; Neu nguoi dung tich "Khoi dong cung Windows" luc cai, ghi san HKCU Run key.
; Dung {olddata} an toan (khong xoa key nguoi khac lo ghi cung ten).
; App cung tu quan ly key nay o Settings (Sprint 5) - installer chi la
; buoc tien loi ban dau, khong xung dot vi cung 1 key/gia tri.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; \
  ValueType: string; ValueName: "{#MyAppName}"; ValueData: """{app}\{#MyAppExeName}"""; \
  Tasks: autostart; Flags: uninsdeletevalue

[Run]
; Tuy chon mo app ngay sau khi cai xong
Filename: "{app}\{#MyAppExeName}"; Description: "Chay {#MyAppName} ngay bay gio"; \
  Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Don config nguoi dung khi go cai dat, CO XAC NHAN qua thong diep rieng
; (xem [Code] ben duoi) - khong tu dong xoa am tham du lieu ca nhan.
; Entry nay chi don file build/cache tam neu vo tinh bi tao trong {app}.
Type: filesandordirs; Name: "{app}\__pycache__"

[Code]
// Hoi nguoi dung truoc khi xoa config ca nhan (%APPDATA%\EzvizFloatCam)
// luc go cai - tranh mat RTSP URL/user/pass da luu ma khong bao truoc.
procedure CurStepChanged(CurStep: TSetupStep);
begin
  // Cho o day de mo rong sau nay neu can kiem tra VLC da cai chua
  // (hien tai chi canh bao thu dong trong README, chua chan cai dat)
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDataConfig: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    AppDataConfig := ExpandConstant('{userappdata}\EzvizFloatCam');
    if DirExists(AppDataConfig) then
    begin
      if MsgBox('Ban co muon xoa luon file cau hinh ca nhan (IP/user/mat khau RTSP da luu) khong?' + #13#10 +
                'Chon "No" neu du dinh cai lai sau va muon giu nguyen cau hinh cu.',
                mbConfirmation, MB_YESNO) = IDYES then
      begin
        DelTree(AppDataConfig, True, True, True);
      end;
    end;
  end;
end;
