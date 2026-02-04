# cogs/music/source.py
import discord
import yt_dlp
import asyncio

from .config import YTDL_OPTIONS, FFMPEG_OPTIONS

# ✅ ytdl global (igual que antes, solo que ahora vive aquí)
ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get("title")
        self.filename = ytdl.prepare_filename(data)

    @classmethod
    async def from_query(cls, query, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=True))
            if "entries" in data:
                data = data["entries"][0]
            filename = ytdl.prepare_filename(data)
            return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)
        except Exception as e:
            print(f"❌ Error YTDL: {e}")
            return None