"""Accessible batch text-to-speech tab for the desktop frame."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from uuid import uuid4

import wx

from .batch import BatchInput, BatchInputError, BatchResult, discover_text_files, process_text_batch
from .config import PRESETS_DIR, default_audio_directory
from .validation import safe_child_path


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
            tab, choices=[self._("tab_clone"), self._("tab_design"), self._("tab_auto")]
        )
        self.batch_mode.SetSelection(0)
        self.batch_mode.SetName(self._("batch_mode"))
        modes.Add(self.batch_mode, 1)
        layout.Add(modes, 0, wx.EXPAND | wx.ALL, 5)
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
        self.batch_list.SetFocus()

    def _refresh_batch_list(self):
        self.batch_list.DeleteAllItems()
        for index, item in enumerate(self.batch_items):
            self.batch_list.InsertItem(index, item.source)
            self.batch_list.SetItem(index, 1, self._("batch_" + item.status))
            self.batch_list.SetItem(index, 2, item.output or self._(item.error))

    def OnBatchRemove(self, event):
        if self.current_op and not self.current_op.finished:
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
        if not self.current_op or self.current_op.finished:
            self.batch_items.clear()
            self._refresh_batch_list()

    def OnBatchKeyDown(self, event):
        if event.GetKeyCode() == wx.WXK_DELETE:
            self.OnBatchRemove(event)
        else:
            event.Skip()

    def OnBatchOutput(self, event):
        with wx.DirDialog(
            self,
            self._("batch_output"),
            defaultPath=self.batch_output.GetValue(),
            style=wx.DD_DEFAULT_STYLE,
        ) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.batch_output.SetValue(dialog.GetPath())

    def OnGenBatch(self, event):
        if not self._CanUseModel():
            wx.MessageBox(self._("msg_load_first"), self._("error_title"), parent=self)
            return
        indices = [index for index, item in enumerate(self.batch_items) if item.status != "done"]
        if not indices:
            wx.MessageBox(self._("batch_no_files"), self._("info_title"), parent=self)
            return
        mode = self.batch_mode.GetSelection()
        languages = (self.clone_lang, self.design_lang, self.auto_lang)
        language = languages[mode].GetValue()
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
            selection = self.combo_presets.GetSelection()
            preset = (
                self.combo_presets.GetClientData(selection) if selection != wx.NOT_FOUND else None
            )
            if preset:
                try:
                    prompt_source = (str(safe_child_path(PRESETS_DIR, preset)), None, None)
                except ValueError as exc:
                    wx.MessageBox(str(exc), self._("error_title"), parent=self)
                    return
            else:
                reference = self.clone_ref_audio.GetValue().strip()
                if not reference or not Path(reference).is_file():
                    wx.MessageBox(self._("err_no_audio_preset"), self._("error_title"), parent=self)
                    return
                prompt_source = (None, reference, self.clone_ref_text.GetValue().strip() or None)
            instruction = self.clone_instruct.GetValue().strip()
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
            kwargs["instruct"] = instruction
        root = self.batch_output.GetValue().strip() or str(default_audio_directory("generated"))
        output = Path(root).expanduser() / (
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
            success_callback=lambda result: self._BatchFinished(result, output),
        )

    def _GenBatchWorker(
        self, state, model, indices, output, kwargs, prompt_source, inputs, preserve_structure
    ):
        import numpy as np
        import soundfile as sf

        from omnivoice import VoiceClonePrompt

        state.check_cancelled()
        # Keep temporary GPU prompt tokens out of the GUI's retained worker args.
        kwargs = dict(kwargs)
        if prompt_source:
            preset, reference, text = prompt_source
            kwargs["voice_clone_prompt"] = (
                VoiceClonePrompt.load(preset)
                if preset
                else model.create_voice_clone_prompt(
                    ref_audio=reference,
                    ref_text=text,
                    preprocess_prompt=kwargs["generation_config"].preprocess_prompt,
                )
            )
        state.check_cancelled()

        def synthesize(text):
            state.check_cancelled()
            audio = np.asarray(model.generate(text=text, **kwargs)[0])
            if audio.ndim != 1 or not audio.size or not np.isfinite(audio).all():
                raise ValueError(self._("invalid_generated_audio"))
            return audio

        def save(path, audio):
            sf.write(str(path), audio, model.sampling_rate, subtype="PCM_16", format="WAV")

        def progress(index, result):
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
