# cogs/musica.py
from __future__ import annotations
import asyncio
import random
import discord
from discord.ext import commands

from .utilidad import clean_query
from .music.services.state import MusicState
from .music.services.player import MusicPlayer
from .music.services.playlists import (
    is_youtube_playlist, is_spotify, is_applemusic,
    expand_youtube_playlist, scrape_playlist_to_yt_queries, clean_track_text
)
from .music.services.config import MAX_IMPORT_LINES, IMPORT_WAIT_SECONDS

class Musica(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.state = MusicState()
        self.player = MusicPlayer(bot, self)

    # ------------ JOIN ------------
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

    # ------------ IMPORT (interactivo) ------------
    async def _read_attachment_lines(self, attachment: discord.Attachment) -> list[str]:
        fname = (attachment.filename or "").lower()
        if not (fname.endswith(".txt") or fname.endswith(".csv")):
            return []
        data = await attachment.read()
        text = data.decode("utf-8", errors="ignore")
        lines = [clean_track_text(x) for x in text.splitlines()]
        lines = [x for x in lines if x]
        return lines[:MAX_IMPORT_LINES]

    async def interactive_import(self, ctx, reason_text: str = "") -> list[str]:
        prompt = (
            f"{reason_text}\n"
            f"📥 **Modo Import**\n"
            f"➡️ Pega la lista (1 canción por línea) **O** adjunta un **.txt/.csv**.\n"
            f"⏱️ Tienes **{IMPORT_WAIT_SECONDS}s**. Escribe `cancel` para cancelar."
        ).strip()
        await ctx.send(prompt)

        def check(m: discord.Message):
            return m.author == ctx.author and m.channel == ctx.channel and (
                (m.content and m.content.strip()) or m.attachments
            )

        try:
            m = await self.bot.wait_for("message", timeout=IMPORT_WAIT_SECONDS, check=check)
        except asyncio.TimeoutError:
            await ctx.send("⏱️ Tiempo agotado.")
            return []

        if (m.content or "").strip().lower() == "cancel":
            await ctx.send("✅ Import cancelado.")
            return []

        if m.attachments:
            lines = await self._read_attachment_lines(m.attachments[0])
            return [f"ytsearch1:{ln} audio" for ln in lines if ln]

        text = (m.content or "").strip()
        lines = [clean_track_text(x) for x in text.splitlines()]
        lines = [x for x in lines if x][:MAX_IMPORT_LINES]
        return [f"ytsearch1:{ln} audio" for ln in lines if ln]

    # ------------ PLAY ------------
    @commands.command(name="p")
    async def play(self, ctx, *, query: str):
        just_joined = False
        if not ctx.voice_client:
            await ctx.invoke(self.join)
            just_joined = True
        if not ctx.voice_client:
            return
        if just_joined:
            await asyncio.sleep(0.8)

        # 1) YouTube playlist
        if is_youtube_playlist(query):
            msg = await ctx.send("📜 Leyendo playlist de YouTube...")
            urls = await expand_youtube_playlist(query, self.bot.loop)
            if not urls:
                return await msg.edit(content="❌ No pude leer esa playlist.")
            await msg.edit(content=f"✅ Playlist: **{len(urls)}** items a la cola.")
            self.state.queue.extend(urls)

            if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
                await self.player.play_music(ctx, self.state.queue.pop(0))
            else:
                if len(self.state.queue) == 1:
                    self.bot.loop.create_task(self.player.preload_next(self.state.queue[0]))
            return

        # 2) Spotify / Apple
        if is_spotify(query) or is_applemusic(query):
            msg = await ctx.send("🕵️ Intentando extraer playlist y buscar en YouTube...")
            yt_queries = await scrape_playlist_to_yt_queries(query)

            if yt_queries:
                await msg.edit(content=f"✅ Listo: **{len(yt_queries)}** canciones añadidas.")
                self.state.queue.extend(yt_queries)
            else:
                await msg.edit(content="⚠️ Scraping falló. Activando Import…")
                fallback = await self.interactive_import(ctx, "🔁 **Scraping falló** (Spotify/Apple bloquean a veces).")
                if fallback:
                    await ctx.send(f"✅ Import: **{len(fallback)}** a la cola.")
                    self.state.queue.extend(fallback)

            if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused() and self.state.queue:
                await self.player.play_music(ctx, self.state.queue.pop(0))
            return

        # 3) Normal
        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
            self.state.queue.append(query)
            await ctx.send(f"✅ En cola: `{clean_query(query)}`")
            if len(self.state.queue) == 1:
                self.bot.loop.create_task(self.player.preload_next(self.state.queue[0]))
        else:
            await self.player.play_music(ctx, query)

    # ------------ comandos varios ------------
    @commands.command(name="import", aliases=["imp"])
    async def import_cmd(self, ctx, *, text: str = None):
        if not ctx.voice_client:
            await ctx.invoke(self.join)
        if not ctx.voice_client:
            return

        if text and text.strip():
            lines = [clean_track_text(x) for x in text.splitlines()]
            lines = [x for x in lines if x][:MAX_IMPORT_LINES]
            queries = [f"ytsearch1:{ln} audio" for ln in lines]
        else:
            queries = await self.interactive_import(ctx, "📥 Import manual.")

        if queries:
            self.state.queue.extend(queries)
            await ctx.send(f"✅ Import: **{len(queries)}** añadidas.")
            if not ctx.voice_client.is_playing() and not ctx.voice_client.is_paused():
                await self.player.play_music(ctx, self.state.queue.pop(0))

    @commands.command(name="autoplay", aliases=["radio"])
    async def autoplay_cmd(self, ctx):
        self.state.autoplay_enabled = not self.state.autoplay_enabled
        await ctx.send(f"📻 Autoplay: **{'✅ ON' if self.state.autoplay_enabled else '❌ OFF'}**")

    @commands.command(name="stop")
    async def stop_cmd(self, ctx):
        await self.player.stop_all(ctx, leave_panel=True)

    @commands.command(name="skip")
    async def skip_cmd(self, ctx):
        if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            ctx.voice_client.stop()
        else:
            await ctx.send("🚫 No hay nada reproduciéndose.")

    @commands.command(name="shuffle", aliases=["mix", "random"])
    async def shuffle_cmd(self, ctx):
        if len(self.state.queue) < 2:
            return await ctx.send("📉 Necesito al menos 2 canciones en cola.")
        random.shuffle(self.state.queue)
        await ctx.send("🔀 **Cola mezclada.**")

async def setup(bot):
    await bot.add_cog(Musica(bot))