"""No-GPU regression tests for temporary, device-scoped generation seeds."""

import builtins
import random
import sys
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from omnisonic.randomness import seeded_generation


class FakeGenerator:
    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.fail_seed = False

    def manual_seed(self, seed):
        self.rng.seed(seed)
        if self.fail_seed:
            raise RuntimeError("seed failure")

    def get_state(self):
        return self.rng.getstate()

    def set_state(self, state):
        self.rng.setstate(state)


class FakeAccelerator:
    def __init__(self):
        self.generators = [FakeGenerator(31), FakeGenerator(47)]
        self.current = 0
        self.calls = []
        self.fail_restore = False
        self.fail_snapshot = False

    def current_device(self):
        self.calls.append(("current",))
        return self.current

    def get_rng_state(self, index):
        self.calls.append(("get", index))
        if self.fail_snapshot:
            raise RuntimeError("snapshot failure")
        return self.generators[index].get_state()

    def set_rng_state(self, state, index):
        self.calls.append(("restore", index))
        if self.fail_restore:
            raise RuntimeError("restore failure")
        self.generators[index].set_state(state)

    @contextmanager
    def device(self, index):
        previous = self.current
        self.current = index
        try:
            yield
        finally:
            self.current = previous

    def manual_seed(self, seed):
        self.calls.append(("seed", self.current, seed))
        self.generators[self.current].manual_seed(seed)


def fake_device(value):
    if not isinstance(value, str):
        return value
    kind, _, index = value.partition(":")
    return SimpleNamespace(type=kind, index=int(index) if index else None)


class SeededGenerationTests(unittest.TestCase):
    def setUp(self):
        self.original_python = random.getstate()
        self.addCleanup(random.setstate, self.original_python)
        self.numpy_generator = FakeGenerator(13)
        self.cpu = FakeGenerator(19)
        self.cuda = FakeAccelerator()
        self.xpu = FakeAccelerator()
        self.numpy = SimpleNamespace(
            random=SimpleNamespace(
                seed=self.numpy_generator.manual_seed,
                get_state=self.numpy_generator.get_state,
                set_state=self.numpy_generator.set_state,
            )
        )
        self.torch = SimpleNamespace(
            device=fake_device,
            default_generator=self.cpu,
            get_rng_state=self.cpu.get_state,
            set_rng_state=self.cpu.set_state,
            cuda=self.cuda,
            xpu=self.xpu,
        )
        dependencies = patch.dict(sys.modules, {"numpy": self.numpy, "torch": self.torch})
        dependencies.start()
        self.addCleanup(dependencies.stop)

    def states(self):
        return (
            random.getstate(),
            self.numpy_generator.get_state(),
            self.cpu.get_state(),
            tuple(generator.get_state() for generator in self.cuda.generators),
            tuple(generator.get_state() for generator in self.xpu.generators),
        )

    def draw(self, accelerator=None, index=0):
        values = [random.random(), self.numpy_generator.rng.random(), self.cpu.rng.random()]
        if accelerator is not None:
            values.append(accelerator.generators[index].rng.random())
        return values

    def test_none_imports_no_dependencies_and_does_not_restore_rngs(self):
        original_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name in ("numpy", "torch"):
                self.fail(f"Unexpected import: {name}")
            return original_import(name, *args, **kwargs)

        before = self.states()
        expected = random.Random()
        expected.setstate(before[0])
        with patch("builtins.__import__", side_effect=guarded_import):
            with seeded_generation(None, object()):
                self.assertEqual(random.random(), expected.random())
        self.assertEqual(random.getstate(), expected.getstate())
        self.assertEqual(self.states()[1:], before[1:])

    def test_invalid_seeds_are_rejected_without_touching_rngs(self):
        for seed in (True, False, 1.5, "1", object(), -1, 2**31):
            with self.subTest(seed=seed):
                before = self.states()
                error = (
                    TypeError if isinstance(seed, bool) or not isinstance(seed, int) else ValueError
                )
                with self.assertRaises(error):
                    with seeded_generation(seed, "cpu"):
                        self.fail("Invalid seed entered generation")
                self.assertEqual(self.states(), before)

    def test_cpu_seed_limits_repeat_and_restore_without_accelerator_access(self):
        for seed in (0, 937, 2**31 - 1):
            with self.subTest(seed=seed):
                before = self.states()
                with seeded_generation(seed, "cpu"):
                    first = self.draw()
                self.assertEqual(self.states(), before)
                with seeded_generation(seed, "cpu"):
                    self.assertEqual(self.draw(), first)
                self.assertEqual(self.states(), before)
        self.assertEqual(self.cuda.calls, [])
        self.assertEqual(self.xpu.calls, [])

    def test_different_seeds_change_the_generated_sequence(self):
        with seeded_generation(123, "cpu"):
            first = self.draw()
        with seeded_generation(456, "cpu"):
            self.assertNotEqual(self.draw(), first)

    def test_only_selected_cuda_or_xpu_device_is_seeded_and_restored(self):
        for name, accelerator in (("cuda", self.cuda), ("xpu", self.xpu)):
            with self.subTest(backend=name):
                before = self.states()
                other = accelerator.generators[0].get_state()
                with seeded_generation(813, fake_device(f"{name}:1")):
                    first = self.draw(accelerator, 1)
                    self.assertEqual(accelerator.generators[0].get_state(), other)
                    self.assertEqual(accelerator.current, 0)
                self.assertEqual(self.states(), before)
                with seeded_generation(813, f"{name}:1"):
                    self.assertEqual(self.draw(accelerator, 1), first)
                self.assertEqual(self.states(), before)
                self.assertEqual(accelerator.current, 0)
                self.assertEqual(
                    accelerator.calls,
                    [("get", 1), ("seed", 1, 813), ("restore", 1)] * 2,
                )

    def test_implicit_device_index_uses_current_gpu(self):
        for name, accelerator in (("cuda", self.cuda), ("xpu", self.xpu)):
            with self.subTest(backend=name):
                accelerator.current = 1
                before = self.states()
                with seeded_generation(29, name):
                    self.draw(accelerator, 1)
                self.assertEqual(self.states(), before)
                self.assertEqual(accelerator.current, 1)
                self.assertEqual(
                    accelerator.calls,
                    [("current",), ("get", 1), ("seed", 1, 29), ("restore", 1)],
                )

    def test_generation_exception_restores_every_rng(self):
        for device in ("cpu", "cuda:1", "xpu:1"):
            with self.subTest(device=device):
                before = self.states()
                accelerator = (
                    self.cuda
                    if device.startswith("cuda")
                    else self.xpu
                    if device.startswith("xpu")
                    else None
                )
                with self.assertRaisesRegex(RuntimeError, "generation failed"):
                    with seeded_generation(27, device):
                        self.draw(accelerator, 1)
                        raise RuntimeError("generation failed")
                self.assertEqual(self.states(), before)

    def test_cpu_seeding_failure_restores_prior_rngs(self):
        before = self.states()
        self.cpu.fail_seed = True
        with self.assertRaisesRegex(RuntimeError, "seed failure"):
            with seeded_generation(13, "cuda:1"):
                self.fail("Failed seeding entered generation")
        self.assertEqual(self.states(), before)

    def test_accelerator_seeding_failure_restores_states_and_current_device(self):
        self.cuda.generators[1].fail_seed = True
        before = self.states()
        with self.assertRaisesRegex(RuntimeError, "seed failure"):
            with seeded_generation(62, "cuda:1"):
                self.fail("Failed seeding entered generation")
        self.assertEqual(self.states(), before)
        self.assertEqual(self.cuda.current, 0)

    def test_snapshot_failure_does_not_seed_any_rng(self):
        self.xpu.fail_snapshot = True
        before = self.states()
        with self.assertRaisesRegex(RuntimeError, "snapshot failure"):
            with seeded_generation(62, "xpu:1"):
                self.fail("Failed snapshot entered generation")
        self.assertEqual(self.states(), before)
        self.assertEqual(self.xpu.calls, [("get", 1)])

    def test_failed_gpu_restore_still_restores_cpu_numpy_and_python(self):
        before = self.states()
        self.cuda.fail_restore = True
        with self.assertRaisesRegex(RuntimeError, "restore failure"):
            with seeded_generation(88, "cuda:1"):
                self.draw(self.cuda, 1)
        self.assertEqual(self.states()[:3], before[:3])
        self.assertEqual(self.cuda.current, 0)

    def test_unsupported_device_does_not_change_rngs(self):
        before = self.states()
        with self.assertRaisesRegex(ValueError, "Unsupported generation seed device"):
            with seeded_generation(5, "meta"):
                self.fail("Unsupported device entered generation")
        self.assertEqual(self.states(), before)

    def test_nested_context_resumes_outer_sequence(self):
        before = self.states()
        with seeded_generation(11, "cuda:1"):
            self.draw(self.cuda, 1)
            outer = self.states()
            with seeded_generation(23, "xpu:1"):
                self.draw(self.xpu, 1)
            self.assertEqual(self.states(), outer)
        self.assertEqual(self.states(), before)


if __name__ == "__main__":
    unittest.main()
