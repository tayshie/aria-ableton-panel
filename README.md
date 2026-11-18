# ARIA — AI copilot panel for Ableton Live

A chat panel that sits on Live's right edge and can actually read and change the set.
Ask it something, or tell it what to do — it calls the same Remote Script that the
Ableton MCP server uses, so it works on the session that is already open.

```
  Live  ─┬─ Remote Script "AbletonMCP" (port 9877, JSON over TCP)
         │
  ARIA   ─┴─ panel server (python stdlib, port 8765)
              ├─ POST /api/chat   → OpenAI-compatible endpoint (OmniRoute / llama.cpp / …)
              └─ GET  /           → the UI, shown in a Chromium app window owned by Live
```

No packages to install, no build step: Python 3.9+ and an Edge or Chrome install.

## Use it

Double-click **ARIA.vbs** (no console flash) or **start.cmd**.

- The window attaches to Live: it takes the right edge of Live's client area, goes
  full height, minimises with Live, and stays above Live without floating over
  other apps.
- **Ctrl+Alt+A** hides / shows it.
- Run it again while it is up and it just re-focuses the existing window.
- If Live is not running, the panel falls back to the screen edge, always-on-top,
  and says so in the header (grey dot).

Options (`start.cmd -Width 480`, etc.):

| flag           | effect                                                          |
|----------------|-----------------------------------------------------------------|
| `-Width 480`   | panel width in px (default 430)                                 |
| `-Floating`    | pin to the screen edge, always-on-top, ignore Live's window      |
| `-Framed`      | keep the window frame (debugging layout)                        |
| `-NoHotkey`    | do not stay resident for the hotkey                             |
| `-ServerOnly`  | only start the panel server (used by the Max for Live device)    |
| `-Restart`     | close an existing panel and start a fresh one                    |

Autostart with Live: `powershell -ExecutionPolicy Bypass -File install-autostart.ps1`
(remove with `-Remove`).

## Model

The backend is any OpenAI-compatible `/v1/chat/completions` with tool calling.
Copy `config.example.json` to `config.json` (it is git-ignored) and fill it in:

```json
{
  "api_base": "http://localhost:20128/v1",
  "api_key": "sk-…",
  "model": "ds-web/deepseek-v4-flash"
}
```

Override with env vars: `ARIA_API_BASE`, `ARIA_API_KEY`, `ARIA_MODEL`.
The dropdown in the panel header switches between the presets in
`app/server.py` (`MODEL_PRESETS`) without restarting anything.

`fallbacks` in `config.json` is a list tried in order when the selected model
errors out or answers with an upstream quota message; whatever answers gets
promoted to the front for the rest of the conversation. Text streamed by a failed
attempt is cleared before the next one speaks, so you never see two models'
half-answers spliced together.

## What it can do

Read: session info, per-track state, clip notes, devices and their parameters,
arrangement clips, browser tree/search, scale, locators, a full session snapshot.

Change: tempo, loop, transport, tracks (create/delete/rename/volume/pan/mute/solo/
arm/arm-sends), clips (create, write notes, quantize, loop, name, fire/stop),
scenes, devices (load, parameter, bypass), locators, undo/redo, save, and `batch`
for several edits in one main-thread pass.

Everything is 0-based and in beats. Mixer values are normalised 0.0–1.0 (0.85 = 0 dB).

## Max for Live device (optional)

`device/ARIA.amxd` embeds the same page in a `jweb` object, so the chat lives in
Live's device view instead of a separate window. `tools/build_device.py` generates
it and copies it (plus `aria_resize.js`) into
`User Library/Presets/Audio Effects/Max Audio Effect/` and `…/Max Instrument/`.

Status, honestly: the device loads and renders the panel, but Max creates `jweb` at
its 320×240 default and ignores a stored box rect, so the embedded view comes up
smaller than the 460×620 the device declares. To make it fill the device, open the
device in Max (the wrench icon), drag the `jweb` corner out, and save — after that
the size sticks. The docked window is the more comfortable way to use it.

Note: M4L devices need Max for Live (Live Suite). The device also needs the panel
server running — `-ServerOnly` or the autostart entry does that.

## Files

| file                     | role                                                        |
|--------------------------|-------------------------------------------------------------|
| `app/server.py`          | HTTP + SSE, the tool-calling loop, LLM client                |
| `app/ableton.py`         | JSON-socket client for the `AbletonMCP` Remote Script        |
| `app/tools.py`           | tool schemas, system prompt, name → command mapping          |
| `ui/*`                   | the panel (plain HTML/CSS/JS, streaming over fetch)          |
| `launch.ps1`             | server + window + Win32 attach/pin + hotkey                  |
| `tools/build_device.py`  | generates/installs the Max for Live device                   |

Runtime state goes to `%LOCALAPPDATA%\ableton-ai-panel\` (browser profile,
`server.log`). Chat history and the chosen model live in the browser profile's
localStorage.

## Troubleshooting

**Grey dot / "Live not connected".** Live must have `AbletonMCP` selected:
Settings → Link, Tempo & MIDI → MIDI → pick a free Control Surface slot →
`AbletonMCP`, Input and Output `None`. Then the status bar in Live says
`AbletonMCP: Client connected`.

**Every command times out.** A modal dialog is open in Live and is blocking the
Remote Script — dismiss it and retry.

**Port already in use.** `start.cmd -Port 8767`, and point the Max device at the
same port in `tools/build_device.py` (`URL`) if you use it.

**Panel drifts over other apps.** That is `-Floating` mode; run without the flag to
make it owned by Live again.
