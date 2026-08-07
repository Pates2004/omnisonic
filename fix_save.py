import io
import re

with io.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()

code = code.replace("self.SaveConfig()", "SaveBasicConfig(self.cfg)")

with io.open("wx_app.py", "w", encoding="utf-8", newline="") as f:
    f.write(code)
