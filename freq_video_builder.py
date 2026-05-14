"""
freq_video_builder.py — Solfeggio frekans videoları için video montajı.

Format: 1080×1920 YouTube Shorts
Yapı:
  0–4s   : Hook ekranı — büyük metin overlay
  4–54s  : Pexels ambient footage + frekans bilgisi (Hz + benefit) overlay
  54–62s : CTA ekranı — "Follow for daily healing frequencies"

Ses: freq_audio_gen.py tarafından üretilen MP3 (62 saniye)
Görsel: Pexels API'den meditation/nature/space klipleri
"""

import os
import json
import random
import math
import tempfile
import requests
import shutil
import subprocess

import numpy as np
from PIL import Image, ImageDraw, ImageFont

if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.LANCZOS

from moviepy.editor import (
    VideoFileClip,
    AudioFileClip,
    CompositeVideoClip,
    ImageClip,
    ColorClip,
    concatenate_videoclips,
)

TARGET_W = 1080
TARGET_H = 1920
OUTPUT_PATH = os.path.join("output", "freq_short.mp4")

# ─── Renk paletleri (mood'a göre) ───────────────────────────────────────────

MOOD_PALETTES = {
    "calm":       {"bg": (10, 20, 40),    "accent": (100, 180, 255), "text": (220, 235, 255)},
    "healing":    {"bg": (5, 30, 15),     "accent": (80, 220, 130),  "text": (200, 255, 220)},
    "liberation": {"bg": (30, 10, 50),    "accent": (180, 100, 255), "text": (230, 210, 255)},
    "cleansing":  {"bg": (5, 25, 35),     "accent": (60, 200, 220),  "text": (200, 240, 255)},
    "cosmic":     {"bg": (5, 5, 25),      "accent": (255, 200, 60),  "text": (255, 240, 200)},
    "miracle":    {"bg": (20, 10, 5),     "accent": (255, 170, 50),  "text": (255, 235, 200)},
    "love":       {"bg": (40, 5, 20),     "accent": (255, 100, 160), "text": (255, 210, 230)},
    "awakening":  {"bg": (5, 15, 40),     "accent": (80, 160, 255),  "text": (200, 220, 255)},
    "spiritual":  {"bg": (15, 5, 35),     "accent": (160, 80, 255),  "text": (220, 200, 255)},
    "divine":     {"bg": (20, 15, 5),     "accent": (255, 215, 80),  "text": (255, 245, 210)},
    "ancient":    {"bg": (25, 20, 10),    "accent": (200, 160, 80),  "text": (240, 225, 190)},
    "focus":      {"bg": (5, 15, 30),     "accent": (0, 200, 255),   "text": (200, 235, 255)},
    "earth":      {"bg": (10, 25, 10),    "accent": (100, 200, 100), "text": (210, 240, 210)},
    "grounding":  {"bg": (20, 15, 5),     "accent": (180, 140, 80),  "text": (240, 225, 190)},
    "sleep":      {"bg": (5, 5, 20),      "accent": (80, 80, 180),   "text": (180, 180, 240)},
    "meditation": {"bg": (10, 15, 30),    "accent": (120, 160, 220), "text": (200, 220, 255)},
    "energy":     {"bg": (30, 10, 5),     "accent": (255, 120, 40),  "text": (255, 220, 180)},
    "brain":      {"bg": (5, 10, 30),     "accent": (0, 180, 255),   "text": (180, 225, 255)},
    "planetary":  {"bg": (5, 5, 15),      "accent": (160, 140, 200), "text": (210, 200, 240)},
    "abundance":  {"bg": (15, 20, 5),     "accent": (200, 200, 60),  "text": (240, 240, 180)},
    "creativity": {"bg": (25, 5, 25),     "accent": (220, 80, 200),  "text": (240, 200, 240)},
    "balance":    {"bg": (10, 20, 20),    "accent": (100, 200, 180), "text": (200, 240, 230)},
}
DEFAULT_PALETTE = {"bg": (5, 10, 30), "accent": (100, 180, 255), "text": (220, 235, 255)}


def _get_palette(mood: str) -> dict:
    return MOOD_PALETTES.get(mood, DEFAULT_PALETTE)


# ─── Font yardımcısı ─────────────────────────────────────────────────────────

FONT_CANDIDATES = [
    "assets/fonts/Montserrat-Bold.ttf",
    "assets/fonts/Roboto-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


# ─── Pexels görsel dedup ─────────────────────────────────────────────────────

FREQ_SEEN_PEXELS_PATH = os.path.join("output", "freq_seen_pexels_ids.json")
MAX_SEEN_IDS = 500


def _load_freq_seen_ids() -> set:
    """Daha önce kullanılan Pexels video ID'lerini yükle."""
    try:
        with open(FREQ_SEEN_PEXELS_PATH, "r") as f:
            ids = json.load(f)
            if isinstance(ids, list):
                return set(ids)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return set()


def _save_freq_seen_ids(seen: set) -> None:
    """Kullanılan Pexels video ID'lerini kaydet (max MAX_SEEN_IDS)."""
    os.makedirs(os.path.dirname(FREQ_SEEN_PEXELS_PATH), exist_ok=True)
    id_list = list(seen)
    if len(id_list) > MAX_SEEN_IDS:
        id_list = id_list[-MAX_SEEN_IDS:]
    with open(FREQ_SEEN_PEXELS_PATH, "w") as f:
        json.dump(id_list, f)
    print(f"[freq_video] Seen Pexels IDs kaydedildi: {len(id_list)} adet")


# ─── Pexels footage indir ────────────────────────────────────────────────────

def _fetch_pexels_clips(keywords: list, n: int = 3, seen_ids: set = None) -> tuple[list[str], set]:
    """Pexels'ten meditation/nature/space klipleri indirir. Daha önce kullanılanları atlar."""
    api_key = os.environ.get("PEXELS_API_KEY", "")
    if seen_ids is None:
        seen_ids = set()
    new_ids = set()

    if not api_key:
        print("[freq_video] PEXELS_API_KEY eksik — renk arka plan kullanılacak")
        return [], new_ids

    downloaded = []
    session_seen = set()

    # Keywords'ü shuffle et ve rastgele 5 tanesini seç
    kw_pool = list(keywords)
    random.shuffle(kw_pool)
    queries = kw_pool[:5]

    for query in queries:
        if len(downloaded) >= n:
            break
        try:
            page = random.randint(1, 3)
            resp = requests.get(
                "https://api.pexels.com/videos/search",
                params={"query": query, "per_page": 10, "orientation": "portrait", "page": page},
                headers={"Authorization": api_key},
                timeout=15,
            )
            if resp.status_code != 200:
                continue
            videos = resp.json().get("videos", [])
            random.shuffle(videos)
            for video in videos:
                if len(downloaded) >= n:
                    break
                vid_id = video['id']
                vid_key = f"pexels_{vid_id}"
                if vid_key in session_seen or vid_id in seen_ids:
                    continue
                session_seen.add(vid_key)
                # 1080p+ MP4 seç (düşük kalite kullanma)
                best = None
                for vf in video.get("video_files", []):
                    if vf.get("file_type") == "video/mp4" and vf.get("height", 0) >= 1080:
                        if best is None or vf.get("height", 0) > best.get("height", 0):
                            best = vf
                if not best:
                    continue
                try:
                    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False, prefix="freq_pexels_")
                    tmp.close()
                    r = requests.get(best["link"], timeout=60, stream=True)
                    r.raise_for_status()
                    with open(tmp.name, "wb") as f:
                        for chunk in r.iter_content(chunk_size=256 * 1024):
                            f.write(chunk)
                    downloaded.append(tmp.name)
                    new_ids.add(vid_id)
                    print(f"[freq_video] Pexels klip indirildi: {query!r} (id={vid_id})")
                except Exception as e:
                    print(f"[freq_video] Pexels indirme hatası: {e}")
        except Exception as e:
            print(f"[freq_video] Pexels arama hatası ({query!r}): {e}")

    return downloaded, new_ids


# ─── Görsel ekran oluşturucular ──────────────────────────────────────────────

def _make_gradient_bg(palette: dict, duration: float) -> ImageClip:
    """Dikey renk geçişli arka plan ImageClip üretir."""
    img = Image.new("RGB", (TARGET_W, TARGET_H))
    draw = ImageDraw.Draw(img)
    bg = palette["bg"]
    accent = palette["accent"]
    for y in range(TARGET_H):
        t = y / TARGET_H
        # Üst: koyu arka plan → orta: hafif accent parlaması → alt: koyu
        mid_factor = math.exp(-((t - 0.5) ** 2) / 0.08) * 0.3
        r = int(bg[0] + (accent[0] - bg[0]) * mid_factor)
        g = int(bg[1] + (accent[1] - bg[1]) * mid_factor)
        b = int(bg[2] + (accent[2] - bg[2]) * mid_factor)
        draw.line([(0, y), (TARGET_W, y)], fill=(r, g, b))
    arr = np.array(img)
    return ImageClip(arr).set_duration(duration)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Metni satırlara böler."""
    words = text.split()
    lines = []
    current = ""
    # ImageDraw olmadan textlength kullan
    tmp_img = Image.new("RGB", (1, 1))
    tmp_draw = ImageDraw.Draw(tmp_img)
    for word in words:
        test = (current + " " + word).strip()
        try:
            w = tmp_draw.textlength(test, font=font)
        except AttributeError:
            bbox = font.getbbox(test)
            w = bbox[2] - bbox[0]
        if w <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _make_hook_overlay(hook_line: str, hook_subtext: str, palette: dict, duration: float) -> ImageClip:
    """
    Tüm video boyunca görünen hook metni overlay'i (şeffaf RGBA).
    Ekranın ortasında konumlanır, footage'ın üzerinde durur.
    """
    img = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    accent = palette["accent"]
    text_color = palette["text"]

    # Hook metni
    hook_font_size = 64
    font_hook = _load_font(hook_font_size)
    max_w = TARGET_W - 100
    lines = _wrap_text(hook_line, font_hook, max_w)

    line_h = hook_font_size + 14
    total_h = len(lines) * line_h
    # Ekranın orta-üst bölgesi (Hz bilgisi altta olduğu için yukarı kaydır)
    y_start = int(TARGET_H * 0.28) - total_h // 2

    # Metin arkasına yarı saydam kutu
    pad = 24
    box_y1 = y_start - pad
    box_y2 = y_start + total_h + pad
    draw.rectangle([(40, box_y1), (TARGET_W - 40, box_y2)], fill=(0, 0, 0, 150))

    for i, line in enumerate(lines):
        y = y_start + i * line_h
        try:
            lw = draw.textlength(line, font=font_hook)
        except AttributeError:
            bbox = font_hook.getbbox(line)
            lw = bbox[2] - bbox[0]
        x = (TARGET_W - lw) // 2
        # Gölge
        draw.text((x + 3, y + 3), line, font=font_hook, fill=(0, 0, 0, 180))
        draw.text((x, y), line, font=font_hook, fill=(*text_color, 240))

    # Accent çizgi
    line_y = box_y2 + 8
    draw.rectangle(
        [(TARGET_W // 2 - 80, line_y), (TARGET_W // 2 + 80, line_y + 3)],
        fill=(*accent, 220),
    )

    # Alt metin
    if hook_subtext:
        font_sub = _load_font(40)
        sub_y = line_y + 16
        try:
            sw = draw.textlength(hook_subtext, font=font_sub)
        except AttributeError:
            bbox = font_sub.getbbox(hook_subtext)
            sw = bbox[2] - bbox[0]
        sx = (TARGET_W - sw) // 2
        draw.text((sx + 2, sub_y + 2), hook_subtext, font=font_sub, fill=(0, 0, 0, 160))
        draw.text((sx, sub_y), hook_subtext, font=font_sub, fill=(*accent, 230))

    arr = np.array(img)
    return ImageClip(arr, ismask=False).set_duration(duration)


def _make_freq_overlay(hz: float, freq_name: str, short_benefit: str, palette: dict) -> ImageClip:
    """
    Ana video bölümünde gösterilecek frekans bilgisi overlay'i.
    Sol alt köşe: büyük Hz sayısı + sağ üst: benefit metni
    """
    img = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    accent = palette["accent"]
    text_color = palette["text"]

    # ─── Sol alt: büyük Hz göstergesi ────────────────────────────────────────
    hz_str = f"{hz:g} Hz"
    font_hz = _load_font(110)
    font_label = _load_font(42)

    # Arka plan kutusu (yarı saydam)
    box_h = 170
    box_y = TARGET_H - box_h - 80
    draw.rectangle([(0, box_y - 15), (TARGET_W, box_y + box_h)], fill=(0, 0, 0, 130))

    # Hz metni
    try:
        hw = draw.textlength(hz_str, font=font_hz)
    except AttributeError:
        bbox = font_hz.getbbox(hz_str)
        hw = bbox[2] - bbox[0]
    hx = (TARGET_W - hw) // 2
    # Glow efekti (arka plan rengi ile)
    draw.text((hx + 4, box_y + 8), hz_str, font=font_hz, fill=(*accent, 60))
    draw.text((hx, box_y + 4), hz_str, font=font_hz, fill=(*text_color, 240))

    # Benefit label
    benefit_upper = short_benefit.upper()
    try:
        bw = draw.textlength(benefit_upper, font=font_label)
    except AttributeError:
        bbox = font_label.getbbox(benefit_upper)
        bw = bbox[2] - bbox[0]
    bx = (TARGET_W - bw) // 2
    draw.text((bx, box_y + 120), benefit_upper, font=font_label, fill=(*accent, 220))

    # ─── Üst: frekans adı (küçük) ─────────────────────────────────────────────
    font_top = _load_font(36)
    top_text = freq_name.upper()
    draw.rectangle([(0, 60), (TARGET_W, 115)], fill=(0, 0, 0, 100))
    try:
        tw = draw.textlength(top_text, font=font_top)
    except AttributeError:
        bbox = font_top.getbbox(top_text)
        tw = bbox[2] - bbox[0]
    draw.text(((TARGET_W - tw) // 2, 70), top_text, font=font_top, fill=(*text_color, 200))

    arr = np.array(img)
    return ImageClip(arr, ismask=False)


def _make_cta_overlay(cta_line: str, palette: dict, duration: float) -> ImageClip:
    """
    Son N saniyede görünen CTA overlay'i (şeffaf RGBA).
    Footage'ın üzerine biner, hook ile birlikte ekranda olur.
    """
    img = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    accent = palette["accent"]
    text_color = palette["text"]

    # Karartma şeridi (orta bölge)
    draw.rectangle([(0, TARGET_H // 2 - 160), (TARGET_W, TARGET_H // 2 + 160)], fill=(0, 0, 0, 170))

    # CTA metni
    font_cta = _load_font(56)
    cta_lines = _wrap_text(cta_line, font_cta, TARGET_W - 100)
    line_h = 68
    total_h = len(cta_lines) * line_h
    y_start = TARGET_H // 2 - total_h // 2

    for i, line in enumerate(cta_lines):
        y = y_start + i * line_h
        try:
            lw = draw.textlength(line, font=font_cta)
        except AttributeError:
            bbox = font_cta.getbbox(line)
            lw = bbox[2] - bbox[0]
        x = (TARGET_W - lw) // 2
        draw.text((x + 2, y + 2), line, font=font_cta, fill=(0, 0, 0, 180))
        draw.text((x, y), line, font=font_cta, fill=(*text_color, 245))

    # Accent çizgi
    draw.rectangle(
        [(TARGET_W // 2 - 80, TARGET_H // 2 + total_h // 2 + 20),
         (TARGET_W // 2 + 80, TARGET_H // 2 + total_h // 2 + 23)],
        fill=(*accent, 220),
    )

    arr = np.array(img)
    return ImageClip(arr, ismask=False).set_duration(duration)


SOUND_WARNING_DURATION = 4.0


def _make_sound_warning_overlay(palette: dict, duration: float = SOUND_WARNING_DURATION) -> ImageClip:
    """'TURN SOUND ON' pill uyarısı — ilk N saniyede ekranda görünür."""
    img = Image.new("RGBA", (TARGET_W, TARGET_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    accent = palette["accent"]

    text = "TURN SOUND ON"
    font = _load_font(46)

    try:
        tw = draw.textlength(text, font=font)
    except AttributeError:
        bbox = font.getbbox(text)
        tw = bbox[2] - bbox[0]

    pad_x, pad_y = 52, 22
    box_w = int(tw) + pad_x * 2
    box_h = 46 + pad_y * 2
    cx = TARGET_W // 2
    # Hook altı - Hz kutusu üstü arası boşluk: %62 yüksekliğe yerleştir
    cy = int(TARGET_H * 0.62)
    x1 = cx - box_w // 2
    y1 = cy - box_h // 2
    x2 = cx + box_w // 2
    y2 = cy + box_h // 2

    try:
        draw.rounded_rectangle([(x1, y1), (x2, y2)], radius=box_h // 2, fill=(*accent, 220))
    except AttributeError:
        draw.rectangle([(x1, y1), (x2, y2)], fill=(*accent, 220))

    # Koyu metin (accent rengi üstünde)
    tx = cx - int(tw) // 2
    ty = y1 + pad_y
    draw.text((tx + 1, ty + 1), text, font=font, fill=(0, 0, 0, 100))
    draw.text((tx, ty), text, font=font, fill=(10, 10, 10, 245))

    arr = np.array(img)
    return ImageClip(arr, ismask=False).set_duration(duration)


# ─── Ana video builder ────────────────────────────────────────────────────────

def build_freq_video(script: dict, audio_path: str, output_path: str = OUTPUT_PATH) -> str:
    """
    Frekans videosu üretir.

    Args:
        script: freq_script_gen.py çıktısı
        audio_path: Frekans MP3 dosyası
        output_path: Çıktı MP4 yolu

    Returns:
        output_path
    """
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    hz = float(script["hz"])
    freq_name = script["freq_name"]
    short_benefit = script["short_benefit"]
    mood = script.get("mood", "cosmic")
    hook_line = script["hook_line"]
    hook_subtext = script.get("hook_subtext", "")
    cta_line = script.get("cta_line", "Follow for daily healing frequencies.")
    pexels_keywords = script.get("pexels_keywords", ["meditation peaceful nature", "calm water reflection"])

    palette = _get_palette(mood)

    # ─── Ses ──────────────────────────────────────────────────────────────────
    audio_clip = AudioFileClip(audio_path)
    total_duration = min(audio_clip.duration, 15.0)

    print(f"[freq_video] Toplam süre: {total_duration:.1f}s")

    # ─── Pexels footage indir (dedup ile) ─────────────────────────────────────
    seen_pexels = _load_freq_seen_ids()
    clip_paths, new_pexels_ids = _fetch_pexels_clips(pexels_keywords, n=1, seen_ids=seen_pexels)
    seen_pexels.update(new_pexels_ids)
    _save_freq_seen_ids(seen_pexels)
    tmp_files = list(clip_paths)

    # ─── Arka plan: tüm video boyunca tek footage bloğu ──────────────────────
    def _prepare_bg_clip(path: str, duration: float) -> VideoFileClip:
        """Klip yükle, 1080×1920 kırp/yakınlaştır, sesi kaldır."""
        clip = VideoFileClip(path, audio=False)

        target_ratio = TARGET_W / TARGET_H
        clip_ratio = clip.w / clip.h

        if clip_ratio > target_ratio:
            new_h = TARGET_H
            new_w = int(clip.w * (TARGET_H / clip.h))
        else:
            new_w = TARGET_W
            new_h = int(clip.h * (TARGET_W / clip.w))

        clip = clip.resize((new_w, new_h))
        x1 = (new_w - TARGET_W) // 2
        y1 = (new_h - TARGET_H) // 2
        clip = clip.crop(x1=x1, y1=y1, x2=x1 + TARGET_W, y2=y1 + TARGET_H)

        if clip.duration < duration:
            n_loops = int(math.ceil(duration / clip.duration))
            clip = concatenate_videoclips([clip] * n_loops).subclip(0, duration)
        else:
            clip = clip.subclip(0, duration)

        darken = ColorClip(size=(TARGET_W, TARGET_H), color=[0, 0, 0]).set_opacity(0.45).set_duration(duration)
        return CompositeVideoClip([clip, darken])

    print("[freq_video] Arka plan hazırlanıyor...")
    if clip_paths:
        bg_clips = []
        per_clip = total_duration / max(len(clip_paths), 1)
        for p in clip_paths:
            try:
                bg_clips.append(_prepare_bg_clip(p, per_clip))
            except Exception as e:
                print(f"[freq_video] Klip yüklenemedi ({p}): {e}")

        if bg_clips:
            bg_video = concatenate_videoclips(bg_clips)
            if bg_video.duration < total_duration:
                fill = _make_gradient_bg(palette, total_duration - bg_video.duration)
                bg_video = concatenate_videoclips([bg_video, fill])
        else:
            bg_video = _make_gradient_bg(palette, total_duration)
    else:
        bg_video = _make_gradient_bg(palette, total_duration)

    # ─── Overlay katmanları ───────────────────────────────────────────────────

    # 1) Hook — tüm video boyunca
    print("[freq_video] Hook overlay oluşturuluyor...")
    hook_overlay = _make_hook_overlay(hook_line, hook_subtext, palette, total_duration)

    # 2) Frekans bilgisi (Hz + benefit) — tüm video boyunca
    print("[freq_video] Frekans overlay oluşturuluyor...")
    freq_overlay = _make_freq_overlay(hz, freq_name, short_benefit, palette).set_duration(total_duration)

    # 3) Ses uyarısı — ilk SOUND_WARNING_DURATION saniye
    print("[freq_video] Ses uyarısı overlay oluşturuluyor...")
    sound_warning = _make_sound_warning_overlay(palette)

    # ─── Birleştir: footage + hook + hz + ses uyarısı ────────────────────────
    print("[freq_video] Katmanlar birleştiriliyor...")
    final_video = CompositeVideoClip(
        [bg_video, hook_overlay, freq_overlay, sound_warning],
        size=(TARGET_W, TARGET_H),
    ).set_duration(total_duration)
    final_video = final_video.set_audio(audio_clip.subclip(0, total_duration))

    # ─── 5) Export ────────────────────────────────────────────────────────────
    print(f"[freq_video] Export ediliyor: {output_path}")
    final_video.write_videofile(
        output_path,
        fps=30,
        codec="libx264",
        audio_codec="aac",
        bitrate="4000k",
        audio_bitrate="192k",
        threads=4,
        preset="fast",
        ffmpeg_params=["-pix_fmt", "yuv420p", "-movflags", "+faststart"],
        logger=None,
    )

    # ─── 6) Temizlik ─────────────────────────────────────────────────────────
    audio_clip.close()
    final_video.close()
    for p in tmp_files:
        try:
            os.unlink(p)
        except OSError:
            pass

    print(f"[freq_video] Video tamamlandı: {output_path}")
    return output_path
