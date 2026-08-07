import codecs
import re

with codecs.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()

def replace_spinctrl(var_name, lbl_name):
    old = f"""        self.{var_name}.SetName({lbl_name})"""
    new = f"""        self.{var_name}.SetName({lbl_name})
        self.{var_name}.SetToolTip({lbl_name})
        for child in self.{var_name}.GetChildren(): child.SetName({lbl_name})"""
    return old, new

for var_name, lbl_name in [("spin_cfg", "lbl_cfg"), ("spin_speed", "lbl_speed")]:
    old, new = replace_spinctrl(var_name, lbl_name)
    code = code.replace(old, new)
    
with codecs.open("wx_app.py", "w", encoding="utf-8") as f:
    f.write(code)
