"""Keyboard shortcut definitions and validation for the desktop app."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ShortcutDefinition:
    key: str
    label_key: str
    default: str


SHORTCUT_DEFINITIONS = (
    ShortcutDefinition("open_reference", "shortcut_action_open_reference", "Ctrl+O"),
    ShortcutDefinition("generate", "shortcut_action_generate", "Ctrl+G"),
    ShortcutDefinition("save_result", "shortcut_action_save_result", "Ctrl+S"),
    ShortcutDefinition("save_preset", "shortcut_action_save_preset", "Ctrl+Shift+S"),
    ShortcutDefinition("record", "shortcut_action_record", "Ctrl+R"),
    ShortcutDefinition("play_pause", "shortcut_action_play_pause", "Ctrl+P"),
    ShortcutDefinition("stop_playback", "shortcut_action_stop_playback", "Ctrl+Shift+P"),
)

_MODIFIER_ALIASES = {
    "ctrl": "Ctrl",
    "control": "Ctrl",
    "alt": "Alt",
    "shift": "Shift",
}
_MODIFIER_ORDER = ("Ctrl", "Alt", "Shift")
_KEY_ALIASES = {
    "space": "Space",
    "enter": "Enter",
    "return": "Enter",
    "tab": "Tab",
    "esc": "Escape",
    "escape": "Escape",
    "backspace": "Backspace",
    "delete": "Delete",
    "del": "Delete",
    "insert": "Insert",
    "ins": "Insert",
    "home": "Home",
    "end": "End",
    "pageup": "PageUp",
    "pgup": "PageUp",
    "pagedown": "PageDown",
    "pgdn": "PageDown",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
}


def default_shortcut_bindings() -> dict[str, str]:
    return {definition.key: definition.default for definition in SHORTCUT_DEFINITIONS}


def default_shortcut_enabled() -> dict[str, bool]:
    return {definition.key: True for definition in SHORTCUT_DEFINITIONS}


def normalize_shortcut(value: object) -> str:
    """Return a stable, human-readable shortcut or raise ``ValueError``."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("empty shortcut")

    raw_parts = [part.strip() for part in value.split("+")]
    if any(not part for part in raw_parts):
        raise ValueError("empty shortcut component")

    modifiers: set[str] = set()
    keys: list[str] = []
    for part in raw_parts:
        modifier = _MODIFIER_ALIASES.get(part.casefold())
        if modifier:
            if modifier in modifiers:
                raise ValueError("duplicate modifier")
            modifiers.add(modifier)
        else:
            keys.append(part)

    if len(keys) != 1:
        raise ValueError("shortcut must contain exactly one key")

    raw_key = keys[0]
    folded_key = raw_key.casefold().replace(" ", "")
    if len(raw_key) == 1 and raw_key.isascii() and raw_key.isalnum():
        key = raw_key.upper()
    elif folded_key.startswith("f") and folded_key[1:].isdigit():
        function_number = int(folded_key[1:])
        if not 1 <= function_number <= 24:
            raise ValueError("unsupported function key")
        key = f"F{function_number}"
    else:
        key = _KEY_ALIASES.get(folded_key, "")
        if not key:
            raise ValueError("unsupported key")

    if len(key) == 1 and key.isalnum() and not ({"Ctrl", "Alt"} & modifiers):
        raise ValueError("letter and number shortcuts require Ctrl or Alt")

    ordered_modifiers = [modifier for modifier in _MODIFIER_ORDER if modifier in modifiers]
    return "+".join((*ordered_modifiers, key))


def shortcut_parts(value: object) -> tuple[tuple[str, ...], str]:
    normalized = normalize_shortcut(value)
    parts = normalized.split("+")
    return tuple(parts[:-1]), parts[-1]


def find_shortcut_conflicts(
    bindings: Mapping[str, object], enabled: Mapping[str, object]
) -> list[tuple[str, str, str]]:
    """Return pairs of enabled actions assigned to the same shortcut."""
    assigned: dict[str, str] = {}
    conflicts: list[tuple[str, str, str]] = []
    for definition in SHORTCUT_DEFINITIONS:
        if enabled.get(definition.key) is not True:
            continue
        normalized = normalize_shortcut(bindings.get(definition.key, definition.default))
        previous = assigned.get(normalized)
        if previous:
            conflicts.append((previous, definition.key, normalized))
        else:
            assigned[normalized] = definition.key
    return conflicts
