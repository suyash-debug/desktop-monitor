$action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument 'd:\code\desktop-monitor\start_monitor.vbs'
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit 0
Register-ScheduledTask -TaskName 'DesktopMonitor' -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force
Write-Host "Registered: $(Get-ScheduledTask -TaskName 'DesktopMonitor' | Select-Object -ExpandProperty State)"
