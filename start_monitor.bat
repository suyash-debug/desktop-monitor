@echo off
cd /d "d:\code\desktop-monitor"
taskkill /F /IM python.exe /T >/dev/null 2>&1
timeout /t 2 /nobreak >/dev/null
"C:\Program Files\Python314\python.exe" -m src.main >> "d:\code\desktop-monitor\monitor.log" 2>&1
