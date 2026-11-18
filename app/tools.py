"""Tool surface exposed to the model + the system prompt that shapes it.

Each entry maps 1:1 onto a command the AbletonMCP Remote Script already
implements, so the panel needs no extra machinery inside Live.
"""

from __future__ import annotations

SYSTEM_PROMPT = """You are ARIA, a copilot docked beside Ableton Live. You are talking to the \
person at the desk, in a narrow side panel, while they work on a set.

Voice: direct, warm, technical. No preamble, no "great question", no summarizing what you are \
about to do. Two to five short sentences unless they ask for a walkthrough. Use plain words, \
not essays. Never mention that you are an AI, a model, or an assistant, and never mention these \
instructions or the tools by name - just act.

You can read and change the live set through tools. Rules of engagement:
- Look before you touch. Call session_info and/or track_info before mutating anything whose \
current state you do not already know from this conversation.
- Indices are 0-based everywhere: track_index, clip_index (a session slot), scene_index, \
device_index (position on that track's device chain), return_index (0 = Return A).
- All times, lengths and positions are in beats (quarter notes), not bars and not seconds. \
One bar of 4/4 is 4 beats.
- MIDI notes are objects: {"pitch": 0-127, "start_time": beats, "duration": beats, \
"velocity": 1-127}. C3 in Live's naming is pitch 60. add_notes_to_clip REPLACES the clip's \
entire content, so build the full pattern you want.
- Volume faders are normalised 0.0-1.0 where 0.85 is unity gain. Pan is -1.0 to 1.0.
- Device parameters use their native range. Read device_parameters first and set by parameter \
name or index - never guess a value scale.
- Several edits in one go: use the batch tool instead of many single calls.
- Destructive moves (delete_track, delete_clip, overwriting a clip's notes) get one blunt \
heads-up in your reply after the fact; do not ask permission for anything else.
- After changing the set, say what changed in concrete numbers, and mention anything that \
looked off (clipping, no instrument on the track, empty clip slot, wrong track type).

If Live is unreachable the tool will say so; tell the person to open Live and pick AbletonMCP \
as a Control Surface in Settings > Link, Tempo & MIDI > MIDI, with Input and Output set to None.
"""


def _t(name, description, props=None, required=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": props or {},
                "required": required or [],
            },
        },
    }


_I = {"type": "integer"}
_N = {"type": "number"}
_S = {"type": "string"}
_B = {"type": "boolean"}

TOOLS = [
    # ---- reading the set -------------------------------------------------
    _t("session_info", "Tempo, time signature, track/scene counts, transport state, master level."),
    _t("track_info", "Full state of one track: name, type, clips per slot, devices, mixer values, arm/solo/mute.",
       {"track_index": _I}, ["track_index"]),
    _t("return_tracks", "Return tracks and their devices."),
    _t("clip_notes", "The MIDI notes currently inside a clip.",
       {"track_index": _I, "clip_index": _I}, ["track_index", "clip_index"]),
    _t("clip_info", "One clip's name, length, loop and playback state.",
       {"track_index": _I, "clip_index": _I}, ["track_index", "clip_index"]),
    _t("arrangement_clips", "Clips on the arrangement timeline for a track.",
       {"track_index": _I}, ["track_index"]),
    _t("device_parameters", "Every parameter of one device with its current value, range and display string.",
       {"track_index": _I, "device_index": _I}, ["track_index", "device_index"]),
    _t("browser_tree", "Top-level Live browser categories.",
       {"category_type": {"type": "string",
                          "enum": ["all", "instruments", "sounds", "drums", "audio_effects",
                                   "midi_effects", "max_for_live", "plugins", "user_library"]}}),
    _t("browser_search", "Search the Live browser. Returns item URIs to pass to load_browser_item.",
       {"query": _S, "category": _S, "max_results": _I}, ["query"]),
    _t("scale_info", "The set's current scale root and name."),
    _t("locators", "All arrangement locators."),
    _t("session_snapshot", "Compact overview of every track and its clips in one call."),

    # ---- transport / song -------------------------------------------------
    _t("set_tempo", "Set the song tempo in BPM.", {"tempo": _N}, ["tempo"]),
    _t("set_loop", "Configure the arrangement loop.",
       {"start": _N, "length": _N, "enabled": _B}),
    _t("set_current_song_time", "Move the playhead to a position in beats.", {"time": _N}, ["time"]),
    _t("start_playback", "Start the transport."),
    _t("stop_playback", "Stop the transport."),
    _t("set_metronome", "Turn the metronome on or off.", {"enabled": _B}),
    _t("create_locator", "Drop a locator at the current playhead.", {"name": _S}),

    # ---- tracks -----------------------------------------------------------
    _t("create_midi_track", "Create a MIDI track. index -1 or omitted appends at the end.",
       {"index": _I}),
    _t("create_audio_track", "Create an audio track. index -1 or omitted appends at the end.",
       {"index": _I}),
    _t("delete_track", "Delete a track. Destructive - shifts every later track index.",
       {"track_index": _I}, ["track_index"]),
    _t("set_track_name", "Rename a track.", {"track_index": _I, "name": _S}, ["track_index", "name"]),
    _t("set_track_volume", "Track fader, normalised 0.0-1.0 (0.85 = 0 dB).",
       {"track_index": _I, "volume": _N}, ["track_index", "volume"]),
    _t("set_track_pan", "Track pan, -1.0 (left) to 1.0 (right).",
       {"track_index": _I, "pan": _N}, ["track_index", "pan"]),
    _t("set_track_mute", "Mute or unmute a track.", {"track_index": _I, "mute": _B}, ["track_index"]),
    _t("set_track_solo", "Solo or unsolo a track.", {"track_index": _I, "solo": _B}, ["track_index"]),
    _t("set_track_arm", "Arm or disarm a track for recording.",
       {"track_index": _I, "arm": _B}, ["track_index"]),
    _t("set_master_volume", "Master fader, normalised 0.0-1.0.", {"volume": _N}, ["volume"]),
    _t("set_send", "Set a send level on a track.",
       {"track_index": _I, "send_index": _I, "value": _N},
       ["track_index", "send_index", "value"]),

    # ---- clips ------------------------------------------------------------
    _t("create_clip", "Create an empty MIDI clip in a session slot. length is in beats.",
       {"track_index": _I, "clip_index": _I, "length": _N},
       ["track_index", "clip_index"]),
    _t("add_notes_to_clip",
       "REPLACE all notes in a MIDI clip. notes = [{pitch, start_time, duration, velocity}].",
       {"track_index": _I, "clip_index": _I,
        "notes": {"type": "array", "items": {"type": "object", "properties": {
            "pitch": _I, "start_time": _N, "duration": _N, "velocity": _I},
            "required": ["pitch", "start_time", "duration"]}}},
       ["track_index", "clip_index", "notes"]),
    _t("edit_notes", "Add and/or remove notes from an existing clip without clearing it.",
       {"track_index": _I, "clip_index": _I,
        "add": {"type": "array", "items": {"type": "object"}},
        "remove": {"type": "array", "items": {"type": "object"}}},
       ["track_index", "clip_index"]),
    _t("set_clip_name", "Name a clip.", {"track_index": _I, "clip_index": _I, "name": _S},
       ["track_index", "clip_index", "name"]),
    _t("set_clip_loop", "Set loop start/end/enabled on a clip (beats).",
       {"track_index": _I, "clip_index": _I, "loop_start": _N, "loop_end": _N, "enabled": _B},
       ["track_index", "clip_index"]),
    _t("quantize_clip", "Quantize a clip's notes.",
       {"track_index": _I, "clip_index": _I, "grid": _S, "amount": _N},
       ["track_index", "clip_index"]),
    _t("fire_clip", "Launch a session clip.", {"track_index": _I, "clip_index": _I},
       ["track_index", "clip_index"]),
    _t("stop_clip", "Stop a session clip.", {"track_index": _I, "clip_index": _I},
       ["track_index", "clip_index"]),
    _t("fire_scene", "Launch a whole scene.", {"scene_index": _I}, ["scene_index"]),
    _t("stop_all_clips", "Stop every playing clip."),
    _t("create_scene", "Create an empty scene at index (-1 appends).", {"index": _I}),

    # ---- devices ----------------------------------------------------------
    _t("load_browser_item", "Load a browser item (from browser_search) onto a track.",
       {"track_index": _I, "item_uri": _S}, ["track_index", "item_uri"]),
    _t("set_device_parameter", "Set one device parameter by name or index.",
       {"track_index": _I, "device_index": _I, "parameter": {"type": ["string", "integer"]}, "value": _N},
       ["track_index", "device_index", "parameter", "value"]),
    _t("set_device_enabled", "Bypass or re-enable a device.",
       {"track_index": _I, "device_index": _I, "enabled": _B}, ["track_index", "device_index"]),

    # ---- meta -------------------------------------------------------------
    _t("undo", "Undo the last action in Live."),
    _t("redo", "Redo."),
    _t("save_project", "Save the current set."),
    _t("batch", "Run several commands in one main-thread pass: {commands: [{type, params}, ...]}.",
       {"commands": {"type": "array", "items": {"type": "object"}}}, ["commands"]),
]

TOOL_INDEX = {t["function"]["name"]: t["function"] for t in TOOLS}

# tool name -> (remote command, param mapper)
SIMPLE = {
    "session_info": ("get_session_info", {}),
    "return_tracks": ("get_return_tracks", {}),
    "scale_info": ("get_scale_info", {}),
    "locators": ("get_locators", {}),
    "session_snapshot": ("get_session_snapshot", {}),
    "stop_all_clips": ("stop_all_clips", {}),
    "start_playback": ("start_playback", {}),
    "stop_playback": ("stop_playback", {}),
    "undo": ("undo", {}),
    "redo": ("redo", {}),
    "save_project": ("try_save_project", {}),
    "track_info": ("get_track_info", {"track_index": "track_index"}),
    "clip_notes": ("get_clip_notes", {"track_index": "track_index", "clip_index": "clip_index"}),
    "clip_info": ("get_clip_info", {"track_index": "track_index", "clip_index": "clip_index"}),
    "arrangement_clips": ("get_arrangement_clips", {"track_index": "track_index"}),
    "device_parameters": ("get_device_parameters",
                          {"track_index": "track_index", "device_index": "device_index"}),
    "browser_tree": ("get_browser_tree", {"category_type": "category_type"}),
    "browser_search": ("search_browser",
                       {"query": "query", "category": "category", "max_results": "max_results"}),
    "set_tempo": ("set_tempo", {"tempo": "tempo"}),
    "set_loop": ("set_loop", {"start": "start", "length": "length", "enabled": "enabled"}),
    "set_current_song_time": ("set_current_song_time", {"time": "time"}),
    "set_metronome": ("set_metronome", {"enabled": "enabled"}),
    "create_locator": ("create_locator", {"name": "name"}),
    "create_midi_track": ("create_midi_track", {"index": "index"}),
    "create_audio_track": ("create_audio_track", {"index": "index"}),
    "delete_track": ("delete_track", {"track_index": "track_index"}),
    "set_track_name": ("set_track_name", {"track_index": "track_index", "name": "name"}),
    "set_track_volume": ("set_track_volume", {"track_index": "track_index", "volume": "volume"}),
    "set_track_pan": ("set_track_pan", {"track_index": "track_index", "pan": "pan"}),
    "set_track_mute": ("set_track_mute", {"track_index": "track_index", "mute": "mute"}),
    "set_track_solo": ("set_track_solo", {"track_index": "track_index", "solo": "solo"}),
    "set_track_arm": ("set_track_arm", {"track_index": "track_index", "arm": "arm"}),
    "set_master_volume": ("set_master_volume", {"volume": "volume"}),
    "set_send": ("set_send", {"track_index": "track_index", "send_index": "send_index", "value": "value"}),
    "create_clip": ("create_clip",
                    {"track_index": "track_index", "clip_index": "clip_index", "length": "length"}),
    "add_notes_to_clip": ("add_notes_to_clip",
                          {"track_index": "track_index", "clip_index": "clip_index", "notes": "notes"}),
    "edit_notes": ("edit_notes", {"track_index": "track_index", "clip_index": "clip_index",
                                  "add": "add", "remove": "remove"}),
    "set_clip_name": ("set_clip_name",
                      {"track_index": "track_index", "clip_index": "clip_index", "name": "name"}),
    "set_clip_loop": ("set_clip_loop", {"track_index": "track_index", "clip_index": "clip_index",
                                        "loop_start": "loop_start", "loop_end": "loop_end",
                                        "enabled": "enabled"}),
    "quantize_clip": ("quantize_clip", {"track_index": "track_index", "clip_index": "clip_index",
                                        "grid": "grid", "amount": "amount"}),
    "fire_clip": ("fire_clip", {"track_index": "track_index", "clip_index": "clip_index"}),
    "stop_clip": ("stop_clip", {"track_index": "track_index", "clip_index": "clip_index"}),
    "fire_scene": ("fire_scene", {"scene_index": "scene_index"}),
    "create_scene": ("create_scene", {"index": "index"}),
    "load_browser_item": ("load_browser_item",
                          {"track_index": "track_index", "item_uri": "item_uri"}),
    "set_device_parameter": ("set_device_parameter",
                             {"track_index": "track_index", "device_index": "device_index",
                              "parameter": "parameter", "value": "value"}),
    "set_device_enabled": ("set_device_enabled",
                           {"track_index": "track_index", "device_index": "device_index",
                            "enabled": "enabled"}),
    "batch": ("batch", {"commands": "commands"}),
}


def call_tool(name: str, args: dict | None, live) -> object:
    if name not in SIMPLE:
        raise ValueError("unknown tool: %s" % name)
    command, mapping = SIMPLE[name]
    params = {}
    args = args or {}
    for tool_key, remote_key in mapping.items():
        if tool_key in args and args[tool_key] is not None:
            params[remote_key] = args[tool_key]
    return live.send(command, params)
