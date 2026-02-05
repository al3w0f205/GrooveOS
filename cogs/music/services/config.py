# cogs/music/services/config.py
from __future__ import annotations

UA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/121.0 Safari/537.36"
    )
}

# --- Scraping / import ---
SCRAPE_TIMEOUT = 10
MAX_SCRAPED_TRACKS = 80
MAX_IMPORT_LINES = 200
MAX_YT_PLAYLIST_ITEMS = 300
IMPORT_WAIT_SECONDS = 45

# --- Cache ---
CACHE_FOLDER = "cache_audio"
CACHE_MAX_AGE_MINUTES = 90

# --- Autoplay ---
AUTOPLAY_ENABLED_DEFAULT = True
AUTOPLAY_COOLDOWN = 2.0
AUTOPLAY_MIN_DURATION = 60
AUTOPLAY_MAX_DURATION = 12 * 60
AUTOPLAY_MIN_OVERLAP = 2

AUTOPLAY_PARANOID = True
AUTOPLAY_DUP_SIM_THRESHOLD = 0.86
AUTOPLAY_DUP_TOKEN_OVERLAP = 0.65
AUTOPLAY_RECENT_BUFFER = 30

# --- yt-dlp ---
# OJO: para evitar el error de formato, mejor NO forzar formatos raros.
# Dejamos bestaudio y que FFmpeg haga la extracción a mp3.
YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "ignoreerrors": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
    "outtmpl": f"{CACHE_FOLDER}/%(id)s-%(title).60s.%(ext)s",
    "postprocessors": [
        {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
    ],
}

# --- FFmpeg ---
# reconnect ayuda a streams que se cortan
FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}