import re
import io

with io.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()

# Fix StartupSplash
code = re.sub(
    r"""            def OnCancel\(evt\):\s*dlg = wx.MessageDialog\(self.dialog, self._\("close_warn"\), self._\("warning_title"\), wx.YES_NO \| wx.ICON_QUESTION\)\s*if dlg.ShowModal\(\) == wx.ID_YES:\s*import sys\s*sys.exit\(0\)""",
    """            def OnCancel(evt):
                dlg = wx.MessageDialog(self.dialog, self._("close_warn"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
                if dlg.ShowModal() == wx.ID_YES:
                    import sys
                    sys.exit(0)
                else:
                    import wx
                    if hasattr(wx, "CloseEvent") and isinstance(evt, wx.CloseEvent):
                        evt.Veto()""",
    code
)

# Fix OperationDialog
code = re.sub(
    r"""            def OnCancel\(evt\):\s*dlg = wx.MessageDialog\(self.dialog, self._\("stop_confirm"\), self._\("warning_title"\), wx.YES_NO \| wx.ICON_QUESTION\)\s*if dlg.ShowModal\(\) == wx.ID_YES:\s*self.cancel_flag = True""",
    """            def OnCancel(evt):
                dlg = wx.MessageDialog(self.dialog, self._("stop_confirm"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
                if dlg.ShowModal() == wx.ID_YES:
                    self.cancel_flag = True
                else:
                    import wx
                    if hasattr(wx, "CloseEvent") and isinstance(evt, wx.CloseEvent):
                        evt.Veto()""",
    code
)

# Fix SettingsDialog HandleCancel
code = re.sub(
    r"""    def OnCancel\(self, event\):\s*self.HandleCancel\(\)\s*def OnClose\(self, event\):\s*self.HandleCancel\(\)\s*def HandleCancel\(self\):\s*if self.is_first_run:\s*dlg = wx.MessageDialog\(self, self._\("exit_confirm"\), self._\("warning_title"\), wx.YES_NO \| wx.ICON_QUESTION\)\s*if dlg.ShowModal\(\) == wx.ID_YES:\s*self.EndModal\(wx.ID_CANCEL\)\s*else:\s*self.EndModal\(wx.ID_CANCEL\)""",
    """    def OnCancel(self, event):
        self.HandleCancel(event)
        
    def OnClose(self, event):
        self.HandleCancel(event)
        
    def HandleCancel(self, event=None):
        if self.is_first_run:
            dlg = wx.MessageDialog(self, self._("exit_confirm"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
            if dlg.ShowModal() == wx.ID_YES:
                self.EndModal(wx.ID_CANCEL)
            else:
                import wx
                if event and hasattr(wx, "CloseEvent") and isinstance(event, wx.CloseEvent):
                    event.Veto()
        else:
            self.EndModal(wx.ID_CANCEL)""",
    code
)

with io.open("wx_app.py", "w", encoding="utf-8", newline="") as f:
    f.write(code)
