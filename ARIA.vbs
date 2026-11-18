' ARIA launcher - double-click this (no console window flash).
' Optional args after the script name are forwarded to launch.ps1, e.g.
'   wscript ARIA.vbs -Width 380
Dim sh, fso, here, args, i, cmd
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
args = ""
For i = 0 To WScript.Arguments.Count - 1
  args = args & " " & WScript.Arguments(i)
Next
cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & _
      here & "\launch.ps1"" " & args
sh.Run cmd, 0, False
