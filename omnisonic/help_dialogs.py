"""Accessible, selectable text for help opened explicitly by the user."""

from __future__ import annotations

import wx

from .theme import apply_theme, theme_for_window


def _restore_focus(window):
    if window and window.IsShownOnScreen() and window.IsEnabled():
        window.SetFocus()


class ReadOnlyTextDialog(wx.Dialog):
    def __init__(self, parent, title, content, close_label, *, font_size=10):
        super().__init__(
            parent,
            title=title,
            size=(680, 540),
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )
        panel = wx.Panel(self)
        layout = wx.BoxSizer(wx.VERTICAL)
        self.text = wx.TextCtrl(
            panel,
            value=content,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
        )
        self.text.SetName(title)
        layout.Add(self.text, 1, wx.ALL | wx.EXPAND, 10)
        self.close_button = wx.Button(panel, wx.ID_CANCEL, close_label)
        self.close_button.SetName(close_label)
        layout.Add(self.close_button, 0, wx.ALL | wx.ALIGN_RIGHT, 10)
        panel.SetSizer(layout)
        self.SetEscapeId(wx.ID_CANCEL)

        font = wx.Font(self.GetFont())
        font.SetPointSize(font_size)
        for control in (self, panel, self.text, self.close_button):
            control.SetFont(font)
        apply_theme(self, theme_for_window(parent))
        self.Bind(wx.EVT_SHOW, self._on_show)
        self.CentreOnParent()

    def ShowModal(self):
        previous_focus = wx.Window.FindFocus()
        try:
            return super().ShowModal()
        finally:
            # Restore after the caller has destroyed this dialog, not while its
            # native close events can still move focus to the parent frame.
            wx.CallAfter(_restore_focus, previous_focus)

    def _on_show(self, event):
        if event.IsShown():
            wx.CallAfter(self._focus_text)
        event.Skip()

    def _focus_text(self):
        # A queued focus callback can outlive a quickly closed native dialog.
        if self and self.IsShownOnScreen():
            self.text.SetInsertionPoint(0)
            self.text.ShowPosition(0)
            self.text.SetFocus()
