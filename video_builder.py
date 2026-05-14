"""
video_builder.py — YouTube CC + DVIDS + Archive'dan footage indirir, MoviePy ile 1080×1920 Short üretir.
Özellikler:
  - YouTube Creative Commons lisanslı gerçek askeri videolar (yt-dlp)
  - DVIDS + Internet Archive fallback
  - Style Profile sistemi (her video benzersiz görünüm)
  - 6 yönlü Ken Burns efekti
  - 8 renk tonu preset'i (mood-aware)
  - 4 farklı geçiş tipi
  - Film grain + vignette overlay
  - VTT tabanlı kesin zamanlı altyazı
  - Hook overlay, CTA ekranı, progress bar, watermark
  - Mood-based müzik seçimi
"""

import os
import json
import random
import requests
import tempfile
import shutil
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Pillow 10+ uyumluluğu
if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

from moviepy.editor import (
    VideoFileClip,
    AudioFileClip,
    CompositeVideoClip,
    CompositeAudioClip,
    ImageClip,
    ColorClip,
    concatenate_videoclips,
)
from moviepy.video.VideoClip import VideoClip

TARGET_W = 1080
TARGET_H = 1920
DVIDS_API = "https://api.dvidshub.net/search"
ARCHIVE_API = "https://archive.org/advancedsearch.php"
YT_COOKIES_PATH = os.environ.get("YT_COOKIES_PATH", "yt_cookies.txt")
YT_PROXY = os.environ.get("YT_PROXY", "")  # e.g. socks5://localhost:1080

# ─── YouTube CC Askeri Keyword Havuzu ────────────────────────────────────────

YT_MILITARY_KEYWORDS = {
    "training": [
        "military training footage", "army training exercise footage",
        "military drill footage", "combat training footage",
        "army boot camp footage", "military obstacle course footage",
        "live fire exercise footage", "infantry training footage",
        "paratrooper training footage", "military academy footage",
        "amphibious assault training footage", "urban warfare training footage",
        "night vision military training footage", "joint military exercise footage",
        "ranger training footage", "marine corps training footage",
    ],
    "jets": [
        "fighter jet takeoff footage", "fighter jet cockpit footage",
        "F-35 footage", "F-22 raptor footage", "Su-57 footage",
        "fighter jet dogfight footage", "air force scramble footage",
        "military jet formation footage", "stealth bomber footage",
        "B-2 bomber footage", "fighter jet landing footage",
        "supersonic jet footage", "jet afterburner footage",
        "eurofighter typhoon footage", "rafale fighter footage",
        "F-16 footage", "F-15 eagle footage", "MiG-29 footage",
    ],
    "helicopter": [
        "military helicopter takeoff footage", "attack helicopter firing footage",
        "Apache helicopter footage", "Black Hawk helicopter footage",
        "helicopter gunship footage", "military helicopter rescue footage",
        "CH-47 Chinook footage", "helicopter air assault footage",
        "Ka-52 helicopter footage", "military helicopter formation footage",
        "medevac helicopter footage", "helicopter fast rope footage",
    ],
    "tanks": [
        "tank firing footage", "tank live fire exercise footage",
        "M1 Abrams tank footage", "Leopard 2 tank footage",
        "tank battle footage", "armored vehicle footage",
        "tank convoy footage", "T-90 tank footage",
        "tank urban combat footage", "Challenger 2 tank footage",
        "Merkava tank footage", "tank night firing footage",
        "armored personnel carrier footage", "tank column footage",
    ],
    "drone": [
        "military drone footage", "drone surveillance footage",
        "Bayraktar TB2 footage", "drone strike footage",
        "UAV military footage", "predator drone footage",
        "reaper drone footage", "combat drone footage",
        "drone swarm military footage", "reconnaissance drone footage",
        "military quadcopter footage", "kamikaze drone footage",
        "drone warfare footage", "tactical drone footage",
    ],
    "navy": [
        "navy exercise footage", "aircraft carrier operations footage",
        "warship footage", "destroyer ship footage",
        "submarine footage", "naval fleet footage",
        "navy SEAL footage", "amphibious landing footage",
        "aircraft carrier takeoff footage", "battleship footage",
        "frigate naval footage", "naval bombardment footage",
        "submarine surfacing footage", "carrier strike group footage",
        "navy fleet formation footage", "cruiser warship footage",
    ],
    "special_forces": [
        "special forces training footage", "navy seals training footage",
        "special operations footage", "delta force footage",
        "SAS training footage", "commando raid footage",
        "special forces night raid footage", "counter terrorism footage",
        "hostage rescue footage", "special forces parachute footage",
        "green beret footage", "spetsnaz training footage",
        "special forces CQB footage", "SWAT tactical footage",
    ],
    "missiles": [
        "missile launch footage", "ICBM launch footage",
        "cruise missile footage", "anti ship missile footage",
        "patriot missile footage", "S-400 missile footage",
        "hypersonic missile footage", "ballistic missile footage",
        "missile defense system footage", "THAAD missile footage",
        "iron dome interception footage", "tomahawk cruise missile footage",
        "nuclear missile test footage", "air defense missile footage",
    ],
    "explosions": [
        "military explosion footage", "bomb explosion footage",
        "airstrike footage", "demolition military footage",
        "artillery firing footage", "howitzer firing footage",
        "carpet bombing footage", "precision strike footage",
        "bunker buster footage", "controlled demolition military footage",
        "mortar firing footage", "rocket artillery footage",
    ],
    "misc": [
        "military parade footage", "soldiers marching footage",
        "military ceremony footage", "troops deployment footage",
        "military logistics footage", "military base footage",
        "war memorial footage", "veterans ceremony footage",
        "military equipment footage", "defense industry footage",
        "military convoy footage", "armed forces footage",
        "military flag ceremony footage", "soldiers patrol footage",
        "military camp footage", "army barracks footage",
    ],
    "conflict": [
        "war zone footage", "frontline combat footage",
        "military operation footage", "battlefield footage",
        "troops advancing footage", "urban warfare footage",
        "ceasefire footage", "military press conference footage",
        "sanctions military news footage", "geopolitics military footage",
        "war correspondent footage", "military checkpoint footage",
        "soldiers in the field footage", "military base operations footage",
        "troop deployment footage", "military strategy briefing footage",
    ],
}
FONT_PATH = "assets/fonts/Montserrat-Bold.ttf"
LOGO_PATH = "assets/logo.png"
INTRO_PATH = "assets/intro.mp4"
OUTRO_PATH = "assets/outro.mp4"
CROSSFADE_DUR = 0.2
CTA_DURATION = 2.0   # 3.0'dan kısaltıldı — % watched artışı için

# Ses efekti dosyaları
SFX = {
    "hook":   "assets/sfx/drum_hit.wav",
    "twist":  "assets/sfx/sword_clash.wav",
    "payoff": "assets/sfx/explosion.wav",
    "cta":    "assets/sfx/trumpet.wav",
}

# Müzik havuzu: (dosya, mood anahtar kelimeleri)
MUSIC_POOL = [
    ("assets/music/epic_01_strength_of_titans.mp3", ["epic", "battle", "war", "empire", "army"]),
    ("assets/music/epic_02_ice_giants.mp3", ["epic", "cold", "north", "viking", "fall"]),
    ("assets/music/epic_03_gothamlicious.mp3", ["epic", "dark", "power", "conquer", "reign"]),
    ("assets/music/dark_04_burn_the_world.mp3", ["destroy", "nuclear", "bomb", "apocalypse", "invasion"]),
    ("assets/music/action_05_adventures.mp3", ["adventure", "explore", "discover", "hero", "victory"]),
    ("assets/music/dark_06_southern_gothic.mp3", ["dark", "mystery", "secret", "conspiracy", "betrayal"]),
    ("assets/music/suspense_07_stay_the_course.mp3", ["suspense", "tension", "crisis", "standoff", "cold war"]),
    ("assets/music/dark_08_tyrant.mp3", ["tyrant", "dictator", "regime", "oppression", "revolution"]),
    ("assets/music/action_09_big_drumming.mp3", ["action", "military", "march", "troops", "combat"]),
    ("assets/music/action_10_new_hero.mp3", ["hero", "rise", "triumph", "victory", "liberation"]),
    ("assets/music/action_11_trouble_tribals.mp3", ["tribal", "ancient", "primitive", "clash", "territory"]),
    ("assets/music/dark_12_feral_angel.mp3", ["dark", "somber", "tragedy", "loss", "aftermath"]),
]
MUSIC_FALLBACK = "assets/music/epic_01_strength_of_titans.mp3"

# ─── 8 Renk Tonu Preset'i ────────────────────────────────────────────────────

COLOR_GRADES = {
    "war_blue": {
        "desaturate": 0.30, "contrast": 1.15,
        "r_shift": -5, "g_shift": 0, "b_shift": +8,
    },
    "vintage_sepia": {
        "desaturate": 0.20, "contrast": 1.10,
        "r_shift": +15, "g_shift": +5, "b_shift": -10,
    },
    "cold_winter": {
        "desaturate": 0.25, "contrast": 1.20,
        "r_shift": -10, "g_shift": +2, "b_shift": +15,
    },
    "high_contrast_bw": {
        "desaturate": 1.0, "contrast": 1.30,
        "r_shift": 0, "g_shift": 0, "b_shift": 0,
    },
    "faded_washed": {
        "desaturate": 0.15, "contrast": 0.85,
        "r_shift": +5, "g_shift": +5, "b_shift": +5,
    },
    "vivid_saturated": {
        "desaturate": -0.20, "contrast": 1.25,
        "r_shift": +3, "g_shift": +3, "b_shift": +3,
    },
    "neutral": {
        "desaturate": 0.0, "contrast": 1.0,
        "r_shift": 0, "g_shift": 0, "b_shift": 0,
    },
    "dark_cinematic": {
        "desaturate": 0.35, "contrast": 1.35,
        "r_shift": -8, "g_shift": -8, "b_shift": -5,
    },
}

# Mood → uygun renk tonları eşleşmesi
MOOD_COLOR_MAP = {
    "dark":       ["dark_cinematic", "high_contrast_bw", "war_blue"],
    "epic":       ["vivid_saturated", "war_blue", "vintage_sepia"],
    "cold":       ["cold_winter", "war_blue", "faded_washed"],
    "mysterious": ["dark_cinematic", "faded_washed", "vintage_sepia"],
    "inspiring":  ["vivid_saturated", "vintage_sepia", "neutral"],
    "neutral":    list(COLOR_GRADES.keys()),
}

# Ken Burns efekt tipleri
KB_EFFECTS = ["zoom_in", "zoom_out", "pan_right", "pan_left", "pan_down", "diagonal_ur"]

# Geçiş tipleri
TRANSITION_TYPES = ["crossfade", "fade_black", "hard_cut", "slide"]

# Klip ve resim süreleri
VIDEO_CLIP_DURATION = 2.5   # Her video klip süresi (saniye)
IMAGE_CLIP_DURATION = 2.0   # Araya eklenen resim süresi (saniye)

# ─── Power word sözlüğü (altyazıda sarı vurgu) ────────────────────────────────
_POWER_WORDS: dict[str, set] = {
    "en": {
        "BREAKING", "URGENT", "SHOCKING", "WARNING", "CRITICAL", "REVEALED",
        "SECRET", "JUST", "ALERT", "EXCLUSIVE", "CLASSIFIED", "TERROR",
        "NUCLEAR", "ATTACK", "DANGER", "NOW", "DEAD", "KILL", "WAR",
    },
    "tr": {
        "ACİL", "ŞOKE", "KRİTİK", "UYARI", "GİZLİ", "İŞTE", "ÖZEL", "SON",
        "ALARM", "TEHLİKE", "SAVAŞ", "NÜKLEER", "SALDIRI", "ÖLÜM", "ŞIMDI",
    },
    "ar": {
        "عاجل", "صادم", "خطير", "حصري", "مرعب", "كارثي", "سري", "الآن",
        "تحذير", "هجوم", "نووي", "حرب", "موت", "مفاجئ", "عاجلاً",
    },
}

def _is_power_word(word: str) -> bool:
    """Kelimenin herhangi bir dildeki power word listesinde olup olmadığını kontrol eder."""
    clean = word.strip(".,!?:;\"'()[]").upper()
    for words in _POWER_WORDS.values():
        if clean in words:
            return True
    return False


# ─── Style Profile ───────────────────────────────────────────────────────────

@dataclass
class StyleProfile:
    """Her video için benzersiz görsel stil konfigürasyonu."""
    color_grade: str
    transition_type: str
    ken_burns_pool: list
    vignette_intensity: float
    film_grain_intensity: float


# Stop words — title'dan keyword çıkarırken filtrele
_STOP_WORDS = {"what", "if", "the", "a", "an", "is", "was", "were", "had", "have", "has",
               "did", "do", "does", "not", "never", "ever", "in", "on", "at", "to", "for",
               "of", "and", "or", "but", "vs", "how", "why", "who", "that", "this", "it",
               "be", "been", "being", "are", "am", "with", "from", "by", "about", "into",
               "ya", "olmasaydı", "eğer", "ve", "bir", "bu", "neden", "nasıl"}


def _extract_title_keywords(title: str) -> list[str]:
    """Title'dan arama için anlamlı keyword'ler çıkarır."""
    import re
    words = re.findall(r"[a-zA-ZğüşöçıİĞÜŞÖÇ]{3,}", title.lower())
    meaningful = [w for w in words if w not in _STOP_WORDS]
    # İlk 4 anlamlı kelimeyi döndür
    return meaningful[:4]


def _infer_mood(script: dict) -> str:
    """Script içeriğinden mood çıkarır."""
    text = (script.get("title", "") + " " + script.get("narration", "")).lower()
    keywords = " ".join(kw.lower() for kw in script.get("search_keywords", []))
    combined = text + " " + keywords

    dark_words = ["destroy", "fall", "death", "tragedy", "loss", "defeat",
                  "apocalypse", "massacre", "collapse", "extinction", "nuclear"]
    if any(w in combined for w in dark_words):
        return "dark"

    epic_words = ["empire", "conquer", "victory", "rise", "triumph", "glory",
                  "legendary", "hero", "revolution", "power"]
    if any(w in combined for w in epic_words):
        return "epic"

    cold_words = ["winter", "north", "ice", "frozen", "arctic", "snow", "cold war"]
    if any(w in combined for w in cold_words):
        return "cold"

    return "neutral"


def _generate_style_profile(script: dict) -> StyleProfile:
    """Video için rastgele ama mood-aware stil profili üretir."""
    # Script'ten gelen mood alanını kullan, yoksa text'ten çıkar
    mood = script.get("mood") if script.get("mood") in MOOD_COLOR_MAP else _infer_mood(script)

    # Renk tonu: %70 mood'a uygun, %30 tamamen rastgele
    if random.random() < 0.7:
        color_grade = random.choice(MOOD_COLOR_MAP[mood])
    else:
        color_grade = random.choice(list(COLOR_GRADES.keys()))

    # Geçiş: tamamen rastgele
    transition_type = random.choice(TRANSITION_TYPES)

    # Ken Burns: 6 efektten 3-4'ü seçilir
    ken_burns_pool = random.sample(KB_EFFECTS, random.randint(3, 4))

    # Overlay yoğunlukları
    vignette_intensity = random.choice([0.0, 0.0, 0.2, 0.3, 0.4])
    film_grain_intensity = random.choice([0.0, 0.0, 0.0, 0.15, 0.25])

    profile = StyleProfile(
        color_grade=color_grade,
        transition_type=transition_type,
        ken_burns_pool=ken_burns_pool,
        vignette_intensity=vignette_intensity,
        film_grain_intensity=film_grain_intensity,
    )

    print(f"[video_builder] Style Profile:")
    print(f"  Mood: {mood} | Color: {color_grade} | Transition: {transition_type}")
    print(f"  KB Pool: {ken_burns_pool}")
    print(f"  Vignette: {vignette_intensity:.1f} | Grain: {film_grain_intensity:.2f}")

    return profile


# ─── Müzik seçimi ────────────────────────────────────────────────────────────

_MILITARY_PRIORITY_TRACKS = {
    "assets/music/dark_04_burn_the_world.mp3",
    "assets/music/action_09_big_drumming.mp3",
    "assets/music/suspense_07_stay_the_course.mp3",
    "assets/music/dark_08_tyrant.mp3",
    "assets/music/dark_12_feral_angel.mp3",
}

_MILITARY_KEYWORDS = {
    "military", "war", "attack", "troops", "missile", "iran", "israel", "gaza",
    "strike", "bomb", "nuclear", "army", "weapon", "conflict", "combat",
    "hamas", "hezbollah", "idf", "irgc", "drone", "airstrike",
}


def _pick_music(script: dict) -> str:
    """Script içeriğine göre en uygun arka plan müziğini seçer.
    Askeri içerik için dark/action parçaları önceliklendirilir.
    """
    text = (script.get("title", "") + " " + script.get("narration", "")).lower()
    keywords = [kw.lower() for kw in script.get("search_keywords", [])]
    all_text = text + " " + " ".join(keywords)

    is_military = any(kw in all_text for kw in _MILITARY_KEYWORDS)

    scores = []
    for path, mood_words in MUSIC_POOL:
        if not os.path.exists(path):
            continue
        score = sum(1 for mw in mood_words if mw in text or mw in " ".join(keywords))
        # Askeri içerik: gerilimli/aksiyonlu parçalara +2 bonus
        if is_military and path in _MILITARY_PRIORITY_TRACKS:
            score += 2
        scores.append((path, score))

    if not scores:
        return MUSIC_FALLBACK

    max_score = max(s for _, s in scores)
    if max_score > 0:
        best = [p for p, s in scores if s == max_score]
        pick = random.choice(best)
    else:
        # Askeri içerik ise yine de priority listesinden seç
        if is_military:
            priority = [p for p, _ in scores if p in _MILITARY_PRIORITY_TRACKS]
            pick = random.choice(priority) if priority else random.choice([p for p, _ in scores])
        else:
            pick = random.choice([p for p, _ in scores])

    print(f"[video_builder] Müzik seçildi: {os.path.basename(pick)} (military={is_military})")
    return pick


# ─── Font yardımcısı ─────────────────────────────────────────────────────────

ARABIC_FONT_PATH = "assets/fonts/NotoNaskhArabic-Bold.ttf"


def _sanitize_for_arabic_font(text: str) -> str:
    """Arapça fontunda bulunmayan özel Unicode karakterleri temizler."""
    replacements = {
        "\u2018": "'", "\u2019": "'",   # curly single quotes → straight
        "\u201C": '"', "\u201D": '"',   # curly double quotes → straight
        "\u2013": "-", "\u2014": "-",   # en/em dash → hyphen
        "\u2026": "...",                # ellipsis → dots
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text


def _prepare_text(text: str) -> str:
    """Arapça metin için harf birleşimi (reshaper) ve RTL yönü (bidi) uygular."""
    if not _is_arabic(text):
        return text
    text = _sanitize_for_arabic_font(text)
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        import re as _re
        reshaped = arabic_reshaper.reshape(text)
        display = get_display(reshaped)
        # PIL bidi kontrol karakterlerini işleyemiyor — temizle
        display = _re.sub(r'[\u200e\u200f\u202a-\u202e\u2066-\u2069]', '', display)
        return display
    except ImportError:
        return text


def _is_arabic(text: str) -> bool:
    """Metnin Arapça karakter içerip içermediğini kontrol eder (presentation forms dahil)."""
    return any(
        "\u0600" <= ch <= "\u06FF"    # Basic Arabic
        or "\uFB50" <= ch <= "\uFDFF"  # Arabic Presentation Forms-A
        or "\uFE70" <= ch <= "\uFEFF"  # Arabic Presentation Forms-B
        for ch in text
    )


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in [
        FONT_PATH,
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _load_font_for_text(text: str, size: int) -> ImageFont.FreeTypeFont:
    """Metne göre uygun fontu yükler: Arapça ise Noto Naskh, değilse varsayılan."""
    if _is_arabic(text):
        import glob as _glob
        candidate_paths = [
            ARABIC_FONT_PATH,
            "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
        ]
        candidate_paths += sorted(_glob.glob("/usr/share/fonts/**/*Arabic*Bold*.ttf", recursive=True))
        candidate_paths += sorted(_glob.glob("/usr/share/fonts/**/*Arabic*.ttf", recursive=True))
        for path in candidate_paths:
            if os.path.exists(path):
                try:
                    return ImageFont.truetype(path, size)
                except OSError:
                    continue
    return _load_font(size)


# ─── Klip indirme ────────────────────────────────────────────────────────────

def _download_clip(url: str) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    r = requests.get(url, stream=True, timeout=60)
    r.raise_for_status()
    for chunk in r.iter_content(chunk_size=8192):
        tmp.write(chunk)
    tmp.close()
    return tmp.name


def _pick_yt_category(keywords: list) -> str:
    """Script keyword'lerine göre en uygun YT keyword kategorisini seçer."""
    kw_lower = " ".join(k.lower() for k in keywords)

    category_hints = {
        "jets": ["jet", "fighter", "f-35", "f-22", "f-16", "stealth", "bomber", "aircraft", "air force", "kaan", "su-57", "rafale"],
        "helicopter": ["helicopter", "apache", "black hawk", "chinook", "heli", "ka-52"],
        "tanks": ["tank", "abrams", "leopard", "armored", "t-90", "merkava", "challenger"],
        "drone": ["drone", "uav", "bayraktar", "tb2", "reaper", "predator", "akinci", "swarm"],
        "navy": ["navy", "carrier", "submarine", "ship", "destroyer", "fleet", "frigate", "cruiser", "naval"],
        "special_forces": ["special forces", "seal", "delta", "sas", "commando", "spetsnaz", "green beret"],
        "missiles": ["missile", "icbm", "hypersonic", "patriot", "s-400", "iron dome", "thaad", "nuclear", "nuke", "rocket"],
        "explosions": ["explosion", "bomb", "airstrike", "artillery", "howitzer", "demolition", "mortar"],
        "training": ["training", "exercise", "drill", "boot camp"],
        "conflict": ["ceasefire", "negotiation", "sanction", "diplomacy", "talks", "agreement",
                     "peace", "frontline", "war zone", "occupation", "offensive", "invasion",
                     "blockade", "embargo", "ultimatum", "tension", "escalat", "geopolit"],
    }

    for cat, hints in category_hints.items():
        if any(h in kw_lower for h in hints):
            return cat

    # Eşleşme yoksa: script'in konusunu anlamlandıran genel savaş/çatışma havuzu
    return "conflict"


def _fetch_youtube_cc_clips(keywords: list, n: int, seen_ids: set) -> list[str]:
    """YouTube'dan Creative Commons lisanslı askeri video indirir (yt-dlp).
    Self-hosted runner'da çalışır — --cookies-from-browser firefox kullanır.
    Returns: list of file paths.
    """
    if not shutil.which("yt-dlp"):
        print("[video_builder] yt-dlp bulunamadı, YouTube CC atlanıyor.")
        return []
    if not shutil.which("ffmpeg"):
        print("[video_builder] ffmpeg bulunamadı, YouTube CC atlanıyor.")
        return []

    downloaded = []

    category = _pick_yt_category(keywords)
    yt_pool = list(YT_MILITARY_KEYWORDS.get(category, []))
    random.shuffle(yt_pool)

    script_queries = []
    for kw in keywords[:10]:
        # Zaten "footage" içeriyorsa tekrar ekleme
        if "footage" in kw.lower() or "operations" in kw.lower():
            script_queries.append(kw)
        else:
            script_queries.append(f"{kw} footage")
    if len(keywords) >= 2:
        combined = f"{keywords[0]} {keywords[1]}"
        if combined not in script_queries:
            script_queries.append(f"{combined} footage")

    all_queries = script_queries + yt_pool
    seen_queries = set()
    unique_queries = []
    for q in all_queries:
        ql = q.lower()
        if ql not in seen_queries:
            seen_queries.add(ql)
            unique_queries.append(q)

    for query in unique_queries:
        if len(downloaded) >= n:
            break

        try:
            # YouTube CC arama filtresi: sp=EgIwAQ%3D%3D → YouTube kendi tarafında
            # sadece Creative Commons videoları döndürür. yt-dlp'nin license field'i
            # YouTube watch sayfasından güvenilir şekilde çekilemiyor (hep boş geliyor),
            # bu yüzden YouTube'un kendi CC filtresine güveniyoruz.
            cookie_args = []
            if os.path.exists(YT_COOKIES_PATH) and os.path.getsize(YT_COOKIES_PATH) > 0:
                cookie_args = ["--cookies", YT_COOKIES_PATH]
            else:
                print(f"[video_builder] Uyarı: {YT_COOKIES_PATH} bulunamadı veya boş — bot tespiti riski yüksek")

            encoded_q = query.replace(" ", "+").replace("'", "%27")
            yt_cc_url = (
                f"https://www.youtube.com/results"
                f"?search_query={encoded_q}&sp=EgIwAQ%3D%3D"
            )
            proxy_args = ["--proxy", YT_PROXY] if YT_PROXY else []
            id_cmd = [
                "yt-dlp",
                yt_cc_url,
                "--flat-playlist",     # sadece metadata, video indirme yok
                "--playlist-end", "5", # ilk 5 sonuç yeterli
                "--print", "id",
                "--no-warnings",
                "--no-progress",
                "--extractor-args", "youtube:player_client=web_creator,web,default",
            ] + cookie_args + proxy_args
            id_result = subprocess.run(id_cmd, timeout=30, capture_output=True, text=True)
            video_ids = [l.strip() for l in id_result.stdout.splitlines()
                         if l.strip() and len(l.strip()) == 11]
            print(f"[video_builder] YouTube CC '{query}': {len(video_ids)} ID "
                  f"(rc={id_result.returncode})")
            if not video_ids and id_result.stderr:
                print(f"[video_builder]   stderr: {id_result.stderr.strip()[:200]}")

            if not video_ids:
                continue

            try:
                import yt_dlp as _ytdlp
            except ImportError:
                print("[video_builder] yt_dlp modülü import edilemiyor.")
                return downloaded

            cookie_file = (YT_COOKIES_PATH
                           if os.path.exists(YT_COOKIES_PATH)
                           and os.path.getsize(YT_COOKIES_PATH) > 0
                           else None)

            # yt-dlp'nin kendi hata mesajlarını bastır; sadece bizim loglarımız görünsün.
            class _SilentLogger:
                def debug(self, _): pass
                def info(self, _): pass
                def warning(self, _): pass
                def error(self, msg):
                    print(f"[video_builder]   yt-dlp: {msg[:120]}")

            # ── YouTube İndirme: 2 katmanlı strateji ──────────────────
            # 1) pytubefix (auth'suz) → ANDROID_VR en güvenilir client
            # 2) yt-dlp + cookies     → son çare
            #
            # NOT: use_po_token deprecated (stdin'den input bekliyor → CI'da patlar).
            # pytubefix OAuth da CI'da pratik değil.

            # pytubefix client listesi: ANDROID_VR tek yeterli, diğerleri zaman kaybı.
            _PTF_CLIENTS = [
                "ANDROID_VR",
            ]

            # pytubefix proxy ayarı (varsa).
            _ptf_proxies = ({"https": YT_PROXY, "http": YT_PROXY}
                            if YT_PROXY else None)

            # yt-dlp client listesi (son çare — daha permissive format).
            _YTDLP_CLIENTS = [
                (["web_creator"], None), (["web"], None),
                (["default"], None),
            ]

            def _pick_stream(yt_obj):
                """En iyi stream'i seç: adaptive 1080p > progressive 720p, 480p altı red."""
                # 1) Adaptive 1080p video-only + ayrı audio → ffmpeg merge
                if shutil.which("ffmpeg"):
                    v = (yt_obj.streams
                         .filter(adaptive=True, file_extension="mp4", only_video=True)
                         .order_by("resolution").desc().first())
                    a = (yt_obj.streams
                         .filter(adaptive=True, only_audio=True)
                         .order_by("abr").desc().first())
                    if v and a:
                        res = getattr(v, "resolution", "") or ""
                        h = int(res.replace("p", "")) if res.replace("p", "").isdigit() else 0
                        if h >= 720:
                            return ("adaptive", v, a)  # tuple → merge gerekli

                # 2) Progressive fallback — min 720p
                s = (yt_obj.streams
                     .filter(progressive=True, file_extension="mp4")
                     .order_by("resolution").desc().first())
                if s:
                    res = getattr(s, "resolution", "") or ""
                    h = int(res.replace("p", "")) if res.replace("p", "").isdigit() else 0
                    if h >= 720:
                        return ("progressive", s)
                return None  # kalite yetersiz, bu videoyu atla

            def _download_stream(stream_info, prefix: str) -> str | None:
                """Stream'i tmp dosyaya indir; adaptive ise ffmpeg ile merge eder."""
                if stream_info is None:
                    return None

                if stream_info[0] == "adaptive":
                    _, v_stream, a_stream = stream_info
                    v_tmp = tempfile.NamedTemporaryFile(suffix="_v.mp4", delete=False, prefix=prefix)
                    v_tmp.close()
                    a_tmp = tempfile.NamedTemporaryFile(suffix="_a.m4a", delete=False, prefix=prefix)
                    a_tmp.close()
                    out_tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False, prefix=prefix)
                    out_tmp.close()
                    try:
                        v_stream.download(output_path=os.path.dirname(v_tmp.name),
                                          filename=os.path.basename(v_tmp.name))
                        a_stream.download(output_path=os.path.dirname(a_tmp.name),
                                          filename=os.path.basename(a_tmp.name))
                        r = subprocess.run(
                            ["ffmpeg", "-y", "-i", v_tmp.name, "-i", a_tmp.name,
                             "-c:v", "copy", "-c:a", "aac", "-shortest", out_tmp.name],
                            capture_output=True, timeout=120
                        )
                        if r.returncode == 0 and os.path.getsize(out_tmp.name) > 10000:
                            return out_tmp.name
                    finally:
                        for p in (v_tmp.name, a_tmp.name):
                            try:
                                os.unlink(p)
                            except OSError:
                                pass
                    return None

                # Progressive
                _, stream = stream_info
                tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False, prefix=prefix)
                tmp.close()
                stream.download(output_path=os.path.dirname(tmp.name),
                                filename=os.path.basename(tmp.name))
                if os.path.exists(tmp.name) and os.path.getsize(tmp.name) > 10000:
                    return tmp.name
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass
                return None

            def _try_pytubefix_plain(vid_id: str) -> str | None:
                """pytubefix auth'suz — ANDROID_VR ile dener, 40s timeout."""
                try:
                    from pytubefix import YouTube as PTYouTube
                except ImportError:
                    return None
                import concurrent.futures as _cf
                _url = f"https://www.youtube.com/watch?v={vid_id}"
                for client in _PTF_CLIENTS:
                    tag = f"ptf/{client}"
                    print(f"[video_builder] YouTube CC: '{query}' → {vid_id} [{tag}]...")
                    def _attempt(url=_url, c=client):
                        yt_obj = PTYouTube(url, client=c, proxies=_ptf_proxies)
                        s = _pick_stream(yt_obj)
                        if not s:
                            return None
                        return _download_stream(s, "ytcc_ptf_")
                    try:
                        with _cf.ThreadPoolExecutor(max_workers=1) as ex:
                            fut = ex.submit(_attempt)
                            path = fut.result(timeout=40)
                        if path:
                            print(f"[video_builder]   {vid_id} [{tag}] ✓")
                            return path
                        print(f"[video_builder]   {vid_id} [{tag}] stream yok")
                    except _cf.TimeoutError:
                        print(f"[video_builder]   {vid_id} [{tag}] timeout (40s)")
                    except Exception as e:
                        print(f"[video_builder]   {vid_id} [{tag}] başarısız: "
                              f"{str(e)[:100]}")
                return None

            def _try_ytdlp_cookies(vid_id: str) -> str | None:
                """yt-dlp + cookies (son çare)."""
                if not cookie_file:
                    return None
                _url = f"https://www.youtube.com/watch?v={vid_id}"
                for _client, _skip in _YTDLP_CLIENTS:
                    tmp = tempfile.NamedTemporaryFile(
                        suffix=".mp4", delete=False, prefix="ytcc_dlp_")
                    tmp.close()
                    _yt_args: dict = {"player_client": _client}
                    if _skip:
                        _yt_args["player_skip"] = _skip
                    dl_opts = {
                        "format": "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
                        "format_sort": ["res:1080", "codec:h264"],
                        "outtmpl": tmp.name,
                        "merge_output_format": "mp4",
                        "max_filesize": 150 * 1024 * 1024,
                        "quiet": True, "no_warnings": True,
                        "logger": _SilentLogger(),
                        "check_formats": False,
                        "no_check_certificate": True,
                        "socket_timeout": 20,      # bağlantı başına 20s
                        "retries": 1,              # tek retry
                        "cookiefile": cookie_file,
                        "extractor_args": {"youtube": _yt_args},
                        **({"proxy": YT_PROXY} if YT_PROXY else {}),
                    }
                    tag = f"yt-dlp/{_client[0]}"
                    print(f"[video_builder] YouTube CC: '{query}' → {vid_id} [{tag}]...")
                    try:
                        with _ytdlp.YoutubeDL(dl_opts) as ydl:
                            ydl.extract_info(_url, download=True)
                    except Exception as e:
                        print(f"[video_builder]   {vid_id} [{tag}] başarısız: "
                              f"{str(e)[:100]}")
                        try:
                            os.unlink(tmp.name)
                        except OSError:
                            pass
                        continue
                    candidate = tmp.name
                    for ext in [".mp4", ".webm", ".mkv"]:
                        alt = tmp.name + ext
                        if os.path.exists(alt) and os.path.getsize(alt) > 10000:
                            candidate = alt
                            break
                    if os.path.exists(candidate) and os.path.getsize(candidate) > 10000:
                        print(f"[video_builder]   {vid_id} [{tag}] ✓")
                        return candidate
                    try:
                        os.unlink(tmp.name)
                    except OSError:
                        pass
                return None

            # ── Ana indirme döngüsü ──
            actual_file = None
            _yt_consecutive_fails = 0
            for cc_video_id in video_ids:
                if _yt_consecutive_fails >= 2:
                    print("[video_builder] YouTube CC: ardarda 2 video başarısız; "
                          "IP muhtemelen engelli.")
                    break

                # Segment bazlı tracking: tam video ID'si yoksa atlamıyoruz
                # (farklı segmentler kullanılabilir — kontrol download sonrası yapılır)
                if f"ytcc_{cc_video_id}_full" in seen_ids:
                    continue

                result = (
                    _try_pytubefix_plain(cc_video_id)
                    or _try_ytdlp_cookies(cc_video_id)
                )

                if result:
                    actual_file = result
                    _yt_consecutive_fails = 0
                    break
                else:
                    _yt_consecutive_fails += 1

            if not actual_file:
                continue

            # Video süresini al
            probe_cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                actual_file,
            ]
            probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=15)
            try:
                video_duration = float(probe_result.stdout.strip())
            except (ValueError, AttributeError):
                video_duration = 30.0

            segment_dur = random.uniform(5.0, 10.0)
            if video_duration <= segment_dur + 1:
                segment_start = 0
                segment_dur = min(segment_dur, video_duration)
            else:
                max_start = max(0, video_duration - segment_dur - 1)
                segment_start = random.uniform(0, max_start)

            segment_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False, prefix="ytcc_seg_")
            segment_file.close()

            cut_cmd = [
                "ffmpeg", "-y",
                "-ss", str(segment_start),
                "-i", actual_file,
                "-t", str(segment_dur),
                "-c", "copy",
                "-loglevel", "error",
                segment_file.name,
            ]
            cut_result = subprocess.run(cut_cmd, timeout=30, capture_output=True)

            try:
                os.unlink(actual_file)
            except OSError:
                pass

            if cut_result.returncode == 0 and os.path.exists(segment_file.name) and os.path.getsize(segment_file.name) > 5000:
                # Segment bazlı ID: aynı videodan farklı segmentler kullanılabilir
                seg_id = f"ytcc_{cc_video_id}_{int(segment_start)}_{int(segment_start + segment_dur)}"
                if seg_id not in seen_ids:
                    seen_ids.add(seg_id)
                    downloaded.append(segment_file.name)
                    print(f"[video_builder] YouTube CC klip {len(downloaded)}/{n}: "
                          f"'{query}' [{segment_start:.1f}s-{segment_start+segment_dur:.1f}s]")
                else:
                    os.unlink(segment_file.name)
            else:
                try:
                    os.unlink(segment_file.name)
                except OSError:
                    pass

        except subprocess.TimeoutExpired:
            print(f"[video_builder] YouTube CC timeout: '{query}'")
        except Exception as e:
            print(f"[video_builder] YouTube CC hata ({query}): {e}")

    return downloaded


# DVIDS branch tespiti: keyword → askeri kol eşleşmesi
_DVIDS_BRANCH_MAP = {
    "Navy":         ["navy", "ship", "carrier", "destroyer", "submarine", "fleet", "frigate",
                     "cruiser", "amphibious", "naval", "seals", "seal", "maritime"],
    "Air Force":    ["air force", "fighter jet", "f-35", "f-22", "f-16", "f-15", "b-2", "b-21",
                     "stealth", "bomber", "aircraft", "airbase", "pilot", "cockpit", "drone",
                     "uav", "reaper", "predator", "refueling"],
    "Army":         ["army", "tank", "abrams", "infantry", "soldier", "troops", "artillery",
                     "howitzer", "ranger", "green beret", "airborne", "convoy", "combat",
                     "armored", "bradley", "stryker", "humvee"],
    "Marine Corps": ["marine", "marines", "usmc", "amphibious assault", "expeditionary"],
    "Space Force":  ["space force", "satellite", "gps", "orbital", "space"],
}

# DVIDS topic-aware query şablonları: kategori → spesifik DVIDS arama terimleri
_DVIDS_TOPIC_QUERIES = {
    "jets":          ["fighter aircraft operations", "close air support", "combat air patrol",
                      "aerial refueling", "carrier launch recovery", "air superiority"],
    "helicopter":    ["rotary wing operations", "helicopter assault", "medevac operations",
                      "attack helicopter gunnery", "helo fast rope", "air assault"],
    "tanks":         ["combined arms exercise", "armor operations", "tank gunnery",
                      "mechanized infantry", "armored brigade combat team", "live fire armor"],
    "drone":         ["unmanned aerial system", "UAS operations", "surveillance drone",
                      "remotely piloted aircraft", "drone exercise"],
    "navy":          ["fleet exercise", "carrier strike group", "amphibious operations",
                      "naval gunfire support", "submarine operations", "surface warfare"],
    "special_forces":["special operations", "joint special operations", "counterterrorism exercise",
                      "unconventional warfare", "direct action", "personnel recovery"],
    "missiles":      ["missile defense", "patriot battery", "missile exercise",
                      "air defense artillery", "ballistic missile defense"],
    "explosions":    ["live fire exercise", "demolition operations", "air strike",
                      "close air support exercise", "artillery live fire", "bomb drop"],
    "training":      ["combat training", "joint exercise", "multinational exercise",
                      "readiness exercise", "military training"],
    "misc":          ["military readiness", "joint operation", "deployment exercise",
                      "expeditionary operations", "force projection"],
}


def _keyword_hits(text: str, keywords: list[str]) -> int:
    """Metnin içinde kaç keyword geçtiğini döndürür. Relevance sıralaması için kullanılır."""
    if not text or not keywords:
        return 0
    text_l = text.lower()
    return sum(1 for kw in keywords if kw.lower() in text_l)


# Tören / brifing / röportaj içeriklerini dışla — video montajına görsel olarak uygunsuz
_NON_ACTION_TERMS = {
    # Tören / protokol
    "briefing", "press briefing", "press conference", "interview",
    "ceremony", "change of command", "retirement", "promotion ceremony",
    "award ceremony", "ribbon cutting", "speech", "remarks", "town hall",
    "graduation", "commencement", "visit", "tour", "meet and greet",
    "signing ceremony", "memorandum", "commemoration", "memorial service",
    "wreath laying", "flag ceremony", "press event", "media day",
    "roundtable", "symposium", "summit", "welcome ceremony", "farewell",
    "promotion", "swearing", "oath of office", "congressional",
    "senator", "secretary of defense", "chief of staff", "pentagon",
    "news conference", "media roundtable", "official visit", "dignitary",
    # Haber / yayın — lower-thirds ve chyron içerir
    "news report", "news story", "broadcast", "reporter", "anchor",
    "correspondent", "newscast", "on camera", "on-camera", "stand-up",
    "package", "live report", "public affairs", "pa product",
    "media embed", "embedded media", "press pool",
}


def _is_action_footage(title: str) -> bool:
    """True dönerse klip aksiyon/eğitim görüntüsüdür. False ise tören/röportaj/brifing."""
    title_l = title.lower()
    return not any(term in title_l for term in _NON_ACTION_TERMS)


def _detect_dvids_branch(keywords: list) -> str | None:
    """Keyword listesinden en uygun DVIDS askeri kolunu tespit eder."""
    kw_text = " ".join(keywords).lower()
    branch_scores = {}
    for branch, hints in _DVIDS_BRANCH_MAP.items():
        score = sum(1 for h in hints if h in kw_text)
        if score > 0:
            branch_scores[branch] = score
    if not branch_scores:
        return None
    return max(branch_scores, key=branch_scores.get)


def _build_dvids_queries(keywords: list) -> list[str]:
    """Script keyword'lerinden öncelikli DVIDS sorgu listesi üretir."""
    queries = []

    # 1) Spesifik: keyword'leri birleştir (en alakalı)
    if len(keywords) >= 2:
        queries.append(" ".join(keywords[:2]))
    if len(keywords) >= 3:
        queries.append(" ".join(keywords[:3]))

    # 2) Kategori bazlı topic query'ler
    category = _pick_yt_category(keywords)
    topic_queries = list(_DVIDS_TOPIC_QUERIES.get(category, _DVIDS_TOPIC_QUERIES["misc"]))
    random.shuffle(topic_queries)
    queries.extend(topic_queries[:4])

    # 3) Tek tek keyword'ler
    for kw in keywords[:5]:
        if kw not in queries:
            queries.append(kw)

    # 4) Kategori bazlı action-only fallback — tören/brifing değil, aksiyon içerikleri
    # _DVIDS_TOPIC_QUERIES'den seçilen topic_queries zaten bunu kapsar (yukarıda eklendi)
    # Genel "military deployment / force readiness" gibi sorgular tören döndürebilirdi — kaldırıldı

    return queries


def _fetch_dvids_clips(keywords: list, api_key: str, n: int, seen_ids: set) -> list:
    """DVIDS'ten (ABD Savunma Bakanlığı) gerçek askeri video indirir. Public Domain.

    İyileştirmeler:
    - sort=date (en yeni önce)
    - date_from = 3 yıl öncesi (eski arşiv videoları hariç)
    - branch otomatik tespiti (Navy / Army / Air Force vb.)
    - Konu-bağlı akıllı query üretimi
    - max_results 25 → 50
    """
    if not shutil.which("ffmpeg"):
        print("[video_builder] ffmpeg bulunamadı, DVIDS atlanıyor.")
        return []

    date_from = (datetime.now() - timedelta(days=3 * 365)).strftime("%Y-%m-%d")
    queries = _build_dvids_queries(keywords)
    downloaded = []

    for query in queries:
        if len(downloaded) >= n:
            break

        params = {
            "q": query,
            "max_results": 50,
            "type": "video",
            "sort": "date",
            "date_from": date_from,
            "api_key": api_key,
        }

        try:
            resp = requests.get(DVIDS_API, params=params, timeout=20)
            resp.raise_for_status()
            results = resp.json().get("results", [])

            # Keyword relevance'a göre sırala: en alakalı önce indirilir
            results.sort(
                key=lambda a: _keyword_hits(a.get("title", ""), keywords),
                reverse=True,
            )
            for asset in results:
                if len(downloaded) >= n:
                    break
                if asset.get("type") != "video":
                    continue
                vid = f"dvids_{asset.get('id')}"
                if vid in seen_ids:
                    continue
                seen_ids.add(vid)
                hls_url = asset.get("hls_url")
                if not hls_url:
                    continue

                title = asset.get("title", "")
                # Röportaj / tören / brifing içeriklerini atla
                if not _is_action_footage(title):
                    print(f"[video_builder] DVIDS atlandı (tören/brifing): '{title[:60]}'")
                    continue

                title = title[:60]
                try:
                    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False, prefix="dvids_")
                    tmp.close()
                    cmd = [
                        "ffmpeg", "-y",
                        "-ss", "8",           # ilk 8sn atla (DVIDS slate + açılış lower-third)
                        "-i", hls_url,
                        # Alt %12'yi kes (lower-thirds / isim-rütbe barları), orijinal boyuta scale et
                        "-vf", "crop=iw:trunc(ih*0.88/2)*2:0:0,scale=iw:ih",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                        "-an",               # ses yok (B-roll)
                        "-t", "30",           # max 30 saniye
                        "-loglevel", "error",
                        tmp.name,
                    ]
                    result = subprocess.run(cmd, timeout=60, capture_output=True)
                    if result.returncode == 0 and os.path.getsize(tmp.name) > 10000:
                        downloaded.append(tmp.name)
                        print(f"[video_builder] DVIDS klip {len(downloaded)}/{n}: '{title}'")
                    else:
                        os.unlink(tmp.name)
                except (subprocess.TimeoutExpired, Exception) as e:
                    print(f"[video_builder] DVIDS indirme hatası: {e}")
                    try:
                        os.unlink(tmp.name)
                    except OSError:
                        pass
        except Exception as e:
            print(f"[video_builder] DVIDS arama hatası ({query!r}): {e}")

    return downloaded


# Archive.org askeri koleksiyonları — yeniden eskiye öncelik sırası
_ARCHIVE_MILITARY_COLLECTIONS = [
    "defense_visual_information",  # DVIDS arşivi — en güncel, HD
    "usnavyfilms",                 # ABD Deniz Kuvvetleri
    "usarmyfilms",                 # ABD Ordusu
    "usmcarchive",                 # ABD Deniz Piyadesi
    "usmilitaryfilms",             # Genel ABD askeri
    "usgovfilms",                  # Genel ABD hükümeti
]

# Keyword → Archive koleksiyon tercihi
_ARCHIVE_BRANCH_COLLECTIONS = {
    "navy":    ["usnavyfilms", "defense_visual_information"],
    "army":    ["usarmyfilms", "defense_visual_information"],
    "marine":  ["usmcarchive", "defense_visual_information"],
    "air":     ["defense_visual_information", "usgovfilms"],
    "default": _ARCHIVE_MILITARY_COLLECTIONS,
}


def _pick_archive_collections(keywords: list) -> list[str]:
    """Keyword'lere göre öncelikli Archive koleksiyon listesi döndürür."""
    kw_text = " ".join(keywords).lower()
    if any(w in kw_text for w in ["navy", "naval", "ship", "carrier", "submarine", "seal"]):
        return _ARCHIVE_BRANCH_COLLECTIONS["navy"]
    if any(w in kw_text for w in ["marine", "usmc", "amphibious"]):
        return _ARCHIVE_BRANCH_COLLECTIONS["marine"]
    if any(w in kw_text for w in ["army", "tank", "infantry", "soldier", "ranger"]):
        return _ARCHIVE_BRANCH_COLLECTIONS["army"]
    if any(w in kw_text for w in ["jet", "aircraft", "bomber", "pilot", "air force"]):
        return _ARCHIVE_BRANCH_COLLECTIONS["air"]
    return _ARCHIVE_BRANCH_COLLECTIONS["default"]


def _score_archive_file(name: str, size: int) -> int:
    """MP4 dosyasını kalite/güncellik puanı ile değerlendirir. Yüksek = tercih edilir."""
    score = 0
    name_l = name.lower()
    # HD indikatörleri
    if "1080" in name_l:
        score += 40
    if "720" in name_l:
        score += 25
    if "_hd" in name_l or "-hd" in name_l or "hd." in name_l:
        score += 20
    if "h264" in name_l or "x264" in name_l or "h.264" in name_l:
        score += 10
    # Dosya büyüklüğü: her 10MB için +5 puan (max 50 puan)
    score += min(50, (size // (10 * 1024 * 1024)) * 5)
    return score


def _fetch_archive_clips(keywords: list, n: int, seen_ids: set) -> list:
    """Internet Archive'dan Public Domain askeri video indirir. API key gereksiz.

    İyileştirmeler:
    - sort=publicdate desc (en yeni önce)
    - date:[2010-01-01 TO *] filtresi (eski çekim görüntüleri dışla)
    - 6 askeri koleksiyona genişletildi
    - HD dosya tercihi (1080 > 720 > hd > büyük boyut)
    - Minimum 3MB dosya boyutu
    """
    downloaded = []

    # Sorgu listesi
    queries = []
    if len(keywords) >= 2:
        queries.append(" ".join(keywords[:2]))
    if len(keywords) >= 3:
        queries.append(" ".join(keywords[:3]))
    for kw in keywords[:4]:
        if kw not in queries:
            queries.append(kw)

    # Generic fallback sorgular kaldırıldı: tören/brifing döndürebiliyordu
    # Archive koleksiyonları zaten askeri içeriğe odaklı

    headers = {"User-Agent": "WarShorts/1.0 (video asset downloader)"}
    collections = _pick_archive_collections(keywords)
    collection_q = " OR ".join(f"collection:{c}" for c in collections)

    for query in queries:
        if len(downloaded) >= n:
            break

        search_q = (
            f"({query}) AND mediatype:movies "
            f"AND ({collection_q}) "
            f"AND date:[2010-01-01 TO *]"   # 2010 öncesi dışla
        )
        params = {
            "q": search_q,
            "output": "json",
            "rows": 20,
            "page": 1,
            "sort[]": "publicdate desc",    # En yeni önce
            "fl[]": ["identifier", "title", "publicdate"],
        }
        try:
            resp = requests.get(ARCHIVE_API, params=params, timeout=20, headers=headers)
            resp.raise_for_status()
            docs = resp.json().get("response", {}).get("docs", [])
            # Relevance'a göre sırala (keyword match > 0 olanlar önce)
            docs.sort(
                key=lambda d: _keyword_hits(
                    (d.get("title") if isinstance(d.get("title"), str)
                     else " ".join(d.get("title") or [])),
                    keywords,
                ),
                reverse=True,
            )

            for doc in docs:
                if len(downloaded) >= n:
                    break
                identifier = doc.get("identifier")
                if not identifier:
                    continue

                # Metadata çekmeden önce title ile hızlı relevance + aksiyon kontrolü
                raw_title = doc.get("title") or ""
                title_str = raw_title if isinstance(raw_title, str) else " ".join(raw_title)
                if not _is_action_footage(title_str):
                    continue  # Tören/brifing/röportaj — atla
                if _keyword_hits(title_str, keywords) == 0 and len(downloaded) > 0:
                    # Zaten yeterli relevantlı klip varsa alakasızları atla
                    continue

                vid = f"archive_{identifier}"
                if vid in seen_ids:
                    continue
                seen_ids.add(vid)

                try:
                    meta_url = f"https://archive.org/metadata/{identifier}"
                    meta_resp = requests.get(meta_url, timeout=15, headers=headers)
                    meta_resp.raise_for_status()
                    files = meta_resp.json().get("files", [])

                    # MP4 adaylarını topla ve kalite puanına göre sırala
                    candidates = []
                    for f in files:
                        name = f.get("name", "")
                        size = int(f.get("size", 0) or 0)
                        fmt = f.get("format", "").lower()
                        is_mp4 = name.lower().endswith(".mp4") or "mpeg4" in fmt or "mp4" in fmt
                        # Min 3MB, max 150MB
                        if is_mp4 and 3 * 1024 * 1024 <= size <= 150 * 1024 * 1024:
                            candidates.append((name, size, _score_archive_file(name, size)))

                    if not candidates:
                        continue

                    # En yüksek puanlı dosyayı seç
                    candidates.sort(key=lambda x: x[2], reverse=True)
                    best_name, best_size, best_score = candidates[0]

                    dl_url = f"https://archive.org/download/{identifier}/{best_name}"
                    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False, prefix="archive_")
                    r = requests.get(dl_url, stream=True, timeout=90, headers=headers)
                    r.raise_for_status()
                    for chunk in r.iter_content(chunk_size=65536):
                        tmp.write(chunk)
                    tmp.close()

                    pub_date = doc.get("publicdate", "?")[:10]
                    if os.path.getsize(tmp.name) > 3 * 1024 * 1024:
                        # Alt %12'yi kes (lower-thirds / haber barları), orijinal boyuta scale et
                        if shutil.which("ffmpeg"):
                            cropped = tempfile.NamedTemporaryFile(
                                suffix=".mp4", delete=False, prefix="archive_crop_"
                            )
                            cropped.close()
                            subprocess.run(
                                [
                                    "ffmpeg", "-y", "-i", tmp.name,
                                    "-vf", "crop=iw:trunc(ih*0.88/2)*2:0:0,scale=iw:ih",
                                    "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                                    "-an", "-loglevel", "error", cropped.name,
                                ],
                                timeout=120, capture_output=True,
                            )
                            os.unlink(tmp.name)
                            if os.path.exists(cropped.name) and os.path.getsize(cropped.name) > 3 * 1024 * 1024:
                                downloaded.append(cropped.name)
                                print(f"[video_builder] Archive klip {len(downloaded)}/{n}: "
                                      f"{identifier} ({pub_date}, score:{best_score})")
                            else:
                                try:
                                    os.unlink(cropped.name)
                                except OSError:
                                    pass
                        else:
                            downloaded.append(tmp.name)
                            print(f"[video_builder] Archive klip {len(downloaded)}/{n}: "
                                  f"{identifier} ({pub_date}, score:{best_score})")
                    else:
                        os.unlink(tmp.name)
                except Exception as e:
                    print(f"[video_builder] Archive indirme hatası ({identifier}): {e}")
        except Exception as e:
            print(f"[video_builder] Archive arama hatası ({query!r}): {e}")

    return downloaded


_STOCK_STOP = frozenset({
    "footage", "video", "clip", "operations", "scene",
    "2024", "2025", "2026", "2027", "latest", "breaking",
})


def _to_stock_query(kw: str, max_words: int = 3) -> str:
    """Convert a specific CC/military query to a shorter stock-API-friendly query.

    'IDF Merkava tank Gaza ground operation footage' → 'idf merkava tank'
    'Iron Dome intercept Hamas rocket footage'       → 'iron dome intercept'
    """
    import re as _re
    words = _re.split(r"[^a-zA-Z0-9]+", kw.lower())
    filtered = [w for w in words if len(w) > 1 and w not in _STOCK_STOP]
    return " ".join(filtered[:max_words]).strip()


def _stock_queries(keywords: list, n: int = 4) -> list[str]:
    """Return simplified, deduplicated queries for Pexels/Pixabay."""
    seen: set[str] = set()
    result: list[str] = []
    for kw in keywords:
        q = _to_stock_query(kw)
        if q and q not in seen:
            seen.add(q)
            result.append(q)
        if len(result) >= n:
            break
    return result or (keywords[:n] if keywords else [])


def _fetch_pexels_clips(keywords: list, n: int, seen_ids: set) -> list[str]:
    """Pexels'ten ücretsiz stock video indirir."""
    api_key = os.environ.get("PEXELS_API_KEY", "")
    if not api_key:
        return []
    downloaded = []
    queries = _stock_queries(keywords, n=6)
    if not queries:
        return []
    random.shuffle(queries)

    for query in queries:
        if len(downloaded) >= n:
            break
        try:
            resp = requests.get(
                "https://api.pexels.com/videos/search",
                params={"query": query, "per_page": 15, "orientation": "portrait"},
                headers={"Authorization": api_key},
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            for video in resp.json().get("videos", []):
                if len(downloaded) >= n:
                    break
                vid = f"pexels_{video['id']}"
                if vid in seen_ids:
                    continue
                seen_ids.add(vid)
                # En iyi mp4 dosyasını bul (720p+)
                best_file = None
                for vf in video.get("video_files", []):
                    if vf.get("file_type") == "video/mp4" and (vf.get("height", 0) >= 720 or not best_file):
                        best_file = vf
                if not best_file:
                    continue
                try:
                    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False, prefix="pexels_")
                    tmp.close()
                    r = requests.get(best_file["link"], timeout=60, stream=True)
                    r.raise_for_status()
                    with open(tmp.name, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 256):
                            f.write(chunk)
                    if os.path.getsize(tmp.name) > 10000:
                        downloaded.append(tmp.name)
                        print(f"[video_builder] Pexels klip {len(downloaded)}/{n} (id:{vid})")
                    else:
                        os.unlink(tmp.name)
                except Exception:
                    try:
                        os.unlink(tmp.name)
                    except OSError:
                        pass
        except Exception as e:
            print(f"[video_builder] Pexels arama hatası ({query}): {e}")
    return downloaded


def _fetch_pixabay_clips(keywords: list, n: int, seen_ids: set) -> list[str]:
    """Pixabay'dan ücretsiz stock video indirir."""
    api_key = os.environ.get("PIXABAY_API_KEY", "")
    if not api_key:
        return []
    downloaded = []
    queries = _stock_queries(keywords, n=6)
    if not queries:
        return []
    random.shuffle(queries)

    for query in queries:
        if len(downloaded) >= n:
            break
        try:
            resp = requests.get(
                "https://pixabay.com/api/videos/",
                params={"key": api_key, "q": query, "per_page": 15},
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            for hit in resp.json().get("hits", []):
                if len(downloaded) >= n:
                    break
                vid = f"pixabay_{hit['id']}"
                if vid in seen_ids:
                    continue
                seen_ids.add(vid)
                # medium veya large video URL
                video_url = None
                for size in ["medium", "large", "small"]:
                    vdata = hit.get("videos", {}).get(size, {})
                    if vdata.get("url"):
                        video_url = vdata["url"]
                        break
                if not video_url:
                    continue
                try:
                    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False, prefix="pixabay_")
                    tmp.close()
                    r = requests.get(video_url, timeout=60, stream=True)
                    r.raise_for_status()
                    with open(tmp.name, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 256):
                            f.write(chunk)
                    if os.path.getsize(tmp.name) > 10000:
                        downloaded.append(tmp.name)
                        print(f"[video_builder] Pixabay klip {len(downloaded)}/{n} (id:{vid})")
                    else:
                        os.unlink(tmp.name)
                except Exception:
                    try:
                        os.unlink(tmp.name)
                    except OSError:
                        pass
        except Exception as e:
            print(f"[video_builder] Pixabay arama hatası ({query}): {e}")
    return downloaded


def _fetch_wikimedia_clips(keywords: list, n: int, seen_ids: set) -> list[str]:
    """Wikimedia Commons'tan video indirir. Klip süresi 3sn ile sınırlı."""
    downloaded = []
    # Sadece gerçek keyword'ler — generic military fallback kaldırıldı
    queries = keywords[:4]
    if not queries:
        return []
    random.shuffle(queries)

    for query in queries:
        if len(downloaded) >= n:
            break
        try:
            params = {
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": f"{query} filetype:video",
                "gsrlimit": 10,
                "prop": "imageinfo",
                "iiprop": "url|size|mime",
                "iiurlwidth": 1280,
            }
            resp = requests.get("https://commons.wikimedia.org/w/api.php", params=params, timeout=15)
            if resp.status_code != 200:
                continue
            pages = resp.json().get("query", {}).get("pages", {})
            for page_id, page in pages.items():
                if len(downloaded) >= n:
                    break
                imageinfo = page.get("imageinfo", [{}])[0]
                mime = imageinfo.get("mime", "")
                if "video" not in mime:
                    continue
                url = imageinfo.get("url", "")
                if not url:
                    continue
                vid = f"wikimedia_{page_id}"
                if vid in seen_ids:
                    continue
                seen_ids.add(vid)
                try:
                    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False, prefix="wiki_full_")
                    tmp.close()
                    r = requests.get(url, timeout=60, stream=True, headers={"User-Agent": "WarShorts/1.0"})
                    r.raise_for_status()
                    with open(tmp.name, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 256):
                            f.write(chunk)
                    if os.path.getsize(tmp.name) < 10000:
                        os.unlink(tmp.name)
                        continue
                    # Wikimedia kliplerini 3sn ile sınırla
                    if shutil.which("ffmpeg"):
                        seg = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False, prefix="wiki_seg_")
                        seg.close()
                        # Rastgele başlangıç noktası için süre al
                        probe = subprocess.run(
                            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=noprint_wrappers=1:nokey=1", tmp.name],
                            capture_output=True, text=True, timeout=10,
                        )
                        try:
                            dur = float(probe.stdout.strip())
                        except Exception:
                            dur = 10.0
                        start = random.uniform(0, max(0, dur - 3.0))
                        subprocess.run(
                            ["ffmpeg", "-y", "-ss", str(start), "-i", tmp.name,
                             "-t", "3", "-c", "copy", "-loglevel", "error", seg.name],
                            timeout=15, capture_output=True,
                        )
                        os.unlink(tmp.name)
                        if os.path.exists(seg.name) and os.path.getsize(seg.name) > 5000:
                            downloaded.append(seg.name)
                            print(f"[video_builder] Wikimedia klip {len(downloaded)}/{n} (3sn, id:{vid})")
                        else:
                            try:
                                os.unlink(seg.name)
                            except OSError:
                                pass
                    else:
                        downloaded.append(tmp.name)
                        print(f"[video_builder] Wikimedia klip {len(downloaded)}/{n} (id:{vid})")
                except Exception:
                    try:
                        os.unlink(tmp.name)
                    except OSError:
                        pass
        except Exception as e:
            print(f"[video_builder] Wikimedia arama hatası ({query}): {e}")
    return downloaded


def _fetch_wikimedia_images(keywords: list, n: int, seen_ids: set) -> list[str]:
    """Wikimedia Commons'tan resim (JPG/PNG) indirir."""
    downloaded = []
    # Sadece gerçek keyword'ler — generic military fallback kaldırıldı
    queries = keywords[:4]
    if not queries:
        return []
    random.shuffle(queries)

    for query in queries:
        if len(downloaded) >= n:
            break
        try:
            params = {
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": f"{query} filetype:bitmap",
                "gsrlimit": 15,
                "prop": "imageinfo",
                "iiprop": "url|size|mime",
                "iiurlwidth": 1280,
            }
            resp = requests.get("https://commons.wikimedia.org/w/api.php", params=params, timeout=15)
            if resp.status_code != 200:
                continue
            pages = resp.json().get("query", {}).get("pages", {})
            for page_id, page in pages.items():
                if len(downloaded) >= n:
                    break
                imageinfo = page.get("imageinfo", [{}])[0]
                mime = imageinfo.get("mime", "")
                if not any(t in mime for t in ("image/jpeg", "image/png", "image/webp")):
                    continue
                url = imageinfo.get("url", "")
                if not url:
                    continue
                img_id = f"wiki_img_{page_id}"
                if img_id in seen_ids:
                    continue
                seen_ids.add(img_id)
                ext = ".jpg" if "jpeg" in mime else ".png"
                try:
                    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False, prefix="wiki_img_")
                    tmp.close()
                    r = requests.get(url, timeout=30, stream=True, headers={"User-Agent": "WarShorts/1.0"})
                    r.raise_for_status()
                    with open(tmp.name, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 256):
                            f.write(chunk)
                    if os.path.getsize(tmp.name) > 5000:
                        downloaded.append(tmp.name)
                        print(f"[video_builder] Wikimedia resim {len(downloaded)}/{n} (id:{img_id})")
                    else:
                        os.unlink(tmp.name)
                except Exception:
                    try:
                        os.unlink(tmp.name)
                    except OSError:
                        pass
        except Exception as e:
            print(f"[video_builder] Wikimedia resim arama hatası ({query}): {e}")
    return downloaded


def _fetch_pexels_images(keywords: list, n: int, seen_ids: set) -> list[str]:
    """Pexels'ten ücretsiz fotoğraf indirir."""
    api_key = os.environ.get("PEXELS_API_KEY", "")
    if not api_key:
        return []
    downloaded = []
    # Sadece gerçek keyword'ler — generic fallback sorgular kaldırıldı
    queries = keywords[:4]
    if not queries:
        return []
    random.shuffle(queries)

    for query in queries:
        if len(downloaded) >= n:
            break
        try:
            resp = requests.get(
                "https://api.pexels.com/v1/search",
                params={"query": query, "per_page": 15, "orientation": "portrait"},
                headers={"Authorization": api_key},
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            for photo in resp.json().get("photos", []):
                if len(downloaded) >= n:
                    break
                img_id = f"pexels_img_{photo['id']}"
                if img_id in seen_ids:
                    continue
                seen_ids.add(img_id)
                url = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large", "")
                if not url:
                    continue
                try:
                    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False, prefix="pexels_img_")
                    tmp.close()
                    r = requests.get(url, timeout=30, stream=True)
                    r.raise_for_status()
                    with open(tmp.name, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 256):
                            f.write(chunk)
                    if os.path.getsize(tmp.name) > 5000:
                        downloaded.append(tmp.name)
                        print(f"[video_builder] Pexels resim {len(downloaded)}/{n} (id:{img_id})")
                    else:
                        os.unlink(tmp.name)
                except Exception:
                    try:
                        os.unlink(tmp.name)
                    except OSError:
                        pass
        except Exception as e:
            print(f"[video_builder] Pexels resim arama hatası ({query}): {e}")
    return downloaded


def _fetch_aljazeera_images(keywords: list, n: int, seen_ids: set) -> list[str]:
    """Al Jazeera Creative Commons'tan resim indirir."""
    downloaded = []
    # Sadece gerçek keyword'ler — generic fallback sorgular kaldırıldı (alakasız resim çekiyordu)
    queries = keywords[:3]
    if not queries:
        return []

    for query in queries:
        if len(downloaded) >= n:
            break
        try:
            # Al Jazeera CC arama API'si
            resp = requests.get(
                "https://creativecommons.aljazeera.net/search",
                params={"q": query, "limit": 20, "offset": 0},
                headers={
                    "User-Agent": "WarShorts/1.0",
                    "Accept": "application/json, text/html",
                },
                timeout=15,
            )
            if resp.status_code != 200:
                continue

            # JSON yanıt denemesi
            try:
                data = resp.json()
                results = data.get("results") or data.get("images") or data.get("hits") or []
                if isinstance(results, dict):
                    results = results.get("hits") or []
            except Exception:
                results = []

            # HTML yanıt — og:image ve data-src URL'lerini regex ile çek
            if not results:
                import re as _re
                urls_found = _re.findall(
                    r'https://[^\s"\'<>]+\.(?:jpg|jpeg|png|webp)[^\s"\'<>]*',
                    resp.text,
                )
                # Sadece Al Jazeera CDN URL'leri
                urls_found = [u for u in urls_found if "aljazeera" in u or "ajenglish" in u]
                for url in urls_found:
                    if len(downloaded) >= n:
                        break
                    img_id = f"aljazeera_{hash(url)}"
                    if img_id in seen_ids:
                        continue
                    seen_ids.add(img_id)
                    try:
                        tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False, prefix="aje_img_")
                        tmp.close()
                        r = requests.get(url, timeout=30, stream=True,
                                         headers={"User-Agent": "WarShorts/1.0"})
                        r.raise_for_status()
                        with open(tmp.name, "wb") as f:
                            for chunk in r.iter_content(chunk_size=1024 * 256):
                                f.write(chunk)
                        if os.path.getsize(tmp.name) > 5000:
                            downloaded.append(tmp.name)
                            print(f"[video_builder] Al Jazeera resim {len(downloaded)}/{n}")
                        else:
                            os.unlink(tmp.name)
                    except Exception:
                        try:
                            os.unlink(tmp.name)
                        except OSError:
                            pass
                continue

            for item in results:
                if len(downloaded) >= n:
                    break
                url = (item.get("url") or item.get("image_url") or
                       item.get("src") or item.get("thumbnail") or "")
                if not url:
                    continue
                # Title/description relevance kontrolü — alakasız haberleri filtrele
                item_text = " ".join(filter(None, [
                    item.get("title") or "",
                    item.get("description") or "",
                    item.get("caption") or "",
                ]))
                if item_text and _keyword_hits(item_text, keywords) == 0:
                    continue
                img_id = f"aljazeera_{item.get('id', hash(url))}"
                if img_id in seen_ids:
                    continue
                seen_ids.add(img_id)
                try:
                    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False, prefix="aje_img_")
                    tmp.close()
                    r = requests.get(url, timeout=30, stream=True,
                                     headers={"User-Agent": "WarShorts/1.0"})
                    r.raise_for_status()
                    with open(tmp.name, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 256):
                            f.write(chunk)
                    if os.path.getsize(tmp.name) > 5000:
                        downloaded.append(tmp.name)
                        print(f"[video_builder] Al Jazeera resim {len(downloaded)}/{n} (id:{img_id})")
                    else:
                        os.unlink(tmp.name)
                except Exception:
                    try:
                        os.unlink(tmp.name)
                    except OSError:
                        pass
        except Exception as e:
            print(f"[video_builder] Al Jazeera resim arama hatası ({query}): {e}")
    return downloaded


def _fetch_unsplash_images(keywords: list, n: int, seen_ids: set) -> list[str]:
    """Unsplash'tan ücretsiz resim indirir (UNSPLASH_ACCESS_KEY gerekli)."""
    access_key = os.environ.get("UNSPLASH_ACCESS_KEY", "")
    if not access_key:
        print("[video_builder] UNSPLASH_ACCESS_KEY bulunamadı, Unsplash atlanıyor.")
        return []
    downloaded = []
    # Sadece gerçek keyword'ler — generic fallback sorgular kaldırıldı
    queries = keywords[:4]
    if not queries:
        return []
    random.shuffle(queries)

    for query in queries:
        if len(downloaded) >= n:
            break
        try:
            resp = requests.get(
                "https://api.unsplash.com/search/photos",
                params={"query": query, "per_page": 15, "orientation": "portrait"},
                headers={"Authorization": f"Client-ID {access_key}"},
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            for photo in resp.json().get("results", []):
                if len(downloaded) >= n:
                    break
                img_id = f"unsplash_{photo['id']}"
                if img_id in seen_ids:
                    continue
                seen_ids.add(img_id)
                # En yüksek çözünürlüklü portrait URL
                url = photo.get("urls", {}).get("regular") or photo.get("urls", {}).get("full", "")
                if not url:
                    continue
                try:
                    tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False, prefix="unsplash_img_")
                    tmp.close()
                    r = requests.get(url, timeout=30, stream=True)
                    r.raise_for_status()
                    with open(tmp.name, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 256):
                            f.write(chunk)
                    if os.path.getsize(tmp.name) > 5000:
                        downloaded.append(tmp.name)
                        print(f"[video_builder] Unsplash resim {len(downloaded)}/{n} (id:{img_id})")
                    else:
                        os.unlink(tmp.name)
                except Exception:
                    try:
                        os.unlink(tmp.name)
                    except OSError:
                        pass
        except Exception as e:
            print(f"[video_builder] Unsplash resim arama hatası ({query}): {e}")
    return downloaded


def _fetch_images(keywords: list, seen_ids: set | None = None) -> list[str]:
    """Keyword'lere göre alakalı resimler indirir.

    Sadece Wikimedia Commons — keyword araması, lisanslı, metin/logo içermez.
    seen_ids paylaşılırsa aynı resim farklı sahneler için iki kez indirilmez.
    """
    if seen_ids is None:
        seen_ids = set()
    images: list[str] = []
    target = 5  # Sahne başına max 5 (3'ü kullanılacak)

    try:
        wiki_imgs = _fetch_wikimedia_images(keywords, target, seen_ids)
        images.extend(wiki_imgs)
        if wiki_imgs:
            print(f"[video_builder] Wikimedia resim: {len(wiki_imgs)}")
    except Exception as e:
        print(f"[video_builder] Wikimedia resim hatası: {e}")

    return images


SEEN_IDS_FILE = os.path.join("output", "seen_clip_ids.json")


_SEEN_IDS_WINDOW_DAYS = 60  # Bu kadar günden eski ID'ler tekrar kullanılabilir


def _load_seen_ids() -> set:
    """Kullanılan klip ID'lerini yükler; 60 günden eski kayıtları filtreler."""
    try:
        with open(SEEN_IDS_FILE, "r") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return set()

    # Eski format: liste → dict'e çevir (tarihsiz kayıtlar bugünden itibaren sayılır)
    if isinstance(data, list):
        today = date.today().isoformat()
        data = {k: today for k in data}

    cutoff = (date.today() - timedelta(days=_SEEN_IDS_WINDOW_DAYS)).isoformat()
    return {k for k, v in data.items() if v >= cutoff}


def _save_seen_ids(seen_ids: set, existing_data: dict | None = None) -> None:
    """Kullanılan klip ID'lerini tarih damgasıyla kaydeder."""
    os.makedirs(os.path.dirname(SEEN_IDS_FILE), exist_ok=True)
    try:
        with open(SEEN_IDS_FILE, "r") as f:
            on_disk = json.load(f)
            if isinstance(on_disk, list):
                on_disk = {k: date.today().isoformat() for k in on_disk}
    except (FileNotFoundError, json.JSONDecodeError):
        on_disk = {}

    today = date.today().isoformat()
    for k in seen_ids:
        if k not in on_disk:
            on_disk[k] = today

    with open(SEEN_IDS_FILE, "w") as f:
        json.dump(on_disk, f)


def _fetch_clips(keywords: list, n: int = 10, seen_ids: set | None = None, scene_index: int = 0) -> list[str]:
    """
    YouTube CC + DVIDS + Pexels + Pixabay + Wikimedia + Archive'dan video klip indirir.
    Paralel fetch: YouTube CC ve Pexels/Pixabay aynı anda çalışır.
    scene_index: Sahne 0=hook(YouTube+DVIDS önce), 1=mid(Pexels önce), 2=son(Archive dahil)
    Returns: list of file paths.
    """
    import concurrent.futures as _cf_fetch

    dvids_key = os.environ.get("DVIDS_API_KEY")
    pexels_key = os.environ.get("PEXELS_API_KEY")
    pixabay_key = os.environ.get("PIXABAY_API_KEY")
    if seen_ids is None:
        seen_ids = _load_seen_ids()
    video_paths = []

    def _safe(fn, *args):
        try:
            return fn(*args) or []
        except Exception as e:
            print(f"[video_builder] {fn.__name__} hatası: {e}")
            return []

    # ─── Paralel: YouTube CC + Pexels aynı anda ────────────────────────────────
    with _cf_fetch.ThreadPoolExecutor(max_workers=2) as ex:
        yt_fut = ex.submit(_safe, _fetch_youtube_cc_clips, keywords, n, seen_ids)
        if pexels_key and scene_index >= 1:
            # Orta ve son sahneler: Pexels paralelde çalışsın
            px_fut = ex.submit(_safe, _fetch_pexels_clips, keywords, n, seen_ids)
        else:
            px_fut = None

        yt_clips = yt_fut.result()
        px_clips = px_fut.result() if px_fut else []

    if scene_index == 0:
        # Hook sahnesi: gerçek haber görüntüsü önce
        video_paths.extend(yt_clips)
        if len(video_paths) < n and dvids_key:
            video_paths.extend(_safe(_fetch_dvids_clips, keywords, dvids_key, n - len(video_paths), seen_ids))
        if len(video_paths) < n and pexels_key:
            video_paths.extend(_safe(_fetch_pexels_clips, keywords, n - len(video_paths), seen_ids))
    elif scene_index == 1:
        # Orta sahne: stok + gerçek karışımı
        half = max(1, n // 2)
        video_paths.extend(px_clips[:half])
        video_paths.extend(yt_clips[:n - len(video_paths)])
        if len(video_paths) < n and pixabay_key:
            video_paths.extend(_safe(_fetch_pixabay_clips, keywords, n - len(video_paths), seen_ids))
    else:
        # Son sahne (2+): YouTube + archive
        video_paths.extend(yt_clips)
        if len(video_paths) < n and dvids_key:
            video_paths.extend(_safe(_fetch_dvids_clips, keywords, dvids_key, n - len(video_paths), seen_ids))
        if len(video_paths) < n:
            video_paths.extend(_safe(_fetch_archive_clips, keywords, n - len(video_paths), seen_ids))

    # ─── Ortak fallback zinciri (tüm sahneler için) ────────────────────────────
    if len(video_paths) < n and pixabay_key and scene_index != 1:
        video_paths.extend(_safe(_fetch_pixabay_clips, keywords, n - len(video_paths), seen_ids))
    if len(video_paths) < n:
        video_paths.extend(_safe(_fetch_wikimedia_clips, keywords, n - len(video_paths), seen_ids))
    if len(video_paths) < n:
        video_paths.extend(_safe(_fetch_archive_clips, keywords, n - len(video_paths), seen_ids))

    if not video_paths:
        raise RuntimeError("Hiç video klip indirilemedi.")

    print(f"[video_builder] Sahne {scene_index+1} toplam: {len(video_paths)} klip")
    _save_seen_ids(seen_ids)
    return video_paths[:n]


# ─── Resize / crop ───────────────────────────────────────────────────────────

def _resize_to_shorts(clip: VideoFileClip) -> VideoFileClip:
    w, h = clip.size
    target_ratio = TARGET_W / TARGET_H
    current_ratio = w / h
    if current_ratio > target_ratio:
        clip = clip.resize(height=TARGET_H)
        clip = clip.crop(x_center=clip.w // 2, width=TARGET_W, height=TARGET_H)
    else:
        clip = clip.resize(width=TARGET_W)
        clip = clip.crop(y_center=clip.h // 2, width=TARGET_W, height=TARGET_H)
    return clip


# ─── Ken Burns — 6 yön ───────────────────────────────────────────────────────

def _apply_ken_burns(clip: VideoFileClip, effect_type: str = "zoom_in",
                     intensity: float = 0.03) -> VideoFileClip:
    """6 farklı Ken Burns hareketi uygular."""
    dur = clip.duration

    if effect_type == "zoom_in":
        def transform(get_frame, t):
            frame = get_frame(t)
            scale = 1 + intensity * (t / max(dur, 0.01))
            h, w = frame.shape[:2]
            nw, nh = int(w * scale), int(h * scale)
            img = Image.fromarray(frame).resize((nw, nh), Image.LANCZOS)
            x, y = (nw - w) // 2, (nh - h) // 2
            return np.array(img.crop((x, y, x + w, y + h)))

    elif effect_type == "zoom_out":
        def transform(get_frame, t):
            frame = get_frame(t)
            scale = 1 + intensity * (1 - t / max(dur, 0.01))
            h, w = frame.shape[:2]
            nw, nh = int(w * scale), int(h * scale)
            img = Image.fromarray(frame).resize((nw, nh), Image.LANCZOS)
            x, y = (nw - w) // 2, (nh - h) // 2
            return np.array(img.crop((x, y, x + w, y + h)))

    elif effect_type == "pan_right":
        def transform(get_frame, t):
            frame = get_frame(t)
            h, w = frame.shape[:2]
            nw = int(w * (1 + intensity))
            img = Image.fromarray(frame).resize((nw, h), Image.LANCZOS)
            progress = t / max(dur, 0.01)
            x = int((nw - w) * progress)
            return np.array(img.crop((x, 0, x + w, h)))

    elif effect_type == "pan_left":
        def transform(get_frame, t):
            frame = get_frame(t)
            h, w = frame.shape[:2]
            nw = int(w * (1 + intensity))
            img = Image.fromarray(frame).resize((nw, h), Image.LANCZOS)
            progress = 1 - (t / max(dur, 0.01))
            x = int((nw - w) * progress)
            return np.array(img.crop((x, 0, x + w, h)))

    elif effect_type == "pan_down":
        def transform(get_frame, t):
            frame = get_frame(t)
            h, w = frame.shape[:2]
            nh = int(h * (1 + intensity))
            img = Image.fromarray(frame).resize((w, nh), Image.LANCZOS)
            progress = t / max(dur, 0.01)
            y = int((nh - h) * progress)
            return np.array(img.crop((0, y, w, y + h)))

    elif effect_type == "diagonal_ur":
        def transform(get_frame, t):
            frame = get_frame(t)
            h, w = frame.shape[:2]
            nw, nh = int(w * (1 + intensity)), int(h * (1 + intensity))
            img = Image.fromarray(frame).resize((nw, nh), Image.LANCZOS)
            progress = t / max(dur, 0.01)
            x = int((nw - w) * progress)
            y = int((nh - h) * (1 - progress))
            return np.array(img.crop((x, y, x + w, y + h)))

    else:
        return clip

    return clip.fl(transform, apply_to="video")


# ─── Renk tonu — parametrik ──────────────────────────────────────────────────

def _color_grade(clip: VideoFileClip, preset: str = "war_blue") -> VideoFileClip:
    """COLOR_GRADES'den preset uygular."""
    params = COLOR_GRADES.get(preset, COLOR_GRADES["war_blue"])

    def grade(frame):
        f = frame.astype(np.float32)
        grey = f.mean(axis=2, keepdims=True)
        desat = params["desaturate"]
        if desat >= 0:
            f = f * (1 - desat) + grey * desat
        else:
            f = f + (f - grey) * abs(desat)
        f = (f - 128) * params["contrast"] + 128
        f[:, :, 0] = f[:, :, 0] + params["r_shift"]
        f[:, :, 1] = f[:, :, 1] + params["g_shift"]
        f[:, :, 2] = f[:, :, 2] + params["b_shift"]
        return np.clip(f, 0, 255).astype(np.uint8)

    return clip.fl_image(grade)


# ─── Overlay efektleri ────────────────────────────────────────────────────────

def _add_vignette(clip: VideoFileClip, intensity: float) -> VideoFileClip:
    """Kenar karartma efekti (0.0-1.0)."""
    if intensity <= 0:
        return clip

    # Vignette maskesini bir kere hesapla
    h, w = TARGET_H, TARGET_W
    Y, X = np.ogrid[:h, :w]
    cy, cx = h // 2, w // 2
    dist = np.sqrt((X - cx) ** 2 + (Y - cy) ** 2)
    max_dist = np.sqrt(cx ** 2 + cy ** 2)
    mask = 1.0 - (dist / max_dist) ** 2 * intensity * 0.7
    mask = np.clip(mask, 0, 1).astype(np.float32)

    def apply_vig(frame):
        h_f, w_f = frame.shape[:2]
        if h_f != h or w_f != w:
            return frame
        return np.clip(frame.astype(np.float32) * mask[:, :, np.newaxis],
                       0, 255).astype(np.uint8)

    return clip.fl_image(apply_vig)


def _add_film_grain(clip: VideoFileClip, intensity: float) -> VideoFileClip:
    """Film grain noise overlay (0.0-1.0)."""
    if intensity <= 0:
        return clip

    noise_level = 255 * intensity * 0.05

    def apply_grain(frame):
        noise = np.random.normal(0, noise_level, frame.shape)
        return np.clip(frame.astype(np.float32) + noise, 0, 255).astype(np.uint8)

    return clip.fl_image(apply_grain)


# ─── Çoklu klip montajı + geçişler ───────────────────────────────────────────

def _build_background(clip_paths: list, total_duration: float,
                      style: StyleProfile,
                      image_paths: list = None) -> VideoFileClip:
    """
    Video klipleri style profile'a göre işler ve birleştirir.
    clip_paths: list[str] — video dosya yolları (her biri VIDEO_CLIP_DURATION sn).
    image_paths: list[str] — araya eklenecek resim dosya yolları (IMAGE_CLIP_DURATION sn).
    """
    processed = []
    img_pool = list(image_paths) if image_paths else []
    # Klip ve resim sırası korunur — sahne bazlı alakalılık için karıştırılmaz
    clip_paths = list(clip_paths)

    for i, path in enumerate(clip_paths):
        kb = style.ken_burns_pool[i % len(style.ken_burns_pool)]

        try:
            c = VideoFileClip(path, audio=False)
            c = _resize_to_shorts(c)
            c = _color_grade(c, style.color_grade)
            c = _apply_ken_burns(c, kb)

            # Video klip süresini VIDEO_CLIP_DURATION'a sabitle
            if c.duration < VIDEO_CLIP_DURATION:
                repeats = int(VIDEO_CLIP_DURATION / c.duration) + 1
                c = concatenate_videoclips([c] * repeats)
            c = c.subclip(0, VIDEO_CLIP_DURATION)
        except Exception as e:
            print(f"[video_builder] Klip işleme hatası, atlanıyor: {e}")
            continue

        # Overlay efektleri
        if style.vignette_intensity > 0:
            c = _add_vignette(c, style.vignette_intensity)
        if style.film_grain_intensity > 0:
            c = _add_film_grain(c, style.film_grain_intensity)

        processed.append(c)

        # Video klibinin ardına resim ekle (son klipten sonra da eklenir)
        if img_pool:
            img_path = img_pool[i % len(img_pool)]
            kb_img = style.ken_burns_pool[(i + 1) % len(style.ken_burns_pool)]
            try:
                img = Image.open(img_path).convert("RGB")
                img_arr = np.array(img)
                img_clip = ImageClip(img_arr).set_duration(IMAGE_CLIP_DURATION)
                img_clip = _resize_to_shorts(img_clip)
                img_clip = _color_grade(img_clip, style.color_grade)
                img_clip = _apply_ken_burns(img_clip, kb_img, intensity=0.05)
                if style.vignette_intensity > 0:
                    img_clip = _add_vignette(img_clip, style.vignette_intensity)
                processed.append(img_clip)
                print(f"[video_builder] Resim eklendi ({i+1}. video sonrası): {os.path.basename(img_path)}")
            except Exception as e:
                print(f"[video_builder] Resim işleme hatası, atlanıyor: {e}")

    if not processed:
        print("[video_builder] Hiç klip işlenemedi, siyah arka plan kullanılıyor.")
        return ColorClip(size=(TARGET_W, TARGET_H), color=(0, 0, 0)).set_duration(total_duration)

    if len(processed) == 1:
        return processed[0].set_duration(total_duration) if processed[0].duration < total_duration else processed[0].subclip(0, total_duration)

    # Geçiş uygulama
    tt = style.transition_type

    if tt == "hard_cut":
        bg = concatenate_videoclips(processed, method="compose")
    elif tt == "fade_black":
        clips = []
        for i, c in enumerate(processed):
            if i > 0:
                c = c.fadein(CROSSFADE_DUR)
            if i < len(processed) - 1:
                c = c.fadeout(CROSSFADE_DUR)
            clips.append(c)
        bg = concatenate_videoclips(clips, method="compose")
    elif tt == "slide":
        clips = [processed[0].crossfadeout(CROSSFADE_DUR * 0.5)]
        for i, c in enumerate(processed[1:], 1):
            c = c.crossfadein(CROSSFADE_DUR * 0.5)
            if i < len(processed) - 1:
                c = c.crossfadeout(CROSSFADE_DUR * 0.5)
            clips.append(c)
        bg = concatenate_videoclips(clips, method="compose",
                                    padding=-CROSSFADE_DUR * 0.5)
    else:  # crossfade (varsayılan)
        clips = [processed[0].crossfadeout(CROSSFADE_DUR)]
        for i, c in enumerate(processed[1:], 1):
            c = c.crossfadein(CROSSFADE_DUR)
            if i < len(processed) - 1:
                c = c.crossfadeout(CROSSFADE_DUR)
            clips.append(c)
        bg = concatenate_videoclips(clips, method="compose",
                                    padding=-CROSSFADE_DUR)

    # Tam uzunluğa getir
    if bg.duration < total_duration:
        n_loops = int(total_duration / bg.duration) + 2
        bg = concatenate_videoclips([bg] * n_loops).subclip(0, total_duration)
    else:
        bg = bg.subclip(0, total_duration)

    return bg


# ─── Altyazı ─────────────────────────────────────────────────────────────────

def _render_subtitle_image(text: str, highlight: bool = False) -> np.ndarray:
    """Tek satır altyazı: beyaz (veya sarı vurgulu) metin + siyah outline, gradient arka plan."""
    MAX_W = TARGET_W - 80

    # Font boyutunu metne göre otomatik küçült (tek satıra sığdır)
    for font_size in [80, 68, 58, 50]:
        font = _load_font_for_text(text, font_size)
        display = _prepare_text(text)
        dummy = Image.new("RGBA", (1, 1))
        dd = ImageDraw.Draw(dummy)
        bbox = dd.textbbox((0, 0), display, font=font)
        text_w = bbox[2] - bbox[0]
        if text_w <= MAX_W:
            break

    padding_x, padding_y = 28, 16
    line_h = bbox[3] - bbox[1]
    img_w = min(text_w + padding_x * 2, TARGET_W)
    img_h = line_h + padding_y * 2

    img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Gradient arka plan çubuğu — power word'lerde daha koyu/kırmızımsı
    bg_color = (30, 5, 5) if highlight else (5, 5, 15)
    for row in range(img_h):
        bar_alpha = int(200 - (row / max(img_h, 1)) * 80) if highlight else int(170 - (row / max(img_h, 1)) * 70)
        draw.line([(0, row), (img_w, row)], fill=(*bg_color, bar_alpha))

    text_color = (255, 232, 77, 255) if highlight else (255, 255, 255, 255)  # sarı vs beyaz
    x = (img_w - text_w) // 2
    y = padding_y
    outline = 3
    for ox, oy in [(-outline, 0), (outline, 0), (0, -outline), (0, outline),
                   (-outline, -outline), (outline, -outline),
                   (-outline, outline), (outline, outline)]:
        draw.text((x + ox, y + oy), display, font=font, fill=(0, 0, 0, 255))
    draw.text((x, y), display, font=font, fill=text_color)

    return np.array(img)


_HOOK_DURATION = 3.0  # Hook overlay süresi — altyazı bu süre boyunca bastırılır

def _make_subtitle_clips(chunks: list, total_duration: float) -> list:
    clips = []
    for chunk in chunks:
        start = chunk["start"]
        # Hook gösterilirken (ilk 3s) altyazı çıkmasın — hook + altyazı çakışması
        if start < _HOOK_DURATION:
            start = _HOOK_DURATION
        end = min(chunk["end"], total_duration - CTA_DURATION - 0.1)
        dur = end - start
        if dur <= 0.1:
            continue
        img_arr = _render_subtitle_image(chunk["text"])
        h, w = img_arr.shape[:2]
        clips.append(
            ImageClip(img_arr, ismask=False)
            .set_duration(dur)
            .set_start(start)
            # %68 → hook ile çakışmaz, YouTube UI butonlarının üzerinde kalır
            .set_position(((TARGET_W - w) // 2, int(TARGET_H * 0.68)))
        )
    return clips


def _make_word_subtitle_clips(chunks: list, total_duration: float) -> list:
    """Word-by-word animated subtitles — each word pops up as it is spoken."""
    clips = []
    for chunk in chunks:
        text = chunk["text"].strip()
        if not text:
            continue
        start = chunk["start"]
        end = min(chunk["end"], total_duration - CTA_DURATION - 0.1)
        chunk_dur = end - start
        if chunk_dur <= 0:
            continue
        words = text.split()
        if not words:
            continue
        word_dur = chunk_dur / len(words)
        for i, word in enumerate(words):
            w_start = start + i * word_dur
            w_dur = word_dur
            if w_dur <= 0.05:
                continue
            img_arr = _render_subtitle_image(word, highlight=_is_power_word(word))
            h, w = img_arr.shape[:2]
            clips.append(
                ImageClip(img_arr, ismask=False)
                .set_duration(w_dur)
                .set_start(w_start)
                .set_position(((TARGET_W - w) // 2, int(TARGET_H * 0.62)))
            )
    return clips


def _make_fallback_subtitle_clips(narration: str, audio_duration: float) -> list:
    words = narration.split()
    secs_per_word = audio_duration / max(len(words), 1)
    n = 4
    chunks = []
    for i in range(0, len(words), n):
        group = words[i:i + n]
        chunks.append({
            "start": i * secs_per_word,
            "end": min((i + n) * secs_per_word, audio_duration),
            "text": " ".join(group),
        })
    return _make_subtitle_clips(chunks, audio_duration)


# ─── Hook overlay ────────────────────────────────────────────────────────────

def _make_hook_clip(hook_text: str, duration: float = 3.0) -> ImageClip:
    font = _load_font_for_text(hook_text, 64)
    max_w = TARGET_W - 80
    words = hook_text.split()
    word_groups, current = [], []
    dummy = Image.new("RGBA", (1, 1))
    dd = ImageDraw.Draw(dummy)

    for word in words:
        test = " ".join(current + [word])
        test_display = _prepare_text(test)
        if dd.textbbox((0, 0), test_display, font=font)[2] > max_w and current:
            word_groups.append(" ".join(current))
            current = [word]
        else:
            current.append(word)
    if current:
        word_groups.append(" ".join(current))

    # Her satırı ayrı ayrı bidi dönüştür
    lines = [_prepare_text(g) for g in word_groups]

    line_h = 76
    h = line_h * len(lines) + 30
    total_h = h + 20
    img = Image.new("RGBA", (TARGET_W, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Sinematik gradient arka plan: kenarlardan soluklaşır, ortada yoğun
    for row in range(total_h):
        progress = row / total_h
        if progress < 0.12:
            alpha = int(progress / 0.12 * 165)
        elif progress > 0.82:
            alpha = int((1.0 - progress) / 0.18 * 165)
        else:
            alpha = 165
        draw.line([(0, row), (TARGET_W, row)], fill=(0, 0, 0, alpha))

    # Sol kırmızı aksan çizgisi
    draw.rectangle([(0, 0), (6, total_h)], fill=(220, 30, 30, 230))

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        lw = bbox[2] - bbox[0]
        x = (TARGET_W - lw) // 2
        y = 15 + i * line_h
        for dx, dy in [(-3, -3), (3, 3), (-3, 3), (3, -3)]:
            draw.text((x + dx, y + dy), line, font=font, fill=(0, 0, 0, 255))
        draw.text((x, y), line, font=font, fill=(255, 220, 0, 255))

    arr = np.array(img)
    h_arr, w_arr = arr.shape[:2]

    # Punch-in: 0.35s içinde 1.22x → 1.0x scale (darbe hissi)
    def _punch_frame(gf, t):
        frame = gf(t)
        t_f = float(np.asarray(t).flat[0])
        if t_f >= 0.35:
            return frame
        scale = 1.22 - 0.22 * (t_f / 0.35)
        fh, fw = frame.shape[:2]
        new_h, new_w = int(fh * scale), int(fw * scale)
        resized = np.array(Image.fromarray(frame).resize((new_w, new_h), Image.LANCZOS))
        x_off = (new_w - fw) // 2
        y_off = (new_h - fh) // 2
        return resized[y_off:y_off + fh, x_off:x_off + fw]

    return (
        ImageClip(arr, ismask=False)
        .set_duration(duration)
        .set_start(0)
        .fl(_punch_frame, apply_to='video')
        .set_position(("center", "center"))
        .crossfadeout(0.5)
    )


# ─── CTA bitiş ekranı ────────────────────────────────────────────────────────

_CTA_TEXTS = {
    "ar": {
        "follow":  "تابعنا",
        "sub":     "للمزيد من التحليلات!",
        "arrow":   "اضغط متابعة  ^",
    },
    "tr": {
        "follow":  "TAKİP ET",
        "sub":     "DAHA FAZLASI İÇİN!",
        "arrow":   "TAKİP ET  ^",
    },
    "en": {
        "follow":  "FOLLOW",
        "sub":     "FOR MORE WHAT-IFS!",
        "arrow":   "TAP FOLLOW  ^",
    },
}


_TEASE_TEXTS = {
    "en": "WATCH TILL THE END",
    "tr": "SONA KADAR IZLE",
    "ar": "شاهد حتى النهاية",
}


def _make_midpoint_tease_clip(total_duration: float, language: str = "en") -> list:
    """Video ortasında (%42) 2s süren 'izlemeye devam et' overlay'i."""
    text_raw = _TEASE_TEXTS.get(language, _TEASE_TEXTS["en"])
    start = total_duration * 0.42
    dur = 2.0
    if start + dur >= total_duration - CTA_DURATION:
        return []

    text = _prepare_text(text_raw)
    font = _load_font_for_text(text, 52)
    dummy = Image.new("RGBA", (1, 1))
    dd = ImageDraw.Draw(dummy)
    bbox = dd.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    pad_x, pad_y = 32, 18
    img_w = tw + pad_x * 2
    img_h = th + pad_y * 2 + 8  # +8 for top accent bar

    img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Arka plan: yarı şeffaf kırmızı-siyah
    for row in range(img_h):
        alpha = 210 if row > 6 else 255
        r = 160 if row > 6 else 220
        draw.line([(0, row), (img_w, row)], fill=(r, 15, 15, alpha))

    # Üst kırmızı aksan çizgisi
    draw.rectangle([(0, 0), (img_w, 5)], fill=(255, 50, 50, 255))

    # Outline + metin
    tx, ty = pad_x, pad_y + 6
    for ox, oy in [(-2, -2), (2, -2), (-2, 2), (2, 2), (0, -2), (0, 2), (-2, 0), (2, 0)]:
        draw.text((tx + ox, ty + oy), text, font=font, fill=(0, 0, 0, 255))
    draw.text((tx, ty), text, font=font, fill=(255, 232, 77, 255))

    arr = np.array(img)
    h, w = arr.shape[:2]
    x_pos = (TARGET_W - w) // 2
    y_pos = int(TARGET_H * 0.52)  # ekranın ortasının biraz üstü

    clip = (
        ImageClip(arr, ismask=False)
        .set_duration(dur)
        .set_start(start)
        .set_position((x_pos, y_pos))
        .crossfadein(0.2)
        .crossfadeout(0.2)
    )
    return [clip]


def _make_cta_clip(total_duration: float, duration: float = CTA_DURATION, language: str = "en") -> list:
    start = total_duration - duration
    cta = _CTA_TEXTS.get(language, _CTA_TEXTS["en"])

    bg = (
        ColorClip(size=(TARGET_W, TARGET_H), color=(0, 0, 0))
        .set_opacity(0.75)
        .set_duration(duration)
        .set_start(start)
        .crossfadein(0.4)
    )

    bar = (
        ColorClip(size=(TARGET_W, 8), color=(200, 30, 30))
        .set_duration(duration)
        .set_start(start)
        .set_position(("center", TARGET_H // 2 - 100))
    )

    def _cta_text_img(raw_text, size, color, outline=(0, 0, 0)):
        text = _prepare_text(raw_text)
        font = _load_font_for_text(text, size)
        dummy = Image.new("RGBA", (1, 1))
        dd = ImageDraw.Draw(dummy)
        bbox = dd.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0] + 20
        h = bbox[3] - bbox[1] + 20
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        for dx, dy in [(-3, -3), (3, 3), (-3, 3), (3, -3), (0, -3), (0, 3), (-3, 0), (3, 0)]:
            draw.text((10 + dx, 10 + dy), text, font=font, fill=(*outline, 255))
        draw.text((10, 10), text, font=font, fill=(*color, 255))
        return np.array(img)

    follow_arr = _cta_text_img(cta["follow"], 80, (255, 220, 0))
    fh, fw = follow_arr.shape[:2]
    follow_clip = (
        ImageClip(follow_arr).set_duration(duration).set_start(start)
        .set_position(((TARGET_W - fw) // 2, TARGET_H // 2 - 80))
        .crossfadein(0.4)
    )

    sub_arr = _cta_text_img(cta["sub"], 44, (255, 255, 255))
    sh, sw = sub_arr.shape[:2]
    sub_clip = (
        ImageClip(sub_arr).set_duration(duration).set_start(start)
        .set_position(((TARGET_W - sw) // 2, TARGET_H // 2 + 20))
        .crossfadein(0.5)
    )

    arrow_arr = _cta_text_img(cta["arrow"], 44, (200, 30, 30))
    ah, aw = arrow_arr.shape[:2]
    arrow_clip = (
        ImageClip(arrow_arr).set_duration(duration).set_start(start)
        .set_position(((TARGET_W - aw) // 2, TARGET_H // 2 + 90))
        .crossfadein(0.6)
    )

    return [bg, bar, follow_clip, sub_clip, arrow_clip]


# ─── Progress bar ────────────────────────────────────────────────────────────

def _make_progress_bar(total_duration: float, bar_h: int = 8) -> VideoClip:
    def make_frame(t):
        w_filled = int(TARGET_W * min(t / total_duration, 1.0))
        frame = np.zeros((bar_h, TARGET_W, 3), dtype=np.uint8)
        for x in range(w_filled):
            ratio = x / max(w_filled, 1)
            r = int(120 + ratio * 80)   # koyu kırmızı → parlak kırmızı
            g = int(10 + ratio * 20)
            b = int(10 + ratio * 10)
            frame[:, x] = [r, g, b]
        # Uç parlaklığı (beyaz glow)
        if w_filled > 3:
            frame[:, w_filled - 3:w_filled] = [255, 200, 200]
        return frame

    return (
        VideoClip(make_frame, duration=total_duration)
        .set_position(("center", TARGET_H - bar_h - 2))
    )


# ─── Logo / watermark ────────────────────────────────────────────────────────

def _make_watermark_clip(total_duration: float) -> ImageClip | None:
    if not os.path.exists(LOGO_PATH):
        return None

    logo = Image.open(LOGO_PATH).convert("RGBA")
    max_size = 120
    w, h = logo.size
    if w > max_size:
        ratio = max_size / w
        logo = logo.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)

    r, g, b, a = logo.split()
    a = a.point(lambda x: int(x * 0.6))
    logo.putalpha(a)

    arr = np.array(logo)
    lh, lw = arr.shape[:2]
    x = TARGET_W - lw - 24
    y = 24

    return (
        ImageClip(arr).set_duration(total_duration).set_start(0)
        .set_position((x, y))
    )


# ─── Ses efektleri ───────────────────────────────────────────────────────────

_SFX_VOLUMES = {
    "hook":   0.65,   # İlk darbe — en güçlü, izleyiciyi kilitler
    "twist":  0.45,   # Orta bölüm
    "payoff": 0.55,   # Patlama anı
    "cta":    0.35,   # Bitti sesi
}


def _build_sfx_audio(audio_duration: float) -> list:
    timings = {
        "hook":   0.1,
        "twist":  min(15.0, audio_duration * 0.4),
        "payoff": max(0, audio_duration - 4.0),
        "cta":    max(0, audio_duration - 0.5),
    }
    sfx_clips = []
    for key, t in timings.items():
        path = SFX.get(key, "")
        if not path or not os.path.exists(path):
            continue
        try:
            vol = _SFX_VOLUMES.get(key, 0.40)
            sfx = AudioFileClip(path).volumex(vol).set_start(t)
            if t + sfx.duration > audio_duration + CTA_DURATION:
                sfx = sfx.subclip(0, audio_duration + CTA_DURATION - t)
            sfx_clips.append(sfx)
            print(f"[video_builder] SFX eklendi: {key} @ {t:.1f}s")
        except Exception as e:
            print(f"[video_builder] SFX yüklenemedi ({key}): {e}")

    return sfx_clips


# ─── Ana fonksiyon ───────────────────────────────────────────────────────────

def build_video(
    script: dict,
    audio_path: str,
    vtt_path: str = None,
    output_path: str = "output/short.mp4",
    seen_ids: set | None = None,
) -> str:
    """Script, ses ve VTT'den 1080x1920 Short üretir."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Style profile (her video benzersiz görünüm)
    style = _generate_style_profile(script)

    # 1) Sahne bazlı klip indirme — her sahne kendi keywords'üyle fetch edilir
    # Bu sayede Sahne 1 görüntüsü Sahne 1 içeriğiyle, Sahne 2 Sahne 2 ile eşleşir
    if seen_ids is None:
        seen_ids = _load_seen_ids()

    try:
        from smart_footage_matcher import get_scene_based_keywords
        scene_keywords = get_scene_based_keywords(script)  # [[s1_kws], [s2_kws], [s3_kws]]
        print(f"[video_builder] Sahne bazlı footage matcher aktif: {len(scene_keywords)} sahne")
    except Exception as e:
        print(f"[video_builder] Sahne matcher başarısız ({e}), fallback kullanılıyor")
        fallback_kws = list(script.get("search_keywords", []))
        title_words = _extract_title_keywords(script.get("title", ""))
        for tw in title_words:
            if tw not in " ".join(fallback_kws).lower():
                fallback_kws.append(tw)
        scene_keywords = [fallback_kws, fallback_kws, fallback_kws]  # 3 sahne

    # Sahne başına 4 klip × 3 sahne = 12 klip, 2.5s × 12 = 30s → 20s videoyu doldurur
    clip_paths = []
    for i, scene_kws in enumerate(scene_keywords[:3]):  # en fazla 3 sahne
        scene_clips = _fetch_clips(scene_kws, n=4, seen_ids=seen_ids, scene_index=i)
        clip_paths.extend(scene_clips)
        first_kw = scene_kws[0][:55] if scene_kws else "—"
        print(f"[video_builder] Sahne {i+1}: {len(scene_clips)} klip — '{first_kw}'")

    if not clip_paths:
        raise RuntimeError("Hiç video klip indirilemedi.")

    # 2) Ses süresi
    narration_audio = AudioFileClip(audio_path)
    MAX_SHORTS_DURATION = 20.0  # 20s hedef: yüksek tamamlanma oranı
    max_narration = MAX_SHORTS_DURATION - CTA_DURATION - 0.3
    if narration_audio.duration > max_narration:
        print(f"[video_builder] Narrasyon çok uzun ({narration_audio.duration:.1f}s), {max_narration:.1f}s'ye kırpılıyor.")
        narration_audio = narration_audio.subclip(0, max_narration)
    total_duration = narration_audio.duration + CTA_DURATION + 0.3

    # 3) Arka plan: çoklu klip + araya resimler + efektler + geçişler
    bg = _build_background(clip_paths, total_duration, style, image_paths=[])

    # 4) Overlay katmanları
    layers = [bg]

    # Hook (ilk 3 sn)
    layers.append(_make_hook_clip(script["hook"], duration=min(3.0, total_duration)))

    # Altyazılar
    vtt_chunks = []
    if vtt_path and os.path.exists(vtt_path):
        from tts import parse_vtt
        vtt_chunks = parse_vtt(vtt_path)
        layers.extend(_make_subtitle_clips(vtt_chunks, total_duration))
        print(f"[video_builder] VTT: {len(vtt_chunks)} altyazı chunk'ı (cümle-cümle)")
    else:
        layers.extend(_make_fallback_subtitle_clips(script["narration"], narration_audio.duration))

    # ─── Kırmızı alarm flash'ları ─────────────────────────────────────
    # Harita/bayrak/stat/format overlay'ler kaldırıldı — görsel kargaşa yaratan,
    # VVSA'yı düşüren gereksiz katmanlar. Sadece 2 adet ince kırmızı flash kaldı.
    try:
        from overlay_system import create_red_flash_data
        flash_times = [total_duration * 0.30, total_duration * 0.65]
        flash_dur = 0.25
        for ft in flash_times:
            if ft + flash_dur > total_duration - CTA_DURATION:
                continue
            flash_arr = create_red_flash_data()
            layers.append(
                ImageClip(flash_arr, ismask=False)
                .set_duration(flash_dur)
                .set_start(ft)
                .set_position((0, 0))
                .crossfadein(0.08)
                .crossfadeout(0.12)
            )
    except ImportError:
        pass
    except Exception as e:
        print(f"[video_builder] Overlay system genel hatası: {e}")
    # ─── Overlay System Sonu ──────────────────────────────────────────

    # Mid-video open-loop tease (%42 noktası)
    lang = script.get("language", "en")
    layers.extend(_make_midpoint_tease_clip(total_duration, language=lang))

    # CTA bitiş ekranı
    layers.extend(_make_cta_clip(total_duration, language=lang))

    # Logo/watermark
    wm = _make_watermark_clip(total_duration)
    if wm:
        layers.append(wm)

    # İlerleme çubuğu
    layers.append(_make_progress_bar(total_duration))

    # 5) Kompozit
    final_video = CompositeVideoClip(layers, size=(TARGET_W, TARGET_H))
    final_video = final_video.set_duration(total_duration)

    # 6) Ses: TTS + müzik + sfx
    audio_tracks = [narration_audio]
    music_path = _pick_music(script)
    if music_path and os.path.exists(music_path):
        music = AudioFileClip(music_path).audio_fadein(1.5)  # 1.5s sessizlik sonra giriş
        if music.duration < total_duration:
            from moviepy.audio.fx.audio_loop import audio_loop
            music = audio_loop(music, nloops=int(total_duration / music.duration) + 1)
        music = music.subclip(0, total_duration)
        # Crescendo: 0.08 → 0.22 (video boyunca gerilim tırmanışı)
        _td = total_duration
        def _crescendo(gf, t):
            frames = gf(t)
            t_arr = np.asarray(t, dtype=float)
            vol = 0.08 + 0.14 * np.clip(t_arr / max(_td, 0.1), 0.0, 1.0)
            if vol.ndim == 0:
                return frames * float(vol)
            # t array ise: (n_samples,) → (n_samples, 1) broadcast
            return frames * vol[:, np.newaxis]
        music = music.fl(_crescendo, apply_to='audio')
        audio_tracks.append(music)

    sfx_clips = _build_sfx_audio(narration_audio.duration)
    audio_tracks.extend(sfx_clips)

    final_video = final_video.set_audio(CompositeAudioClip(audio_tracks))

    # 7) Branded intro / outro
    segments = []
    if os.path.exists(INTRO_PATH):
        try:
            intro = VideoFileClip(INTRO_PATH, audio=True)
            intro = _resize_to_shorts(intro)
            segments.append(intro.crossfadeout(0.3))
        except Exception as e:
            print(f"[video_builder] Intro yüklenemedi: {e}")

    final_video_faded = final_video.crossfadein(0.3) if segments else final_video
    segments.append(final_video_faded)

    if os.path.exists(OUTRO_PATH):
        try:
            outro = VideoFileClip(OUTRO_PATH, audio=True)
            outro = _resize_to_shorts(outro)
            segments.append(outro.crossfadein(0.3))
        except Exception as e:
            print(f"[video_builder] Outro yüklenemedi: {e}")

    if len(segments) > 1:
        final_video = concatenate_videoclips(segments, method="compose", padding=-0.3)

    # 8) Export
    print(f"[video_builder] Render ediliyor -> {output_path}")
    final_video.write_videofile(
        output_path,
        fps=30,
        codec="libx264",
        audio_codec="aac",
        temp_audiofile=os.path.join(os.path.dirname(output_path), "temp_audio.m4a"),
        remove_temp=True,
        threads=4,
        preset="slow",
        ffmpeg_params=["-crf", "17", "-b:a", "192k", "-movflags", "+faststart",
                       "-profile:v", "high", "-level", "4.1", "-pix_fmt", "yuv420p"],
        verbose=False,
        logger=None,
    )

    # Cleanup
    narration_audio.close()
    for path in clip_paths:
        try:
            os.unlink(path)
        except OSError:
            pass

    print(f"[video_builder] Video hazır: {output_path}")
    return output_path


if __name__ == "__main__":
    import sys

    script_path = sys.argv[1] if len(sys.argv) > 1 else "output/script.json"
    audio_path = sys.argv[2] if len(sys.argv) > 2 else "output/narration.mp3"
    vtt_path = sys.argv[3] if len(sys.argv) > 3 else "output/narration.vtt"

    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    build_video(script, audio_path, vtt_path if os.path.exists(vtt_path) else None)
