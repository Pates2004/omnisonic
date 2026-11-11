"""Accessible batch text-to-speech tab for the desktop frame."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

import wx

from .batch import BatchInput, BatchInputError, BatchResult, discover_text_files, process_text_batch
from .config import PRESETS_DIR, default_audio_directory
from .randomness import seeded_generation
from .validation import (
    normalize_pasted_path,
    operation_error_message,
    output_directory_path,
    safe_child_path,
    validation_error_message,
)


class BatchTabMixin:
    def SetupBatchTab(self, tab):
        self.batch_items: list[BatchResult] = []
        layout = wx.BoxSizer(wx.VERTICAL)
        description = wx.StaticText(tab, label=self._("batch_description"))
        description.Wrap(680)
        layout.Add(description, 0, wx.EXPAND | wx.ALL, 5)
        toolbar = wx.BoxSizer(wx.HORIZONTAL)
        for name, label, handler in (
            ("btn_batch_files", "batch_add_files", self.OnBatchAddFiles),
            ("btn_batch_folders", "batch_add_folders", self.OnBatchAddFolders),
            ("btn_batch_remove", "batch_remove", self.OnBatchRemove),
            ("btn_batch_clear", "batch_clear", self.OnBatchClear),
        ):
            button = wx.Button(tab, label=self._(label))
            button.Bind(wx.EVT_BUTTON, handler)
            setattr(self, name, button)
            toolbar.Add(button, 0, wx.RIGHT, 5)
        layout.Add(toolbar, 0, wx.ALL, 5)
        self.batch_recursive = wx.CheckBox(tab, label=self._("batch_recursive"))
        self.batch_recursive.SetValue(True)
        layout.Add(self.batch_recursive, 0, wx.ALL, 5)
        self.batch_preserve_structure = wx.CheckBox(tab, label=self._("batch_preserve_structure"))
        self.batch_preserve_structure.SetName(self._("batch_preserve_structure"))
        self.batch_preserve_structure.SetValue(True)
        layout.Add(self.batch_preserve_structure, 0, wx.ALL, 5)
        self.batch_list = wx.ListCtrl(tab, style=wx.LC_REPORT)
        self.batch_list.SetMinSize((-1, 130))
        self.batch_list.SetName(self._("batch_queue"))
        for index, (label, width) in enumerate(
            (("batch_file", 330), ("batch_status", 140), ("batch_result", 420))
        ):
            self.batch_list.InsertColumn(index, self._(label), width=width)
        self.batch_list.Bind(wx.EVT_KEY_DOWN, self.OnBatchKeyDown)
        layout.Add(self.batch_list, 1, wx.EXPAND | wx.ALL, 5)
        modes = wx.BoxSizer(wx.HORIZONTAL)
        modes.Add(
            wx.StaticText(tab, label=self._("batch_mode")),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            5,
        )
        self.batch_mode = wx.Choice(
            tab,
            choices=[
                self._("tab_clone"),
                self._("tab_design"),
                self._("tab_auto"),
                self._("batch_custom"),
            ],
        )
        self.batch_mode.SetSelection(3)
        self.batch_mode.SetName(self._("batch_mode"))
        self.batch_mode.Bind(wx.EVT_CHOICE, self.OnBatchModeChanged)
        modes.Add(self.batch_mode, 1)
        layout.Add(modes, 0, wx.EXPAND | wx.ALL, 5)
        self.batch_custom_panel = wx.Panel(tab)
        custom = wx.BoxSizer(wx.VERTICAL)
        custom.Add(
            wx.StaticText(self.batch_custom_panel, label=self._("batch_custom_voice")),
            0,
            wx.LEFT | wx.TOP,
            5,
        )
        self.batch_custom_voice = wx.Choice(
            self.batch_custom_panel,
            choices=[self._("tab_clone"), self._("tab_design"), self._("tab_auto")],
        )
        self.batch_custom_voice.SetName(self._("batch_custom_voice"))
        self.batch_custom_voice.SetSelection(0)
        self.batch_custom_voice.Bind(wx.EVT_CHOICE, self.OnBatchCustomVoiceChanged)
        custom.Add(self.batch_custom_voice, 0, wx.EXPAND | wx.ALL, 5)

        self.batch_custom_reference_panel = wx.Panel(self.batch_custom_panel)
        reference = wx.BoxSizer(wx.VERTICAL)
        reference.Add(
            wx.StaticText(self.batch_custom_reference_panel, label=self._("preset_list")),
            0,
            wx.LEFT | wx.TOP,
            5,
        )
        presets = wx.BoxSizer(wx.HORIZONTAL)
        self.batch_custom_preset = wx.ComboBox(
            self.batch_custom_reference_panel, style=wx.CB_READONLY
        )
        self.batch_custom_preset.SetName(self._("preset_list"))
        self.batch_custom_preset.Bind(wx.EVT_COMBOBOX, self.OnBatchCustomVoiceChanged)
        presets.Add(self.batch_custom_preset, 1, wx.RIGHT, 5)
        self.btn_batch_preset_refresh = wx.Button(
            self.batch_custom_reference_panel, label=self._("refresh")
        )
        self.btn_batch_preset_refresh.Bind(wx.EVT_BUTTON, lambda event: self.RefreshPresets())
        presets.Add(self.btn_batch_preset_refresh, 0)
        reference.Add(presets, 0, wx.EXPAND | wx.ALL, 5)
        reference.Add(
            wx.StaticText(self.batch_custom_reference_panel, label=self._("ref_audio")),
            0,
            wx.LEFT | wx.TOP,
            5,
        )
        audio = wx.BoxSizer(wx.HORIZONTAL)
        self.batch_custom_audio = wx.TextCtrl(self.batch_custom_reference_panel)
        self.batch_custom_audio.SetName(self._("ref_audio"))
        self.batch_custom_audio.Bind(wx.EVT_TEXT, self.OnBatchReferenceChanged)
        audio.Add(self.batch_custom_audio, 1, wx.RIGHT, 5)
        self.btn_batch_ref_browse = wx.Button(
            self.batch_custom_reference_panel, label=self._("browse")
        )
        self.btn_batch_ref_browse.Bind(
            wx.EVT_BUTTON, lambda event: self.BrowseFor(self.batch_custom_audio)
        )
        audio.Add(self.btn_batch_ref_browse, 0)
        reference.Add(audio, 0, wx.EXPAND | wx.ALL, 5)
        reference.Add(
            wx.StaticText(self.batch_custom_reference_panel, label=self._("ref_text")),
            0,
            wx.LEFT | wx.TOP,
            5,
        )
        self.batch_custom_text = wx.TextCtrl(
            self.batch_custom_reference_panel, style=wx.TE_MULTILINE, size=(-1, 50)
        )
        self.batch_custom_text.SetName(self._("ref_text"))
        reference.Add(self.batch_custom_text, 0, wx.EXPAND | wx.ALL, 5)
        self.batch_custom_reference_panel.SetSizer(reference)
        custom.Add(self.batch_custom_reference_panel, 0, wx.EXPAND)

        custom.Add(
            wx.StaticText(self.batch_custom_panel, label=self._("lang_select")),
            0,
            wx.LEFT | wx.TOP,
            5,
        )
        self.batch_custom_language = wx.ComboBox(
            self.batch_custom_panel, choices=self.clone_lang.GetItems(), style=wx.CB_READONLY
        )
        self.batch_custom_language.SetName(self._("lang_select"))
        self.batch_custom_language.SetValue("Auto")
        custom.Add(self.batch_custom_language, 0, wx.EXPAND | wx.ALL, 5)
        self.batch_custom_instruction_panel = wx.Panel(self.batch_custom_panel)
        instructions = wx.BoxSizer(wx.VERTICAL)
        instructions.Add(
            wx.StaticText(self.batch_custom_instruction_panel, label=self._("clone_instruct")),
            0,
            wx.LEFT | wx.TOP,
            5,
        )
        self.batch_custom_instruction = wx.TextCtrl(self.batch_custom_instruction_panel)
        self.batch_custom_instruction.SetName(self._("clone_instruct"))
        instructions.Add(self.batch_custom_instruction, 0, wx.EXPAND | wx.ALL, 5)
        self.batch_custom_instruction_panel.SetSizer(instructions)
        custom.Add(self.batch_custom_instruction_panel, 0, wx.EXPAND)
        self.batch_custom_panel.SetSizer(custom)
        layout.Add(self.batch_custom_panel, 0, wx.EXPAND | wx.ALL, 5)
        layout.Add(wx.StaticText(tab, label=self._("batch_output")), 0, wx.LEFT | wx.TOP, 5)
        output = wx.BoxSizer(wx.HORIZONTAL)
        self.batch_output = wx.TextCtrl(tab, value=self.cfg["generated_audio_directory"])
        self.batch_output.SetName(self._("batch_output"))
        output.Add(self.batch_output, 1, wx.RIGHT, 5)
        self.btn_batch_browse = wx.Button(tab, label=self._("browse"))
        self.btn_batch_browse.Bind(wx.EVT_BUTTON, self.OnBatchOutput)
        output.Add(self.btn_batch_browse, 0)
        layout.Add(output, 0, wx.EXPAND | wx.ALL, 5)
        self.btn_gen_batch = wx.Button(tab, label=self._("batch_start"))
        self.btn_gen_batch.Bind(wx.EVT_BUTTON, self.OnGenBatch)
        layout.Add(self.btn_gen_batch, 0, wx.ALL, 5)
        tab.SetSizer(layout)
        tab.SetupScrolling(scroll_x=False)
        self._UpdateBatchCustomControls()

    def OnBatchModeChanged(self, event):
        self._UpdateBatchCustomControls()

    def OnBatchCustomVoiceChanged(self, event):
        self._UpdateBatchCustomControls()

    def OnBatchReferenceChanged(self, event):
        # A transcript belongs to its own source, not the Clone tab's file.
        self.batch_custom_text.ChangeValue("")
        event.Skip()

    def _UpdateBatchCustomControls(self):
        self.batch_custom_panel.Show(self.batch_mode.GetSelection() == 3)
        voice = self.batch_custom_voice.GetSelection()
        self.batch_custom_reference_panel.Show(voice == 0)
        self.batch_custom_instruction_panel.Show(voice != 2)
        selection = self.batch_custom_preset.GetSelection()
        preset = (
            self.batch_custom_preset.GetClientData(selection) if selection != wx.NOT_FOUND else None
        )
        for control in (self.batch_custom_audio, self.batch_custom_text, self.btn_batch_ref_browse):
            control.Enable(not preset)
        self.tab_batch.Layout()
        self.tab_batch.FitInside()

    def OnBatchAddFiles(self, event):
        with wx.FileDialog(
            self,
            self._("batch_add_files"),
            wildcard=self._("batch_text_filter"),
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE,
        ) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self._scan_batch_inputs(dialog.GetPaths())

    def OnBatchAddFolders(self, event):
        with wx.DirDialog(
            self,
            self._("batch_add_folders"),
            style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST | wx.DD_MULTIPLE,
        ) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self._scan_batch_inputs(dialog.GetPaths())

    def _scan_batch_inputs(self, paths):
        self.RunOperation(
            "batch_scan_title",
            "batch_scan_message",
            self._ScanBatchWorker,
            tuple(paths),
            tuple(item.source for item in self.batch_items),
            self.batch_recursive.GetValue(),
            success_callback=self._BatchScanned,
        )

    def _ScanBatchWorker(self, state, paths, existing, recursive):
        try:
            return discover_text_files(paths, existing, recursive, state.check_cancelled)
        except BatchInputError as exc:
            raise ValueError(self._(str(exc))) from exc

    def _BatchScanned(self, result):
        inputs, errors = result
        self.batch_items.extend(
            BatchResult(
                str(item.path), source_root=str(item.root) if item.root is not None else None
            )
            for item in inputs
        )
        self._refresh_batch_list()
        self.Log(self._("batch_added").format(count=len(inputs), total=len(self.batch_items)))
        if errors:
            self.Log("\n".join(f"{path}: {self._(error)}" for path, error in errors))
        if self.batch_list.IsShownOnScreen() and self.batch_list.IsEnabled():
            self.batch_list.SetFocus()

    def _refresh_batch_list(self):
        self.batch_list.DeleteAllItems()
        for index, item in enumerate(self.batch_items):
            self.batch_list.InsertItem(index, item.source)
            self.batch_list.SetItem(index, 1, self._("batch_" + item.status))
            self.batch_list.SetItem(index, 2, item.output or self._(item.error))

    def OnBatchRemove(self, event):
        if self.current_op is not None:
            return
        selected = []
        index = self.batch_list.GetFirstSelected()
        while index != -1:
            selected.append(index)
            index = self.batch_list.GetNextSelected(index)
        for index in reversed(selected):
            del self.batch_items[index]
        self._refresh_batch_list()

    def OnBatchClear(self, event):
        if self.current_op is None:
            self.batch_items.clear()
            self._refresh_batch_list()

    def OnBatchKeyDown(self, event):
        if event.GetKeyCode() == wx.WXK_DELETE:
            self.OnBatchRemove(event)
        else:
            event.Skip()

    def OnBatchOutput(self, event):
        try:
            default_path = str(output_directory_path(self.batch_output.GetValue()))
        except (OSError, ValueError):
            default_path = ""
        with wx.DirDialog(
            self,
            self._("batch_output"),
            defaultPath=default_path,
            style=wx.DD_DEFAULT_STYLE,
        ) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.batch_output.SetValue(dialog.GetPath())

    def OnGenBatch(self, event):
        if not self._CanStartGeneration():
            return
        if not self._CanUseModel():
            wx.MessageBox(self._("msg_load_first"), self._("error_title"), parent=self)
            return
        indices = [index for index, item in enumerate(self.batch_items) if item.status != "done"]
        if not indices:
            wx.MessageBox(self._("batch_no_files"), self._("info_title"), parent=self)
            return
        source = self.batch_mode.GetSelection()
        custom = source == 3
        mode = self.batch_custom_voice.GetSelection() if custom else source
        if mode not in (0, 1, 2):
            wx.MessageBox(self._("batch_invalid_mode"), self._("error_title"), parent=self)
            return
        language = (
            self.batch_custom_language.GetValue()
            if custom
            else (self.clone_lang, self.design_lang, self.auto_lang)[mode].GetValue()
        )
        if not self._CheckTextNormalization(language):
            return
        kwargs = {
            "generation_config": self.GetGenConfig(),
            "normalize_text": self.cfg.get("normalize_text", False),
        }
        if language != "Auto":
            kwargs["language"] = language
        if self.chk_duration.GetValue():
            kwargs["duration"] = self.spin_duration.GetValue()
        else:
            kwargs["speed"] = self.spin_speed.GetValue()
        prompt_source = None
        if mode == 0:
            presets = self.batch_custom_preset if custom else self.combo_presets
            selection = presets.GetSelection()
            preset = presets.GetClientData(selection) if selection != wx.NOT_FOUND else None
            if preset:
                try:
                    prompt_source = (
                        str(safe_child_path(PRESETS_DIR, preset, reject_links=True)),
                        None,
                        None,
                    )
                except (OSError, ValueError) as exc:
                    wx.MessageBox(
                        self._("preset_access_failed").format(
                            error=validation_error_message(exc, self._)
                        ),
                        self._("error_title"),
                        parent=self,
                    )
                    return
            else:
                reference = normalize_pasted_path(
                    (self.batch_custom_audio if custom else self.clone_ref_audio).GetValue()
                )
                if not reference or not Path(reference).is_file():
                    wx.MessageBox(self._("err_no_audio_preset"), self._("error_title"), parent=self)
                    return
                transcript = self.batch_custom_text if custom else self.clone_ref_text
                prompt_source = (None, reference, transcript.GetValue().strip() or None)
            instruction = (
                (self.batch_custom_instruction if custom else self.clone_instruct)
                .GetValue()
                .strip()
            )
        elif mode == 1 and custom:
            instruction = self.batch_custom_instruction.GetValue().strip()
        elif mode == 1:
            instructions = []
            for combo in self.design_combos:
                selection = combo.GetSelection()
                value = combo.GetClientData(selection) if selection != wx.NOT_FOUND else "None"
                if value != "None":
                    instructions.append(value)
            instructions.append(self.design_custom_instruct.GetValue().strip())
            instruction = ", ".join(value for value in instructions if value)
        else:
            instruction = ""
        if instruction:
            if not self._CheckVoiceInstruction(instruction):
                return
            kwargs["instruct"] = instruction
        root = self.batch_output.GetValue()
        if not normalize_pasted_path(root).strip():
            root = str(default_audio_directory("generated"))
        try:
            output_root = output_directory_path(root)
        except (OSError, ValueError) as exc:
            wx.MessageBox(
                validation_error_message(exc, self._),
                self._("error_title"),
                wx.OK | wx.ICON_ERROR,
                parent=self,
            )
            return
        output = output_root / (
            "batch-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
        )
        self.OnStopAudio(None)
        self.RunModelOperation(
            "batch_title",
            "batch_working",
            self._GenBatchWorker,
            tuple(indices),
            output,
            kwargs,
            prompt_source,
            tuple(
                BatchInput(
                    Path(self.batch_items[index].source),
                    Path(self.batch_items[index].source_root)
                    if self.batch_items[index].source_root is not None
                    else None,
                )
                for index in indices
            ),
            self.batch_preserve_structure.GetValue(),
            self._GetGenerationSeed(),
            success_callback=lambda result: self._BatchFinished(result, output),
        )

    def _GenBatchWorker(
        self,
        state,
        model,
        indices,
        output,
        kwargs,
        prompt_source,
        inputs,
        preserve_structure,
        seed=None,
    ):
        from copy import copy

        import numpy as np
        import soundfile as sf

        from omnivoice import VoiceClonePrompt
        from omnisonic.operations import OperationCancelled
        from omnisonic.subtitles import (
            MAX_CUE_DURATION_MS,
            SubtitleError,
            read_subtitles,
            render_subtitles,
        )

        state.check_cancelled()
        # Keep temporary GPU prompt tokens out of the GUI's retained worker args.
        kwargs = dict(kwargs)
        if prompt_source:
            preset, reference, text = prompt_source
            kwargs["voice_clone_prompt"] = (
                VoiceClonePrompt.load(
                    str(safe_child_path(PRESETS_DIR, Path(preset).name, reject_links=True))
                )
                if preset
                else self._models.reference_prompt(
                    state,
                    model,
                    reference,
                    text,
                    preprocess_prompt=kwargs["generation_config"].preprocess_prompt,
                )
            )
        state.check_cancelled()

        def synthesize(text, duration=None):
            state.check_cancelled()
            try:
                generation_kwargs = kwargs
                if duration is not None:
                    generation_kwargs = dict(kwargs)
                    generation_kwargs.pop("speed", None)
                    generation_kwargs["duration"] = duration
                    timed_config = copy(kwargs["generation_config"])
                    timed_config.pad_duration = 0.0
                    timed_config.postprocess_output = False
                    timed_config.fade_duration = min(timed_config.fade_duration, duration / 2)
                    # Long-form chunk joins insert gaps and would alter cue timing.
                    timed_config.audio_chunk_threshold = max(
                        timed_config.audio_chunk_threshold, MAX_CUE_DURATION_MS / 1000 + 1
                    )
                    generation_kwargs["generation_config"] = timed_config
                # Each item has its own seed scope: retries and queue ordering
                # must not change the fixed-seed result of another item.
                with seeded_generation(seed, model.device):
                    audio = np.asarray(model.generate(text=text, **generation_kwargs)[0])
            except Exception as exc:
                message = operation_error_message(exc, self._)
                if message == str(exc):
                    raise
                raise ValueError(message) from exc
            if audio.ndim != 1 or not audio.size or not np.isfinite(audio).all():
                raise ValueError(self._("invalid_generated_audio"))
            return audio

        def save(path, audio):
            sf.write(str(path), audio, model.sampling_rate, subtype="PCM_16", format="WAV")

        def render_subtitle(source, destination):
            try:
                cues = read_subtitles(source, check_cancelled=state.check_cancelled)
                current_cue = 0

                def cue_progress(index, total, cue):
                    nonlocal current_cue
                    current_cue = cue.index
                    message = self._("subtitle_progress").format(
                        current=cue.index, total=total, file=source.name
                    )
                    state.set_progress(index, total, message)
                    if index == cue.index - 1:
                        wx.CallAfter(self.Log, message)

                def synthesize_cue(text, duration):
                    try:
                        return synthesize(text, duration)
                    except OperationCancelled:
                        raise
                    except Exception as exc:
                        raise ValueError(
                            self._("subtitle_generation_failed").format(
                                index=current_cue, error=operation_error_message(exc, self._)
                            )
                        ) from exc

                with sf.SoundFile(
                    str(destination),
                    mode="w",
                    samplerate=model.sampling_rate,
                    channels=1,
                    subtype="PCM_16",
                    format="WAV",
                ) as stream:
                    render_subtitles(
                        cues,
                        model.sampling_rate,
                        synthesize_cue,
                        stream.write,
                        check_cancelled=state.check_cancelled,
                        on_progress=cue_progress,
                    )
            except SubtitleError as exc:
                raise ValueError(operation_error_message(exc, self._)) from exc

        def progress(index, result):
            if result.status == "failed":
                self._models.clear_reference_prompt_cache()
            done = index if result.status == "running" else index + 1
            state.set_progress(
                done,
                len(inputs),
                self._("batch_progress").format(
                    current=index + 1,
                    total=len(inputs),
                    file=Path(result.source).name,
                ),
            )
            wx.CallAfter(self._BatchProgress, indices[index], result)

        return process_text_batch(
            list(inputs),
            output,
            state,
            synthesize,
            save,
            progress,
            preserve_structure=preserve_structure,
            render_subtitle=render_subtitle,
        )

    def _BatchProgress(self, index, result):
        if not self or self.IsBeingDeleted():
            return
        self.batch_items[index] = result
        self.batch_list.SetItem(index, 1, self._("batch_" + result.status))
        self.batch_list.SetItem(index, 2, result.output or self._(result.error))
        if result.status == "running":
            self.Log(self._("batch_current").format(file=result.source))

    def _BatchFinished(self, results, output):
        message = self._("batch_finished").format(
            done=sum(item.status == "done" for item in results),
            failed=sum(item.status == "failed" for item in results),
            folder=output,
        )
        self.Log(message)
        wx.MessageBox(message, self._("batch_title"), wx.OK | wx.ICON_INFORMATION, parent=self)
