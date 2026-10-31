#define AppName "NIANG IA"
#define AppVersion "1.0.19"
#define SourceDir AddBackslash(SourcePath) + "dist\NIANG_IA_" + AppVersion

[Setup]
AppId={{AC51AB64-08DA-4BC6-9CE1-1D5D0AD4B304}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\Programs\NIANG IA
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
Name: "{group}\NIANG IA"; Filename: "{app}\START_NIANG_IA.bat"; WorkingDir: "{app}"; IconFilename: "{app}\assets\niang_ia.ico"
Name: "{autodesktop}\NIANG IA"; Filename: "{app}\START_NIANG_IA.bat"; WorkingDir: "{app}"; IconFilename: "{app}\assets\niang_ia.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\START_NIANG_IA.bat"; Description: "Launch NIANG IA"; WorkingDir: "{app}"; Flags: postinstall nowait skipifsilent

[Code]
const
  HexDigits = '0123456789ABCDEF';

var
  PersonalizationPage: TWizardPage;
  ApiKeyPage: TWizardPage;
  UserNameEdit: TNewEdit;
  LanguageCombo: TNewComboBox;
  GeminiKeyEdit: TNewEdit;
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
  ExistingProfile :=
    FileExists(ExpandConstant('{app}\memory\long_term.json')) or
    FileExists(ExpandConstant('{app}\memory\installer_profile.json'));
  ExistingApiConfig :=
    FileExists(ExpandConstant('{app}\config\installer_gemini_key.txt')) or
    FileExists(ExpandConstant('{app}\config\api_keys.json'));

  PersonalizationPage :=
    CreateCustomPage(wpWelcome, '', '');

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
    'La clé est enregistrée localement. Tu peux aussi continuer et la configurer plus tard.';
  ApiKeyInfo.Font.Name := 'Segoe UI';
  ApiKeyInfo.Font.Size := 8;
  ApiKeyInfo.Font.Color := clGray;
  ApiKeyInfo.WordWrap := True;
  ApiKeyInfo.AutoSize := False;
  ApiKeyInfo.Left := ContentLeft;
  ApiKeyInfo.Top := GeminiKeyEdit.Top + GeminiKeyEdit.Height +
    ScaleY(10);
  ApiKeyInfo.Width := ContentWidth;
  ApiKeyInfo.Height := ScaleY(36);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result :=
    ((PageID = PersonalizationPage.ID) and ExistingProfile) or
    ((PageID = ApiKeyPage.ID) and ExistingApiConfig);
end;

procedure OpenGeminiApiKeyPage(Sender: TObject);
var
  ErrorCode: Integer;
begin
  if not ShellExec('open', 'https://aistudio.google.com/apikey', '', '',
    SW_SHOWNORMAL, ewNoWait, ErrorCode) then
    MsgBox('Impossible d''ouvrir Google AI Studio. Va sur ' +
      'https://aistudio.google.com/apikey pour créer ta clé Gemini.',
      mbError, MB_OK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Json, IdentityFields, ProfilePath, KeyPath: string;
  HasIdentityField: Boolean;
begin
  if CurStep <> ssPostInstall then
    Exit;

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
    ProfilePath := ExpandConstant('{app}\memory\installer_profile.json');
    if not ForceDirectories(ExtractFileDir(ProfilePath)) then
      RaiseException('Impossible de créer le dossier du profil utilisateur.');
    if not SaveStringToFile(ProfilePath, Json, False) then
      RaiseException('Impossible d''enregistrer le profil utilisateur sur cet ordinateur.');
  end;

  if (not ExistingApiConfig) and (Trim(GeminiKeyEdit.Text) <> '') then
  begin
    KeyPath := ExpandConstant('{app}\config\installer_gemini_key.txt');
    if not ForceDirectories(ExtractFileDir(KeyPath)) then
      RaiseException('Impossible de créer le dossier de configuration.');
    if not SaveStringToFile(KeyPath, Trim(GeminiKeyEdit.Text), False) then
      RaiseException('Impossible d''enregistrer la clé Gemini sur cet ordinateur.');
  end;
end;
