"""Single-worker model ownership and independent Whisper/synthesis lifetimes."""


class ModelLifecycle:
    def __init__(self, factory, collect, transcriber_factory=None):
        self.factory = factory
        self.collect = collect
        self.transcriber_factory = transcriber_factory
        self.model = None
        self.asr_pipe = None
        self.needs_collection = False
        self.sampling_rate = 24000
        self.asr_model_name = None

    def configure_asr(self, settings):
        name = settings.get("asr_model_name")
        if name is None:
            return
        if self.asr_model_name is not None and self.asr_model_name != name:
            self.release_asr()
        self.asr_model_name = name
        if self.model is not None:
            if getattr(self.model, "_asr_model_name", name) != name:
                self.release_asr()
            self.model._asr_model_name = name

    def ensure(self, state, settings):
        state.check_cancelled()
        self.configure_asr(settings)
        if self.model is None:
            self.model = self.factory(state, settings)
            if self.asr_pipe is not None:
                self.model._asr_pipe = self.asr_pipe
                self.asr_pipe = None
        self.model.unload_asr_after_transcription = settings.get(
            "unload_asr_after_transcription", False
        )
        self.sampling_rate = int(getattr(self.model, "sampling_rate", 24000) or 24000)
        state.check_cancelled()
        return self.model

    def run(self, state, settings, worker, *args):
        try:
            self.ensure(state, settings)
            return worker(state, self.model, *args)
        finally:
            if settings.get("unload_asr_after_transcription", False):
                # Also release a preloaded pipeline after cancellation/loading
                # errors before transcription, and collect cleared error frames.
                self.release_asr()
            if settings.get("unload_omnivoice_after_operation", False):
                self.release_model()

    def release_model(self):
        if self.model is not None:
            release_caches = getattr(self.model, "release_inference_caches", None)
            if callable(release_caches):
                release_caches()
            # Whisper has its own policy. Keep it without retaining OmniVoice.
            self.asr_pipe = getattr(self.model, "_asr_pipe", None)
            self.model._asr_pipe = None
            self.model = None
        self.needs_collection = True

    def run_transcription(self, state, settings, worker, *args):
        if self.model is not None:
            return self.run(state, settings, worker, *args)
        state.check_cancelled()
        self.configure_asr(settings)
        transcriber = self.transcriber_factory(settings)
        transcriber._asr_pipe = self.asr_pipe
        self.asr_pipe = None
        unload = settings.get("unload_asr_after_transcription", False)
        transcriber.unload_asr_after_transcription = unload
        try:
            return worker(state, transcriber, *args)
        finally:
            self.asr_pipe = None if unload else transcriber._asr_pipe
            transcriber._asr_pipe = None
            self.needs_collection = self.needs_collection or unload

    def release_asr(self):
        self.asr_pipe = None
        if self.model is not None:
            self.model._asr_pipe = None
        self.needs_collection = True

    def release_all(self):
        self.release_model()
        self.release_asr()

    def collect_if_needed(self):
        # Called after the worker has returned and exception frames are cleared:
        # empty_cache alone cannot free tensors still referenced by a traceback.
        if self.needs_collection:
            self.collect()
            self.needs_collection = False
