# musicbot/downloader.py
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Optional, Dict, Any

import yt_dlp


@dataclass
class DownloadResult:
    file_path: Optional[str]
    info: Dict[str, Any]


class YTDLDownloader:
    """
    - Resuelve info (title, duration, url, thumbnail) usando yt-dlp
    - Descarga audio al disco (no streaming) para reproducción estable
    """

    def __init__(self):
        self._resolve_opts = {
            "quiet": True,
            "no_warnings": True,
            "default_search": "ytsearch1",
            "noplaylist": True,
            "extract_flat": False,
            "skip_download": True,
        }

        self._download_opts_base = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio/best",
            "noplaylist": True,
            "retries": 3,
            "fragment_retries": 3,
            "concurrent_fragment_downloads": 4,
        }

    async def resolve_youtube_info(self, query_or_url: str) -> Dict[str, Any]:
        """
        Acepta búsqueda o URL. Si es búsqueda, usa ytsearch1.
        Retorna info del primer resultado.
        """
        q = (query_or_url or "").strip()

        def _extract():
            with yt_dlp.YoutubeDL(self._resolve_opts) as ydl:
                info = ydl.extract_info(q, download=False)
                if isinstance(info, dict) and "entries" in info:
                    return info["entries"][0]
                return info

        return await asyncio.to_thread(_extract)

    async def download_audio(self, url: str, out_dir: str, uid: str) -> DownloadResult:
        """
        Descarga el audio del video (url) en out_dir con nombre basado en uid.
        Retorna (file_path, info).
        """
        os.makedirs(out_dir, exist_ok=True)
        template = os.path.join(out_dir, f"{uid}.%(ext)s")

        def _dl():
            opts = dict(self._download_opts_base)
            # yt-dlp soporta outtmpl como string; lo dejamos simple y compatible
            opts["outtmpl"] = template
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                return info

        info = await asyncio.to_thread(_dl)

        # localizar archivo final (por prefijo uid.)
        final_path = None
        try:
            for f in os.listdir(out_dir):
                if f.startswith(uid + "."):
                    final_path = os.path.join(out_dir, f)
                    break
        except Exception:
            final_path = None

        return DownloadResult(file_path=final_path, info=info or {})