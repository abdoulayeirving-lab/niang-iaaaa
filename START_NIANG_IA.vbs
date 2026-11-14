Option Explicit

Dim fso, shell, baseDir, pythonw, mainScript, voiceScript, batchFile, command
Dim entryScript, argument
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = fso.BuildPath(baseDir, ".venv\Scripts\pythonw.exe")
mainScript = fso.BuildPath(baseDir, "main.py")
voiceScript = fso.BuildPath(baseDir, "voice_launcher.py")
batchFile = fso.BuildPath(baseDir, "START_NIANG_IA.bat")
entryScript = mainScript

For Each argument In WScript.Arguments
    If LCase(CStr(argument)) = "--voice" Then
        entryScript = voiceScript
    End If
Next

If Not fso.FileExists(entryScript) Then
    MsgBox "Le point d'entrée de NIANG IA est introuvable.", vbCritical, "NIANG IA"
    WScript.Quit 1
End If

If fso.FileExists(pythonw) Then
    command = Quote(pythonw) & " -u " & Quote(entryScript)
    For Each argument In WScript.Arguments
        If LCase(CStr(argument)) <> "--voice" Then
            command = command & " " & Quote(CStr(argument))
        End If
    Next
    shell.Run command, 0, False
ElseIf fso.FileExists(batchFile) Then
    ' First launch: keep setup visible so installation errors are not hidden.
    shell.Run Quote(batchFile), 1, False
Else
    MsgBox "Pythonw est introuvable. Relancez l'installation de NIANG IA.", vbCritical, "NIANG IA"
    WScript.Quit 1
End If

Function Quote(value)
    Quote = Chr(34) & value & Chr(34)
End Function
