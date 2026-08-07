import io

with io.open("langs/pl.lng", "r", encoding="utf-8") as f:
    pl = f.read()

if '"btn_pause"' not in pl:
    pl = pl.replace('"play": "Odtwórz",', '"play": "Odtwórz",\n    "btn_pause": "Pauza",\n    "resume_play": "Wznów",')
    
with io.open("langs/pl.lng", "w", encoding="utf-8", newline="") as f:
    f.write(pl)

with io.open("langs/en.lng", "r", encoding="utf-8") as f:
    en = f.read()

if '"btn_pause"' not in en:
    en = en.replace('"play": "Play",', '"play": "Play",\n    "btn_pause": "Pause",\n    "resume_play": "Resume",')
    
with io.open("langs/en.lng", "w", encoding="utf-8", newline="") as f:
    f.write(en)
    
with io.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()

# Add pause/resume functionality
play_code = """    def OnPlayAudio(self, event):
        if self.btn_play.GetLabel() == self._("play"):
            if self.audio_data is not None and sd:
                sd.play(self.audio_data, samplerate=self.sample_rate)
                self.btn_play.SetLabel(self._("stop_play"))
                duration_ms = int((len(self.audio_data) / self.sample_rate) * 1000)
                if hasattr(self, 'play_timer'): self.play_timer.Stop()
                self.play_timer = wx.CallLater(duration_ms + 100, lambda: self.btn_play.SetLabel(self._("play")))
        else:
            if sd: sd.stop()
            if hasattr(self, 'play_timer'): self.play_timer.Stop()
            self.btn_play.SetLabel(self._("play"))"""

new_play_code = """    def OnPlayAudio(self, event):
        if self.btn_play.GetLabel() in [self._("play"), self._("resume_play")]:
            if self.audio_data is not None and sd:
                if not hasattr(self, 'is_paused') or not self.is_paused:
                    self.current_frame = 0
                    self.total_frames = len(self.audio_data)
                    self.is_paused = False
                    
                frames_left = self.total_frames - self.current_frame
                sd.play(self.audio_data[self.current_frame:], samplerate=self.sample_rate)
                
                self.btn_play.SetLabel(self._("stop_play"))
                self.btn_pause.Enable()
                self.btn_pause.SetLabel(self._("btn_pause"))
                
                duration_ms = int((frames_left / self.sample_rate) * 1000)
                if hasattr(self, 'play_timer'): self.play_timer.Stop()
                
                def on_finish():
                    self.btn_play.SetLabel(self._("play"))
                    self.btn_pause.Disable()
                    self.is_paused = False
                    self.current_frame = 0
                    
                self.play_timer = wx.CallLater(duration_ms + 100, on_finish)
                
        else: # stop play
            if sd: sd.stop()
            if hasattr(self, 'play_timer'): self.play_timer.Stop()
            self.btn_play.SetLabel(self._("play"))
            self.btn_pause.Disable()
            self.btn_pause.SetLabel(self._("btn_pause"))
            self.is_paused = False
            self.current_frame = 0

    def OnPauseAudio(self, event):
        if not hasattr(self, 'is_paused'):
            self.is_paused = False
            
        if sd and self.btn_play.GetLabel() == self._("stop_play"):
            if not self.is_paused:
                self.is_paused = True
                if hasattr(self, 'play_timer'):
                    # Save progress
                    elapsed_ms = self.play_timer.GetInterval() - self.play_timer.TimeRemaining()
                    self.current_frame += int((elapsed_ms / 1000) * self.sample_rate)
                    self.play_timer.Stop()
                sd.stop()
                self.btn_play.SetLabel(self._("resume_play"))
                self.btn_pause.SetLabel(self._("play")) # Swap button text conceptually or just keep it "pause", actually disable it is better, no let's just make Play button "Resume"
                self.btn_pause.Disable()
                """

code = code.replace(play_code, new_play_code)

with io.open("wx_app.py", "w", encoding="utf-8", newline="") as f:
    f.write(code)
