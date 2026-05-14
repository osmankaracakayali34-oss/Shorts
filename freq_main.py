"""
freq_main.py — FREQ SHORTS pipeline orkestratörü.

Kullanım:
  python freq_main.py                      # Normal çalıştırma
  python freq_main.py --dry-run            # Upload olmadan test
  python freq_main.py --hz 528            # Belirli frekans ile çalıştır

Pipeline:
  1) freq_topic_pool.json'dan frekans seç
  2) Gemini ile title/hook/tags üret
  3) Belirtilen Hz'de sinüs dalgası sesi üret (17 saniye)
  4) Pexels'ten meditation/nature/space klipleri indir
  5) Video montajı: hook ekranı + ambient footage (15s)
  6) YouTube'a yükle (WAR SHORTS'un uploader.py'ini kullanır)
  7) Telegram bildirimi gönder
"""

import argparse
import json
import os
import random
import sys
import traceback

from freq_script_gen import generate_freq_script, generate_localizations, save_freq_script
from freq_audio_gen import generate_frequency_audio
from freq_video_builder import build_freq_video
from notifier import send_notification, send_error_notification

# Kuyruk modu: USE_FREQ_QUEUE=true ise freq_batch_producer kuyruğundan yayınlar
USE_QUEUE = os.environ.get("USE_FREQ_QUEUE", "false").lower() == "true"

OUTPUT_DIR = "output"
TOPIC_POOL_PATH = "freq_topic_pool.json"
USED_FREQ_PATH = "freq_used_topics.json"
FREQ_AUDIO_PATH = os.path.join(OUTPUT_DIR, "freq_audio.mp3")
FREQ_VIDEO_PATH = os.path.join(OUTPUT_DIR, "freq_short.mp4")
FREQ_SCRIPT_PATH = os.path.join(OUTPUT_DIR, "freq_script.json")

# ─── Seçim & durum ──────────────────────────────────────────────────────────

def _load_pool() -> list:
    with open(TOPIC_POOL_PATH, encoding="utf-8") as f:
        return json.load(f)


def _load_used() -> list:
    if os.path.exists(USED_FREQ_PATH):
        with open(USED_FREQ_PATH, encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_used(used: list) -> None:
    with open(USED_FREQ_PATH, "w", encoding="utf-8") as f:
        json.dump(used, f, indent=2)


def pick_topic(hz_override: float = None) -> dict:
    """
    Frekans seçer. hz_override verilmişse o Hz'i döner.
    Aksi halde kullanılmamış frekanslardan rastgele seçer.
    Tüm frekanslar kullanıldıysa listeyi sıfırlar.
    """
    pool = _load_pool()

    if hz_override is not None:
        for topic in pool:
            if float(topic["hz"]) == float(hz_override):
                return topic
        raise ValueError(f"{hz_override} Hz frekans havuzda bulunamadı.")

    used = _load_used()
    used_set = set(str(u) for u in used)

    available = [t for t in pool if str(t["hz"]) not in used_set]
    if not available:
        print("[freq_main] Tüm frekanslar kullanıldı — liste sıfırlanıyor.")
        used = []
        _save_used(used)
        available = pool

    topic = random.choice(available)
    used.append(str(topic["hz"]))
    _save_used(used)
    return topic


# ─── Adım çalıştırıcı ────────────────────────────────────────────────────────

def _step(name: str, fn, topic_name: str = ""):
    try:
        return fn()
    except Exception as e:
        print(f"\n[freq_main] HATA — {name}: {e}", file=sys.stderr)
        traceback.print_exc()
        try:
            send_error_notification(name, e, topic_name)
        except Exception:
            pass
        raise


# ─── Pipeline ────────────────────────────────────────────────────────────────

def run(dry_run: bool = False, hz_override: float = None) -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Önceki çıktıları temizle
    for p in [FREQ_AUDIO_PATH, FREQ_VIDEO_PATH, FREQ_SCRIPT_PATH]:
        if os.path.exists(p):
            os.remove(p)

    print("=" * 52)
    print("🎵  FREQ SHORTS — Pipeline Başlatıldı")
    print("=" * 52)

    # Kuyruk modunda batch_producer'dan hazır video kullan
    queued = None
    if USE_QUEUE and not hz_override:
        from freq_batch_producer import get_next_queued, mark_published as queue_mark_published
        queued = get_next_queued()

    localizations = None

    if queued:
        print(f"\n[freq_main] Kuyruk modu — {queued['scheduled_date']} / {queued['freq_name']}")
        with open(queued["script_path"], encoding="utf-8") as f:
            script = json.load(f)
        audio_path = queued["audio_path"]
        video_path = queued["video_path"]
    else:
        # 1) Frekans seç
        topic = pick_topic(hz_override)
        print(f"\n[freq_main] Seçilen frekans: {topic['name']} — {topic['short_benefit']}")

        # 2) Script/metadata üret (Gemini)
        print("\n[freq_main] Metadata üretiliyor...")
        script = _step(
            "Script üretimi",
            lambda: generate_freq_script(topic),
            topic["name"],
        )
        save_freq_script(script, FREQ_SCRIPT_PATH)
        print(f"[freq_main] Başlık: {script['title']}")
        print(f"[freq_main] Hook: {script['hook_line']}")

        # 2.5) Çoklu dil çevirileri üret — başarısız olursa video lokalizasyonsuz yüklenir
        print("\n[freq_main] Çoklu dil çevirileri üretiliyor...")
        try:
            localizations = generate_localizations(script)
        except Exception as _loc_err:
            print(f"[freq_main] Localization üretilemedi (kritik değil): {_loc_err}")
            localizations = None

        # 3) Frekans sesi üret
        print(f"\n[freq_main] {topic['hz']} Hz ses üretiliyor...")
        audio_path = _step(
            "Ses üretimi",
            lambda: generate_frequency_audio(
                hz=float(topic["hz"]),
                output_mp3=FREQ_AUDIO_PATH,
            ),
            topic["name"],
        )

        # 4) Video üret
        print("\n[freq_main] Video montajı yapılıyor...")
        video_path = _step(
            "Video montajı",
            lambda: build_freq_video(script, audio_path, FREQ_VIDEO_PATH),
            topic["name"],
        )

    if dry_run:
        # Localization bilgisini script JSON'a ekleyip tekrar kaydet
        if localizations:
            script["localizations"] = localizations
            save_freq_script(script, FREQ_SCRIPT_PATH)

        print("\n" + "=" * 52)
        print("✅  DRY RUN TAMAMLANDI (upload atlandı)")
        print(f"   Script → {FREQ_SCRIPT_PATH}")
        print(f"   Ses    → {audio_path}")
        print(f"   Video  → {video_path}")
        print("=" * 52)
        return

    # 5) YouTube'a yükle
    print("\n[freq_main] YouTube'a yükleniyor...")
    from uploader import upload_video, build_description

    base_tags = [
        "Neuro-Frequency", "Neural Frequency", "Healing Frequency", "Meditation Music",
        "Binaural Beats", "Solfeggio Frequencies", "Nervous System", "Brain Waves",
        "Sound Therapy", "ADHD", "ADHD Focus", "Shorts",
    ]
    upload_tags = list(dict.fromkeys(script["tags"] + base_tags))

    hz_val = script.get("hz", "")
    short_benefit = script.get("short_benefit", "")
    description_fallback = (
        f"{script['title']}\n\n"
        f"{short_benefit} — {script.get('freq_name', f'{hz_val} Hz')} neuro-frequency session.\n\n"
        f"🎧 Use headphones for full binaural effect.\n\n"
        f"Follow for daily neuro-frequency sessions.\n\n"
        f"#NeuralFrequency #NeuroFrequency #HealingFrequency #MeditationMusic #BinauralBeats #Shorts"
    )
    description = script.get("description") or description_fallback

    video_id = _step(
        "YouTube upload",
        lambda: upload_video(
            video_path=video_path,
            title=script["title"],
            description=description,
            tags=upload_tags,
            thumbnail_path=None,  # opsiyonel: thumbnail eklenebilir
            localizations=localizations,
            category_id="10",  # Music
        ),
        topic["name"],
    )

    if queued:
        from freq_batch_producer import mark_published as queue_mark_published
        queue_mark_published(queued["scheduled_date"])
        print(f"[freq_main] Kuyruk güncellendi: {queued['scheduled_date']} → yayınlandı")

    print(f"\n[freq_main] Video yüklendi: https://youtube.com/shorts/{video_id}")

    # 6) Telegram bildirimi
    print("\n[freq_main] Bildirim gönderiliyor...")
    try:
        send_notification(
            title=script["title"],
            video_id=video_id,
            duration_sec=15,
            tags=script["tags"],
        )
    except Exception as e:
        print(f"[freq_main] Telegram bildirimi gönderilemedi (kritik değil): {e}")

    print("\n" + "=" * 52)
    print(f"✅  TAMAMLANDI! (FREQ SHORTS)")
    print(f"   https://youtube.com/shorts/{video_id}")
    print("=" * 52)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FREQ SHORTS Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Upload olmadan test et")
    parser.add_argument("--hz", type=float, default=None, help="Belirli bir frekans Hz değeri")
    args = parser.parse_args()

    try:
        run(dry_run=args.dry_run, hz_override=args.hz)
    except Exception as e:
        print(f"\n❌ Pipeline başarısız: {e}", file=sys.stderr)
        sys.exit(1)
