import io
import re

with io.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()

# Remove self.tab_presets = wx.Panel(self.notebook)
code = re.sub(r'^[ \t]*self\.tab_presets = wx\.Panel\(self\.notebook\)\n?', '', code, flags=re.MULTILINE)

# Remove self.notebook.AddPage(self.tab_presets, self._("tab_presets"))
code = re.sub(r'^[ \t]*self\.notebook\.AddPage\(self\.tab_presets, self\._\("tab_presets"\)\)\n?', '', code, flags=re.MULTILINE)

# Remove self.SetupPresetsTab(self.tab_presets)
code = re.sub(r'^[ \t]*self\.SetupPresetsTab\(self\.tab_presets\)\n?', '', code, flags=re.MULTILINE)

with io.open("wx_app.py", "w", encoding="utf-8", newline="") as f:
    f.write(code)
