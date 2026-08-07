import io
import json
import codecs

pl_add = {
    "err_no_audio_preset": "Wybierz plik audio lub preset.",
    "err_bad_preset_name": "Zły plik lub brak nazwy presetu.",
    "msg_save_ok": "Zapisano pomyślnie!",
    "title_save": "Zapis",
    "err_file_not_found": "Plik audio nie istnieje!",
    "err_playback": "Błąd odtwarzania: {e}",
    "msg_wait": "Proszę czekać..."
}

en_add = {
    "err_no_audio_preset": "Select reference audio or a preset.",
    "err_bad_preset_name": "Bad file or missing preset name.",
    "msg_save_ok": "Saved successfully!",
    "title_save": "Save",
    "err_file_not_found": "Audio file does not exist!",
    "err_playback": "Playback error: {e}",
    "msg_wait": "Please wait..."
}

for lng_file, strings in [("langs/pl.lng", pl_add), ("langs/en.lng", en_add)]:
    try:
        with codecs.open(lng_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in strings.items():
            data[k] = v
        with codecs.open(lng_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except:
        pass

import re
with io.open("wx_app.py", "r", encoding="utf-8") as f:
    code = f.read()

# Fix msg_wait in StartupSplash
code = re.sub(r'msg or "ProszÄ„â„˘ czekaÄ„â€ˇ\.\.\."', r'msg or self._("msg_wait")', code)

# Fix DownloadDialog error message (line 289)
code = re.sub(r'wx\.CallAfter\(wx\.MessageBox, str\(e\), "Error", wx\.OK \| wx\.ICON_ERROR\)', r'wx.CallAfter(wx.MessageBox, str(e), self._("error_title"), wx.OK | wx.ICON_ERROR)', code)

# Fix err_no_audio_preset
code = re.sub(r'wx\.MessageBox\("Wybierz plik audio lub preset\. / Select reference audio or a preset\.", self\._\("error_title"\), wx\.OK \| wx\.ICON_ERROR\)', r'wx.MessageBox(self._("err_no_audio_preset"), self._("error_title"), wx.OK | wx.ICON_ERROR)', code)

# Fix err_bad_preset_name
code = re.sub(r'wx\.MessageBox\("Zły plik lub brak nazwy presetu\. / Bad file or missing preset name\.", self\._\("error_title"\), wx\.OK \| wx\.ICON_ERROR\)', r'wx.MessageBox(self._("err_bad_preset_name"), self._("error_title"), wx.OK | wx.ICON_ERROR)', code)

# Fix msg_save_ok
code = re.sub(r'wx\.MessageBox\("Zapisano pomyÄąâ€şlnie!", "Zapis", wx\.OK \| wx\.ICON_INFORMATION\)', r'wx.MessageBox(self._("msg_save_ok"), self._("title_save"), wx.OK | wx.ICON_INFORMATION)', code)

# Fix err_file_not_found
code = re.sub(r'wx\.MessageBox\("Plik audio nie istnieje!", "BÄąâ€šĂ„â€¦d", wx\.OK \| wx\.ICON_ERROR\)', r'wx.MessageBox(self._("err_file_not_found"), self._("error_title"), wx.OK | wx.ICON_ERROR)', code)

# Fix err_playback
code = re.sub(r'wx\.MessageBox\(f"BÄąâ€šĂ„â€¦d odtwarzania: \{str\(e\)\}", "BÄąâ€šĂ„â€¦d", wx\.OK \| wx\.ICON_ERROR\)', r'wx.MessageBox(self._("err_playback").format(e=str(e)), self._("error_title"), wx.OK | wx.ICON_ERROR)', code)

with io.open("wx_app.py", "w", encoding="utf-8", newline="") as f:
    f.write(code)
