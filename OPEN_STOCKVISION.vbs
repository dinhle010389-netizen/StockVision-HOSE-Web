Option Explicit
Dim fso, sh, root, pythonw, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = root & "\.venv\Scripts\pythonw.exe"
If fso.FileExists(pythonw) Then
  cmd = Chr(34) & pythonw & Chr(34) & " " & Chr(34) & root & "\desktop_launcher.py" & Chr(34)
  sh.Run cmd, 0, False
Else
  sh.Run Chr(34) & root & "\START_STOCKVISION.bat" & Chr(34), 1, False
End If
