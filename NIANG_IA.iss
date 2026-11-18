#define AppName "NIANG IA"
#define AppVersion "1.0.50"
#define SourceDir AddBackslash(SourcePath) + "dist\NIANG_IA_" + AppVersion

[Setup]
AppId={{AC51AB64-08DA-4BC6-9CE1-1D5D0AD4B304}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=NIANG IA
AppPublisherURL=https://github.com/niang-ia
VersionInfoVersion={#AppVersion}
VersionInfoDescription=NIANG IA — Assistant vocal intelligent
VersionInfoProductName=NIANG IA
VersionInfoProductVersion={#AppVersion}
VersionInfoCompany=NIANG IA
DefaultDirName={localappdata}\Programs\NIANG IA
UsePreviousAppDir=yes
DefaultGroupName=NIANG IA
OutputDir=dist
OutputBaseFilename=NIANG_IA_Setup_{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile={#SourcePath}\assets\niang_ia.ico
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\NIANG IA"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\START_NIANG_IA.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\niang_ia.ico"
Name: "{autodesktop}\NIANG IA"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\START_NIANG_IA.vbs"""; WorkingDir: "{app}"; IconFilename: "{app}\assets\niang_ia.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install_screen_vision.ps1"""; StatusMsg: "Installation d'Ollama et téléchargement du modèle de vision (environ 1,9 Go)..."; Flags: waituntilterminated
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\install_agent_reach.ps1"""; StatusMsg: "Téléchargement et installation des connecteurs Agent-Reach..."; Flags: waituntilterminated; Check: ShouldInstallAgentReach
Filename: "{sys}\wscript.exe"; Parameters: """{app}\START_NIANG_IA.vbs"""; Description: "Launch NIANG IA"; WorkingDir: "{app}"; Flags: postinstall nowait skipifsilent

[Code]
const
  HexDigits = '0123456789ABCDEF';
  GeminiApiKeyUrl = 'https://aistudio.google.com/apikey';

var
  PersonalizationPage: TWizardPage;
  ApiKeyPage: TWizardPage;
  AgentReachPage: TWizardPage;
  UserNameEdit: TNewEdit;
  LanguageCombo: TNewComboBox;
  GeminiKeyEdit: TNewEdit;
  AgentReachInstallCheck: TNewCheckBox;
  AgentReachSessionReuseCheck: TNewCheckBox;
  GetApiKeyButton: TNewButton;
  BrandLabel: TNewStaticText;
  TaglineLabel: TNewStaticText;
  SectionLabel: TNewStaticText;
  NameLabel: TNewStaticText;
  LanguageLabel: TNewStaticText;
  InfoLabel: TNewStaticText;
  ApiKeyTitle: TNewStaticText;
  ApiKeyDescription: TNewStaticText;
  ApiKeyLabel: TNewStaticText;
  ApiKeyInfo: TNewStaticText;
  AgentReachTitle: TNewStaticText;
  AgentReachInfo: TNewStaticText;
  ExistingProfile: Boolean;
  ExistingApiConfig: Boolean;

function UnicodeEscape(Code: Integer): string;
var
  I, Digit: Integer;
begin
  Result := '';
  for I := 1 to 4 do
  begin
    Digit := Code mod 16;
    Result := HexDigits[Digit + 1] + Result;
    Code := Code div 16;
  end;
end;

function JsonEscape(const Value: string): string;
var
  I: Integer;
  Code: Integer;
begin
  Result := '';
  for I := 1 to Length(Value) do
  begin
    Code := Ord(Value[I]);
    case Code of
      34: Result := Result + '\"';
      92: Result := Result + '\\';
      8: Result := Result + '\b';
      9: Result := Result + '\t';
      10: Result := Result + '\n';
      12: Result := Result + '\f';
      13: Result := Result + '\r';
    else
      if (Code < 32) or (Code > 126) then
        Result := Result + '\u' + UnicodeEscape(Code)
      else
        Result := Result + Value[I];
    end;
  end;
end;

procedure AddProfileField(var Json: string; var HasField: Boolean;
  const Name, Value: string);
begin
  if Trim(Value) = '' then
    Exit;
  if HasField then
    Json := Json + ',';
  Json := Json + Chr(13) + Chr(10) + '    "' + Name + '": {"value": "' +
    JsonEscape(Trim(Value)) + '"}';
  HasField := True;
end;

procedure OpenGeminiApiKeyPage(Sender: TObject); forward;

procedure InitializeWizard;
var
  ContentWidth, ContentLeft: Integer;
begin
  PersonalizationPage :=
    CreateCustomPage(wpSelectDir, '', '');

  ContentWidth := PersonalizationPage.Surface.Width - ScaleX(48);
  ContentLeft := ScaleX(24);

  BrandLabel := TNewStaticText.Create(WizardForm);
  BrandLabel.Parent := PersonalizationPage.Surface;
  BrandLabel.Caption := 'Niang IA';
  BrandLabel.Font.Name := 'Segoe UI';
  BrandLabel.Font.Size := 23;
  BrandLabel.Font.Style := [fsBold];
  BrandLabel.Font.Color := $00A63D20;
  BrandLabel.AutoSize := True;
  BrandLabel.Left := (PersonalizationPage.Surface.Width - BrandLabel.Width) div 2;
  BrandLabel.Top := ScaleY(8);

  TaglineLabel := TNewStaticText.Create(WizardForm);
  TaglineLabel.Parent := PersonalizationPage.Surface;
  TaglineLabel.Caption := 'Ton assistant, toujours avec toi';
  TaglineLabel.Font.Name := 'Segoe UI';
  TaglineLabel.Font.Size := 9;
  TaglineLabel.Font.Color := clGray;
  TaglineLabel.AutoSize := True;
  TaglineLabel.Left := (PersonalizationPage.Surface.Width - TaglineLabel.Width) div 2;
  TaglineLabel.Top := BrandLabel.Top + BrandLabel.Height;

  SectionLabel := TNewStaticText.Create(WizardForm);
  SectionLabel.Parent := PersonalizationPage.Surface;
  SectionLabel.Caption := 'Personnalisation de NIANG IA';
  SectionLabel.Font.Name := 'Segoe UI';
  SectionLabel.Font.Size := 15;
  SectionLabel.Font.Style := [fsBold];
  SectionLabel.Font.Color := clNavy;
  SectionLabel.AutoSize := True;
  SectionLabel.Left := ContentLeft;
  SectionLabel.Top := ScaleY(64);

  NameLabel := TNewStaticText.Create(WizardForm);
  NameLabel.Parent := PersonalizationPage.Surface;
  NameLabel.Caption := 'Comment veux-tu que NIANG IA t''appelle ?';
  NameLabel.Font.Name := 'Segoe UI';
  NameLabel.Font.Size := 10;
  NameLabel.Font.Style := [fsBold];
  NameLabel.AutoSize := True;
  NameLabel.Left := ContentLeft;
  NameLabel.Top := ScaleY(105);

  UserNameEdit := TNewEdit.Create(WizardForm);
  UserNameEdit.Parent := PersonalizationPage.Surface;
  UserNameEdit.Font.Name := 'Segoe UI';
  UserNameEdit.Font.Size := 10;
  UserNameEdit.Left := ContentLeft;
  UserNameEdit.Top := NameLabel.Top + ScaleY(24);
  UserNameEdit.Width := ContentWidth;
  UserNameEdit.Height := ScaleY(30);

  LanguageLabel := TNewStaticText.Create(WizardForm);
  LanguageLabel.Parent := PersonalizationPage.Surface;
  LanguageLabel.Caption := 'Langue par défaut de NIANG IA';
  LanguageLabel.Font.Name := 'Segoe UI';
  LanguageLabel.Font.Size := 10;
  LanguageLabel.Font.Style := [fsBold];
  LanguageLabel.AutoSize := True;
  LanguageLabel.Left := ContentLeft;
  LanguageLabel.Top := UserNameEdit.Top + UserNameEdit.Height +
    ScaleY(16);

  LanguageCombo := TNewComboBox.Create(WizardForm);
  LanguageCombo.Parent := PersonalizationPage.Surface;
  LanguageCombo.Font.Name := 'Segoe UI';
  LanguageCombo.Font.Size := 10;
  LanguageCombo.Style := csDropDown;
  LanguageCombo.Items.Add('Français');
  LanguageCombo.Items.Add('Wolof');
  LanguageCombo.Items.Add('English');
  LanguageCombo.Items.Add('Español');
  LanguageCombo.Items.Add('العربية');
  LanguageCombo.ItemIndex := 0;
  LanguageCombo.Left := ContentLeft;
  LanguageCombo.Top := LanguageLabel.Top + ScaleY(24);
  LanguageCombo.Width := ContentWidth;
  LanguageCombo.Height := ScaleY(30);

  InfoLabel := TNewStaticText.Create(WizardForm);
  InfoLabel.Parent := PersonalizationPage.Surface;
  InfoLabel.Caption :=
    'Ces informations sont facultatives. Une mise à jour conserve ton profil existant.';
  InfoLabel.Font.Name := 'Segoe UI';
  InfoLabel.Font.Size := 8;
  InfoLabel.Font.Color := clGray;
  InfoLabel.WordWrap := True;
  InfoLabel.AutoSize := False;
  InfoLabel.Left := ContentLeft;
  InfoLabel.Top := LanguageCombo.Top + LanguageCombo.Height +
    ScaleY(12);
  InfoLabel.Width := ContentWidth;
  InfoLabel.Height := ScaleY(30);

  ApiKeyPage := CreateCustomPage(PersonalizationPage.ID, '', '');

  ApiKeyTitle := TNewStaticText.Create(WizardForm);
  ApiKeyTitle.Parent := ApiKeyPage.Surface;
  ApiKeyTitle.Caption := 'Connecter NIANG IA';
  ApiKeyTitle.Font.Name := 'Segoe UI';
  ApiKeyTitle.Font.Size := 17;
  ApiKeyTitle.Font.Style := [fsBold];
  ApiKeyTitle.Font.Color := clNavy;
  ApiKeyTitle.AutoSize := True;
  ApiKeyTitle.Left := ContentLeft;
  ApiKeyTitle.Top := ScaleY(20);

  ApiKeyDescription := TNewStaticText.Create(WizardForm);
  ApiKeyDescription.Parent := ApiKeyPage.Surface;
  ApiKeyDescription.Caption :=
    'Crée ta clé Gemini gratuite, puis colle-la ci-dessous pour activer l''assistant.';
  ApiKeyDescription.Font.Name := 'Segoe UI';
  ApiKeyDescription.Font.Size := 9;
  ApiKeyDescription.Font.Color := clGray;
  ApiKeyDescription.WordWrap := True;
  ApiKeyDescription.AutoSize := False;
  ApiKeyDescription.Left := ContentLeft;
  ApiKeyDescription.Top := ApiKeyTitle.Top + ApiKeyTitle.Height +
    ScaleY(10);
  ApiKeyDescription.Width := ContentWidth;
  ApiKeyDescription.Height := ScaleY(42);

  GetApiKeyButton := TNewButton.Create(WizardForm);
  GetApiKeyButton.Parent := ApiKeyPage.Surface;
  GetApiKeyButton.Caption := 'Obtenir une clé Gemini';
  GetApiKeyButton.Font.Name := 'Segoe UI';
  GetApiKeyButton.Font.Size := 10;
  GetApiKeyButton.Left := ContentLeft;
  GetApiKeyButton.Top := ApiKeyDescription.Top +
    ApiKeyDescription.Height + ScaleY(10);
  GetApiKeyButton.Width := ContentWidth;
  GetApiKeyButton.Height := ScaleY(36);
  GetApiKeyButton.OnClick := @OpenGeminiApiKeyPage;

  ApiKeyLabel := TNewStaticText.Create(WizardForm);
  ApiKeyLabel.Parent := ApiKeyPage.Surface;
  ApiKeyLabel.Caption := 'Colle ici ta clé API Gemini';
  ApiKeyLabel.Font.Name := 'Segoe UI';
  ApiKeyLabel.Font.Size := 10;
  ApiKeyLabel.Font.Style := [fsBold];
  ApiKeyLabel.AutoSize := True;
  ApiKeyLabel.Left := ContentLeft;
  ApiKeyLabel.Top := GetApiKeyButton.Top + GetApiKeyButton.Height +
    ScaleY(18);

  GeminiKeyEdit := TNewEdit.Create(WizardForm);
  GeminiKeyEdit.Parent := ApiKeyPage.Surface;
  GeminiKeyEdit.Font.Name := 'Segoe UI';
  GeminiKeyEdit.Font.Size := 10;
  GeminiKeyEdit.PasswordChar := '*';
  GeminiKeyEdit.Left := ContentLeft;
  GeminiKeyEdit.Top := ApiKeyLabel.Top + ScaleY(24);
  GeminiKeyEdit.Width := ContentWidth;
  GeminiKeyEdit.Height := ScaleY(30);

  ApiKeyInfo := TNewStaticText.Create(WizardForm);
  ApiKeyInfo.Parent := ApiKeyPage.Surface;
  ApiKeyInfo.Caption :=
    'La clé est enregistrée localement. Tu peux aussi continuer et la configurer plus tard. ' +
    'Si le navigateur ne s''ouvre pas, visite ' + GeminiApiKeyUrl + '.';
  ApiKeyInfo.Font.Name := 'Segoe UI';
  ApiKeyInfo.Font.Size := 8;
  ApiKeyInfo.Font.Color := clGray;
  ApiKeyInfo.WordWrap := True;
  ApiKeyInfo.AutoSize := False;
  ApiKeyInfo.Left := ContentLeft;
  ApiKeyInfo.Top := GeminiKeyEdit.Top + GeminiKeyEdit.Height +
    ScaleY(10);
  ApiKeyInfo.Width := ContentWidth;
  ApiKeyInfo.Height := ScaleY(48);

  AgentReachPage := CreateCustomPage(ApiKeyPage.ID, '', '');

  AgentReachTitle := TNewStaticText.Create(WizardForm);
  AgentReachTitle.Parent := AgentReachPage.Surface;
  AgentReachTitle.Caption := 'Recherche Internet avec Agent-Reach';
  AgentReachTitle.Font.Name := 'Segoe UI';
  AgentReachTitle.Font.Size := 15;
  AgentReachTitle.Font.Style := [fsBold];
  AgentReachTitle.Font.Color := clNavy;
  AgentReachTitle.AutoSize := True;
  AgentReachTitle.Left := ContentLeft;
  AgentReachTitle.Top := ScaleY(14);

  AgentReachInfo := TNewStaticText.Create(WizardForm);
  AgentReachInfo.Parent := AgentReachPage.Surface;
  AgentReachInfo.Caption :=
    'L''installation telecharge uv 0.13.7 et Agent-Reach 1.6.1 depuis leurs sources officielles, ' +
    'puis installe les connecteurs et leurs dependances (dont OpenCLI, un navigateur dedie, ' +
    'des paquets Python/Node et FFmpeg). Une connexion Internet est necessaire; aucun droit ' +
    'administrateur n''est demande. Aucun cookie, identifiant ni cle API n''est fourni. ' +
    'Xiaoyuzhou est installe, mais sa transcription reste desactivee sans cle Groq protegee par DPAPI ' +
    'et approbation explicite a chaque appel; des frais de fournisseur peuvent s''appliquer.';
  AgentReachInfo.Font.Name := 'Segoe UI';
  AgentReachInfo.Font.Size := 8;
  AgentReachInfo.Font.Color := clGray;
  AgentReachInfo.WordWrap := True;
  AgentReachInfo.AutoSize := False;
  AgentReachInfo.Left := ContentLeft;
  AgentReachInfo.Top := AgentReachTitle.Top + AgentReachTitle.Height + ScaleY(10);
  AgentReachInfo.Width := ContentWidth;
  AgentReachInfo.Height := ScaleY(126);

  AgentReachInstallCheck := TNewCheckBox.Create(WizardForm);
  AgentReachInstallCheck.Parent := AgentReachPage.Surface;
  AgentReachInstallCheck.Caption :=
    'Telecharger et installer maintenant Agent-Reach et tous ses connecteurs declares';
  AgentReachInstallCheck.Font.Name := 'Segoe UI';
  AgentReachInstallCheck.Font.Size := 9;
  AgentReachInstallCheck.Left := ContentLeft;
  AgentReachInstallCheck.Top := AgentReachInfo.Top + AgentReachInfo.Height + ScaleY(8);
  AgentReachInstallCheck.Width := ContentWidth;
  AgentReachInstallCheck.Height := ScaleY(38);
  AgentReachInstallCheck.Checked := False;

  AgentReachSessionReuseCheck := TNewCheckBox.Create(WizardForm);
  AgentReachSessionReuseCheck.Parent := AgentReachPage.Surface;
  AgentReachSessionReuseCheck.Caption :=
    'J''autorise NIANG IA a reutiliser, uniquement pour une recherche demandee, les cookies locaux du site concerne dans son profil Agent-Reach dedie.';
  AgentReachSessionReuseCheck.Font.Name := 'Segoe UI';
  AgentReachSessionReuseCheck.Font.Size := 9;
  AgentReachSessionReuseCheck.Left := ContentLeft;
  AgentReachSessionReuseCheck.Top :=
    AgentReachInstallCheck.Top + AgentReachInstallCheck.Height + ScaleY(4);
  AgentReachSessionReuseCheck.Width := ContentWidth;
  AgentReachSessionReuseCheck.Height := ScaleY(48);
  AgentReachSessionReuseCheck.Checked := False;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  AppDir, DataDir, ReuseConsentPath: string;
  ReuseConsentValue: AnsiString;
begin
  Result := True;
  if CurPageID <> wpSelectDir then
    Exit;

  AppDir := AddBackslash(WizardDirValue);
  DataDir := ExpandConstant('{localappdata}\NIANG IA\');
  ExistingProfile :=
    FileExists(AppDir + 'memory\long_term.json') or
    FileExists(AppDir + 'memory\installer_profile.json') or
    FileExists(DataDir + 'memory\long_term.json') or
    FileExists(DataDir + 'memory\installer_profile.json');
  ExistingApiConfig :=
    FileExists(AppDir + 'config\installer_gemini_key.txt') or
    FileExists(AppDir + 'config\api_keys.json') or
    FileExists(DataDir + 'config\installer_gemini_key.txt') or
    FileExists(DataDir + 'config\api_keys.json') or
    FileExists(ExpandConstant('{localappdata}\NIANG IA\api_keys.dpapi'));

  ReuseConsentPath := AppDir + 'config\agent_reach_session_reuse.txt';
  if LoadStringFromFile(ReuseConsentPath, ReuseConsentValue) then
    AgentReachSessionReuseCheck.Checked :=
      Lowercase(Trim(ReuseConsentValue)) = 'true'
  else
    AgentReachSessionReuseCheck.Checked := False;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result :=
    ((PageID = PersonalizationPage.ID) and ExistingProfile) or
    ((PageID = ApiKeyPage.ID) and ExistingApiConfig);
end;

function ShouldInstallAgentReach: Boolean;
begin
  Result := Assigned(AgentReachInstallCheck) and AgentReachInstallCheck.Checked;
end;

procedure OpenGeminiApiKeyPage(Sender: TObject);
var
  ErrorCode: Integer;
begin
  if ShellExec('open', GeminiApiKeyUrl, '', '', SW_SHOWNORMAL, ewNoWait,
    ErrorCode) then
    Exit;

  if Exec(ExpandConstant('{sys}\rundll32.exe'),
    'url.dll,FileProtocolHandler "' + GeminiApiKeyUrl + '"', '',
    SW_SHOWNORMAL, ewNoWait, ErrorCode) then
    Exit;

  MsgBox('Impossible d''ouvrir Google AI Studio. Va sur ' + GeminiApiKeyUrl +
    ' pour créer ta clé Gemini.', mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Json, IdentityFields, ProfilePath, KeyPath, DataDir,
  ReuseConsentPath: string;
  ReuseConsentValue: AnsiString;
  HasIdentityField: Boolean;
begin
  if CurStep <> ssPostInstall then
    Exit;

  DataDir := ExpandConstant('{localappdata}\NIANG IA\');
  if not ExistingProfile then
  begin
    IdentityFields := '';
    HasIdentityField := False;
    AddProfileField(IdentityFields, HasIdentityField, 'name',
      UserNameEdit.Text);
    AddProfileField(IdentityFields, HasIdentityField, 'language',
      LanguageCombo.Text);

    Json := '{' + Chr(13) + Chr(10) + '  "identity": {' + IdentityFields +
      Chr(13) + Chr(10) + '  }' + Chr(13) + Chr(10) + '}' + Chr(13) + Chr(10);
    ProfilePath := DataDir + 'memory\installer_profile.json';
    if not ForceDirectories(ExtractFileDir(ProfilePath)) then
      RaiseException('Impossible de créer le dossier du profil utilisateur.');
    if not SaveStringToFile(ProfilePath, Json, False) then
      RaiseException('Impossible d''enregistrer le profil utilisateur sur cet ordinateur.');
  end;

  if (not ExistingApiConfig) and (Trim(GeminiKeyEdit.Text) <> '') then
  begin
    KeyPath := DataDir + 'config\installer_gemini_key.txt';
    if not ForceDirectories(ExtractFileDir(KeyPath)) then
      RaiseException('Impossible de créer le dossier de configuration.');
    if not SaveStringToFile(KeyPath, Trim(GeminiKeyEdit.Text), False) then
      RaiseException('Impossible d''enregistrer la clé Gemini sur cet ordinateur.');
  end;

  ReuseConsentPath := AddBackslash(WizardDirValue) +
    'config\agent_reach_session_reuse.txt';
  if (not WizardSilent) or (not FileExists(ReuseConsentPath)) then
  begin
    ReuseConsentValue := 'false';
    if Assigned(AgentReachSessionReuseCheck) and AgentReachSessionReuseCheck.Checked then
      ReuseConsentValue := 'true';
    if not ForceDirectories(ExtractFileDir(ReuseConsentPath)) then
      RaiseException('Impossible de créer le dossier de configuration Agent-Reach.');
    if not SaveStringToFile(ReuseConsentPath, ReuseConsentValue, False) then
      RaiseException('Impossible d''enregistrer le choix de réutilisation des cookies locaux.');
  end;
end;
