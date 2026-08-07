import io

with io.open('wx_app.py', 'r', encoding='utf-8') as f:
    c = f.read()

c = c.replace('self._("dl_model_prompt") if', 'self._("dl_model_prompt").replace("{name}", new_asr) if')

with io.open('wx_app.py', 'w', encoding='utf-8', newline="") as f:
    f.write(c)
