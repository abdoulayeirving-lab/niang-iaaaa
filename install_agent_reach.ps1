param(
    [switch]$PlanOnly
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$UvVersion = "0.13.7"
$UvArchiveName = "uv-x86_64-pc-windows-msvc.zip"
$UvArchiveUrl = "https://releases.astral.sh/github/uv/releases/download/$UvVersion/$UvArchiveName"
$UvArchiveSha256 = "0cdc5b38fe5a8168ed6a25814f5ba43c21d313dd3187314fccb37b7cec46e021"
$AgentReachVersion = "1.6.1"
$AgentReachArchiveUrl = "https://github.com/Panniantong/Agent-Reach/releases/download/v$AgentReachVersion/agent-reach.zip"
$AgentReachArchiveSha256 = "51443d733bcb26064262442083a8f8abf6ba5e3e7df54beebafe98c88be04a60"
$OptionalChannels = @(
    "twitter",
    "reddit",
    "facebook",
    "instagram",
    "xiaohongshu",
    "linkedin",
    "boss",
    "xueqiu",
    "xiaoyuzhou"
)

if ($PlanOnly) {
    Write-Output "uv $UvVersion ($UvArchiveSha256)"
    Write-Output "Agent-Reach $AgentReachVersion ($AgentReachArchiveSha256)"
    Write-Output "Default channels: github, youtube, bilibili, v2ex, web"
    Write-Output ("Optional channels: " + ($OptionalChannels -join ", "))
    Write-Output "Target: %LOCALAPPDATA%\NIANG IA\agent_reach (isolated)"
    Write-Output "No API keys, cookies, or provider credentials are configured."
    exit 0
}

function Show-SetupFailure([string]$Message) {
    Write-Host "[ERREUR] $Message" -ForegroundColor Red
    try {
        Add-Type -AssemblyName System.Windows.Forms
        [System.Windows.Forms.MessageBox]::Show(
            "$Message`r`n`r`nTu peux relancer install_agent_reach.ps1 depuis le dossier de NIANG IA.",
            "Installation d'Agent-Reach",
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Warning
        ) | Out-Null
    }
    catch {
        Write-Warning "L'installation d'Agent-Reach a echoue. Consulte la sortie PowerShell."
    }
}

function Get-Python312 {
    $pythonPath = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (Test-Path -LiteralPath $pythonPath -PathType Leaf) {
        & $pythonPath -c "import sys; raise SystemExit(sys.version_info[:2] != (3, 12))" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return $pythonPath
        }
    }

    $pythonInstaller = Join-Path $PSScriptRoot "runtime\python-3.12.10-amd64.exe"
    if (-not (Test-Path -LiteralPath $pythonInstaller -PathType Leaf)) {
        throw "Python 3.12 is not installed and the bundled Python installer is missing."
    }

    $pythonDir = Split-Path -Parent $pythonPath
    $installArguments = @(
        "/quiet",
        "InstallAllUsers=0",
        "TargetDir=`"$pythonDir`"",
        "PrependPath=0",
        "Include_launcher=0",
        "Include_pip=1",
        "Include_tcltk=1",
        "Include_test=0",
        "Shortcuts=0"
    )
    $process = Start-Process -FilePath $pythonInstaller `
        -ArgumentList $installArguments -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        throw "The bundled Python installer exited with code $($process.ExitCode)."
    }
    if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
        throw "Python 3.12 was not found after its per-user installation."
    }
    return $pythonPath
}

function Get-VerifiedDownload(
    [string]$Url,
    [string]$ExpectedSha256,
    [string]$Destination
) {
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Destination -TimeoutSec 300
    $actualSha256 = (Get-FileHash -LiteralPath $Destination -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualSha256 -ne $ExpectedSha256) {
        throw "SHA-256 verification failed for $([System.IO.Path]::GetFileName($Destination))."
    }
}

function Invoke-AgentReach([string]$Executable, [string[]]$Arguments) {
    $output = & $Executable @Arguments 2>&1
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Agent-Reach $($Arguments -join ' ') exited with code $exitCode."
    }
    try {
        $result = (($output | Out-String).Trim() | ConvertFrom-Json -ErrorAction Stop)
    }
    catch {
        throw "Agent-Reach $($Arguments -join ' ') returned invalid JSON."
    }
    if ($result.ok -ne $true) {
        $errorCode = if ($result.error.code) { $result.error.code } else { "UNKNOWN" }
        throw "Agent-Reach $($Arguments -join ' ') failed ($errorCode)."
    }
}

$installRoot = Join-Path $env:LOCALAPPDATA "NIANG IA\agent_reach"
$uvHome = Join-Path $installRoot "uv"
$toolDir = Join-Path $installRoot "uv_tools"
$toolBinDir = Join-Path $installRoot "bin"
$cacheDir = Join-Path $installRoot "cache"
$agentReachHome = Join-Path $installRoot "home"
$uvExe = Join-Path $uvHome "uv.exe"
$agentReachExe = Join-Path $toolDir "agent-reach\Scripts\agent-reach.exe"
$temporaryRoot = Join-Path $env:TEMP ("niang-agent-reach-" + [guid]::NewGuid().ToString("N"))

try {
    foreach ($directory in @($uvHome, $toolDir, $toolBinDir, $cacheDir, $agentReachHome, $temporaryRoot)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }

    $env:HOME = $agentReachHome
    $env:UV_TOOL_DIR = $toolDir
    $env:UV_TOOL_BIN_DIR = $toolBinDir
    $env:UV_CACHE_DIR = $cacheDir
    $env:UV_NO_CONFIG = "1"
    $env:UV_PYTHON_DOWNLOADS = "never"
    $env:UV_NO_PROGRESS = "1"
    Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue

    $uvArchive = Join-Path $temporaryRoot $UvArchiveName
    $uvExtract = Join-Path $temporaryRoot "uv"
    Get-VerifiedDownload $UvArchiveUrl $UvArchiveSha256 $uvArchive
    Expand-Archive -LiteralPath $uvArchive -DestinationPath $uvExtract -Force
    $uvMatches = @(Get-ChildItem -LiteralPath $uvExtract -Filter "uv.exe" -File -Recurse)
    if ($uvMatches.Count -ne 1) {
        throw "The verified uv archive did not contain exactly one uv.exe."
    }
    Copy-Item -LiteralPath $uvMatches[0].FullName -Destination $uvExe -Force

    $pythonExe = Get-Python312
    $reachArchive = Join-Path $temporaryRoot "agent-reach.zip"
    Get-VerifiedDownload $AgentReachArchiveUrl $AgentReachArchiveSha256 $reachArchive

    & $uvExe tool install --force --python $pythonExe $reachArchive
    if ($LASTEXITCODE -ne 0) {
        throw "uv could not install Agent-Reach into the isolated tool environment."
    }
    if (-not (Test-Path -LiteralPath $agentReachExe -PathType Leaf)) {
        throw "Agent-Reach was not found in its isolated tool environment."
    }

    Invoke-AgentReach $agentReachExe @("setup")
    $failedChannels = [System.Collections.Generic.List[string]]::new()
    foreach ($channel in $OptionalChannels) {
        try {
            Invoke-AgentReach $agentReachExe @("add", $channel)
            Write-Host "Agent-Reach channel installed: $channel"
        }
        catch {
            $failedChannels.Add($channel)
            Write-Warning "Agent-Reach channel $channel could not be installed: $($_.Exception.Message)"
        }
    }

    if ($failedChannels.Count -gt 0) {
        throw ("Some optional channels could not be installed: " +
            ($failedChannels -join ", ") +
            ". Check the connection and rerun install_agent_reach.ps1.")
    }

    Write-Host "Agent-Reach $AgentReachVersion and all declared channels are installed."
}
catch {
    Show-SetupFailure "La configuration d'Agent-Reach a echoue : $($_.Exception.Message)"
    exit 1
}
finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        try {
            Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
        }
        catch {
            Write-Warning "Temporary installer files could not be removed from $temporaryRoot."
        }
    }
}

exit 0
