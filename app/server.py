#!/usr/bin/env python3
"""ARIA - a local AI copilot panel for Ableton Live.

Serves a single-page chat UI and speaks two protocols:

  * OpenAI-compatible chat completions (OmniRoute / llama.cpp / any endpoint)
  * the JSON socket of the AbletonMCP Remote Script on port 9877

Everything is stdlib-only on purpose: no venv, no pip, no build step.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
import urllib.error
import urllib.request

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from ableton import Live, LiveError  # noqa: E402
from tools import SYSTEM_PROMPT, TOOLS, call_tool  # noqa: E402

DEFAULTS = {
    "api_base": "http://localhost:20128/v1",
    "api_key": "",
    "model": "ds-web/deepseek-v4-flash",
    "fallbacks": [
        "auto/best-free",
        "hcnsec/DeepSeek-V4-Flash",
        "kc/openrouter/free",
        "pollinations/openai/gpt-oss-20b",
    ],
    "temperature": 0.4,
    "max_steps": 8,
    "abelton_host": "127.0.0.1",
    "abelton_port": 9877,
}
MODEL_PRESETS = [
    "auto/chat",
    "auto/best-free",
    "auto/fast",
    "auto/smart",
    "kc/openrouter/free",
    "ds-web/deepseek-v4-flash",
    "hcnsec/DeepSeek-V4-Flash",
    "pollinations/openai/gpt-oss-20b",
]


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    path = os.path.join(ROOT, "config.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                cfg.update({k: v for k, v in json.load(fh).items() if k in DEFAULTS})
        except Exception as exc:  # bad config should not stop the panel
            print("config.json ignored:", exc, file=sys.stderr)
    for key, env in (("api_base", "ARIA_API_BASE"), ("api_key", "ARIA_API_KEY"),
                     ("model", "ARIA_MODEL"), ("abelton_port", "ABLETON_PORT"),
                     ("abelton_host", "ABLETON_HOST")):
        if os.environ.get(env):
            val = os.environ[env]
            cfg[key] = int(val) if key.endswith("_port") else val
    return cfg


CFG = load_config()
LIVE = Live(CFG["abelton_host"], CFG["abelton_port"])
DEBUG = bool(os.environ.get("ARIA_DEBUG"))


# --------------------------------------------------------------------------
# LLM
# --------------------------------------------------------------------------
def _endpoint() -> str:
    return CFG["api_base"].rstrip("/") + "/chat/completions"


def _auth_headers() -> dict:
    if not CFG["api_key"]:
        raise RuntimeError(
            "No API key configured. Put one in config.json (\"api_key\") or set ARIA_API_KEY."
        )
    return {"Content-Type": "application/json",
            "Authorization": "Bearer " + CFG["api_key"]}


def _payload(messages, model, stream=True):
    return {
        "model": model,
        "messages": messages,
        "tools": TOOLS,
        "tool_choice": "auto",
        "temperature": CFG["temperature"],
        "stream": stream,
    }


def llm_call(messages, model, on_text):
    """One completion. Streams visible text through on_text.

    Returns (text, [ {id, name, arguments} ], finish_reason).
    Falls back to a non-streaming request if the router refuses to stream.
    """
    body = json.dumps(_payload(messages, model, True)).encode("utf-8")
    req = urllib.request.Request(_endpoint(), data=body, method="POST",
                                 headers=_auth_headers())
    try:
        return _consume_stream(req, on_text)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise RuntimeError("LLM HTTP %s: %s" % (exc.code, detail)) from None
    except Exception as exc:  # noqa: BLE001 - retry once without streaming
        if DEBUG:
            traceback.print_exc()
        print("stream failed (%s), retrying non-streaming" % exc, file=sys.stderr)
        return _non_stream(messages, model, on_text)


def _consume_stream(req, on_text):
    text: list[str] = []
    calls: dict[int, dict] = {}
    finish = None

    with urllib.request.urlopen(req, timeout=300) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line or line.startswith(":"):
                continue
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except json.JSONDecodeError:
                continue
            for choice in chunk.get("choices") or []:
                if choice.get("finish_reason"):
                    finish = choice["finish_reason"]
                msg = choice.get("message") or {}
                if msg.get("content"):
                    text.append(msg["content"])
                    on_text(msg["content"])
                for tc in msg.get("tool_calls") or []:
                    _merge_call(calls, tc)
                delta = choice.get("delta") or {}
                if delta.get("content"):
                    text.append(delta["content"])
                    on_text(delta["content"])
                for tc in delta.get("tool_calls") or []:
                    _merge_call(calls, tc)

    ordered = [_finish_call(calls[i]) for i in sorted(calls)]
    return "".join(text), ordered, finish


def _merge_call(calls: dict, tc: dict) -> None:
    idx = tc.get("index", 0)
    slot = calls.setdefault(idx, {"id": None, "name": "", "arguments": ""})
    if tc.get("id"):
        slot["id"] = tc["id"]
    fn = tc.get("function") or {}
    if fn.get("name"):
        slot["name"] = fn["name"] if not slot["name"] else slot["name"] + fn["name"]
    if fn.get("arguments"):
        slot["arguments"] += fn["arguments"]


def _finish_call(slot: dict) -> dict:
    return {
        "id": slot["id"] or "call_%d" % abs(hash(slot["name"] + slot["arguments"])),
        "name": slot["name"],
        "arguments": slot["arguments"] or "{}",
    }


def _non_stream(messages, model, on_text):
    body = json.dumps(_payload(messages, model, False)).encode("utf-8")
    req = urllib.request.Request(_endpoint(), data=body, method="POST",
                                 headers=_auth_headers())
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise RuntimeError("LLM HTTP %s: %s" % (exc.code, detail)) from None
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    text = msg.get("content") or ""
    if text:
        on_text(text)
    calls = [_finish_call({
        "id": tc.get("id"), "name": (tc.get("function") or {}).get("name", ""),
        "arguments": (tc.get("function") or {}).get("arguments", "{}"),
    }) for tc in (msg.get("tool_calls") or [])]
    return text, calls, choice.get("finish_reason")


def _parse_args(raw: str) -> dict:
    try:
        val = json.loads(raw) if raw.strip() else {}
        return val if isinstance(val, dict) else {}
    except json.JSONDecodeError:
        return {}


def _short(value, limit=1600) -> str:
    try:
        s = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        s = str(value)
    return s if len(s) <= limit else s[:limit] + " ...(truncated)"


def _looks_like_backend_error(text: str) -> str | None:
    """Some routers answer 200 with an operator message in the content field."""
    low = text.lower()
    for needle, hint in (
        ("doesn't have enough credits", "that model's upstream account is out of credits"),
        ("insufficient", "that model's upstream account is out of credits"),
        ("all credentials for model", "all credentials for that model are cooling down"),
        ("invalid_api_key", "the upstream key for that model is rejected"),
        ("rate limit", "that model is rate limited right now"),
    ):
        if needle in low and len(text) < 800:
            return hint
    return None


def _models_for(model: str) -> list[str]:
    out: list[str] = []
    for m in [model] + list(CFG.get("fallbacks") or []):
        m = (m or "").strip()
        if m and m not in out:
            out.append(m)
    return out


def _attempt(models, messages, emit):
    """Try each model until one answers with something usable.

    Text that streams before an attempt fails is discarded by a `reset` event,
    so the panel never shows a half-sentence from a dead upstream followed by a
    different model's answer.
    """
    problems = []
    for model in models:
        streamed = [0]

        def on_text(delta, _s=streamed):
            _s[0] += 1
            emit({"t": "delta", "text": delta})

        try:
            text, calls, finish = llm_call(messages, model, on_text)
        except RuntimeError as exc:
            if streamed[0]:
                emit({"t": "reset"})
            problems.append("%s: %s" % (model, exc))
            continue

        if not calls:
            hint = _looks_like_backend_error(text)
            if hint:
                if streamed[0]:
                    emit({"t": "reset"})
                problems.append("%s: %s" % (model, hint))
                continue

        return model, text, calls

    raise RuntimeError(
        "No configured model answered. Tried %s. Check config.json / the model dropdown."
        % "; ".join(problems) if problems else "No model configured."
    )


def run_chat(body: dict, emit) -> None:
    model = (body.get("model") or CFG["model"]).strip()
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in (body.get("messages") or [])[-40:]:
        role = m.get("role")
        content = m.get("content")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    models = _models_for(model)

    for step in range(int(CFG["max_steps"])):
        used, text, calls = _attempt(models, messages, emit)

        # Whatever answered is most likely to answer again: put it first.
        models = [used] + [m for m in models if m != used]

        if not calls:
            return

        messages.append({
            "role": "assistant",
            "content": text or None,
            "tool_calls": [{"id": c["id"], "type": "function",
                            "function": {"name": c["name"], "arguments": c["arguments"]}}
                           for c in calls],
        })

        for call in calls:
            args = _parse_args(call["arguments"])
            emit({"t": "tool", "name": call["name"], "args": args})
            try:
                result = call_tool(call["name"], args, LIVE)
                ok = True
            except (LiveError, ValueError, KeyError) as exc:
                result = {"error": str(exc)}
                ok = False
            except Exception as exc:  # noqa: BLE001
                if DEBUG:
                    traceback.print_exc()
                result = {"error": "%s: %s" % (type(exc).__name__, exc)}
                ok = False
            emit({"t": "tool_result", "name": call["name"], "ok": ok,
                  "preview": _short(result, 700)})
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "content": _short(result, 6000)})

        if step == int(CFG["max_steps"]) - 1:
            emit({"t": "delta", "text": "\n\n(Stopped after %d tool rounds - ask me to continue if you want the rest.)"
                  % CFG["max_steps"]})


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".json": "application/json",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    server_version = "ARIA/1.0"

    def log_message(self, fmt, *args):  # quiet unless debugging
        if DEBUG:
            print("%s - %s" % (self.address_string(), fmt % args), file=sys.stderr)

    # -- helpers -----------------------------------------------------------
    def _json(self, obj, code=200):
        raw = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _static(self, rel):
        path = os.path.normpath(os.path.join(ROOT, "ui", rel.lstrip("/\\")))
        if not path.startswith(os.path.join(ROOT, "ui")) or not os.path.isfile(path):
            self._json({"error": "not found"}, 404)
            return
        ext = os.path.splitext(path)[1].lower()
        with open(path, "rb") as fh:
            raw = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _emit(self, obj):
        try:
            self.wfile.write(("data: " + json.dumps(obj, ensure_ascii=False) + "\n\n").encode("utf-8"))
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            raise

    # -- routes ------------------------------------------------------------
    def do_GET(self):
        route = urlparse(self.path).path
        if route in ("/", "/index.html"):
            self._static("index.html")
        elif route == "/api/health":
            ok, err = LIVE.probe()
            self._json({"live": ok, "error": err, "model": CFG["model"]})
        elif route == "/api/frame":
            path = os.path.join(ROOT, "frame.json")
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    self._json(json.load(fh))
            except Exception:
                self._json({"chrome": 0})
        elif route == "/api/config":
            self._json({"model": CFG["model"], "models": MODEL_PRESETS,
                        "api_base": CFG["api_base"]})
        elif route.startswith("/ui/") or route.endswith((".css", ".js")):
            self._static(route.replace("/ui/", ""))
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        route = urlparse(self.path).path
        if route == "/api/frame":
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                chrome = int(body.get("chrome") or 0)
            except Exception:
                self._json({"ok": False}, 400)
                return
            try:
                with open(os.path.join(ROOT, "frame.json"), "w", encoding="utf-8") as fh:
                    json.dump({"chrome": max(0, min(chrome, 200))}, fh)
            except OSError:
                pass
            self._json({"ok": True, "chrome": chrome})
            return

        if route != "/api/chat":
            self._json({"error": "not found"}, 404)
            return

        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json({"error": "bad json"}, 400)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        try:
            run_chat(body, self._emit)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:  # noqa: BLE001 - always tell the UI something
            if DEBUG:
                traceback.print_exc()
            try:
                self._emit({"t": "error", "message": str(exc)})
            except (BrokenPipeError, ConnectionResetError):
                return
        try:
            self._emit({"t": "done"})
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    ap = argparse.ArgumentParser(description="ARIA - Ableton AI panel")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True
    print("ARIA panel on http://%s:%d  (model %s, Live %s:%s)"
          % (args.host, args.port, CFG["model"], CFG["abelton_host"], CFG["abelton_port"]))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
