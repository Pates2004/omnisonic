import io
import json

def update_lng(path, updates):
    with io.open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for k, v in updates.items():
        data[k] = v
    with io.open(path, "w", encoding="utf-8", newline="") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

update_lng("langs/pl.lng", {
    "dl_model_prompt": "Wybrany model ({name}) nie jest pobrany. Czy chcesz go pobrać i zainstalować teraz?",
    "dl_title": "Pobieranie modelu"
})

update_lng("langs/en.lng", {
    "dl_model_prompt": "Selected model ({name}) is not downloaded yet. Do you want to download and install it now?",
    "dl_title": "Downloading model"
})
