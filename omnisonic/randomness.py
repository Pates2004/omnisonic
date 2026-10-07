"""Temporarily seed generation without changing unrelated accelerator RNGs."""

from __future__ import annotations

import random
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Any


@contextmanager
def seeded_generation(seed: int | None, device: Any) -> Iterator[None]:
    """Seed one generation and restore every acquired RNG state on exit.

    ``None`` leaves RNGs untouched and imports neither NumPy nor PyTorch.
    Otherwise seed must be an integer in 0..2**31-1, excluding bool. Device
    accepts a torch.device or a device string: cpu, cuda[:index] (also ROCm),
    or xpu[:index]. Only that accelerator is seeded; its current-device setting
    and the states of other GPUs are preserved. Global determinism flags are
    never changed. This does not make nondeterministic kernels deterministic,
    nor isolate unrelated threads that concurrently consume process-wide RNGs.
    """
    if seed is None:
        yield
        return
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise TypeError("Generation seed must be an integer or None.")
    if not 0 <= seed <= 2**31 - 1:
        raise ValueError("Generation seed must be between 0 and 2147483647.")

    # Register each restoration immediately. ExitStack attempts the remaining
    # restorations even if acquiring/seeding/restoring another RNG raises.
    with ExitStack() as restore:
        restore.callback(random.setstate, random.getstate())
        import numpy as np

        restore.callback(np.random.set_state, np.random.get_state())
        import torch

        restore.callback(torch.set_rng_state, torch.get_rng_state())
        resolved = torch.device(device)
        if resolved.type not in ("cpu", "cuda", "xpu"):
            raise ValueError(f"Unsupported generation seed device: {resolved.type}.")

        accelerator = None
        index = None
        if resolved.type != "cpu":
            accelerator = getattr(torch, resolved.type)
            index = resolved.index
            if index is None:
                index = accelerator.current_device()
            state = accelerator.get_rng_state(index)
            restore.callback(accelerator.set_rng_state, state, index)

        random.seed(seed)
        np.random.seed(seed)
        # torch.manual_seed also seeds all GPUs, including unrelated devices.
        torch.default_generator.manual_seed(seed)
        if accelerator is not None:
            # get_rng_state above initialized this backend, so manual_seed's
            # lazy callback runs now, while the selected device is current.
            with accelerator.device(index):
                accelerator.manual_seed(seed)
        yield
