# cogs/music/services/source.py
from __future__ import annotations
import asyncio
import os
import yt_dlp
import discord

from .config import YTDL_OPTIONS, FFMPEG_OPTIONS, CACHE_FOLDER

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, filename: str, volume: float = 0.5):
        super().__init__(source, volume)
        self.data = data or {}
        self.filename = filename

    @classmethod
    async def from_query(cls, query: str, *, loop: asyncio.AbstractEventLoop):
        loop = loop or asyncio.get_event_loop()
        os.makedirs(CACHE_FOLDER, exist_ok=True)

        def _extract():
            with yt_dlp.YoutubeDL(YTDL_OPTIONS) as ydl:
                info = ydl.extract_info(query, download=True)
                if not info:
                    return None, None

                # si es búsqueda, toma el primer entry válido
                if "entries" in info:
                    info = next((e for e in info["entries"] if e), None)
                    if not info:
                        return None, None

                filename = ydl.prepare_filename(info)
                base, _ext = os.path.splitext(filename)

                # por postprocessor, suele quedar como .mp3
                mp3 = base + ".mp3"
                if os.path.exists(mp3):
                    filename = mp3

                return info, filename

        data, filename = await loop.run_in_executor(None, _extract)
        if not data or not filename or not os.path.exists(filename):
            return None

        # Audio local (mp3) -> ffmpeg a PCM para discord
        audio = discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS)
        return cls(audio, data=data, filename=filename)