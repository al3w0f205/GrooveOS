# cogs/music/config.py

# ==========================================
# ⚙️ CONFIGURACIÓN DE AUDIO (Proxmox-safe)
# ==========================================
YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "outtmpl": "cache_audio/%(extractor)s-%(id)s-%(title)s.%(ext)s",
    "restrictfilenames": True,
    "windowsfilenames": True,
    "overwrites": True,

    # ✅ mantenemos esto True para evitar que yt-dlp intente bajar playlists
    "noplaylist": True,

    "nocheckcertificate": True,
    "ignoreerrors": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
}

# ✅ Estabilidad Discord Voice (48kHz/2ch) + reconexión
FFMPEG_OPTIONS = {
    "options": "-vn -loglevel quiet -ar 48000 -ac 2 -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
}

# ==========================================
# 🎧 AUTOPLAY SETTINGS (estricto)
# ==========================================
AUTOPLAY_MAX_DURATION = 10 * 60   # máx 10 min
AUTOPLAY_MIN_DURATION = 45        # min 45s
AUTOPLAY_MIN_OVERLAP = 3          # mínimo 3 palabras en común
AUTOPLAY_COOLDOWN = 2.0

# ==========================================
# 🧨 AUTOPLAY PARANOID (anti-duplicados fuerte)
# ==========================================
AUTOPLAY_PARANOID = True
AUTOPLAY_DUP_SIM_THRESHOLD = 0.92
AUTOPLAY_DUP_TOKEN_OVERLAP = 0.78
AUTOPLAY_RECENT_BUFFER = 80

# ==========================================
# 🧩 PLAYLIST / IMPORT SETTINGS
# ==========================================
SCRAPE_TIMEOUT = 12
MAX_SCRAPED_TRACKS = 250
MAX_IMPORT_LINES = 350
MAX_YT_PLAYLIST_ITEMS = 400
IMPORT_WAIT_SECONDS = 90

UA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
}
