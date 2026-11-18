# ARIA - AI panel attached to Ableton Live
#
#   1. starts the local panel server (node-free, python stdlib)
#   2. opens the UI as a frameless Chromium "app" window
#   3. makes that window OWNED BY Live's main window and pins it to Live's right
#      client edge, so it moves/resizes/minimises with Live and never floats over
#      other apps. Ctrl+Alt+A shows / hides it.
#
# Usage:
#   start.cmd                 attach to Live
#   start.cmd -Floating       pin to the screen edge instead (always on top)
#   start.cmd -ServerOnly     only run the server (for the Max for Live device)
#   start.cmd -Framed         keep the window frame (for debugging layout)

[CmdletBinding()]
param(
    [int]$Port = 8765,
    [int]$Width = 430,
    [switch]$Framed,
    [switch]$NoHotkey,
    [switch]$Floating,
    [switch]$ServerOnly,
    [switch]$Restart,
    [string]$Model = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProfileDir = Join-Path $env:LOCALAPPDATA "ableton-ai-panel\profile"
$StateDir = Join-Path $env:LOCALAPPDATA "ableton-ai-panel"

Add-Type -AssemblyName System.Windows.Forms | Out-Null

# ---------------------------------------------------------------- Win32 glue
if (-not ("AriaWin" -as [type])) {
    Add-Type -Language CSharp -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

[StructLayout(LayoutKind.Sequential)]
public struct ARIA_RECT { public int Left, Top, Right, Bottom; }

[StructLayout(LayoutKind.Sequential)]
public struct ARIA_POINT { public int X, Y; }

[StructLayout(LayoutKind.Sequential)]
public struct ARIA_MSG {
    public IntPtr hwnd;
    public uint message;
    public IntPtr wParam;
    public IntPtr lParam;
    public uint time;
    public int ptX;
    public int ptY;
}

public static class AriaWin {
    public const int GWL_STYLE = -16;
    public const int GWL_EXSTYLE = -20;
    public const int GWL_HWNDPARENT = -8;

    public const long WS_CAPTION = 0x00C00000L;
    public const long WS_THICKFRAME = 0x00040000L;
    public const long WS_SYSMENU = 0x00080000L;
    public const long WS_MINIMIZEBOX = 0x00020000L;
    public const long WS_MAXIMIZEBOX = 0x00010000L;
    public const long WS_POPUP = 0x80000000L;

    public const long WS_EX_APPWINDOW = 0x00040000L;
    public const long WS_EX_TOOLWINDOW = 0x00000080L;

    public const uint SWP_NOSIZE = 0x0001;
    public const uint SWP_NOMOVE = 0x0002;
    public const uint SWP_NOZORDER = 0x0004;
    public const uint SWP_NOACTIVATE = 0x0010;
    public const uint SWP_FRAMECHANGED = 0x0020;
    public const uint SWP_SHOWWINDOW = 0x0040;

    public static readonly IntPtr HWND_TOPMOST = new IntPtr(-1);
    public static readonly IntPtr HWND_TOP = IntPtr.Zero;

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr GetWindowLongPtr(IntPtr hWnd, int nIndex);
    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr SetWindowLongPtr(IntPtr hWnd, int nIndex, IntPtr dwNewLong);
    [DllImport("user32.dll")]
    public static extern bool SetWindowPos(IntPtr hWnd, IntPtr after, int x, int y, int cx, int cy, uint flags);
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int cmd);
    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool IsWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool IsIconic(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool GetClientRect(IntPtr hWnd, out ARIA_RECT r);
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out ARIA_RECT r);
    [DllImport("user32.dll")]
    public static extern bool ClientToScreen(IntPtr hWnd, ref ARIA_POINT p);
    [DllImport("user32.dll")]
    public static extern bool RegisterHotKey(IntPtr hWnd, int id, uint mods, uint vk);
    [DllImport("user32.dll")]
    public static extern bool UnregisterHotKey(IntPtr hWnd, int id);
    [DllImport("user32.dll")]
    public static extern bool PeekMessage(out ARIA_MSG msg, IntPtr hWnd, uint min, uint max, uint remove);

    public delegate bool EnumProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumProc cb, IntPtr lParam);
    [DllImport("user32.dll")]
    public static extern bool PostMessage(IntPtr hWnd, uint msg, IntPtr w, IntPtr l);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder s, int n);

    // Top-level visible window whose title contains `part` (case-insensitive).
    public static IntPtr FindByTitle(string part) {
        IntPtr found = IntPtr.Zero;
        EnumWindows(delegate(IntPtr h, IntPtr l) {
            if (!IsWindowVisible(h)) return true;
            var sb = new System.Text.StringBuilder(256);
            GetWindowText(h, sb, 256);
            if (sb.Length > 0 && sb.ToString().IndexOf(part, StringComparison.OrdinalIgnoreCase) >= 0) {
                found = h;
                return false;
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }

    public static void Borderless(IntPtr h) {
        long style = GetWindowLongPtr(h, GWL_STYLE).ToInt64();
        style &= ~(WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX);
        style |= WS_POPUP;
        SetWindowLongPtr(h, GWL_STYLE, new IntPtr(style));
        SetWindowPos(h, IntPtr.Zero, 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED);
    }

    // Owned window: no taskbar button, always directly above its owner.
    public static void Own(IntPtr h, IntPtr owner) {
        long ex = GetWindowLongPtr(h, GWL_EXSTYLE).ToInt64();
        ex = (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW;
        SetWindowLongPtr(h, GWL_EXSTYLE, new IntPtr(ex));
        SetWindowLongPtr(h, GWL_HWNDPARENT, owner);
    }

    public static void Place(IntPtr h, int x, int y, int cx, int cy, bool topmost) {
        IntPtr after = topmost ? HWND_TOPMOST : HWND_TOP;
        SetWindowPos(h, after, x, y, cx, cy, SWP_NOACTIVATE | SWP_SHOWWINDOW);
    }

    public static void Raise(IntPtr h, bool topmost) {
        IntPtr after = topmost ? HWND_TOPMOST : HWND_TOP;
        SetWindowPos(h, after, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE);
    }

    public static void Close(IntPtr h) { PostMessage(h, 0x0010, IntPtr.Zero, IntPtr.Zero); }
}
'@ | Out-Null
}

# ---------------------------------------------------------------- helpers
function Test-Port([int]$p) {
    try {
        $c = New-Object Net.Sockets.TcpClient
        $c.Connect("127.0.0.1", $p)
        $c.Close()
        return $true
    } catch { return $false }
}

function Find-Python {
    foreach ($d in @(
        (Join-Path $env:USERPROFILE "miniconda3\pythonw.exe"),
        (Join-Path $env:USERPROFILE "miniconda3\python.exe"),
        (Join-Path $env:USERPROFILE "anaconda3\pythonw.exe"))) {
        if (Test-Path $d) { return $d }
    }
    foreach ($n in @("pythonw.exe", "python.exe")) {
        $c = Get-Command $n -ErrorAction SilentlyContinue
        if ($c) { return $c.Source }
    }
    throw "No Python interpreter found. Install Python 3.9+ or add python.exe to PATH."
}

function Find-Browser {
    foreach ($c in @(
        (Join-Path $env:ProgramFiles "Microsoft\Edge\Application\msedge.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Microsoft\Edge\Application\msedge.exe"),
        (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
        (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe"))) {
        if (Test-Path $c) { return $c }
    }
    return $null
}

function Find-AriaWindow {
    # Chromium app windows do not always expose a MainWindowTitle to Get-Process,
    # so look the window up by title directly.
    $h = [AriaWin]::FindByTitle("ARIA")
    if ($h -ne [IntPtr]::Zero) {
        return [pscustomobject]@{ MainWindowHandle = $h }
    }
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -like "*ARIA*" } |
        Select-Object -First 1
}

function Find-LiveWindow {
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ProcessName -like "Ableton Live*" -and $_.MainWindowHandle -ne 0 } |
        Select-Object -First 1
}

function Get-LiveClient {
    $p = Find-LiveWindow
    if (-not $p) { return $null }
    $h = $p.MainWindowHandle
    $r = New-Object ARIA_RECT
    if (-not [AriaWin]::GetClientRect($h, [ref]$r)) { return $null }
    $pt = New-Object ARIA_POINT
    $pt.X = 0; $pt.Y = 0
    [AriaWin]::ClientToScreen($h, [ref]$pt) | Out-Null
    [pscustomobject]@{
        Hwnd = $h
        X    = $pt.X
        Y    = $pt.Y
        W    = $r.Right - $r.Left
        H    = $r.Bottom - $r.Top
    }
}

# ---------------------------------------------------------------- server
New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
$python = Find-Python
if (-not (Test-Port $Port)) {
    $srv = Join-Path $Root "app\server.py"
    if ($Model) { $env:ARIA_MODEL = $Model }
    Start-Process -FilePath $python `
        -ArgumentList "`"$srv`"", "--port", "$Port" `
        -WindowStyle Hidden `
        -RedirectStandardError (Join-Path $StateDir "server.log") `
        -RedirectStandardOutput (Join-Path $StateDir "server.out") | Out-Null

    $deadline = (Get-Date).AddSeconds(25)
    while (-not (Test-Port $Port) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 200 }
    if (-not (Test-Port $Port)) {
        throw "Panel server failed to start on port $Port. Run: python `"$srv`" --port $Port"
    }
}
if ($ServerOnly) { return }

# ---------------------------------------------------------------- existing window?
$existing = Find-AriaWindow
if ($existing -and -not $Restart) {
    [AriaWin]::ShowWindow($existing.MainWindowHandle, 5) | Out-Null
    [AriaWin]::Raise($existing.MainWindowHandle, $Floating)
    [AriaWin]::SetForegroundWindow($existing.MainWindowHandle) | Out-Null
    return
}
if ($existing -and $Restart) {
    try { [AriaWin]::Close($existing.MainWindowHandle) } catch {}
    Start-Sleep -Milliseconds 900
}

$browser = Find-Browser
if (-not $browser) { throw "Edge or Chrome not found - one of them is needed for the panel window." }
New-Item -ItemType Directory -Path $ProfileDir -Force | Out-Null

# The page reports how tall the browser's own title bar is; a stale value from a
# previous run would shift the window by the wrong amount.
$frameFile = Join-Path $Root "frame.json"
if (Test-Path $frameFile) { Remove-Item $frameFile -Force -ErrorAction SilentlyContinue }

# ---------------------------------------------------------------- geometry
$wa = [System.Windows.Forms.Screen]::PrimaryScreen.WorkingArea
$panelW = [Math]::Min($Width, [int]($wa.Width * 0.5))
$url = "http://127.0.0.1:$Port/"

$bargs = @(
    "--app=`"$url`"",
    "--window-size=$panelW,900",
    "--window-position=$($wa.Right - $panelW),$($wa.Top)",
    "--user-data-dir=`"$ProfileDir`"",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-features=Translate,MediaRouter,msEdgeTranslate",
    "--disable-session-crashed-bubble",
    "--hide-crash-restore-bubble",
    "--disable-background-mode"
)
Start-Process -FilePath $browser -ArgumentList $bargs | Out-Null

# ---------------------------------------------------------------- find + dress
$hwnd = [IntPtr]::Zero
$deadline = (Get-Date).AddSeconds(40)
while ($hwnd -eq [IntPtr]::Zero -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 250
    $p = Find-AriaWindow
    if ($p) { $hwnd = $p.MainWindowHandle }
}
if ($hwnd -eq [IntPtr]::Zero) {
    throw "The panel window never appeared. Open $url manually to check for errors."
}

Start-Sleep -Milliseconds 400
if (-not $Framed) { [AriaWin]::Borderless($hwnd) }

$chromeH = 0
if (-not $Framed) {
    $deadline = (Get-Date).AddSeconds(8)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $frameFile) {
            try {
                $fj = Get-Content $frameFile -Raw | ConvertFrom-Json
                if ($null -ne $fj.chrome -and [int]$fj.chrome -gt 0) { $chromeH = [int]$fj.chrome; break }
            } catch {}
        }
        Start-Sleep -Milliseconds 150
    }
    if ($chromeH -le 0) { $chromeH = 24 }
}

# ---------------------------------------------------------------- attach
$live = Get-LiveClient
$attached = $false
if ($live -and -not $Floating) {
    [AriaWin]::Own($hwnd, $live.Hwnd)
    $attached = $true
}

function Place-Panel {
    param($Panel, [bool]$Attached, $Live, [int]$Chrome)
    if ($Attached -and $Live) {
        $x = $Live.X + $Live.W - $panelW
        $y = $Live.Y - $Chrome
        $h = $Live.H + $Chrome
        [AriaWin]::Place($Panel, $x, $y, $panelW, $h, $false)
    } else {
        $x = $wa.Right - $panelW
        $y = $wa.Top - $Chrome
        $h = $wa.Height + $Chrome
        [AriaWin]::Place($Panel, $x, $y, $panelW, $h, $true)
    }
}

# Chromium restores its saved bounds shortly after the window appears.
for ($i = 0; $i -lt 6; $i++) {
    Place-Panel -Panel $hwnd -Attached $attached -Live $live -Chrome $chromeH
    Start-Sleep -Milliseconds 350
}
[AriaWin]::SetForegroundWindow($hwnd) | Out-Null

# ---------------------------------------------------------------- hotkey + sync
if ($NoHotkey) { return }

$MOD_ALT = 0x1
$MOD_CONTROL = 0x2
$VK_A = 0x41
$HOTKEY_ID = 0xA11A
$WM_HOTKEY = 0x0312

if (-not [AriaWin]::RegisterHotKey([IntPtr]::Zero, $HOTKEY_ID, ($MOD_CONTROL -bor $MOD_ALT), $VK_A)) {
    Write-Warning "Ctrl+Alt+A is already taken by another app; the panel stays visible."
}

$msg = New-Object ARIA_MSG
$ticks = 0
$hiddenByUser = $false
$lastKey = ""

while ([AriaWin]::IsWindow($hwnd)) {
    while ([AriaWin]::PeekMessage([ref]$msg, [IntPtr]::Zero, 0, 0, 1)) {
        if ($msg.message -eq $WM_HOTKEY -and $msg.wParam.ToInt32() -eq $HOTKEY_ID) {
            if ([AriaWin]::IsWindowVisible($hwnd) -and -not $hiddenByUser) {
                [AriaWin]::ShowWindow($hwnd, 0) | Out-Null
                $hiddenByUser = $true
            } else {
                [AriaWin]::ShowWindow($hwnd, 5) | Out-Null
                $hiddenByUser = $false
                Place-Panel -Panel $hwnd -Attached $attached -Live $live -Chrome $chromeH
                [AriaWin]::SetForegroundWindow($hwnd) | Out-Null
            }
        }
    }

    $ticks++
    if ($ticks % 3 -eq 0) {
        $live = Get-LiveClient
        if ($attached -and -not $live) {
            # Live went away: fall back to the screen edge instead of vanishing.
            $attached = $false
        }
        $key = if ($live) { "$($live.Hwnd):$($live.X):$($live.Y):$($live.W):$($live.H)" } else { "none" }
        if ($key -ne $lastKey) {
            $lastKey = $key
            if (-not $hiddenByUser) {
                if ($attached) {
                    $min = $live -and [AriaWin]::IsIconic($live.Hwnd)
                    if ($min) { [AriaWin]::ShowWindow($hwnd, 0) | Out-Null }
                    else {
                        [AriaWin]::ShowWindow($hwnd, 5) | Out-Null
                        Place-Panel -Panel $hwnd -Attached $true -Live $live -Chrome $chromeH
                    }
                } else {
                    [AriaWin]::ShowWindow($hwnd, 5) | Out-Null
                    Place-Panel -Panel $hwnd -Attached $false -Live $null -Chrome $chromeH
                }
            }
        }
    }
    Start-Sleep -Milliseconds 300
}
