"""Parse SRT/WebVTT and stream a single narrator onto an exact audio timeline.

This is a narration importer, not a browser subtitle renderer. Overlapping cues
are rejected rather than silently dropping words or mixing different speakers.
"""

from __future__ import annotations

import codecs
import html
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np


MAX_SUBTITLE_BYTES = 5 * 1024 * 1024
MAX_SUBTITLE_CUES = 20_000
MAX_TIMELINE_MS = 12 * 60 * 60 * 1000
MAX_CUE_DURATION_MS = 120 * 1000
# The caller writes mono PCM16 WAV. Leave room for RIFF/container metadata.
MAX_OUTPUT_FRAMES = ((1 << 32) - 1024) // 2

_MESSAGES = {
    "subtitle_unsupported_format": "Unsupported subtitle format: {extension}.",
    "subtitle_too_large": "Subtitle file exceeds {max_mb} MiB.",
    "subtitle_encoding_error": "Use UTF-8 subtitles, or UTF-16 with a BOM for SRT.",
    "subtitle_invalid_header": "WebVTT requires a WEBVTT header followed by a blank line.",
    "subtitle_timestamp_map": "WebVTT X-TIMESTAMP-MAP is not supported; use film timestamps.",
    "subtitle_invalid_cue": "Subtitle {index} has invalid cue syntax or a missing separator.",
    "subtitle_invalid_timestamp": "Subtitle {index} has an invalid timestamp: {value}.",
    "subtitle_invalid_range": "Subtitle {index} must end after it starts: {start} --> {end}.",
    "subtitle_overlap": "Subtitle {index} overlaps or precedes subtitle {previous}.",
    "subtitle_empty": "The subtitle file contains no narration cues.",
    "subtitle_empty_cue": "Subtitle {index} contains no spoken text.",
    "subtitle_too_many": "Subtitle file exceeds {max_cues} cues.",
    "subtitle_timeline_limit": "Subtitle timeline exceeds {max_hours} hours.",
    "subtitle_cue_too_long": "Subtitle {index} exceeds {max_seconds} seconds; split it first.",
    "subtitle_audio_invalid": "Subtitle {index} did not produce finite, nonempty mono audio.",
    "subtitle_audio_overflow": (
        "Subtitle {index} produced {actual_seconds:.6f} seconds of audio for a "
        "{available_seconds:.6f}-second interval. No speech was trimmed."
    ),
    "subtitle_invalid_sample_rate": "Subtitle audio sample rate must be a positive integer.",
    "subtitle_output_too_large": "Subtitle audio would exceed the WAV container size limit.",
}

_SRT_TIMESTAMP = re.compile(r"([0-9]{2,6}):([0-9]{2}):([0-9]{2})[,.]([0-9]{3})")
_VTT_TIMESTAMP = re.compile(r"(?:([0-9]{2,6}):)?([0-9]{2}):([0-9]{2})\.([0-9]{3})")
_TIMING_LINE = re.compile(r"([^\s]+)[ \t]+-->[ \t]+([^\s]+)(?:[ \t]+(.*))?")
_TAG = re.compile(
    r"<(?P<close>/)?(?P<name>b|i|u|s|font|em|strong|c|v|lang|ruby|rt|br)"
    r"(?P<extra>(?:[. \t][^<>]*?)?)(?P<selfclose>/)?>",
    re.IGNORECASE,
)
_INLINE_TIMESTAMP = re.compile(r"<(?:[0-9]{2,6}:)?[0-9]{2}:[0-9]{2}\.[0-9]{3}>")
_MARKUP_TOKEN = re.compile(f"(?:{_TAG.pattern})|(?:{_INLINE_TIMESTAMP.pattern})", re.IGNORECASE)
_ASS_BLOCK = re.compile(r"\{(\\[^{}]*)\}")
_NUMBER = r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)"
_ASS_COMMAND = re.compile(
    rf"(?:an[1-9]|a(?:[1-9]|10|11)|[bius][01]|q[0-3]|p[0-9]+|"
    rf"(?:fs|fsc[xy]|fsp|fr[xyz]?|fax|fay|bord|[xy]bord|shad|[xy]shad|be|blur|pbo){_NUMBER}|"
    r"fn[^\\{}]+|r[^\\{}]*|[1-4]?[ca]&H[0-9a-f]{1,8}&|alpha&H[0-9a-f]{1,2}&|"
    rf"(?:pos|org)\({_NUMBER},{_NUMBER}\)|"
    rf"(?:move|fad|fade)\({_NUMBER}(?:,{_NUMBER}){{1,6}}\))",
    re.IGNORECASE,
)


class SubtitleError(ValueError):
    """A translatable error with an English diagnostic representation."""

    def __init__(self, message_key: str, **values):
        self.message_key = message_key
        self.values = values
        super().__init__(_MESSAGES[message_key].format(**values))


@dataclass(frozen=True)
class SubtitleCue:
    """A one-based file-order cue, with integer millisecond boundaries."""

    index: int
    start_ms: int
    end_ms: int
    text: str


def _timestamp(value: str, index: int, *, webvtt: bool) -> int:
    match = (_VTT_TIMESTAMP if webvtt else _SRT_TIMESTAMP).fullmatch(value)
    if match is None:
        raise SubtitleError("subtitle_invalid_timestamp", index=index, value=value[:100])
    hours, minutes, seconds, milliseconds = (int(part or 0) for part in match.groups())
    if minutes > 59 or seconds > 59:
        raise SubtitleError("subtitle_invalid_timestamp", index=index, value=value)
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + milliseconds


def _spoken_text(value: str) -> str:
    """Remove recognized styling, preserving literal comparisons/voice markers."""

    def remove_ass(match):
        commands = match.group(1).split("\\")[1:]
        return "" if all(_ASS_COMMAND.fullmatch(item) for item in commands) else match.group(0)

    value = _ASS_BLOCK.sub(remove_ass, value)
    result = []
    position = 0
    ruby_text_depth = 0
    for match in _MARKUP_TOKEN.finditer(value):
        if not ruby_text_depth:
            result.append(value[position : match.start()])
        tag = _TAG.fullmatch(match.group(0))
        if tag:
            name = tag.group("name").lower()
            closing = bool(tag.group("close"))
            if name == "rt" and not tag.group("selfclose"):
                ruby_text_depth = max(0, ruby_text_depth - 1) if closing else ruby_text_depth + 1
            elif name == "ruby" and closing:
                # WebVTT permits the last </rt> to be omitted inside <ruby>.
                ruby_text_depth = 0
            elif name == "br" and not ruby_text_depth:
                result.append(" ")
        position = match.end()
    if not ruby_text_depth:
        result.append(value[position:])
    # Decode after stripping real markup: &lt;b&gt; is literal visible text.
    return " ".join(html.unescape("".join(result)).split())


def _validate_cues(cues: tuple[SubtitleCue, ...], check_cancelled: Callable[[], None]) -> None:
    if not cues:
        raise SubtitleError("subtitle_empty")
    if len(cues) > MAX_SUBTITLE_CUES:
        raise SubtitleError("subtitle_too_many", max_cues=MAX_SUBTITLE_CUES)
    previous = None
    for cue in cues:
        check_cancelled()
        if not isinstance(cue, SubtitleCue) or any(
            isinstance(number, bool) or not isinstance(number, int)
            for number in (cue.index, cue.start_ms, cue.end_ms)
        ):
            raise SubtitleError("subtitle_invalid_cue", index=getattr(cue, "index", "?"))
        if cue.index < 1 or cue.start_ms < 0 or cue.end_ms <= cue.start_ms:
            raise SubtitleError(
                "subtitle_invalid_range", index=cue.index, start=cue.start_ms, end=cue.end_ms
            )
        if cue.end_ms > MAX_TIMELINE_MS:
            raise SubtitleError("subtitle_timeline_limit", max_hours=MAX_TIMELINE_MS // 3_600_000)
        if cue.end_ms - cue.start_ms > MAX_CUE_DURATION_MS:
            raise SubtitleError(
                "subtitle_cue_too_long",
                index=cue.index,
                max_seconds=MAX_CUE_DURATION_MS // 1000,
            )
        if previous is not None and cue.start_ms < previous.end_ms:
            raise SubtitleError("subtitle_overlap", index=cue.index, previous=previous.index)
        if not isinstance(cue.text, str) or not cue.text.strip():
            raise SubtitleError("subtitle_empty_cue", index=cue.index)
        previous = cue


def read_subtitles(
    path: str | Path, check_cancelled: Callable[[], None] = lambda: None
) -> tuple[SubtitleCue, ...]:
    """Read SRT or WebVTT, rejecting malformed cues instead of silently omitting them."""
    path = Path(path)
    extension = path.suffix.lower()
    if extension not in {".srt", ".vtt"}:
        raise SubtitleError("subtitle_unsupported_format", extension=extension)
    check_cancelled()
    with path.open("rb") as stream:
        data = stream.read(MAX_SUBTITLE_BYTES + 1)
    check_cancelled()
    if len(data) > MAX_SUBTITLE_BYTES:
        raise SubtitleError("subtitle_too_large", max_mb=MAX_SUBTITLE_BYTES // (1024 * 1024))
    webvtt = extension == ".vtt"
    encoding = "utf-8-sig"
    if not webvtt and data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        encoding = "utf-16"
    try:
        text = data.decode(encoding)
    except UnicodeError as exc:
        raise SubtitleError("subtitle_encoding_error") from exc
    if "\0" in text:
        raise SubtitleError("subtitle_encoding_error")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = [block.strip("\n") for block in re.split(r"\n(?:[ \t]*\n)+", text) if block.strip()]
    if webvtt:
        if not blocks:
            raise SubtitleError("subtitle_invalid_header")
        header = blocks.pop(0).splitlines()
        if not re.fullmatch(r"WEBVTT(?:[ \t].*)?", header[0]) or any(
            "-->" in line for line in header
        ):
            raise SubtitleError("subtitle_invalid_header")
        if any(re.match(r"[ \t]*X-TIMESTAMP-MAP(?:[=: \t]|$)", line) for line in header):
            raise SubtitleError("subtitle_timestamp_map")
    cues = []
    for block in blocks:
        check_cancelled()
        lines = block.splitlines()
        first = lines[0]
        index = len(cues) + 1
        if webvtt and (
            re.match(r"NOTE(?:[ \t]|$)", first)
            or (first in {"STYLE", "REGION"} and (len(lines) < 2 or "-->" not in lines[1]))
        ):
            if any("-->" in line for line in lines):
                # Missing separators must not hide a cue inside display metadata.
                raise SubtitleError("subtitle_invalid_cue", index=index)
            continue
        if webvtt and first.startswith("X-TIMESTAMP-MAP"):
            raise SubtitleError("subtitle_timestamp_map")
        if index > MAX_SUBTITLE_CUES:
            raise SubtitleError("subtitle_too_many", max_cues=MAX_SUBTITLE_CUES)
        timing_index = 0 if webvtt and "-->" in first else 1
        if len(lines) <= timing_index or (not webvtt and re.fullmatch(r"[0-9]+", first) is None):
            raise SubtitleError("subtitle_invalid_cue", index=index)
        match = _TIMING_LINE.fullmatch(lines[timing_index].strip())
        if match is None or (not webvtt and match.group(3)):
            raise SubtitleError("subtitle_invalid_cue", index=index)
        payload = lines[timing_index + 1 :]
        if any("-->" in line for line in payload):
            # A missing blank line must not turn the next cue's timing into speech.
            raise SubtitleError("subtitle_invalid_cue", index=index)
        cues.append(
            SubtitleCue(
                index,
                _timestamp(match.group(1), index, webvtt=webvtt),
                _timestamp(match.group(2), index, webvtt=webvtt),
                _spoken_text("\n".join(payload)),
            )
        )
    result = tuple(cues)
    _validate_cues(result, check_cancelled)
    return result


def render_subtitles(
    cues: Iterable[SubtitleCue],
    sampling_rate: int,
    synthesize: Callable[[str, float], np.ndarray],
    write_audio: Callable[[np.ndarray], None],
    check_cancelled: Callable[[], None] = lambda: None,
    on_progress: Callable[[int, int, SubtitleCue], None] = lambda _index, _total, _cue: None,
) -> None:
    """Stream mono narration and silence; never trim speech or shift a cue's start.

    The caller owns the destination and removes a partial file on failure.
    `synthesize` receives the cue's exact duration in seconds. Any generated
    samples beyond its interval raise an error, including submillisecond excess.
    """
    check_cancelled()
    if (
        isinstance(sampling_rate, (bool, np.bool_))
        or not isinstance(sampling_rate, (int, np.integer))
        or sampling_rate <= 0
    ):
        raise SubtitleError("subtitle_invalid_sample_rate")
    sampling_rate = int(sampling_rate)
    collected = []
    for cue in cues:
        check_cancelled()
        collected.append(cue)
        if len(collected) > MAX_SUBTITLE_CUES:
            raise SubtitleError("subtitle_too_many", max_cues=MAX_SUBTITLE_CUES)
    validated = tuple(collected)
    _validate_cues(validated, check_cancelled)

    def frame(milliseconds):
        return (milliseconds * sampling_rate + 500) // 1000

    if frame(validated[-1].end_ms) > MAX_OUTPUT_FRAMES:
        raise SubtitleError("subtitle_output_too_large")
    for cue in validated:
        if frame(cue.end_ms) <= frame(cue.start_ms):
            raise SubtitleError(
                "subtitle_invalid_range", index=cue.index, start=cue.start_ms, end=cue.end_ms
            )
    # Reuse one bounded zero block even for a long initial silent interval.
    block_frames = min(sampling_rate, 65_536)
    silence = np.zeros(block_frames, dtype=np.float32)

    def write_silence(length):
        while length > 0:
            check_cancelled()
            count = min(length, block_frames)
            write_audio(silence[:count])
            length -= count

    position = 0
    for done, cue in enumerate(validated):
        check_cancelled()
        start = frame(cue.start_ms)
        end = frame(cue.end_ms)
        on_progress(done, len(validated), cue)
        generated = synthesize(cue.text, (cue.end_ms - cue.start_ms) / 1000)
        try:
            audio = np.asarray(generated)
        except (ValueError, TypeError) as exc:
            raise SubtitleError("subtitle_audio_invalid", index=cue.index) from exc
        check_cancelled()
        if (
            audio.ndim != 1
            or not audio.size
            or audio.dtype.kind not in "fi"
            or not np.isfinite(audio).all()
        ):
            raise SubtitleError("subtitle_audio_invalid", index=cue.index)
        if len(audio) > end - start:
            raise SubtitleError(
                "subtitle_audio_overflow",
                index=cue.index,
                actual_seconds=len(audio) / sampling_rate,
                available_seconds=(end - start) / sampling_rate,
            )
        with np.errstate(over="ignore", invalid="ignore"):
            audio = audio.astype(np.float32, copy=False)
        if not np.isfinite(audio).all():
            raise SubtitleError("subtitle_audio_invalid", index=cue.index)
        write_silence(start - position)
        for offset in range(0, len(audio), block_frames):
            check_cancelled()
            write_audio(audio[offset : offset + block_frames])
        write_silence(end - start - len(audio))
        position = end
        on_progress(done + 1, len(validated), cue)
    check_cancelled()
