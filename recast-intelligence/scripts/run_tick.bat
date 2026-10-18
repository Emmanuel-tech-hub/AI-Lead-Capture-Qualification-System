@echo off
REM Called by Windows Task Scheduler every 15 minutes. Does whatever is due (collect, alerts, daily briefing).
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m recast_intel tick >> "logs\scheduler.log" 2>&1
