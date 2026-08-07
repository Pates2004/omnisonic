import codecs

with codecs.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()

# Fix OperationDialog OnCancel
op_old = """            def OnCancel(evt):
                dlg = wx.MessageDialog(self.dialog, self._("stop_confirm"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
                if dlg.ShowModal() == wx.ID_YES:
                    self.cancel_flag = True"""
                    
op_new = """            def OnCancel(evt):
                dlg = wx.MessageDialog(self.dialog, self._("stop_confirm"), self._("warning_title"), wx.YES_NO | wx.ICON_QUESTION)
                if dlg.ShowModal() == wx.ID_YES:
                    self.cancel_flag = True
                else:
                    import wx
                    if isinstance(evt, wx.CloseEvent):
                        evt.Veto()"""
code = code.replace(op_old, op_new)

# Fix DownloadDialog OnCancel
dl_old = """    def OnCancel(self, event):
        msg = self._("cancel_dl_prompt")
        title = self._("cancel_title")
        if wx.MessageBox(msg, title, wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
            self.cancel_flag = True
            self.timer.Stop()
            self.EndModal(wx.ID_CANCEL)"""
            
dl_new = """    def OnCancel(self, event):
        msg = self._("cancel_dl_prompt")
        title = self._("cancel_title")
        if wx.MessageBox(msg, title, wx.YES_NO | wx.ICON_QUESTION) == wx.YES:
            self.cancel_flag = True
            self.timer.Stop()
            self.EndModal(wx.ID_CANCEL)
        else:
            import wx
            if isinstance(event, wx.CloseEvent):
                event.Veto()"""
code = code.replace(dl_old, dl_new)

with codecs.open("wx_app.py", "w", encoding="utf-8") as f:
    f.write(code)
