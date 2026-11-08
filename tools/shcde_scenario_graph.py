#!/usr/bin/env python3
"""Compile a visual-style scenario event graph into reusable SHCDE Lua logic.

Produces honest, independently testable Lua: Tick/Signal handlers invoke an
author-provided context bridge. Registration with the installed game's Script
Extender is game/mod-specific; the generated module does not claim to install
or register unverified hooks.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from typing import Any


SCHEMA = "spritesuite.shcde.scenario-graph.v1"


def lua_string(text: str) -> str:
    if not isinstance(text, str):
        raise TypeError("Lua string expected")
    pieces = ['"']
    for char in text:
        code = ord(char)
        if char == "\\":
            pieces.append("\\\\")
        elif char == '"':
            pieces.append('\\"')
        elif char == "\n":
            pieces.append("\\n")
        elif char == "\r":
            pieces.append("\\r")
        elif char == "\t":
            pieces.append("\\t")
        elif code < 32 or code == 127:
            pieces.append("\\" + str(code).zfill(3))
        else:
            pieces.append(char)
    pieces.append('"')
    return "".join(pieces)


def lua_value(value: Any, depth: int = 0) -> str:
    if depth > 50:
        raise ValueError("Scenario payload is too deeply nested")
    if value is None:
        return "nil"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("NaN/Infinity cannot be compiled to Lua")
        return format(value, ".17g")
    if isinstance(value, str):
        return lua_string(value)
    if isinstance(value, (tuple, list)):
        return "{" + ", ".join(lua_value(v, depth + 1) for v in value) + "}"
    if isinstance(value, dict):
        return "{" + ", ".join(
            "[" + lua_string(str(k)) + "] = " + lua_value(v, depth + 1)
            for k, v in sorted(value.items(), key=lambda entry: str(entry[0]))
        ) + "}"
    raise TypeError("Unsupported JSON payload in scenario: " + type(value).__name__)


def validate_graph(document: dict) -> list[dict]:
    if not isinstance(document, dict) or not isinstance(document.get("events"), list):
        raise ValueError("Scenario requires an events array")
    events = document["events"]
    seen: set[str] = set()
    result: list[dict] = []
    for index, entry in enumerate(events):
        if not isinstance(entry, dict):
            raise ValueError("Event must be a JSON object: " + str(index))
        ident = entry.get("id")
        if not isinstance(ident, str) or not ident or ident in seen:
            raise ValueError("Missing or duplicated event ID")
        seen.add(ident)
        trigger = entry.get("trigger", {})
        if not isinstance(trigger, dict):
            raise ValueError("Event trigger must be an object")
        kind = trigger.get("kind", "start")
        if kind not in ("start", "once", "interval", "flag", "signal", "custom"):
            raise ValueError("Unknown trigger type: " + str(kind))
        if kind == "interval":
            every = trigger.get("ticks")
            if type(every) is not int or every <= 0:
                raise ValueError("Interval needs positive integer ticks")
        if kind in ("signal", "flag"):
            name = trigger.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError(kind + " requires a nonempty name")
        if kind == "custom" and not isinstance(trigger.get("luaExpression"), str):
            raise ValueError("Custom trigger needs its author-written Lua expression")
        actions = entry.get("actions")
        if not isinstance(actions, list):
            raise ValueError("Scenario event requires an actions array")
        for action in actions:
            if not isinstance(action, dict) or not isinstance(action.get("type"), str):
                raise ValueError("Each event action requires a string type")
        result.append(entry)
    return result


def _conditions(trigger: dict, *, tick: bool) -> str:
    kind = trigger.get("kind", "start")
    if kind == "start":
        return "not state.fired[id]" if tick else "false"
    if kind == "once":
        return "not state.fired[id]" if tick else "false"
    if kind == "interval":
        return "tick > 0 and tick % " + str(trigger["ticks"]) + " == 0" if tick else "false"
    if kind == "flag":
        return "ctx.get_flag ~= nil and ctx:get_flag(" + lua_string(trigger["name"]) + ") == " + lua_value(trigger.get("equals", True)) if tick else "false"
    if kind == "signal":
        return "name == " + lua_string(trigger["name"]) if not tick else "false"
    if kind == "custom":
        return "(" + trigger["luaExpression"] + ")" if tick else "false"
    return "false"


def compile_lua(document: dict) -> str:
    events = validate_graph(document)
    result = [
        "-- Generated by SpriteSuite. Source graph remains fully editable.",
        "-- Context bridge must provide :perform(type, payload); optional :get_flag(name).",
        "-- Call M.Tick(ctx, tick) or M.Signal(ctx, name, payload) from your real",
        "-- SHCDE Lua event registration. No unverified hook is installed here.",
        "local M = {}",
        "local state = { fired = {} }",
        "",
        "function M.Reset()",
        "  state = { fired = {} }",
        "end",
        "",
        "local function dispatch(ctx, typ, payload)",
        "  if ctx == nil or type(ctx.perform) ~= 'function' then",
        "    error('SpriteSuite scenario bridge must implement ctx:perform')",
        "  end",
        "  return ctx:perform(typ, payload)",
        "end",
        "",
    ]
    for index, event in enumerate(events):
        ident = event["id"]
        actions = event["actions"]
        result += ["local function action_" + str(index) + "(ctx)",
                   "  local id = " + lua_string(ident)]
        if event.get("once", False) or event.get("trigger", {}).get("kind", "start") in ("start", "once"):
            result.append("  state.fired[id] = true")
        for action in actions:
            payload = {k: v for k, v in action.items() if k != "type"}
            result.append("  dispatch(ctx, " + lua_string(action["type"]) +
                          ", " + lua_value(payload) + ")")
        result += ["end", ""]
    for public_name, tick in (("Tick", True), ("Signal", False)):
        signature = "ctx, tick" if tick else "ctx, name, payload"
        result.append("function M." + public_name + "(" + signature + ")")
        if not tick:
            result.append("  payload = payload or {}")
        for index, event in enumerate(events):
            kind = event.get("trigger", {}).get("kind", "start")
            if (kind == "signal") == tick:
                continue
            cond = _conditions(event.get("trigger", {}), tick=tick)
            if kind == "signal":
                equals = event.get("trigger", {}).get("match", {})
                if not isinstance(equals, dict):
                    raise ValueError("Signal matching must be an object")
                for key, expected in sorted(equals.items()):
                    cond += " and payload[" + lua_string(key) + "] == " + lua_value(expected)
            result += ["  if " + cond.replace("state.fired[id]", "state.fired[" + lua_string(event["id"]) + "]") + " then",
                       "    action_" + str(index) + "(ctx)",
                       "  end"]
        result += ["end", ""]
    result.append("return M")
    return "\n".join(result) + "\n"


def guide(document: dict) -> str:
    return (
        "# SpriteSuite Scenario Integration\n\n"
        "This package contains an executable Lua **module**, not a verified native "
        "hook. Load it in the target Script Extender Lua environment, implement "
        "the ctx:perform(action, payload) bridge using validated game APIs, and "
        "register M.Tick / M.Signal with actual game events.\n\n"
        "The project graph can describe unit, economy, dialogue and mission "
        "events without requiring artistic approvals or a pinned game version. "
        "Multiplayer state changes must be synchronized through the game's "
        "authoritative Chore/event transport, not locally invoked on clients.\n\n"
        "Events: " + str(len(validate_graph(document))) + "\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--guide", type=Path)
    args = parser.parse_args(argv)
    try:
        document = json.loads(args.graph.read_text(encoding="utf-8-sig"))
        output = compile_lua(document)
        if args.output.exists():
            raise FileExistsError("Existing Lua output is not overwritten: " + str(args.output))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8", newline="\n")
        if args.guide:
            if args.guide.exists():
                raise FileExistsError("Existing guide is not overwritten")
            args.guide.write_text(guide(document), encoding="utf-8")
        print(json.dumps({"output": str(args.output),
                          "events": len(document["events"]),
                          "gameEventHookInstalled": False,
                          "independentLuaModuleCreated": True}, indent=2))
        return 0
    except (OSError, ValueError, TypeError) as error:
        print("SpriteSuite Scenario: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
