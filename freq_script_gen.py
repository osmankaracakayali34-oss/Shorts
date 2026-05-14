"""
freq_script_gen.py — Solfeggio frekans videoları için Gemini ile metadata üretir.

Üretilen alanlar:
  - title: YouTube başlığı (≤60 karakter)
  - hook_line: Ekranda gösterilecek kısa hook metni (≤12 kelime, 1 satır)
  - hook_subtext: Hook altı küçük metin (opsiyonel, ≤8 kelime)
  - description: YouTube açıklaması (SEO optimized)
  - tags: YouTube etiketleri
  - thumbnail_text: Thumbnail'daki büyük metin (2-4 kelime caps)
  - cta_line: Video sonu CTA metni
"""

import os
import json
import random
import re
import time
import requests


GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_MODELS = ["gemini-2.5-flash-lite", "gemini-2.0-flash-lite", "gemini-2.0-flash"]


def _call_gemini(prompt: str, max_tokens: int = 1024) -> str:
    """Gemini API'yi çağırır, model bulunamazsa fallback dener."""
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY ortam değişkeni eksik.")

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.85, "maxOutputTokens": max_tokens},
    }
    last_err = None
    for model in GEMINI_MODELS:
        url = GEMINI_API_BASE.format(model=model) + f"?key={api_key}"
        for attempt in range(3):
            try:
                resp = requests.post(url, json=payload, timeout=30)
                if resp.status_code == 404:
                    break  # Bu model yok, sonrakini dene
                resp.raise_for_status()
                return resp.json()["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as e:
                last_err = e
                if attempt < 2:
                    time.sleep(2 ** attempt)
    raise RuntimeError(f"Tüm Gemini modelleri başarısız: {last_err}")


def _extract_json(text: str) -> dict:
    """Metin içinden JSON bloğunu ayıklar."""
    # ```json ... ``` bloğu
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # Direkt JSON
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    raise ValueError(f"JSON bulunamadı:\n{text[:400]}")


def _repair_and_extract_json(text: str) -> dict:
    """JSON ayıklar; hatalıysa yaygın sorunları düzeltmeyi dener."""
    # Önce normal yolu dene
    try:
        return _extract_json(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # JSON bloğunu bul
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    raw = m.group(1) if m else None
    if not raw:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        raw = m.group(0) if m else None
    if not raw:
        raise ValueError(f"JSON bulunamadı:\n{text[:400]}")

    # Yaygın düzeltmeler
    # 1) Description içindeki escape edilmemiş newline'ları temizle
    fixed = re.sub(r'(?<=": ")(.*?)(?="[,\s*}])', lambda m: m.group(0).replace('\n', '\\n'), raw, flags=re.DOTALL)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 2) Her dil bloğunu ayrı ayrı parse etmeyi dene
    result = {}
    pattern = r'"(\w{2})"\s*:\s*\{[^}]*"title"\s*:\s*"([^"]*)"[^}]*"description"\s*:\s*"([^"]*)"[^}]*\}'
    for lang, title, desc in re.findall(pattern, raw):
        result[lang] = {"title": title, "description": desc}
    if result:
        return result

    raise ValueError(f"JSON parse edilemedi (repair de başarısız):\n{raw[:400]}")


PROMPT_TEMPLATE = """You are a viral YouTube Shorts creator for healing frequency content. Study the top-performing channel "Neural Frequency Sounds" and replicate their exact title/hook/tag strategy.

Frequency: {hz} Hz
Name: {name}
Key Benefit: {benefit}
Mood: {mood}
Description: {description}

HOOK INSPIRATION (use as base, then upgrade with Neuro-Frequency language):
{hooks_str}

━━━ TITLE RULES (Neural Frequency Sounds style) ━━━
Format: "[Hz] Hz [emoji] Neuro-[Action] – [Outcome 1] & [Outcome 2] | Meditation Music"
- ≤60 chars total
- Emoji must match mood: 🧘‍♀️ sleep | ⚡ focus/energy | 🌿 healing | 🔮 spiritual | 🌊 calm | 🧠 brain
- "Neuro-[Action]" examples: Neuro-Detox, Neuro-Reset, Neural Activation, Neural Clarity, Neuro-Boost
- Outcomes must be SPECIFIC and physiological:
  GOOD: "Purge Cortisol & Reset Emotional Balance", "Flush Anxiety & Rewire Sleep Patterns", "Boost GABA & Calm the Nervous System"
  BAD: "Relax and Sleep", "Feel Better", "Healing Music"
- End ALWAYS with "| Meditation Music"
- For focus / calm / energy / brain / sleep moods, include "ADHD" or "ADHD Focus" in the title (e.g. "… ADHD Focus & Deep Sleep | Meditation Music")

━━━ HOOK LINE RULES ━━━
- Shown as large overlay text on screen. ≤12 words.
- Do NOT always start with "If you listen to this" — vary the formula:
  * "[Hz] Hz is activating your [brain region/system] right now..."
  * "Your nervous system is about to reset. Stay until the end."
  * "This neuro-frequency flushes [specific thing] in [time]..."
  * "Let [Hz] Hz reprogram your [emotion/system] while you watch."
- Must create PHYSICAL sensation in the reader's mind — they should feel it.

━━━ HOOK SUBTEXT ━━━
≤8 words. Creates curiosity/urgency. Examples:
- "Most people feel it within 30 seconds."
- "Use headphones for full neural effect."
- "Your body knows what to do with this."

━━━ THUMBNAIL TEXT ━━━
2-4 ALL CAPS words. Use Neuro-Frequency language:
NEURO DETOX | NEURAL RESET | CORTISOL FLUSH | FREQ ACTIVATE | BRAIN REWIRE | MOOD SHIFT | DEEP RESET

━━━ CTA LINE ━━━
Neural Frequency Sounds style. Examples:
- "Follow for daily neuro-frequency sessions."
- "Subscribe — your nervous system will thank you."
- "Follow for frequencies that actually work."

━━━ DESCRIPTION ━━━
80-120 words. Structure:
1. Open with the physiological benefit (what this Hz does to the body/brain)
2. Mention specific brain waves or bodily systems affected
3. "🎧 Use headphones for full binaural effect."
4. List 3 best use cases (sleep, study, anxiety relief, etc.)
5. Close with follow CTA
End with relevant hashtags on new lines.

━━━ TAGS ━━━
12-15 tags. Must include:
- Exact Hz number: "{hz} Hz"
- "Neuro-Frequency", "Neural Frequency", "Healing Frequency"
- Specific physiological keywords from the benefit (e.g. "Cortisol Relief", "Nervous System Reset")
- Brainwave type if applicable (Delta Waves, Theta, Alpha, Gamma, etc.)
- "Binaural Beats", "Solfeggio Frequencies", "Meditation Music", "Sleep Music" or "Focus Music"
- ALWAYS include: "ADHD", "ADHD Focus"

Output ONLY valid JSON:
{{
  "title": "...",
  "hook_line": "...",
  "hook_subtext": "...",
  "thumbnail_text": "...",
  "cta_line": "...",
  "description": "...",
  "tags": ["...", "..."]
}}
"""


def generate_freq_script(topic: dict) -> dict:
    """
    Frekans konusu için Gemini metadata üretir.

    Args:
        topic: freq_topic_pool.json'dan bir kayıt

    Returns:
        Üretilen metadata dict
    """
    hz = topic["hz"]
    hooks_str = "\n".join(f"- {h}" for h in topic.get("hooks", []))

    prompt = PROMPT_TEMPLATE.format(
        hz=hz,
        name=topic["name"],
        benefit=topic["benefit"],
        mood=topic["mood"],
        description=topic["description"],
        hooks_str=hooks_str,
    )

    print(f"[freq_script_gen] {topic['name']} için Gemini çağrılıyor...")
    raw = _call_gemini(prompt)
    script = _extract_json(raw)

    # Eksik alan varsa topic pool'dan default al
    script.setdefault("title", topic["title_name"])
    script.setdefault("hook_line", random.choice(topic["hooks"]))
    script.setdefault("hook_subtext", "")
    script.setdefault("thumbnail_text", topic["short_benefit"].upper())
    script.setdefault("cta_line", "Follow for daily healing frequencies.")
    script.setdefault("tags", topic["tags"])
    script.setdefault("description", topic["description"])

    # Topic meta bilgilerini ekle
    script["hz"] = hz
    script["freq_name"] = topic["name"]
    script["short_benefit"] = topic["short_benefit"]
    script["mood"] = topic["mood"]
    script["pexels_keywords"] = topic.get("pexels_keywords", [])

    print(f"[freq_script_gen] Başlık: {script['title']}")
    print(f"[freq_script_gen] Hook: {script['hook_line']}")
    return script


LOCALIZATION_PROMPT = """Translate this YouTube video title and description into 12 languages.

RULES:
- Keep Hz numbers unchanged (e.g. "528 Hz" stays "528 Hz")
- Keep hashtags in English
- Keep descriptions SHORT (max 2 sentences per language)
- Do NOT use unescaped quotes or newlines inside JSON string values

Title: {title}
Description: {description}

Languages: es, fr, pt, de, tr, ar, ja, ko, hi, it, ru, zh-Hans

Output ONLY valid JSON with ALL 12 languages:
{{"es":{{"title":"...","description":"..."}},"fr":{{"title":"...","description":"..."}},"pt":{{"title":"...","description":"..."}},"de":{{"title":"...","description":"..."}},"tr":{{"title":"...","description":"..."}},"ar":{{"title":"...","description":"..."}},"ja":{{"title":"...","description":"..."}},"ko":{{"title":"...","description":"..."}},"hi":{{"title":"...","description":"..."}},"it":{{"title":"...","description":"..."}},"ru":{{"title":"...","description":"..."}},"zh-Hans":{{"title":"...","description":"..."}}}}
"""

TARGET_LANGS = ["es", "fr", "pt", "de", "tr", "ar", "ja", "ko", "hi", "it", "ru", "zh-Hans"]


def generate_localizations(script: dict) -> dict:
    """
    Gemini'ye title+description gönderip 12 dile çeviri alır.

    Args:
        script: generate_freq_script() çıktısı

    Returns:
        YouTube localizations formatında dict:
        {"es": {"title": "...", "description": "..."}, ...}
    """
    title = script.get("title", "")
    description = script.get("description", "")

    prompt = LOCALIZATION_PROMPT.format(title=title, description=description)

    MIN_LANGS = 8  # En az 8/12 dil gelmeli

    for attempt in range(3):
        print(f"[freq_script_gen] Çoklu dil çevirileri üretiliyor (12 dil, deneme {attempt + 1})...")
        raw = _call_gemini(prompt, max_tokens=4096)
        localizations = _repair_and_extract_json(raw)

        # Sadece geçerli dilleri tut, her birinin title+description'ı olmalı
        valid = {}
        for lang in TARGET_LANGS:
            if lang in localizations:
                entry = localizations[lang]
                if isinstance(entry, dict) and "title" in entry and "description" in entry:
                    valid[lang] = {
                        "title": entry["title"],
                        "description": entry["description"],
                    }

        print(f"[freq_script_gen] {len(valid)} dil çevirisi alındı: {', '.join(valid.keys())}")

        if len(valid) >= MIN_LANGS:
            return valid

        missing = [l for l in TARGET_LANGS if l not in valid]
        print(f"[freq_script_gen] Yetersiz ({len(valid)}/{MIN_LANGS}), eksik: {', '.join(missing)}")
        if attempt < 2:
            time.sleep(2)

    raise RuntimeError(
        f"Localization başarısız: 3 denemede en az {MIN_LANGS} dil alınamadı "
        f"(son: {len(valid)} dil)"
    )


def save_freq_script(script: dict, path: str = "output/freq_script.json") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(script, f, indent=2, ensure_ascii=False)
    print(f"[freq_script_gen] Script kaydedildi: {path}")
