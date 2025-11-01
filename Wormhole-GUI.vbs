' Save at repo root as Wormhole-GUI.vbs
Set oShell = CreateObject("Wscript.Shell")
Set oFSO = CreateObject("Scripting.FileSystemObject")
exe = oFSO.BuildPath(CreateObject("WScript.Shell").CurrentDirectory, "dist\wormhole\wormhole.exe")
oShell.Run """" & exe & """" & " --gui", 0, False
