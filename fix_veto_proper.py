import codecs

with codecs.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()

# Fix 1: StartupSplash OnCancel
old_1 = """            def OnCancel(evt):
                dlg = wx.MessageDialog(self.dialog, self._("close_warn"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
                if dlg.ShowModal() == wx.ID_YES:
                    import sys
                    sys.exit(0)
            btn.Bind(wx.EVT_BUTTON, OnCancel)"""
            
new_1 = """            def OnCancel(evt):
                dlg = wx.MessageDialog(self.dialog, self._("close_warn"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
                if dlg.ShowModal() == wx.ID_YES:
                    import sys
                    sys.exit(0)
                else:
                    import wx
                    if hasattr(wx, "CloseEvent") and isinstance(evt, wx.CloseEvent):
                        evt.Veto()
            btn.Bind(wx.EVT_BUTTON, OnCancel)"""

code = code.replace(old_1, new_1)

# Fix 2: OperationDialog OnCancel
old_2 = """            def OnCancel(evt):
                dlg = wx.MessageDialog(self.dialog, self._("stop_confirm"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
                if dlg.ShowModal() == wx.ID_YES:
                    self.cancel_flag = True
            btn.Bind(wx.EVT_BUTTON, OnCancel)"""
            
new_2 = """            def OnCancel(evt):
                dlg = wx.MessageDialog(self.dialog, self._("stop_confirm"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
                if dlg.ShowModal() == wx.ID_YES:
                    self.cancel_flag = True
                else:
                    import wx
                    if hasattr(wx, "CloseEvent") and isinstance(evt, wx.CloseEvent):
                        evt.Veto()
            btn.Bind(wx.EVT_BUTTON, OnCancel)"""

code = code.replace(old_2, new_2)

# Fix 3: SettingsDialog HandleCancel
old_3 = """    def OnCancel(self, event):
        self.HandleCancel()
        
    def OnClose(self, event):
        self.HandleCancel()
        
    def HandleCancel(self):
        if self.is_first_run:
            dlg = wx.MessageDialog(self, self._("exit_confirm"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
            if dlg.ShowModal() == wx.ID_YES:
                self.EndModal(wx.ID_CANCEL)
        else:
            self.EndModal(wx.ID_CANCEL)"""
            
new_3 = """    def OnCancel(self, event):
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
            self.EndModal(wx.ID_CANCEL)"""

code = code.replace(old_3, new_3)

with codecs.open("wx_app.py", "w", encoding="utf-8") as f:
    f.write(code)
