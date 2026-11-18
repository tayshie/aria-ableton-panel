@echo off
rem Starts ARIA (panel server + docked window). Pass extra args through, e.g.
rem   start.cmd -Width 380 -Framed
start "" powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0launch.ps1" %*
