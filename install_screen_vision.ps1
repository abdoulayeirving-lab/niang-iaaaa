$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$model = "qwen3-vl:2b"
$ollamaVersion = "0.40.13"
$installerUrl = "https://github.com/ollama/ollama/releases/download/v$ollamaVersion/OllamaSetup.exe"
$installerSha256 = "9e3c76e54e7184c68e88a2378b909bf59bbe454f83c076cb4f4a717e946ae719"
$ollamaPath = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
$apiUrl = "http://127.0.0.1:11434/api/tags"

function Test-OllamaApi {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $apiUrl -TimeoutSec 3
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Show-SetupFailure([string]$message) {
    Write-Host "[ERREUR] $message" -ForegroundColor Red
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(
            "$message`r`n`r`nTu peux relancer install_screen_vision.ps1 depuis le dossier de NIANG IA.",
            "Installation de la vision locale",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning
        ) | Out-Null
    }
    catch {
        Write-Warning "Affiche cette erreur et relance install_screen_vision.ps1 après avoir corrigé le problème."
    }
}

function Test-OllamaNeedsInstall {
    if (-not (Test-Path -LiteralPath $ollamaPath -PathType Leaf)) {
        return $true
    }

    $versionOutput = & $ollamaPath --version 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "Impossible de vérifier la version d'Ollama."
    }
    $versionMatch = [regex]::Match(($versionOutput -join " "), "\b(\d+\.\d+\.\d+)\b")
    if (-not $versionMatch.Success) {
        throw "La version d'Ollama n'a pas pu être identifiée."
    }
    return [version]$versionMatch.Groups[1].Value -lt [version]"0.12.7"
}

try {
    $ollamaCommand = Get-Command "ollama.exe" -ErrorAction SilentlyContinue
    if ($ollamaCommand) {
        $ollamaPath = $ollamaCommand.Source
    }

    if (Test-OllamaNeedsInstall) {
        Write-Host "Téléchargement de l'installateur officiel Ollama $ollamaVersion..."
        $ollamaInstallerName = "NIANG-IA-OllamaSetup-$ollamaVersion-$([guid]::NewGuid().ToString('N')).exe"
        $ollamaInstaller = Join-Path $env:TEMP $ollamaInstallerName
        try {
            Invoke-WebRequest -UseBasicParsing -Uri $installerUrl -OutFile $ollamaInstaller
            $actualHash = (Get-FileHash -LiteralPath $ollamaInstaller -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actualHash -ne $installerSha256) {
                throw "La vérification SHA-256 de l'installateur Ollama a échoué."
            }

            Write-Host "Installation d'Ollama pour l'utilisateur actuel..."
            $process = Start-Process -FilePath $ollamaInstaller `
                -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-" `
                -Wait -PassThru
            if ($process.ExitCode -ne 0) {
                throw "L'installateur Ollama s'est terminé avec le code $($process.ExitCode)."
            }
        }
        finally {
            if (Test-Path -LiteralPath $ollamaInstaller) {
                Remove-Item -LiteralPath $ollamaInstaller -Force
            }
        }
    }

    if (-not (Test-Path -LiteralPath $ollamaPath -PathType Leaf)) {
        throw "Ollama est introuvable après son installation."
    }

    if (-not (Test-OllamaApi)) {
        Write-Host "Démarrage du service Ollama local..."
        Start-Process -FilePath $ollamaPath -ArgumentList "serve" -WindowStyle Hidden
        $apiReady = $false
        for ($attempt = 0; $attempt -lt 40; $attempt++) {
            Start-Sleep -Seconds 3
            if (Test-OllamaApi) {
                $apiReady = $true
                break
            }
        }
        if (-not $apiReady) {
            throw "Le service Ollama n'a pas démarré sur 127.0.0.1:11434."
        }
    }

    $modelResponse = Invoke-WebRequest -UseBasicParsing -Uri $apiUrl -TimeoutSec 10
    $installedModels = ($modelResponse.Content | ConvertFrom-Json).models
    $modelInstalled = $false
    foreach ($installedModel in $installedModels) {
        if ($installedModel.name -eq $model -or $installedModel.name -like ($model + ":*")) {
            $modelInstalled = $true
            break
        }
    }

    if ($modelInstalled) {
        Write-Host "Le modèle $model est déjà installé."
    }
    else {
        Write-Host "Téléchargement du modèle $model (environ 1,9 Go)..."
        & $ollamaPath pull $model
        if ($LASTEXITCODE -ne 0) {
            throw "Le téléchargement de $model a échoué (code $LASTEXITCODE)."
        }
    }

    Write-Host "La vision locale de NIANG IA est prête."
    exit 0
}
catch {
    Show-SetupFailure "La configuration de la vision locale a échoué : $($_.Exception.Message)"
    exit 1
}
