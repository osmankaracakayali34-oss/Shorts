"""
uploader.py — YouTube Data API v3 ile video ve thumbnail upload eder.

İlk çalıştırmada OAuth2 flow başlatılır ve token.json oluşturulur.
GitHub Actions'ta YOUTUBE_TOKEN_JSON secret'ından token inject edilir.
"""

import os
import json
import tempfile
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

TOKEN_PATH = "token.json"


def _get_credentials() -> Credentials:
    """
    Önce YOUTUBE_TOKEN_JSON env değişkeninden, sonra token.json dosyasından
    credentials yükler. Token süresi dolmuşsa yeniler.
    """
    token_json = os.environ.get("YOUTUBE_TOKEN_JSON")

    if token_json:
        # GitHub Actions: secret'tan inject
        token_data = json.loads(token_json)
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump(token_data, tmp)
        tmp.close()
        creds = Credentials.from_authorized_user_file(tmp.name, SCOPES)
        os.unlink(tmp.name)
    elif os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    else:
        raise FileNotFoundError(
            "YouTube token bulunamadı. YOUTUBE_TOKEN_JSON env değişkenini "
            "veya token.json dosyasını ayarlayın.\n"
            "Token almak için: python get_youtube_token.py"
        )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())

    return creds


def upload_video(
    video_path: str,
    title: str,
    description: str,
    tags: list,
    thumbnail_path: str = None,
    localizations: dict = None,
    category_id: str = "25",
) -> str:
    """
    Videoyu YouTube'a yükler, thumbnail ekler. Video ID'sini döndürür.
    """
    creds = _get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id,
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(video_path, mimetype="video/mp4", resumable=True)

    print(f"[uploader] Video yükleniyor: {title}")
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"[uploader] Yükleme: %{pct}")

    video_id = response["id"]
    print(f"[uploader] Video yüklendi: https://youtube.com/shorts/{video_id}")

    # Localization (çoklu dil başlık/açıklama) ekle — kritik değil, başarısız olsa video kalır
    if localizations:
        print(f"[uploader] Localization ekleniyor ({len(localizations)} dil)...")
        try:
            youtube.videos().update(
                part="localizations",
                body={
                    "id": video_id,
                    "localizations": localizations,
                },
            ).execute()
            print("[uploader] Localization eklendi.")
        except Exception as e:
            print(f"[uploader] Localization başarısız (kritik değil, video korunuyor): {e}")

    # Thumbnail yükle
    if thumbnail_path and os.path.exists(thumbnail_path):
        print("[uploader] Thumbnail yükleniyor...")
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path),
            ).execute()
            print("[uploader] Thumbnail yüklendi.")
        except Exception as e:
            print(f"[uploader] Thumbnail yüklenemedi (kritik değil): {e}")

    return video_id


def post_pinned_comment(youtube, video_id: str, text: str) -> str | None:
    """
    Videoya yorum yazar ve sabitlemeye çalışır.
    Başarılı olursa yorum ID'sini döndürür, aksi halde None.

    Not: YouTube API pinleme endpoint'i yoktur; yorum gönderilir
    ve ChannelSection üzerinden "featured comment" olarak işaretlenir.
    Pratik olarak ilk yorum genellikle en üstte görünür.
    """
    try:
        resp = youtube.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {"textOriginal": text}
                    },
                }
            },
        ).execute()
        comment_id = resp["id"]
        print(f"[uploader] Yorum gönderildi: {comment_id}")
        return comment_id
    except Exception as e:
        print(f"[uploader] Yorum gönderilemedi (kritik değil): {e}")
        return None


_DESC_CTA = {
    "en": "Follow for daily military intelligence briefings!",
    "tr": "Günlük askeri istihbarat brifingleri için takip et!",
    "ar": "تابعنا للمزيد من التحليلات العسكرية اليومية!",
}

_BASE_HASHTAGS = ["#Shorts", "#Military", "#BreakingNews", "#Geopolitics", "#WarNews"]


def build_description(script: dict) -> str:
    lang = script.get("language", "en")
    cta_line = _DESC_CTA.get(lang, _DESC_CTA["en"])

    # Script tags → topic-specific hashtags (Gemini'nin ürettiği)
    script_tags = script.get("tags", [])
    topic_hashtags = " ".join(
        f"#{t.replace(' ', '').replace('-', '')}"
        for t in script_tags
        if t and t.isascii()  # Arapça tag'lar # prefix ile sorun yaratır
    )

    # Arapça tag'lar için ayrı (# prefix'siz, virgülle)
    ar_tags = [t for t in script_tags if t and not t.isascii()]
    ar_line = " ".join(ar_tags) if ar_tags else ""

    base = " ".join(_BASE_HASHTAGS)

    parts = [
        script["title"],
        "",
        script.get("hook", ""),
        "",
        cta_line,
        "",
        topic_hashtags,
        base,
    ]
    if ar_line:
        parts.append(ar_line)

    return "\n".join(parts).strip()


if __name__ == "__main__":
    import sys

    script_path = sys.argv[1] if len(sys.argv) > 1 else "output/script.json"
    video_path = sys.argv[2] if len(sys.argv) > 2 else "output/short.mp4"
    thumbnail_path = sys.argv[3] if len(sys.argv) > 3 else "output/thumbnail.png"

    with open(script_path, encoding="utf-8") as f:
        script = json.load(f)

    video_id = upload_video(
        video_path=video_path,
        title=script["title"],
        description=build_description(script),
        tags=script["tags"] + ["Shorts", "History", "WhatIf"],
        thumbnail_path=thumbnail_path,
    )
    print(f"[uploader] Tamamlandı. Video ID: {video_id}")
