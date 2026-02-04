import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import ctypes.util
import requests
from bs4 import BeautifulSoup
import random
import time
import re
import difflib
import json
from collections import deque
from urllib.parse import urlparse

from .utilidad import THEME, user_footer, fmt_time, short_queue_preview, clean_query

# ✅ IMPORTS nuevos (desde la carpeta cogs/music/)
from .music.config import (
    AUTOPLAY_MAX_DURATION, AUTOPLAY_MIN_DURATION, AUTOPLAY_MIN_OVERLAP, AUTOPLAY_COOLDOWN,
    AUTOPLAY_PARANOID, AUTOPLAY_DUP_SIM_THRESHOLD, AUTOPLAY_DUP_TOKEN_OVERLAP, AUTOPLAY_RECENT_BUFFER,
    SCRAPE_TIMEOUT, MAX_SCRAPED_TRACKS, MAX_IMPORT_LINES, MAX_YT_PLAYLIST_ITEMS, IMPORT_WAIT_SECONDS,
    UA_HEADERS, YTDL_OPTIONS
)
from .music.source import YTDLSource
from .music.ui import ControlesMusica


# ==========================================
# COG MÚSICA
# ==========================================
class Musica(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        # Cola / estado
        self.song_queue = []
        self.loop_enabled = False
        self.current_track = None

        # Preload
        self.preloaded_player = None
        self.preloaded_query = None

        # Panel / barra
        self.barra_task = None

        # Panel references
        self.panel_msg = None
        self.panel_start_time = None
        self.panel_duration = 0
        self.panel_data = None
        self.panel_ctx = None
        self.panel_view = None

        # Autoplay
        self.autoplay_enabled = True
        self._autoplay_flip = False
        self.autoplay_history = []
        self.autoplay_fingerprints = set()
        self.autoplay_lock = asyncio.Lock()
        self.last_autoplay_time = 0.0
        self.autoplay_cooldown = AUTOPLAY_COOLDOWN

        # Paranoid buffers
        self.autoplay_core_fingerprints = set()
        self.autoplay_recent_core_titles = deque(maxlen=AUTOPLAY_RECENT_BUFFER)

        # Cargar Opus
        opus_path = ctypes.util.find_library("opus")
        if opus_path:
            try:
                discord.opus.load_opus(opus_path)
            except Exception:
                pass

        os.makedirs("cache_audio", exist_ok=True)

    # -------------------------
    # Utils
    # -------------------------
    def cleanup_file(self, filename):
        if filename and os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass

    def purge_old_cache(self, folder="cache_audio", max_age_minutes=90):
        if not os.path.isdir(folder):
            return
        now = time.time()
        max_age = max_age_minutes * 60
        for fn in os.listdir(folder):
            path = os.path.join(folder, fn)
            try:
                if os.path.isfile(path) and (now - os.path.getmtime(path)) > max_age:
                    os.remove(path)
            except Exception:
                pass

    def _has_listeners(self, vc: discord.VoiceClient) -> bool:
        try:
            if not vc or not vc.channel:
                return False
            humans = [m for m in vc.channel.members if not m.bot]
            return len(humans) > 0
        except Exception:
            return False

    async def preload_next(self, query):
        try:
            if self.preloaded_query == query and self.preloaded_player:
                return

            if self.preloaded_player and getattr(self.preloaded_player, "filename", None):
                self.cleanup_file(self.preloaded_player.filename)

            player = await YTDLSource.from_query(query, loop=self.bot.loop)
            if player:
                self.preloaded_player = player
                self.preloaded_query = query
        except Exception as e:
            print(f"❌ Error en pre-carga: {e}")

    # -------------------------
    # 🔎 Playlist / import helpers
    # -------------------------
    def _is_youtube_playlist(self, q: str) -> bool:
        q = (q or "").strip()
        if "youtube.com/playlist" in q:
            return True
        if "list=" in q and ("youtube.com" in q or "youtu.be" in q):
            return True
        return False

    def _is_spotify(self, q: str) -> bool:
        return "open.spotify.com" in (q or "")

    def _is_applemusic(self, q: str) -> bool:
        return "music.apple.com" in (q or "")

    def _spotify_embed_url(self, url: str) -> str:
        try:
            u = urlparse(url)
            parts = u.path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] == "playlist":
                return f"https://open.spotify.com/embed/playlist/{parts[1]}"
        except Exception:
            pass
        return url

    def _dedupe_keep_order(self, items):
        seen = set()
        out = []
        for x in items:
            x = (x or "").strip()
            if not x:
                continue
            if x in seen:
                continue
            seen.add(x)
            out.append(x)
        return out

    def _clean_track_text(self, s: str) -> str:
        s = (s or "").strip()
        s = re.sub(r"\s+", " ", s)
        s = s.replace("–", "-").replace("—", "-")
        return s.strip()

    def _extract_names_from_jsonld(self, soup: BeautifulSoup) -> list[str]:
        tracks = []
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                raw = script.string
                if not raw:
                    continue
                data = json.loads(raw)
                candidates = data if isinstance(data, list) else [data]
                for obj in candidates:
                    if not isinstance(obj, dict):
                        continue

                    ile = obj.get("itemListElement") or []
                    for it in ile:
                        if isinstance(it, dict):
                            name = it.get("name")
                            if name:
                                tracks.append(self._clean_track_text(name))
                            item = it.get("item") or {}
                            if isinstance(item, dict):
                                name2 = item.get("name")
                                if name2:
                                    tracks.append(self._clean_track_text(name2))

                    tr = obj.get("track") or []
                    if isinstance(tr, list):
                        for t in tr:
                            if isinstance(t, dict) and t.get("name"):
                                tracks.append(self._clean_track_text(t["name"]))
            except Exception:
                continue
        return tracks

    def _extract_names_spotify(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")

        meta_tracks = [
            m.get("content")
            for m in soup.find_all("meta", property="music:song")
            if m.get("content")
        ]

        jsonld_tracks = self._extract_names_from_jsonld(soup)

        regex_tracks = []
        for m in re.finditer(r'"name"\s*:\s*"([^"]{2,120})"\s*,\s*"uri"\s*:\s*"spotify:track:', html):
            regex_tracks.append(self._clean_track_text(m.group(1)))

        tracks = self._dedupe_keep_order(meta_tracks + jsonld_tracks + regex_tracks)
        return tracks[:MAX_SCRAPED_TRACKS]

    def _extract_names_apple(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        jsonld_tracks = self._extract_names_from_jsonld(soup)

        regex_tracks = []
        for m in re.finditer(r'"name"\s*:\s*"([^"]{2,120})"\s*,\s*"@type"\s*:\s*"MusicRecording"', html):
            regex_tracks.append(self._clean_track_text(m.group(1)))

        tracks = self._dedupe_keep_order(jsonld_tracks + regex_tracks)
        return tracks[:MAX_SCRAPED_TRACKS]

    async def scrape_playlist_to_yt_queries(self, url: str) -> list[str]:
        try:
            fetch_url = self._spotify_embed_url(url) if self._is_spotify(url) else url
            r = requests.get(fetch_url, headers=UA_HEADERS, timeout=SCRAPE_TIMEOUT)
            html = r.text or ""

            if self._is_spotify(url):
                names = self._extract_names_spotify(html)
            elif self._is_applemusic(url):
                names = self._extract_names_apple(html)
            else:
                names = []

            # spotify: si embed no funcionó, intenta normal
            if self._is_spotify(url) and not names and fetch_url != url:
                r2 = requests.get(url, headers=UA_HEADERS, timeout=SCRAPE_TIMEOUT)
                names = self._extract_names_spotify(r2.text or "")

            out = []
            for name in names:
                name = self._clean_track_text(name)
                if not name:
                    continue
                out.append(f"ytsearch1:{name} audio")

            return out[:MAX_SCRAPED_TRACKS]
        except Exception as e:
            print(f"❌ scrape_playlist_to_yt_queries error: {e}")
            return []

    async def expand_youtube_playlist(self, url: str) -> list[str]:
        loop = self.bot.loop
        try:
            opts = dict(YTDL_OPTIONS)
            opts.update({
                "noplaylist": False,
                "extract_flat": "in_playlist",
                "skip_download": True,
                "quiet": True,
                "no_warnings": True,
                "ignoreerrors": True,
            })
            ydlp = yt_dlp.YoutubeDL(opts)
            info = await loop.run_in_executor(None, lambda: ydlp.extract_info(url, download=False))
            entries = (info or {}).get("entries") or []
            out = []
            for e in entries:
                if not e:
                    continue
                vid = e.get("id") or e.get("url")
                if not vid:
                    continue
                if isinstance(vid, str) and vid.startswith("http"):
                    out.append(vid)
                else:
                    out.append(f"https://www.youtube.com/watch?v={vid}")
                if len(out) >= MAX_YT_PLAYLIST_ITEMS:
                    break
            return out
        except Exception as e:
            print(f"❌ expand_youtube_playlist error: {e}")
            return []

    async def enqueue_many(self, ctx, queries: list[str]):
        if not queries:
            return False
        for q in queries:
            self.song_queue.append(q)

        if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
            await self.play_music(ctx, self.song_queue.pop(0))
        else:
            if len(self.song_queue) == 1:
                self.bot.loop.create_task(self.preload_next(self.song_queue[0]))
        return True

    async def _read_attachment_to_lines(self, attachment: discord.Attachment) -> list[str]:
        try:
            fname = (attachment.filename or "").lower()
            if not (fname.endswith(".txt") or fname.endswith(".csv")):
                return []

            data = await attachment.read()
            text = data.decode("utf-8", errors="ignore")

            lines = []
            if fname.endswith(".txt"):
                lines = [self._clean_track_text(x) for x in text.splitlines()]
                lines = [x for x in lines if x]
                return lines[:MAX_IMPORT_LINES]

            raw_lines = text.splitlines()
            if not raw_lines:
                return []

            sep = "," if "," in raw_lines[0] else ";"
            cols = [c.strip() for c in raw_lines[0].split(sep)]
            col_map = {c.lower(): i for i, c in enumerate(cols)}

            track_keys = ["track", "title", "song", "name"]
            artist_keys = ["artist", "artists", "band"]

            track_idx = next((col_map[k] for k in track_keys if k in col_map), None)
            artist_idx = next((col_map[k] for k in artist_keys if k in col_map), None)

            for row in raw_lines[1:]:
                parts = [p.strip() for p in row.split(sep)]
                if not parts:
                    continue

                if track_idx is not None and track_idx < len(parts):
                    t = parts[track_idx]
                    a = parts[artist_idx] if artist_idx is not None and artist_idx < len(parts) else ""
                    name = f"{a} - {t}".strip(" -")
                    name = self._clean_track_text(name)
                    if name:
                        lines.append(name)
                else:
                    rr = self._clean_track_text(row)
                    if rr:
                        lines.append(rr)

                if len(lines) >= MAX_IMPORT_LINES:
                    break

            return lines[:MAX_IMPORT_LINES]
        except Exception as e:
            print(f"❌ _read_attachment_to_lines error: {e}")
            return []

    async def interactive_import_fallback(self, ctx, reason_text: str = "") -> list[str]:
        prompt = (
            f"{reason_text}\n"
            f"📥 **Modo Import (automático)**\n"
            f"➡️ Pega la lista (1 canción por línea) **O** adjunta un **.txt/.csv**.\n"
            f"⏱️ Tienes **{IMPORT_WAIT_SECONDS}s**. Escribe `cancel` para cancelar."
        ).strip()

        await ctx.send(prompt)

        def check(m: discord.Message):
            if m.author != ctx.author:
                return False
            if m.channel != ctx.channel:
                return False
            return bool((m.content and m.content.strip()) or m.attachments)

        try:
            m = await self.bot.wait_for("message", timeout=IMPORT_WAIT_SECONDS, check=check)
        except asyncio.TimeoutError:
            await ctx.send("⏱️ Tiempo agotado. Intenta de nuevo con `.p <link>` o pega la lista.")
            return []

        if (m.content or "").strip().lower() == "cancel":
            await ctx.send("✅ Import cancelado.")
            return []

        if m.attachments:
            lines = await self._read_attachment_to_lines(m.attachments[0])
            if lines:
                return [f"ytsearch1:{ln} audio" for ln in lines if ln][:MAX_IMPORT_LINES]

        text = (m.content or "").strip()
        lines = [self._clean_track_text(x) for x in text.splitlines()]
        lines = [x for x in lines if x]
        if not lines:
            await ctx.send("⚠️ No detecté canciones válidas. Intenta de nuevo.")
            return []

        lines = lines[:MAX_IMPORT_LINES]
        return [f"ytsearch1:{ln} audio" for ln in lines if ln]

    # -------------------------
    # AUTOPLAY helpers (anti repetidos + estricto)
    # -------------------------
    def _history_has(self, key: str) -> bool:
        return key in self.autoplay_history

    def _history_add(self, key: str, cap: int = 250):
        if not key:
            return
        if key in self.autoplay_history:
            return
        self.autoplay_history.append(key)
        if len(self.autoplay_history) > cap:
            self.autoplay_history = self.autoplay_history[-cap:]

    def _duration_ok(self, entry: dict) -> bool:
        if not entry:
            return False
        if entry.get("is_live") or entry.get("live_status") in ("is_live", "live"):
            return False
        dur = entry.get("duration", None)
        if dur is None:
            return False
        try:
            dur = int(dur)
        except Exception:
            return False
        if dur < AUTOPLAY_MIN_DURATION:
            return False
        if dur > AUTOPLAY_MAX_DURATION:
            return False
        return True

    def _normalize_text(self, s: str) -> str:
        s = (s or "").lower()
        trash = [
            "official video", "official music video", "official audio", "audio",
            "lyrics", "lyric video", "video oficial", "videoclip", "visualizer",
            "explicit", "clean", "hq", "4k", "hd", "mv", "m/v"
        ]
        for t in trash:
            s = s.replace(t, "")

        s = s.replace("feat.", "feat").replace("ft.", "ft").replace("featuring", "feat")
        s = re.sub(r"\([^)]*\)", " ", s)
        s = re.sub(r"\[[^\]]*\]", " ", s)

        for ch in "{}|.,!?:;\"'`~@#$%^&*_+=<>/\\-":
            s = s.replace(ch, " ")

        s = " ".join(s.split())
        return s

    def _core_title(self, title: str) -> str:
        t = self._normalize_text(title)
        drop = {
            "official", "video", "music", "audio", "lyrics", "lyric", "visualizer",
            "remix", "edit", "version", "ver", "mix", "extended", "radio", "live",
            "performance", "sped", "up", "slowed", "reverb", "bass", "boosted",
            "instrumental", "karaoke", "clean", "explicit", "tiktok",
            "prod", "producer", "produced",
        }
        tokens = [w for w in t.split() if w not in drop and len(w) > 1]
        core = " ".join(tokens)
        return core.strip()[:120]

    def _fingerprint(self, title: str, uploader: str) -> str:
        t = self._normalize_text(title)[:90]
        u = self._normalize_text(uploader)[:50]
        return f"{t}::{u}"

    def _core_fingerprint(self, title: str) -> str:
        return self._core_title(title)

    def _seed_tokens(self, title: str, uploader: str) -> set:
        base = self._normalize_text(f"{title} {uploader}")
        return set(base.split())

    def _score_candidate(self, seed_tokens: set, cand_title: str, cand_uploader: str) -> int:
        cand_tokens = set(self._normalize_text(f"{cand_title} {cand_uploader}").split())
        return len(seed_tokens & cand_tokens)

    def _passes_strictness(self, overlap: int, seed_uploader: str, cand_title: str, cand_uploader: str) -> bool:
        if overlap >= AUTOPLAY_MIN_OVERLAP:
            return True
        su = self._normalize_text(seed_uploader)
        if not su:
            return False
        ct = self._normalize_text(cand_title)
        cu = self._normalize_text(cand_uploader)
        if su and (su in cu or su in ct):
            return True
        return False

    def _near_duplicate_by_core(self, cand_title: str) -> bool:
        if not AUTOPLAY_PARANOID:
            return False
        core = self._core_title(cand_title)
        if not core or len(core) < 4:
            return False
        if core in self.autoplay_core_fingerprints:
            return True

        cand_tokens = set(core.split())
        if not cand_tokens:
            return False

        for prev in self.autoplay_recent_core_titles:
            if not prev:
                continue
            ratio = difflib.SequenceMatcher(None, core, prev).ratio()
            if ratio >= AUTOPLAY_DUP_SIM_THRESHOLD:
                return True
            prev_tokens = set(prev.split())
            if not prev_tokens:
                continue
            inter = len(cand_tokens & prev_tokens)
            union = len(cand_tokens | prev_tokens)
            if union > 0:
                j = inter / union
                if j >= AUTOPLAY_DUP_TOKEN_OVERLAP:
                    return True
        return False

    def _already_used(self, url: str, fp: str, cand_title: str = "") -> bool:
        if not url:
            return True
        if self.current_track and url == self.current_track:
            return True
        if url in self.song_queue:
            return True
        if fp in self.autoplay_fingerprints:
            return True
        if cand_title and self._near_duplicate_by_core(cand_title):
            return True
        return False

    def _register_now_playing_for_autoplay(self, data: dict):
        try:
            if not data:
                return

            url_now = (data.get("webpage_url") or data.get("url") or "").strip()
            vid_now = (data.get("id") or "").strip()

            title_now = data.get("title") or ""
            upl_now = data.get("uploader") or data.get("channel") or ""

            key_now = str(vid_now or url_now).strip()
            if key_now:
                self._history_add(key_now)

            fp_now = self._fingerprint(title_now, upl_now)
            if fp_now:
                self.autoplay_fingerprints.add(fp_now)

            core_fp = self._core_fingerprint(title_now)
            if core_fp:
                self.autoplay_core_fingerprints.add(core_fp)
                self.autoplay_recent_core_titles.append(core_fp)

        except Exception as e:
            print(f"⚠️ register_now_playing error: {e}")

    async def _search_youtube(self, query: str):
        loop = self.bot.loop
        try:
            # usamos el ytdl global de yt_dlp (config ya cargada)
            ytdl_local = yt_dlp.YoutubeDL(YTDL_OPTIONS)
            info = await loop.run_in_executor(None, lambda: ytdl_local.extract_info(query, download=False))
            return (info or {}).get("entries") or []
        except Exception as e:
            print(f"❌ Autoplay search error: {e}")
            return []

    async def get_autoplay_candidate(self, seed_data: dict):
        if not seed_data:
            return None

        seed_title = (seed_data.get("title") or "").strip()
        seed_uploader = (seed_data.get("uploader") or "").strip()
        seed_url = (seed_data.get("webpage_url") or "").strip()
        seed_id = seed_data.get("id")

        if not seed_title and not seed_uploader:
            return None

        seed_tokens = self._seed_tokens(seed_title, seed_uploader)

        # 1) related_videos
        if seed_url:
            try:
                ytdl_local = yt_dlp.YoutubeDL(YTDL_OPTIONS)
                info = await self.bot.loop.run_in_executor(None, lambda: ytdl_local.extract_info(seed_url, download=False))
                related = (info or {}).get("related_videos") or []

                best = None
                best_overlap = -1

                for e in related:
                    if not e or not self._duration_ok(e):
                        continue

                    url = e.get("webpage_url") or e.get("url")
                    vid = e.get("id")
                    if not url:
                        continue
                    if seed_id and vid == seed_id:
                        continue

                    cand_title = e.get("title") or ""
                    cand_uploader = e.get("uploader") or e.get("channel") or ""

                    if AUTOPLAY_PARANOID:
                        if self._near_duplicate_by_core(cand_title):
                            continue
                        if self._core_title(cand_title) and self._core_title(seed_title):
                            r = difflib.SequenceMatcher(None, self._core_title(cand_title), self._core_title(seed_title)).ratio()
                            if r >= AUTOPLAY_DUP_SIM_THRESHOLD:
                                continue

                    overlap = self._score_candidate(seed_tokens, cand_title, cand_uploader)
                    if not self._passes_strictness(overlap, seed_uploader, cand_title, cand_uploader):
                        continue

                    fp = self._fingerprint(cand_title, cand_uploader)
                    key = str(vid or url)

                    if self._history_has(key):
                        continue
                    if self._already_used(url, fp, cand_title=cand_title):
                        continue

                    if overlap > best_overlap:
                        best_overlap = overlap
                        best = (url, fp, key, cand_title)

                if best:
                    url, fp, key, cand_title = best
                    self._history_add(key)
                    self.autoplay_fingerprints.add(fp)

                    if AUTOPLAY_PARANOID:
                        core_fp = self._core_fingerprint(cand_title)
                        if core_fp:
                            self.autoplay_core_fingerprints.add(core_fp)
                            self.autoplay_recent_core_titles.append(core_fp)

                    return url

            except Exception as e:
                print(f"❌ related_videos error: {e}")

        # 2) fallback
        self._autoplay_flip = not self._autoplay_flip

        if self._autoplay_flip:
            base = f"{seed_title} {seed_uploader}".strip()
            queries = [
                f"ytsearch15:{base} audio",
                f"ytsearch15:{seed_title} audio",
                f"ytsearch15:{base} official audio",
            ]
        else:
            base = seed_uploader or seed_title
            queries = [
                f"ytsearch15:{base} mix",
                f"ytsearch15:{base} official audio",
                f"ytsearch15:{base} topic audio",
            ]

        best = None
        best_overlap = -1

        for q in queries:
            entries = await self._search_youtube(q)
            for e in entries:
                if not e or not self._duration_ok(e):
                    continue

                url = e.get("webpage_url") or e.get("url")
                vid = e.get("id")
                if not url:
                    continue
                if seed_id and vid == seed_id:
                    continue

                cand_title = e.get("title") or ""
                cand_uploader = e.get("uploader") or e.get("channel") or ""

                if AUTOPLAY_PARANOID:
                    if self._near_duplicate_by_core(cand_title):
                        continue
                    if self._core_title(cand_title) and self._core_title(seed_title):
                        r = difflib.SequenceMatcher(None, self._core_title(cand_title), self._core_title(seed_title)).ratio()
                        if r >= AUTOPLAY_DUP_SIM_THRESHOLD:
                            continue

                overlap = self._score_candidate(seed_tokens, cand_title, cand_uploader)
                if not self._passes_strictness(overlap, seed_uploader, cand_title, cand_uploader):
                    continue

                fp = self._fingerprint(cand_title, cand_uploader)
                key = str(vid or url)

                if self._history_has(key):
                    continue
                if self._already_used(url, fp, cand_title=cand_title):
                    continue

                if overlap > best_overlap:
                    best_overlap = overlap
                    best = (url, fp, key, cand_title)

        if best:
            url, fp, key, cand_title = best
            self._history_add(key)
            self.autoplay_fingerprints.add(fp)

            if AUTOPLAY_PARANOID:
                core_fp = self._core_fingerprint(cand_title)
                if core_fp:
                    self.autoplay_core_fingerprints.add(core_fp)
                    self.autoplay_recent_core_titles.append(core_fp)

            return url

        return None

    async def ensure_autoplay(self, ctx, seed_data: dict):
        if not self.autoplay_enabled:
            return
        if self.song_queue:
            return
        if not ctx.voice_client:
            return
        if not self._has_listeners(ctx.voice_client):
            return

        async with self.autoplay_lock:
            if not self.autoplay_enabled or self.song_queue or not ctx.voice_client:
                return
            if not self._has_listeners(ctx.voice_client):
                return

            now = time.time()
            if now - self.last_autoplay_time < self.autoplay_cooldown:
                return
            self.last_autoplay_time = now

            candidate = await self.get_autoplay_candidate(seed_data)
            if not candidate:
                return

            if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                return

            await self.play_music(ctx, candidate)

    # -------------------------
    # Panel minimalista (SIN barra)
    # -------------------------
    def build_now_playing_embed(self, ctx, paused=False):
        data = self.panel_data or {}
        duracion = int(self.panel_duration or 0)
        start_time = float(self.panel_start_time or time.time())

        titulo = data.get("title", "Desconocido")
        url = data.get("webpage_url", "")
        thumbnail = data.get("thumbnail")
        uploader = data.get("uploader", "Desconocido")

        elapsed = int(time.time() - start_time)
        elapsed = max(0, min(elapsed, duracion)) if duracion else max(0, elapsed)
        remaining = max(0, duracion - elapsed) if duracion else 0

        estado = "⏸️ Pausado" if paused else "▶️ Reproduciendo"
        color = THEME["warning"] if paused else THEME["primary"]
        loop_txt = "ON ✅" if self.loop_enabled else "OFF ❌"
        auto_txt = "ON ✅" if self.autoplay_enabled else "OFF ❌"

        desc = (
            f"**{estado}**\n"
            f"👤 **Artista/Canal:** `{uploader}`\n"
            f"──────────────\n"
        )

        embed = discord.Embed(
            title=f"🎶 {titulo}",
            url=url,
            description=desc,
            color=color
        )

        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        embed.add_field(
            name="⏱️ Tiempo",
            value=(
                f"🕒 **Transcurrido:** `{fmt_time(elapsed)}`\n"
                f"⏳ **Duración:** `{fmt_time(duracion)}`\n"
                f"⌛ **Restante:** `{fmt_time(remaining)}`"
            ),
            inline=False
        )

        preview = short_queue_preview(self.song_queue, limit=3)
        embed.add_field(
            name="📜 Próximas",
            value=f"{preview}\n\u200b",
            inline=False
        )

        embed.set_footer(**user_footer(ctx, f"Loop: {loop_txt} • Auto: {auto_txt}"))
        return embed

    async def actualizar_panel_loop(self):
        try:
            while True:
                await asyncio.sleep(10)
                if not self.panel_msg or not self.panel_ctx or not self.panel_data:
                    break
                vc = self.panel_ctx.voice_client
                if not vc:
                    break
                embed = self.build_now_playing_embed(self.panel_ctx, paused=vc.is_paused())
                await self.panel_msg.edit(embed=embed, view=self.panel_view)

                if self.panel_duration and (time.time() - self.panel_start_time) > self.panel_duration:
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Error panel: {e}")

    async def enviar_panel(self, ctx, player):
        data = player.data
        self.panel_ctx = ctx
        self.panel_data = data
        self.panel_duration = int(data.get("duration", 0))
        self.panel_start_time = time.time()

        view = ControlesMusica(ctx, self, data.get("webpage_url", ""))
        self.panel_view = view

        embed = self.build_now_playing_embed(ctx, paused=False)
        msg = await ctx.send(embed=embed, view=view)
        self.panel_msg = msg

        if self.barra_task:
            self.barra_task.cancel()
        self.barra_task = self.bot.loop.create_task(self.actualizar_panel_loop())

    # -------------------------
    # Playback
    # -------------------------
    async def play_next(self, ctx, last_file=None, seed_data=None):
        if self.barra_task:
            self.barra_task.cancel()

        if last_file:
            self.cleanup_file(last_file)

        if len(self.song_queue) > 0:
            await self.play_music(ctx, self.song_queue.pop(0))
        else:
            if seed_data and self.autoplay_enabled and not self.loop_enabled:
                await self.ensure_autoplay(ctx, seed_data)

    async def play_music(self, ctx, query):
        self.purge_old_cache()

        if self.preloaded_query == query and self.preloaded_player:
            player = self.preloaded_player
            self.preloaded_player = None
            self.preloaded_query = None
        else:
            msg = await ctx.send("💿 **Cargando...**")
            player = await YTDLSource.from_query(query, loop=self.bot.loop)
            if not player:
                return await msg.edit(content="❌ Error de descarga.")
            await msg.delete()

        try:
            data = player.data or {}
            url_now = (data.get("webpage_url") or data.get("url") or "").strip()
            self.current_track = url_now or query
            self._register_now_playing_for_autoplay(data)
        except Exception as e:
            print(f"⚠️ Error set current_track/register: {e}")
            self.current_track = query

        def after_playing(error):
            try:
                if self.barra_task:
                    self.barra_task.cancel()

                if error:
                    print(f"Error: {error}")

                if self.loop_enabled and self.current_track:
                    self.song_queue.insert(0, self.current_track)

                asyncio.run_coroutine_threadsafe(
                    self.play_next(ctx, player.filename, seed_data=player.data),
                    self.bot.loop
                )
            except Exception as e:
                print(f"❌ Error en after_playing: {e}")

        if not ctx.voice_client:
            return await ctx.send("🚫 No estoy conectado a voz. Usa `.join` primero.")

        ctx.voice_client.play(player, after=after_playing)
        await self.enviar_panel(ctx, player)

        if len(self.song_queue) > 0:
            self.bot.loop.create_task(self.preload_next(self.song_queue[0]))

    async def stop_all(self, ctx, leave_panel: bool = True):
        self.song_queue = []

        if self.barra_task:
            self.barra_task.cancel()
            self.barra_task = None

        if self.preloaded_player and getattr(self.preloaded_player, "filename", None):
            self.cleanup_file(self.preloaded_player.filename)
        self.preloaded_player = None
        self.preloaded_query = None

        vc = ctx.voice_client
        if vc:
            try:
                vc.stop()
            except Exception:
                pass
            try:
                await vc.disconnect()
            except Exception:
                pass

        self.purge_old_cache(max_age_minutes=10)

        if leave_panel and self.panel_msg and self.panel_ctx:
            try:
                embed = self.build_now_playing_embed(self.panel_ctx, paused=False)
                if embed.description:
                    embed.description = embed.description.replace("▶️ Reproduciendo", "🛑 Detenido")
                    embed.description = embed.description.replace("⏸️ Pausado", "🛑 Detenido")
                embed.color = THEME["neutral"]

                if self.panel_view:
                    for item in self.panel_view.children:
                        if hasattr(item, "disabled"):
                            item.disabled = True

                await self.panel_msg.edit(embed=embed, view=self.panel_view)
            except Exception:
                pass

        self.panel_data = None
        self.panel_ctx = None

    # -------------------------
    # Commands
    # -------------------------
    @commands.command(name="join")
    async def join(self, ctx):
        if ctx.author.voice:
            canal = ctx.author.voice.channel
            if ctx.voice_client:
                await ctx.voice_client.move_to(canal)
            else:
                await canal.connect()
        else:
            await ctx.send("🚫 Debes estar en un canal de voz primero.")

    @commands.command(name="p")
    async def play(self, ctx, *, query: str):
        """
        ✅ TODO EN UNO:
        - YouTube playlist => expande y encola
        - Spotify/Apple => intenta scraping; si falla => modo import automático (pegar lista o adjuntar txt/csv)
        - texto normal => reproduce o encola
        """
        just_joined = False
        if not ctx.voice_client:
            await ctx.invoke(self.join)
            just_joined = True
        if not ctx.voice_client:
            return
        if just_joined:
            await asyncio.sleep(0.8)

        # 1) YouTube playlist
        if self._is_youtube_playlist(query):
            msg = await ctx.send("📜 Leyendo playlist de YouTube...")
            urls = await self.expand_youtube_playlist(query)
            if not urls:
                return await msg.edit(content="❌ No pude leer esa playlist de YouTube.")
            await msg.edit(content=f"✅ Playlist YouTube: **{len(urls)}** items añadidos a cola.")
            await self.enqueue_many(ctx, urls)
            return

        # 2) Spotify/Apple: scraping => si falla => import automático
        is_preloaded = (self.preloaded_query == query and self.preloaded_player is not None)
        if (not is_preloaded) and (self._is_spotify(query) or self._is_applemusic(query)):
            msg = await ctx.send("🕵️ Intentando extraer playlist (scraping) y buscar en YouTube...")
            yt_queries = await self.scrape_playlist_to_yt_queries(query)

            if yt_queries:
                await msg.edit(content=f"✅ Listo: **{len(yt_queries)}** canciones añadidas (YouTube search).")
                await self.enqueue_many(ctx, yt_queries)
                return

            # fallback 100% confiable: import interactivo
            await msg.edit(content="⚠️ No pude extraer por scraping. Activando modo Import automático…")
            fallback_queries = await self.interactive_import_fallback(
                ctx,
                reason_text="🔁 **Scraping falló** (Spotify/Apple suele usar JS / bloquear)."
            )
            if fallback_queries:
                await ctx.send(f"✅ Import: **{len(fallback_queries)}** canciones a la cola.")
                await self.enqueue_many(ctx, fallback_queries)
            return

        # 3) Normal
        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
            self.song_queue.append(query)
            await ctx.send(f"✅ En cola: `{clean_query(query)}`")

            if len(self.song_queue) == 1:
                self.bot.loop.create_task(self.preload_next(self.song_queue[0]))
        else:
            await self.play_music(ctx, query)

    @commands.command(name="import", aliases=["imp"])
    async def import_cmd(self, ctx, *, text: str = None):
        """
        Import manual opcional (sigue existiendo).
        Si no mandas texto, entra al modo interactivo (pegar o adjuntar).
        """
        just_joined = False
        if not ctx.voice_client:
            await ctx.invoke(self.join)
            just_joined = True
        if not ctx.voice_client:
            return
        if just_joined:
            await asyncio.sleep(0.8)

        if text and text.strip():
            lines = [self._clean_track_text(x) for x in text.splitlines()]
            lines = [x for x in lines if x][:MAX_IMPORT_LINES]
            if not lines:
                return await ctx.send("⚠️ No detecté canciones válidas.")
            queries = [f"ytsearch1:{ln} audio" for ln in lines]
            await ctx.send(f"📥 Import: **{len(queries)}** canciones a la cola.")
            await self.enqueue_many(ctx, queries)
            return

        # interactivo
        queries = await self.interactive_import_fallback(ctx, reason_text="📥 Import manual (sin link).")
        if queries:
            await ctx.send(f"✅ Import: **{len(queries)}** canciones a la cola.")
            await self.enqueue_many(ctx, queries)

    @commands.command(name="autoplay", aliases=["radio"])
    async def autoplay_cmd(self, ctx):
        self.autoplay_enabled = not self.autoplay_enabled
        estado = "✅ ON" if self.autoplay_enabled else "❌ OFF"
        await ctx.send(f"📻 Autoplay: **{estado}**")

    @commands.command(name="stop")
    async def stop_cmd(self, ctx):
        await self.stop_all(ctx, leave_panel=True)

    @commands.command(name="skip")
    async def skip_cmd(self, ctx):
        if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            ctx.voice_client.stop()
        else:
            await ctx.send("🚫 No hay ninguna canción reproduciéndose.")

    @commands.command(name="shuffle", aliases=["mix", "random"])
    async def shuffle_cmd(self, ctx):
        if len(self.song_queue) < 2:
            return await ctx.send("📉 Necesito al menos 2 canciones en la cola para mezclar.")
        random.shuffle(self.song_queue)
        await ctx.send("🔀 **Cola mezclada.**")


async def setup(bot):
    await bot.add_cog(Musica(bot))