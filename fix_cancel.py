import io
import re

with io.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()
    
# Fix HandleCancel behavior
old_cancel = """    def HandleCancel(self, event=None):
        if self.is_first_run:
            dlg = wx.MessageDialog(self, self._("exit_confirm"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
            if dlg.ShowModal() == wx.ID_YES:
                self.EndModal(wx.ID_CANCEL)
            else:
                import wx
                if event and hasattr(wx, "CloseEvent") and isinstance(event, wx.CloseEvent):
                    event.Veto()
        else:
            self.EndModal(wx.ID_CANCEL)"""

new_cancel = """    def HandleCancel(self, event=None):
        dlg = wx.MessageDialog(self, self._("exit_confirm"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
        if dlg.ShowModal() == wx.ID_YES:
            self.EndModal(wx.ID_CANCEL)
        else:
            import wx
            if event and hasattr(wx, "CloseEvent") and isinstance(event, wx.CloseEvent):
                event.Veto()"""
                
code = code.replace(old_cancel, new_cancel)

with io.open("wx_app.py", "w", encoding="utf-8", newline="") as f:
    f.write(code)
