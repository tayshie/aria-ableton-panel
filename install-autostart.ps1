# Puts ARIA in the Windows Startup folder so the panel is already docked when
# you open Live. Run:  powershell -ExecutionPolicy Bypass -File install-autostart.ps1
# Remove with:        powershell -ExecutionPolicy Bypass -File install-autostart.ps1 -Remove

[CmdletBinding()]
param([switch]$Remove)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$startup = [Environment]::GetFolderPath("Startup")
$lnkPath = Join-Path $startup "ARIA Ableton Panel.lnk"

if ($Remove) {
    if (Test-Path $lnkPath) { Remove-Item $lnkPath -Force; Write-Host "Removed $lnkPath" }
    else { Write-Host "Nothing to remove." }
    return
}

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($lnkPath)
$lnk.TargetPath = "$env:WINDIR\System32\wscript.exe"
$lnk.Arguments = '"' + (Join-Path $Root "ARIA.vbs") + '"'
$lnk.WorkingDirectory = $Root
$lnk.WindowStyle = 7
$lnk.Description = "ARIA - docked Ableton copilot"
$lnk.Save()
Write-Host "Installed shortcut: $lnkPath"
