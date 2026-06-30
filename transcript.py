#!/usr/bin/env python3
"""
YouTube video transcript indirici.

Kullanım:
    ./transcript.py https://www.youtube.com/watch?v=VIDEO_ID
    ./transcript.py https://youtu.be/VIDEO_ID
    ./transcript.py VIDEO_ID

İsteğe bağlı:
    ./transcript.py <url> --lang tr      # tercih edilen dil
    ./transcript.py <url> --list         # mevcut altyazı dillerini listele
    ./transcript.py <url> --timestamps   # zaman damgalı çıktı

Gereksinim:
    python -m pip install youtube-transcript-api

Not: 'innertube' kütüphanesi artık YouTube'un bot korumaları nedeniyle
transcript çekemiyor (eski client sürümleri reddediliyor). Bu yüzden bu
script bakımı yapılan youtube-transcript-api kullanıyor.
"""

import sys

import argparse

from app.config import Settings
from app.transcripts import (
    TranscriptServiceError,
    extract_video_id,
    fetch_youtube_transcript,
    format_timestamp,
    list_youtube_transcript_languages,
)


fmt_ts = format_timestamp


def main():
    ap = argparse.ArgumentParser(description="YouTube video transcript indirici")
    ap.add_argument("url", help="YouTube URL ya da video id")
    ap.add_argument("--lang", help="Tercih edilen dil kodu (örn. tr, en)", default=None)
    ap.add_argument("--list", action="store_true", help="Mevcut altyazı dillerini listele")
    ap.add_argument("--timestamps", action="store_true", help="Zaman damgalı çıktı")
    args = ap.parse_args()

    try:
        settings = Settings.from_env()
        if args.list:
            result = list_youtube_transcript_languages(args.url, settings=settings)
            for language in result["languages"]:
                kind = "AUTO " if language["is_generated"] else "MANUEL"
                print(f"{kind} {language['language_code']:8} {language['language']}")
            return

        result = fetch_youtube_transcript(args.url, lang=args.lang, timestamps=args.timestamps, settings=settings)
        for snippet in result["segments"]:
            if args.timestamps:
                print(f"[{snippet['timestamp']}] {snippet['text']}")
            else:
                print(snippet["text"])

    except (ValueError, TranscriptServiceError) as e:
        print(f"Hata: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
