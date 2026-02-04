# cogs/music/playlists.py
import asyncio
import re
import json
import yt_dlp
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from .config import (
    SCRAPE_TIMEOUT, MAX_SCRAPED_TRACKS, MAX_IMPORT_LINES, MAX_YT_PLAYLIST_ITEMS,
    IMPORT_WAIT_SECONDS, UA_HEADERS, YTDL_OPTIONS
)


class PlaylistTools:
    def __init__(self, bot):
        self.bot = bot

    # -------------------------
    # Detectores
    # -------------------------
    def is_youtube_playlist(self, q: str) -> bool:
        q = (q or "").strip()
        if "youtube.com/playlist" in q:
            return True
        if "list=" in q and ("youtube.com" in q or "youtu.be" in q):
            return True
        return False

    def is_spotify(self, q: str) -> bool:
        return "open.spotify.com" in (q or "")

    def is_applemusic(self, q: str) -> bool:
        return "music.apple.com" in (q or "")

    def spotify_embed_url(self, url: str) -> str:
        try:
            u = urlparse(url)
            parts = u.path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] == "playlist":
                return f"https://open.spotify.com/embed/playlist/{parts[1]}"
        except Exception:
            pass
        return url

    # -------------------------
    # Helpers texto
    # -------------------------
    def dedupe_keep_order(self, items):
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

    def clean_track_text(self, s: str) -> str:
        s = (s or "").strip()
        s = re.sub(r"\s+", " ", s)
        s = s.replace("–", "-").replace("—", "-")
        return s.strip()

    def extract_names_from_jsonld(self, soup: BeautifulSoup) -> list[str]:
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
                                tracks.append(self.clean_track_text(name))
                            item = it.get("item") or {}
                            if isinstance(item, dict):
                                name2 = item.get("name")
                                if name2:
                                    tracks.append(self.clean_track_text(name2))

                    tr = obj.get("track") or []
                    if isinstance(tr, list):
                        for t in tr:
                            if isinstance(t, dict) and t.get("name"):
                                tracks.append(self.clean_track_text(t["name"]))
            except Exception:
                continue
        return tracks

    def extract_names_spotify(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")

        meta_tracks = [
            m.get("content")
            for m in soup.find_all("meta", property="music:song")
            if m.get("content")
        ]

        jsonld_tracks = self.extract_names_from_jsonld(soup)

        regex_tracks = []
        for m in re.finditer(r'"name"\s*:\s*"([^"]{2,120})"\s*,\s*"uri"\s*:\s*"spotify:track:', html):
            regex_tracks.append(self.clean_track_text(m.group(1)))

        tracks = self.dedupe_keep_order(meta_tracks + jsonld_tracks + regex_tracks)
        return tracks[:MAX_SCRAPED_TRACKS]

    def extract_names_apple(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        jsonld_tracks = self.extract_names_from_jsonld(soup)

        regex_tracks = []
        for m in re.finditer(r'"name"\s*:\s*"([^"]{2,120})"\s*,\s*"@type"\s*:\s*"MusicRecording"', html):
            regex_tracks.append(self.clean_track_text(m.group(1)))

        tracks = self.dedupe_keep_order(jsonld_tracks + regex_tracks)
        return tracks[:MAX_SCRAPED_TRACKS]

    # -------------------------
    # Spotify/Apple scraping -> ytsearch
    # -------------------------
    async def scrape_playlist_to_yt_queries(self, url: str) -> list[str]:
        try:
            fetch_url = self.spotify_embed_url(url) if self.is_spotify(url) else url
            r = requests.get(fetch_url, headers=UA_HEADERS, timeout=SCRAPE_TIMEOUT)
            html = r.text or ""

            if self.is_spotify(url):
                names = self.extract_names_spotify(html)
            elif self.is_applemusic(url):
                names = self.extract_names_apple(html)
            else:
                names = []

            if self.is_spotify(url) and not names and fetch_url != url:
                r2 = requests.get(url, headers=UA_HEADERS, timeout=SCRAPE_TIMEOUT)
                names = self.extract_names_spotify(r2.text or "")

            out = []
            for name in names:
                name = self.clean_track_text(name)
                if not name:
                    continue
                out.append(f"ytsearch1:{name} audio")

            return out[:MAX_SCRAPED_TRACKS]
        except Exception as e:
            print(f"❌ scrape_playlist_to_yt_queries error: {e}")
            return []

    # -------------------------
    # Expand YouTube playlist (extract_flat)
    # -------------------------
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

    # -------------------------
    # Import: txt/csv adjunto o texto pegado
    # -------------------------
    async def read_attachment_to_lines(self, attachment) -> list[str]:
        try:
            fname = (attachment.filename or "").lower()
            if not (fname.endswith(".txt") or fname.endswith(".csv")):
                return []

            data = await attachment.read()
            text = data.decode("utf-8", errors="ignore")

            lines = []
            if fname.endswith(".txt"):
                lines = [self.clean_track_text(x) for x in text.splitlines()]
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
                    name = self.clean_track_text(name)
                    if name:
                        lines.append(name)
                else:
                    rr = self.clean_track_text(row)
                    if rr:
                        lines.append(rr)

                if len(lines) >= MAX_IMPORT_LINES:
                    break

            return lines[:MAX_IMPORT_LINES]
        except Exception as e:
            print(f"❌ read_attachment_to_lines error: {e}")
            return []

    async def interactive_import_fallback(self, ctx, reason_text: str = "") -> list[str]:
        prompt = (
            f"{reason_text}\n"
            f"📥 **Modo Import (automático)**\n"
            f"➡️ Pega la lista (1 canción por línea) **O** adjunta un **.txt/.csv**.\n"
            f"⏱️ Tienes **{IMPORT_WAIT_SECONDS}s**. Escribe `cancel` para cancelar."
        ).strip()

        await ctx.send(prompt)

        def check(m):
            return m.author == ctx.author and m.channel == ctx.channel and ((m.content and m.content.strip()) or m.attachments)

        try:
            m = await self.bot.wait_for("message", timeout=IMPORT_WAIT_SECONDS, check=check)
        except asyncio.TimeoutError:
            await ctx.send("⏱️ Tiempo agotado. Intenta de nuevo con `.p <link>` o pega la lista.")
            return []

        if (m.content or "").strip().lower() == "cancel":
            await ctx.send("✅ Import cancelado.")
            return []

        if m.attachments:
            lines = await self.read_attachment_to_lines(m.attachments[0])
            if lines:
                return [f"ytsearch1:{ln} audio" for ln in lines if ln][:MAX_IMPORT_LINES]

        text = (m.content or "").strip()
        lines = [self.clean_track_text(x) for x in text.splitlines()]
        lines = [x for x in lines if x]
        if not lines:
            await ctx.send("⚠️ No detecté canciones válidas. Intenta de nuevo.")
            return []

        lines = lines[:MAX_IMPORT_LINES]
        return [f"ytsearch1:{ln} audio" for ln in lines if ln]