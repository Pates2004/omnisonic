"""Explicit PortAudio routes without changing process or system defaults."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal


WASAPI = "Windows WASAPI"


def normalize_audio_device(value):
    """Persist a host API and exact name, never a volatile PortAudio index."""
    if (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(isinstance(part, str) and part.strip() for part in value)
    ):
        return list(value)
    return None


@dataclass(frozen=True)
class AudioDevice:
    index: int
    host: str
    name: str

    @property
    def key(self):
        return [self.host, self.name]

    @property
    def label(self):
        return f"{self.name} ({self.host})"


class AudioDeviceUnavailableError(LookupError):
    def __init__(self, host: str, name: str):
        self.host = host
        self.name = name
        super().__init__(f"{name} ({host})")


def list_audio_devices(audio, kind: Literal["input", "output"]):
    if audio is None:
        return []
    hosts = audio.query_hostapis()
    devices = [
        AudioDevice(item["index"], hosts[item["hostapi"]]["name"], item["name"])
        for item in audio.query_devices()
        if item[f"max_{kind}_channels"] > 0
    ]
    counts = Counter((device.host, device.name) for device in devices)
    # Identical names on the same host cannot be persisted unambiguously.
    unique = [item for item in devices if counts[item.host, item.name] == 1]
    return sorted(unique, key=lambda d: (d.host != WASAPI, d.name.casefold(), d.host))


def stream_options(audio, selection, kind: Literal["input", "output"]):
    if selection is None:
        return {}
    for device in list_audio_devices(audio, kind):
        if device.key == selection:
            options = {"device": device.index}
            if kind == "output" and device.host == WASAPI:
                # The speech rate need not match the endpoint's Windows mix rate.
                options["extra_settings"] = audio.WasapiSettings(auto_convert=True)
            return options
    raise AudioDeviceUnavailableError(*selection)
