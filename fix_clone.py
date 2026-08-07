import io

with io.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()
    
old_call = """        self.RunOperation("op_gen_title", "op_gen_msg", self._GenCloneWorker, text, ref_audio, preset_path, ref_text, lang, speed, success_callback=on_success)
        
    def _GenCloneWorker(self, op_dialog, text, ref_audio, preset_path, ref_text, lang, speed):"""

new_call = """        self.RunOperation("op_gen_title", "op_gen_msg", self._GenCloneWorker, text, ref_audio, preset_path, ref_text, lang, speed, duration, norm_txt, success_callback=on_success)
        
    def _GenCloneWorker(self, op_dialog, text, ref_audio, preset_path, ref_text, lang, speed, duration, norm_txt):"""
    
code = code.replace(old_call, new_call)

with io.open("wx_app.py", "w", encoding="utf-8", newline="") as f:
    f.write(code)
