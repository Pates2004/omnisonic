import io

with io.open("langs/pl.lng", "r", encoding="utf-8") as f:
    pl = f.read()
    
# Fix duration translation
pl = pl.replace('"duration_lbl": "Wymuś czas (Duration) w sekundach:"', '"duration_lbl": "Wymuś długość nagrania w sekundach:"')

# Add missing translations
if '"tab_auto"' not in pl:
    pl = pl.replace('"tab_adv": "Zaawansowane",', '"tab_adv": "Zaawansowane",\n    "tab_auto": "Głos Systemowy (AutoVoice)",\n    "menu_help": "Pomoc",\n    "menu_help_tags": "Znaczniki (Laughter itp)",')
    
if '"auto_text_lbl"' not in pl:
    pl = pl.replace('"op_gen_msg": "Generowanie...",', '"op_gen_msg": "Generowanie...",\n    "auto_text_lbl": "Tekst do wygenerowania",\n    "auto_lang_lbl": "Język:",\n    "btn_gen_auto": "Wygeneruj",\n    "op_auto_title": "Generowanie AutoVoice",\n    "op_auto_msg": "Generowanie...",')
    
with io.open("langs/pl.lng", "w", encoding="utf-8", newline="") as f:
    f.write(pl)
    
with io.open("langs/en.lng", "r", encoding="utf-8") as f:
    en = f.read()

if '"tab_auto"' not in en:
    en = en.replace('"tab_adv": "Advanced Options",', '"tab_adv": "Advanced Options",\n    "tab_auto": "System Voice (AutoVoice)",\n    "menu_help": "Help",\n    "menu_help_tags": "Voice Tags (Laughter etc)",')

if '"auto_text_lbl"' not in en:
    en = en.replace('"op_gen_msg": "Generating...",', '"op_gen_msg": "Generating...",\n    "auto_text_lbl": "Text to generate",\n    "auto_lang_lbl": "Language:",\n    "btn_gen_auto": "Generate",\n    "op_auto_title": "Generating AutoVoice",\n    "op_auto_msg": "Generating...",')

with io.open("langs/en.lng", "w", encoding="utf-8", newline="") as f:
    f.write(en)
