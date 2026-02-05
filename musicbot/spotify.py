# musicbot/spotify.py
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

import yt_dlp


SPOTIFY_REGEX = re.compile(r"(https?://open\.spotify\.com/(track|playlist)/[A-Za-z0-9]+)")


@dataclass
class SpotifyItem:
    title: str
    query: str  # query que usaremos en YouTube (artist - track)
    raw: Dict[str, Any]


class SpotifyResolver:
    """
    Resuelve links de Spotify sin credenciales:
    - Extrae metadata con yt-dlp (extract_flat)
    - Genera queries estilo "Artist - Track"
    """

    def __init__(self):
        self._opts = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": True,
            "skip_download": True,
            "noplaylist": False,
        }

    def is_spotify_url(self, text: str) -> Optional[str]:
        m = SPOTIFY_REGEX.search(text or "")
        return m.group(1) if m else None

    async def resolve(self, spotify_url: str) -> List[SpotifyItem]:
        def _extract():
            with yt_dlp.YoutubeDL(self._opts) as ydl:
                return ydl.extract_info(spotify_url, download=False)

        info = await asyncio.to_thread(_extract)
        if not info:
            return []

        items: List[SpotifyItem] = []

        entries = info.get("entries") or []
        if entries:
            for e in entries:
                title = e.get("title") or "Spotify Track"
                artist = e.get("artist") or e.get("uploader") or ""
                track = e.get("track") or ""

                if artist and track:
                    query = f"{artist} - {track}"
                else:
                    # fallback: usar title como query
                    query = title

                items.append(SpotifyItem(title=title, query=query, raw=e))
            return items

        # track único sin entries (fallback)
        title = info.get("title") or "Spotify"
        items.append(SpotifyItem(title=title, query=title, raw=info))
        return items