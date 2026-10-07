"""Bounded worker-owned CPU cache for unchanged reference audio conditioning."""

from __future__ import annotations

import hashlib
import os
import stat
import weakref
from dataclasses import dataclass
from pathlib import Path


_HASH_CHUNK_BYTES = 1024 * 1024
_MAX_TOKEN_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True)
class _Entry:
    owner: weakref.ReferenceType
    key: tuple
    prompt: object


def _file_version(info):
    # Windows stat/fstat do not consistently agree on ctime semantics across
    # Python versions. The content digest catches replacements preserving mtime.
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _source_fingerprint(state, source):
    """Hash a stable regular file without loading it into RAM or following a FIFO."""
    state.check_cancelled()
    try:
        path = Path(source).resolve(strict=True)
        initial = path.stat()
        if not stat.S_ISREG(initial.st_mode):
            return None
        version = _file_version(initial)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            if _file_version(opened) != version:
                return None
            while True:
                state.check_cancelled()
                chunk = stream.read(_HASH_CHUNK_BYTES)
                if not chunk:
                    break
                digest.update(chunk)
            final = os.fstat(stream.fileno())
        if _file_version(final) != version or _file_version(path.stat()) != version:
            return None
        state.check_cancelled()
        return (os.path.normcase(str(path)), version, digest.digest())
    except (OSError, TypeError, ValueError):
        # Caching is optional. The normal audio loader owns unsupported paths
        # and missing/unreadable-source diagnostics, not this optimization.
        return None


def _copy_cpu_prompt(prompt):
    """Keep no GPU storage or mutable alias to an encoder/caller-owned prompt."""
    return type(prompt)(
        ref_audio_tokens=prompt.ref_audio_tokens.detach().cpu().clone(),
        ref_text=str(prompt.ref_text),
        ref_rms=float(prompt.ref_rms),
    )


class ReferencePromptCache:
    """A single entry, used only by the application's serialized model worker.

    Misses return the encoder's original prompt. Hits return independent CPU
    tensors of the same prompt type. No model instance is retained by a key.
    """

    def __init__(self, max_token_bytes=_MAX_TOKEN_BYTES):
        self.max_token_bytes = max_token_bytes
        self._entry = None

    def clear(self):
        self._entry = None

    def get_or_create(
        self, state, model, source, transcript, preprocess_prompt=True, *, asr_identity=None
    ):
        try:
            fingerprint = _source_fingerprint(state, source)
            key = (fingerprint, transcript, bool(preprocess_prompt), asr_identity)
            entry = self._entry
            if (
                fingerprint is not None
                and entry is not None
                and entry.owner() is model
                and entry.key == key
            ):
                prompt = _copy_cpu_prompt(entry.prompt)
                state.check_cancelled()
                return prompt

            self.clear()
            state.check_cancelled()
            prompt = model.create_voice_clone_prompt(
                ref_audio=source, ref_text=transcript, preprocess_prompt=preprocess_prompt
            )
            state.check_cancelled()
            if fingerprint is None:
                return prompt
            tokens = prompt.ref_audio_tokens
            if tokens.numel() * tokens.element_size() > self.max_token_bytes:
                return prompt
            prompt.validate()
            try:
                owner = weakref.ref(model)
            except TypeError:
                return prompt
            stored_prompt = _copy_cpu_prompt(prompt)
            if _source_fingerprint(state, source) != fingerprint:
                return prompt
            state.check_cancelled()
            self._entry = _Entry(owner, key, stored_prompt)
            return prompt
        except Exception:
            self.clear()
            raise
