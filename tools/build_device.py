#!/usr/bin/env python3
"""Builds ARIA.amxd - a Max for Live device that embeds the panel UI in Live.

Structure:
  - one `jweb` filling the device area, in presentation mode
  - `loadbang -> [js aria_resize.js]`, which sizes the browser (Max ignores a
    stored rect for jweb when loading from disk) and loads the panel URL

An .amxd is a small container format:
    "ampf" + uint32(4) + "mmmm"
      chunk: 4-byte id + uint32 length + payload
        "meta" -> uint32(1)
        "ptch" -> patcher JSON (UTF-8, NUL-terminated)
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(ROOT, "device")

WIDTH = 460
HEIGHT = 620
URL = "http://127.0.0.1:8765/"


def patcher(width=WIDTH, height=HEIGHT, url=URL) -> dict:
    return {
        "patcher": {
            "fileversion": 1,
            "appversion": {"major": 9, "minor": 1, "revision": 5, "architecture": "x64",
                           "modernui": 1},
            "classnamespace": "box",
            "rect": [0.0, 0.0, float(width), float(height)],
            "openrect": [0.0, 0.0, float(width), float(height)],
            "bglocked": 0,
            "openinpresentation": 1,
            "default_fontsize": 11.0,
            "default_fontface": 0,
            "default_fontname": "Arial",
            "gridonopen": 1,
            "gridsize": [15.0, 15.0],
            "gridsnaponopen": 1,
            "statusbarvisible": 0,
            "toolbarvisible": 1,
            "boxanimatetime": 200,
            "imprint": 0,
            "enablehscroll": 1,
            "enablevscroll": 1,
            "devicewidth": float(width),
            "description": "ARIA - AI copilot panel for the live set",
            "tags": "ai panel copilot chat",
            "boxes": [
                {
                    "box": {
                        "id": "aria-web",
                        "maxclass": "newobj",
                        "numinlets": 1,
                        "numoutlets": 0,
                        "outlettype": [],
                        "patching_rect": [0.0, 0.0, 320.0, 240.0],
                        "presentation": 1,
                        "presentation_rect": [0.0, 0.0, float(width), float(height)],
                        "text": "jweb",
                        "varname": "aria-web",
                    }
                },
                {
                    "box": {
                        "id": "aria-loadbang",
                        "maxclass": "newobj",
                        "numinlets": 1,
                        "numoutlets": 1,
                        "outlettype": ["bang"],
                        "patching_rect": [20.0, float(height) + 40.0, 64.0, 22.0],
                        "text": "loadbang",
                    }
                },
                {
                    "box": {
                        "id": "aria-js",
                        "maxclass": "newobj",
                        "numinlets": 1,
                        "numoutlets": 0,
                        "outlettype": [],
                        "patching_rect": [100.0, float(height) + 40.0, 150.0, 22.0],
                        "text": "js aria_resize.js",
                    }
                },
            ],
            "lines": [
                {"patchline": {"destination": ["aria-js", 0], "disabled": 0, "hidden": 0,
                               "source": ["aria-loadbang", 0]}},
            ],
            "parameters": {},
            "dependency_cache": [],
            "latency": 0,
            "project": {
                "version": 1,
                "creationdate": -835212571,
                "modificationdate": -835212571,
                "viewrect": [0.0, 0.0, float(width), float(height)],
                "autoorganize": 1,
                "hideprojectwindow": 1,
                "showdependencies": 1,
                "autolocalize": 0,
                "contents": {"patchers": {}},
                "layout": {},
                "searchpath": {},
                "detailsvisible": 0,
            },
        }
    }


def _container(doc: dict) -> bytes:
    payload = json.dumps(doc).encode("utf-8") + b"\x00"
    blob = b"ampf" + struct.pack("<I", 4) + b"mmmm"
    blob += b"meta" + struct.pack("<I", 4) + struct.pack("<I", 1)
    blob += b"ptch" + struct.pack("<I", len(payload)) + payload
    return blob


def build(path: str, width=WIDTH, height=HEIGHT, url=URL) -> str:
    with open(path, "wb") as fh:
        fh.write(_container(patcher(width, height, url)))
    return path


def verify(path: str) -> dict:
    data = open(path, "rb").read()
    assert data[:4] == b"ampf", "bad magic"
    assert data[4:12] == struct.pack("<I", 4) + b"mmmm", "bad header"
    off, chunks, doc = 12, [], None
    while off < len(data):
        cid = data[off:off + 4]
        size = struct.unpack("<I", data[off + 4:off + 8])[0]
        chunks.append((cid.decode("ascii"), size))
        if cid == b"ptch":
            doc, _ = json.JSONDecoder().raw_decode(data[off + 8:off + 8 + size].decode("utf-8"))
        off += 8 + size
    return {"chunks": chunks, "objects": [b["box"]["text"] for b in doc["patcher"]["boxes"]]}


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    target = os.path.join(OUT_DIR, "ARIA.amxd")
    build(target)
    print("built", target, "->", verify(target))

    js_src = os.path.join(OUT_DIR, "aria_resize.js")
    dest_dirs = [
        os.path.join(os.environ["USERPROFILE"], "Documents", "Ableton", "User Library",
                     "Presets", "Audio Effects", "Max Audio Effect"),
        os.path.join(os.environ["USERPROFILE"], "Documents", "Ableton", "User Library",
                     "Presets", "Instruments", "Max Instrument"),
    ]
    for d in dest_dirs:
        os.makedirs(d, exist_ok=True)
        shutil.copy2(target, os.path.join(d, "ARIA.amxd"))
        if os.path.exists(js_src):
            shutil.copy2(js_src, os.path.join(d, "aria_resize.js"))
        print("installed", os.path.join(d, "ARIA.amxd"))


if __name__ == "__main__":
    main()
