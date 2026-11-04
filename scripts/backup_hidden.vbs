Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(files.GetParentFolderName(WScript.ScriptFullName))
shell.CurrentDirectory = root
command = Chr(34) & root & "\.venv\Scripts\python.exe" & Chr(34) & " " & Chr(34) & root & "\manage.py" & Chr(34) & " backup --scheduled"
WScript.Quit shell.Run(command, 0, True)
