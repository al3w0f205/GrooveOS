# cogs/music/services/playlists.py
from __future__ import annotations
import json
import re
from urllib.parse import urlparse

import requests
import yt_dlp
from bs4 import BeautifulSoup

from .config import (
    UA_HEADERS, SCRAPE_TIMEOUT, MAX_SCRAPED_TRACKS,
    MAX_YT_PLAYLIST_ITEMS, YTDL_OPTIONS
)

def is_youtube_playlist(q: str) -> bool:
    q = (q or "").strip()
    return ("youtube.com/playlist" in q) or ("list=" in q and ("youtube.com" in q or "youtu.be" in q))

def is_spotify(q: str) -> bool:
    return "open.spotify.com" in (q or "")

def is_applemusic(q: str) -> bool:
    return "music.apple.com" in (q or "")

def spotify_embed_url(url: str) -> str:
    try:
        u = urlparse(url)
        parts = u.path.strip("/").split("/")
        if len(parts) >= 2 and parts[0] == "playlist":
            return f"https://open.spotify.com/embed/playlist/{parts[1]}"
    except Exception:
        pass
    return url

def clean_track_text(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = s.replace("–", "-").replace("—", "-")
    return s.strip()

def dedupe_keep_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for x in items:
        x = (x or "").strip()
        if not x or x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out

def extract_names_from_jsonld(soup: BeautifulSoup) -> list[str]:
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
                            tracks.append(clean_track_text(name))
                        item = it.get("item") or {}
                        if isinstance(item, dict):
                            name2 = item.get("name")
                            if name2:
                                tracks.append(clean_track_text(name2))

                tr = obj.get("track") or []
                if isinstance(tr, list):
                    for t in tr:
                        if isinstance(t, dict) and t.get("name"):
                            tracks.append(clean_track_text(t["name"]))
        except Exception:
            continue
    return tracks

def extract_names_spotify(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    meta_tracks = [
        m.get("content")
        for m in soup.find_all("meta", property="music:song")
        if m.get("content")
    ]
    jsonld_tracks = extract_names_from_jsonld(soup)

    regex_tracks = []
    for m in re.finditer(r'"name"\s*:\s*"([^"]{2,120})"\s*,\s*"uri"\s*:\s*"spotify:track:', html):
        regex_tracks.append(clean_track_text(m.group(1)))

    return dedupe_keep_order(meta_tracks + jsonld_tracks + regex_tracks)[:MAX_SCRAPED_TRACKS]

def extract_names_apple(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    jsonld_tracks = extract_names_from_jsonld(soup)

    regex_tracks = []
    for m in re.finditer(r'"name"\s*:\s*"([^"]{2,120})"\s*,\s*"@type"\s*:\s*"MusicRecording"', html):
        regex_tracks.append(clean_track_text(m.group(1)))

    return dedupe_keep_order(jsonld_tracks + regex_tracks)[:MAX_SCRAPED_TRACKS]

async def scrape_playlist_to_yt_queries(url: str) -> list[str]:
    try:
        fetch_url = spotify_embed_url(url) if is_spotify(url) else url
        r = requests.get(fetch_url, headers=UA_HEADERS, timeout=SCRAPE_TIMEOUT)
        html = r.text or ""

        if is_spotify(url):
            names = extract_names_spotify(html)
        elif is_applemusic(url):
            names = extract_names_apple(html)
        else:
            names = []

        # spotify fallback: si embed no funcionó, intenta normal
        if is_spotify(url) and not names and fetch_url != url:
            r2 = requests.get(url, headers=UA_HEADERS, timeout=SCRAPE_TIMEOUT)
            names = extract_names_spotify(r2.text or "")

        return [f"ytsearch1:{n} audio" for n in names if n][:MAX_SCRAPED_TRACKS]
    except Exception:
        return []

async def expand_youtube_playlist(url: str, loop) -> list[str]:
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
    except Exception:
        return []