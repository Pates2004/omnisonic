"""Apply a readable palette to every wx window, including modal dialogs."""

from __future__ import annotations

import ctypes
import os

import wx


DARK_SURFACE = wx.Colour(32, 35, 41)
DARK_FIELD = wx.Colour(46, 50, 57)
DARK_BUTTON = wx.Colour(56, 62, 71)
DARK_TEXT = wx.Colour(240, 242, 245)
DARK_ACCENT = wx.Colour(94, 176, 239)
LIGHT_SURFACE = wx.Colour(246, 247, 249)
LIGHT_FIELD = wx.Colour(255, 255, 255)
LIGHT_BUTTON = wx.Colour(232, 235, 239)
LIGHT_TEXT = wx.Colour(24, 28, 34)
LIGHT_ACCENT = wx.Colour(26, 97, 175)


def theme_for_window(window: wx.Window | None) -> str:
    """Use the active dialog preview when opening a child dialog."""
    while window is not None:
        current = getattr(window, "_omnisonic_theme", None)
        if current in ("light", "dark"):
            return current
        config = getattr(window, "cfg", None)
        if isinstance(config, dict):
            return config.get("theme", "light")
        window = window.GetParent()
    return "light"


def _set_native_dark_mode(window: wx.Window, dark: bool) -> None:
    """Request dark native chrome without changing the system-wide theme."""
    if os.name != "nt":
        return
    handle = window.GetHandle()
    if not handle:
        return
    if isinstance(window, wx.TopLevelWindow):
        try:
            value = ctypes.c_int(int(dark))
            for attribute in (20, 19):
                result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    ctypes.c_void_p(handle),
                    attribute,
                    ctypes.byref(value),
                    ctypes.sizeof(value),
                )
                if result == 0:
                    break
        except (AttributeError, OSError, ValueError):
            pass  # Older Windows builds may not support a dark title bar.

    if isinstance(
        window,
        (
            wx.Notebook,
            wx.ListCtrl,
            wx.ListBox,
            wx.TextCtrl,
            wx.Choice,
            wx.ComboBox,
            wx.Button,
            wx.CheckBox,
            wx.RadioButton,
            wx.SpinCtrl,
            wx.SpinCtrlDouble,
            wx.Gauge,
            wx.ScrollBar,
            wx.Slider,
            wx.TreeCtrl,
        ),
    ):
        try:
            set_theme = ctypes.windll.uxtheme.SetWindowTheme
            set_theme.argtypes = (ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p)
            set_theme.restype = ctypes.c_long
            theme_name = "DarkMode_Explorer" if dark else None
            set_theme(ctypes.c_void_p(handle), theme_name, None)
        except (AttributeError, OSError, ValueError):
            pass  # The explicit palette below still applies.


def apply_theme(window: wx.Window, theme: str) -> None:
    """Style a window tree for either theme, including live theme changes."""
    dark = theme == "dark"
    window._omnisonic_theme = "dark" if dark else "light"

    def visit(control: wx.Window) -> None:
        _set_native_dark_mode(control, dark)
        if isinstance(control, wx.Gauge):
            background = DARK_FIELD if dark else LIGHT_FIELD
            foreground = DARK_ACCENT if dark else LIGHT_ACCENT
        elif isinstance(
            control,
            (
                wx.TextCtrl,
                wx.ListCtrl,
                wx.ListBox,
                wx.Choice,
                wx.ComboBox,
                wx.SpinCtrl,
                wx.SpinCtrlDouble,
            ),
        ):
            background = DARK_FIELD if dark else LIGHT_FIELD
            foreground = DARK_TEXT if dark else LIGHT_TEXT
        elif isinstance(control, wx.Button):
            background = DARK_BUTTON if dark else LIGHT_BUTTON
            foreground = DARK_TEXT if dark else LIGHT_TEXT
        else:
            background = DARK_SURFACE if dark else LIGHT_SURFACE
            foreground = DARK_TEXT if dark else LIGHT_TEXT
        control.SetBackgroundColour(background)
        control.SetForegroundColour(foreground)
        for child in control.GetChildren():
            visit(child)
        control.Refresh()

    visit(window)
    window.Layout()
