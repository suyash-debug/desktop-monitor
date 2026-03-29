@echo off
schtasks /create /tn "DesktopMonitor" /tr "wscript.exe \"d:\code\desktop-monitor\start_monitor.vbs\"" /sc onlogon /rl highest /f
echo Task registered. Desktop Monitor will start automatically at login.
pause
