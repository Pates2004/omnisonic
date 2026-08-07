import codecs

with codecs.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()

# Fix StartupSplash OnCancel
splash_old = """            def OnCancel(evt):
                dlg = wx.MessageDialog(self.dialog, self._("close_warn"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
                if dlg.ShowModal() == wx.ID_YES:
                    import sys
                    sys.exit(0)"""
                    
splash_new = """            def OnCancel(evt):
                dlg = wx.MessageDialog(self.dialog, self._("close_warn"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
                if dlg.ShowModal() == wx.ID_YES:
                    import sys
                    sys.exit(0)
                else:
                    import wx
                    if isinstance(evt, wx.CloseEvent):
                        evt.Veto()"""
code = code.replace(splash_old, splash_new)

# Fix SettingsDialog OnClose / HandleCancel
settings_old = """    def OnCancel(self, event):
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
            
settings_new = """    def OnCancel(self, event):
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
                if event and isinstance(event, wx.CloseEvent):
                    event.Veto()
        else:
            self.EndModal(wx.ID_CANCEL)"""
code = code.replace(settings_old, settings_new)

with codecs.open("wx_app.py", "w", encoding="utf-8") as f:
    f.write(code)
