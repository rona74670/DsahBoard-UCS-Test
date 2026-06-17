' Start UCS Dashboard Server (hidden - no black window)
Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = Left(WScript.ScriptFullName, InStrRev(WScript.ScriptFullName, "\")) & "backend"
objShell.Run "py -m uvicorn app:app --host 0.0.0.0 --port 9000", 0, False

' Open browser after short delay
WScript.Sleep 2000
objShell.Run "http://localhost:9000", 1, False
