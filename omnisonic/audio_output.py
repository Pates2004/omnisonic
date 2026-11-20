"""Explicit PortAudio output selection without changing the default microphone."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


WASAPI = "Windows WASAPI"


def normalize_output_device(value):
    """Persist a host API and exact name, never a volatile PortAudio index."""
    if (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(isinstance(part, str) and part.strip() for part in value)
    ):
        return list(value)
    return None


@dataclass(frozen=True)
class OutputDevice:
    index: int
    host: str
    name: str

    @property
    def key(self):
        return [self.host, self.name]

    @property
    def label(self):
        return f"{self.name} ({self.host})"


class OutputDeviceUnavailableError(LookupError):
    pass


def list_output_devices(audio):
    if audio is None:
        return []
    hosts = audio.query_hostapis()
    devices = [
        OutputDevice(item["index"], hosts[item["hostapi"]]["name"], item["name"])
        for item in audio.query_devices()
        if item["max_output_channels"] > 0
    ]
    counts = Counter((device.host, device.name) for device in devices)
    # Identical names on the same host cannot be persisted unambiguously.
    unique = [item for item in devices if counts[item.host, item.name] == 1]
    return sorted(unique, key=lambda d: (d.host != WASAPI, d.name.casefold(), d.host))


def playback_options(audio, selection):
    if selection is None:
        return {}
    for device in list_output_devices(audio):
        if device.key == selection:
            options = {"device": device.index}
            if device.host == WASAPI:
                # The speech rate need not match the endpoint's Windows mix rate.
                options["extra_settings"] = audio.WasapiSettings(auto_convert=True)
            return options
    raise OutputDeviceUnavailableError
