param(
    [string]$BackupPath,
    [string]$Destination
)

$ErrorActionPreference = 'Stop'

Add-Type -AssemblyName System.Security
Add-Type -AssemblyName System.Windows.Forms

$backupFiles = @()
if ($BackupPath) {
    $backupFiles = @(Get-Item -LiteralPath $BackupPath -ErrorAction Stop)
} else {
    $backupFiles = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter 'NIANG_IA_*.nia' -File)
    if ($backupFiles.Count -ne 1) {
        throw "Expected exactly one NIANG IA backup archive beside this script; found $($backupFiles.Count)."
    }
}

$backupPath = $backupFiles[0].FullName
$destination = if ($Destination) {
    [System.IO.Path]::GetFullPath($Destination)
} else {
    Join-Path $HOME 'Downloads\NIANG_IA_1.0.24_Restored'
}
if (Test-Path -LiteralPath $destination) {
    throw "The restore destination already exists. Move it or rename it before restoring: $destination"
}

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Restaurer la sauvegarde NIANG IA'
$form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
$form.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$form.ClientSize = New-Object System.Drawing.Size(440, 202)
$form.MaximizeBox = $false
$form.MinimizeBox = $false

$message = New-Object System.Windows.Forms.Label
$message.Location = New-Object System.Drawing.Point(16, 14)
$message.Size = New-Object System.Drawing.Size(408, 38)
$message.Text = "Saisissez le mot de passe de la sauvegarde. Les fichiers seront restaurés dans :`r`n$destination"
$form.Controls.Add($message)

$passwordLabel = New-Object System.Windows.Forms.Label
$passwordLabel.Location = New-Object System.Drawing.Point(16, 64)
$passwordLabel.Size = New-Object System.Drawing.Size(150, 22)
$passwordLabel.Text = 'Mot de passe :'
$form.Controls.Add($passwordLabel)

$passwordBox = New-Object System.Windows.Forms.TextBox
$passwordBox.Location = New-Object System.Drawing.Point(172, 62)
$passwordBox.Size = New-Object System.Drawing.Size(248, 24)
$passwordBox.UseSystemPasswordChar = $true
$form.Controls.Add($passwordBox)

$confirmLabel = New-Object System.Windows.Forms.Label
$confirmLabel.Location = New-Object System.Drawing.Point(16, 98)
$confirmLabel.Size = New-Object System.Drawing.Size(150, 22)
$confirmLabel.Text = 'Confirmez :'
$form.Controls.Add($confirmLabel)

$confirmBox = New-Object System.Windows.Forms.TextBox
$confirmBox.Location = New-Object System.Drawing.Point(172, 96)
$confirmBox.Size = New-Object System.Drawing.Size(248, 24)
$confirmBox.UseSystemPasswordChar = $true
$form.Controls.Add($confirmBox)

$okButton = New-Object System.Windows.Forms.Button
$okButton.Location = New-Object System.Drawing.Point(238, 150)
$okButton.Size = New-Object System.Drawing.Size(88, 30)
$okButton.Text = 'Restaurer'
$okButton.DialogResult = [System.Windows.Forms.DialogResult]::OK
$form.Controls.Add($okButton)

$cancelButton = New-Object System.Windows.Forms.Button
$cancelButton.Location = New-Object System.Drawing.Point(332, 150)
$cancelButton.Size = New-Object System.Drawing.Size(88, 30)
$cancelButton.Text = 'Annuler'
$cancelButton.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
$form.Controls.Add($cancelButton)
$form.AcceptButton = $okButton
$form.CancelButton = $cancelButton

if ($form.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) {
    throw 'Restauration annulée.'
}
if ([string]::IsNullOrWhiteSpace($passwordBox.Text) -or $passwordBox.Text -cne $confirmBox.Text) {
    $passwordBox.Clear()
    $confirmBox.Clear()
    $form.Dispose()
    throw 'Le mot de passe est vide ou les deux saisies ne correspondent pas.'
}

$password = $passwordBox.Text
$passwordBox.Clear()
$confirmBox.Clear()
$form.Dispose()

$tarCommand = Get-Command tar.exe -ErrorAction Stop
$stream = $null
$hmac = $null
$aes = $null
$process = $null
$encryptionKey = $null
$authenticationKey = $null
$createdDestination = $false

try {
    $stream = [System.IO.File]::OpenRead($backupPath)
    $magic = New-Object byte[] 8
    if ($stream.Read($magic, 0, $magic.Length) -ne $magic.Length -or
        [System.Text.Encoding]::ASCII.GetString($magic) -cne 'NIANGIA1') {
        throw 'This is not a supported NIANG IA backup.'
    }

    $metadata = New-Object byte[] 36
    if ($stream.Read($metadata, 0, $metadata.Length) -ne $metadata.Length) {
        throw 'The backup header is incomplete.'
    }
    $iterations = [System.BitConverter]::ToInt32($metadata, 0)
    if ($iterations -lt 100000 -or $iterations -gt 2000000) {
        throw 'The backup encryption settings are invalid.'
    }

    $header = New-Object byte[] 44
    [Array]::Copy($magic, 0, $header, 0, 8)
    [Array]::Copy($metadata, 0, $header, 8, $metadata.Length)
    $salt = New-Object byte[] 16
    $iv = New-Object byte[] 16
    [Array]::Copy($metadata, 4, $salt, 0, $salt.Length)
    [Array]::Copy($metadata, 20, $iv, 0, $iv.Length)

    $pbkdf = [System.Security.Cryptography.Rfc2898DeriveBytes]::new(
        $password,
        $salt,
        $iterations,
        [System.Security.Cryptography.HashAlgorithmName]::SHA256
    )
    $keys = $pbkdf.GetBytes(64)
    $pbkdf.Dispose()
    $encryptionKey = New-Object byte[] 32
    $authenticationKey = New-Object byte[] 32
    [Array]::Copy($keys, 0, $encryptionKey, 0, 32)
    [Array]::Copy($keys, 32, $authenticationKey, 0, 32)
    [Array]::Clear($keys, 0, $keys.Length)

    $hmac = [System.Security.Cryptography.HMACSHA256]::new($authenticationKey)
    $null = $hmac.TransformBlock($header, 0, $header.Length, $header, 0)
    $ciphertextLength = $stream.Length - $header.Length - 32
    if ($ciphertextLength -le 0 -or ($ciphertextLength % 16) -ne 0) {
        throw 'The backup archive is incomplete.'
    }

    $buffer = New-Object byte[] 65536
    $remaining = $ciphertextLength
    while ($remaining -gt 0) {
        $requested = [int][Math]::Min($buffer.Length, $remaining)
        $read = 0
        while ($read -lt $requested) {
            $count = $stream.Read($buffer, $read, $requested - $read)
            if ($count -eq 0) {
                throw 'The backup archive ended unexpectedly.'
            }
            $read += $count
        }
        $null = $hmac.TransformBlock($buffer, 0, $read, $buffer, 0)
        $remaining -= $read
    }

    $null = $hmac.TransformFinalBlock((New-Object byte[] 0), 0, 0)
    $expectedTag = New-Object byte[] 32
    if ($stream.Read($expectedTag, 0, $expectedTag.Length) -ne $expectedTag.Length) {
        throw 'The backup authentication data is incomplete.'
    }
    $difference = 0
    for ($index = 0; $index -lt $expectedTag.Length; $index++) {
        $difference = $difference -bor ($expectedTag[$index] -bxor $hmac.Hash[$index])
    }
    if ($difference -ne 0) {
        throw 'The password is incorrect or the backup has been modified.'
    }

    $stream.Position = $header.Length
    $aes = [System.Security.Cryptography.Aes]::Create()
    $aes.KeySize = 256
    $aes.BlockSize = 128
    $aes.Mode = [System.Security.Cryptography.CipherMode]::CBC
    $aes.Padding = [System.Security.Cryptography.PaddingMode]::PKCS7
    $aes.Key = $encryptionKey
    $aes.IV = $iv
    $decryptor = $aes.CreateDecryptor()

    New-Item -ItemType Directory -Path $destination | Out-Null
    $createdDestination = $true
    $arguments = '-xzf - -C "' + $destination + '"'
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = $tarCommand.Source
    $startInfo.Arguments = $arguments
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardInput = $true
    $startInfo.RedirectStandardError = $true
    $process = [System.Diagnostics.Process]::Start($startInfo)
    $tarInput = $process.StandardInput.BaseStream
    $remaining = $ciphertextLength - 16
    while ($remaining -gt 0) {
        $requested = [int][Math]::Min($buffer.Length, $remaining)
        $read = 0
        while ($read -lt $requested) {
            $count = $stream.Read($buffer, $read, $requested - $read)
            if ($count -eq 0) {
                throw 'The backup archive ended unexpectedly during extraction.'
            }
            $read += $count
        }
        $plain = $decryptor.TransformBlock($buffer, 0, $read, $buffer, 0)
        if ($plain -gt 0) {
            $tarInput.Write($buffer, 0, $plain)
        }
        $remaining -= $read
    }

    $lastCipherBlock = New-Object byte[] 16
    if ($stream.Read($lastCipherBlock, 0, $lastCipherBlock.Length) -ne $lastCipherBlock.Length) {
        throw 'Le bloc final de la sauvegarde est incomplet.'
    }
    $finalPlain = $decryptor.TransformFinalBlock($lastCipherBlock, 0, $lastCipherBlock.Length)
    if ($finalPlain.Length -gt 0) {
        $tarInput.Write($finalPlain, 0, $finalPlain.Length)
    }
    $tarInput.Dispose()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) {
        $errorText = $process.StandardError.ReadToEnd()
        throw "Échec de l'extraction de la sauvegarde : $errorText"
    }

    Write-Output "NIANG IA restaurée dans : $destination"
    $appFolder = Join-Path $destination 'NIANG_IA'
    Write-Output "Pour démarrer NIANG IA, lancez START_NIANG_IA.bat dans : $appFolder"
} catch {
    if ($process -and -not $process.HasExited) {
        $process.Kill()
        $process.WaitForExit()
    }
    if ($createdDestination -and (Test-Path -LiteralPath $destination)) {
        Remove-Item -LiteralPath $destination -Recurse -Force
    }
    throw
} finally {
    if ($stream) { $stream.Dispose() }
    if ($hmac) { $hmac.Dispose() }
    if ($aes) { $aes.Dispose() }
    if ($process) { $process.Dispose() }
    if ($encryptionKey) { [Array]::Clear($encryptionKey, 0, $encryptionKey.Length) }
    if ($authenticationKey) { [Array]::Clear($authenticationKey, 0, $authenticationKey.Length) }
    $password = $null
}
