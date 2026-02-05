# cogs/music/services/player.py
from __future__ import annotations
import asyncio
import os
import time
import discord

from .source import YTDLSource
from .panel import build_now_playing_embed
from .ui import ControlesMusica
from .autoplay import pick_candidate, cooldown_ok
from .config import CACHE_FOLDER, CACHE_MAX_AGE_MINUTES

class MusicPlayer:
    def __init__(self, bot, musica_cog):
        self.bot = bot
        self.musica = musica_cog

        # Panel
        self.panel_msg = None
        self.panel_ctx = None
        self.panel_data = None
        self.panel_duration = 0
        self.panel_start_time = 0.0
        self.panel_task = None
        self.panel_view = None

    def cleanup_file(self, filename: str | None):
        if filename and os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass

    def purge_old_cache(self, max_age_minutes=CACHE_MAX_AGE_MINUTES):
        if not os.path.isdir(CACHE_FOLDER):
            return
        now = time.time()
        max_age = max_age_minutes * 60
        for fn in os.listdir(CACHE_FOLDER):
            path = os.path.join(CACHE_FOLDER, fn)
            try:
                if os.path.isfile(path) and (now - os.path.getmtime(path)) > max_age:
                    os.remove(path)
            except Exception:
                pass

    def has_listeners(self, vc: discord.VoiceClient) -> bool:
        try:
            if not vc or not vc.channel:
                return False
            humans = [m for m in vc.channel.members if not m.bot]
            return len(humans) > 0
        except Exception:
            return False

    async def preload_next(self, query: str):
        st = self.musica.state
        try:
            if st.preloaded_query == query and st.preloaded_player:
                return

            if st.preloaded_player and getattr(st.preloaded_player, "filename", None):
                self.cleanup_file(st.preloaded_player.filename)

            player = await YTDLSource.from_query(query, loop=self.bot.loop)
            if player:
                st.preloaded_player = player
                st.preloaded_query = query
        except Exception as e:
            print(f"❌ Preload error: {e}")

    async def _panel_loop(self):
        try:
            while True:
                await asyncio.sleep(10)
                if not self.panel_msg or not self.panel_ctx or not self.panel_data:
                    return
                vc = self.panel_ctx.voice_client
                if not vc:
                    return

                embed = build_now_playing_embed(
                    self.panel_ctx,
                    data=self.panel_data,
                    queue=self.musica.state.queue,
                    loop_enabled=self.musica.state.loop_enabled,
                    autoplay_enabled=self.musica.state.autoplay_enabled,
                    start_time=self.panel_start_time,
                    duration=self.panel_duration,
                    paused=vc.is_paused()
                )
                await self.panel_msg.edit(embed=embed, view=self.panel_view)

                if self.panel_duration and (time.time() - self.panel_start_time) > self.panel_duration:
                    return
        except asyncio.CancelledError:
            return
        except Exception as e:
            print(f"Panel loop error: {e}")

    async def send_panel(self, ctx, player):
        data = player.data or {}
        self.panel_ctx = ctx
        self.panel_data = data
        self.panel_duration = int(data.get("duration", 0))
        self.panel_start_time = time.time()

        self.panel_view = ControlesMusica(ctx, self.musica)
        embed = build_now_playing_embed(
            ctx,
            data=data,
            queue=self.musica.state.queue,
            loop_enabled=self.musica.state.loop_enabled,
            autoplay_enabled=self.musica.state.autoplay_enabled,
            start_time=self.panel_start_time,
            duration=self.panel_duration,
            paused=False
        )
        self.panel_msg = await ctx.send(embed=embed, view=self.panel_view)

        if self.panel_task:
            self.panel_task.cancel()
        self.panel_task = self.bot.loop.create_task(self._panel_loop())

    async def play_next(self, ctx, last_file=None, seed_data=None):
        if self.panel_task:
            self.panel_task.cancel()

        if last_file:
            self.cleanup_file(last_file)

        st = self.musica.state

        if st.queue:
            await self.play_music(ctx, st.queue.pop(0))
            return

        # Autoplay si no hay cola
        if seed_data and st.autoplay_enabled and not st.loop_enabled and ctx.voice_client and self.has_listeners(ctx.voice_client):
            async with st.autoplay_lock:
                if not cooldown_ok(st):
                    return
                if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
                    return
                candidate = await pick_candidate(self.bot.loop, st, seed_data)
                if candidate:
                    await self.play_music(ctx, candidate)

    async def play_music(self, ctx, query: str):
        self.purge_old_cache()

        st = self.musica.state

        # usar preload si coincide
        if st.preloaded_query == query and st.preloaded_player:
            player = st.preloaded_player
            st.preloaded_player = None
            st.preloaded_query = None
        else:
            msg = await ctx.send("💿 **Cargando...**")
            player = await YTDLSource.from_query(query, loop=self.bot.loop)
            if not player:
                return await msg.edit(content="❌ Error descargando/reproduciendo.")
            await msg.delete()

        data = player.data or {}
        url_now = (data.get("webpage_url") or data.get("url") or "").strip()
        st.current_track = url_now or query

        def after_playing(error):
            try:
                if error:
                    print(f"After error: {error}")

                if st.loop_enabled and st.current_track:
                    st.queue.insert(0, st.current_track)

                asyncio.run_coroutine_threadsafe(
                    self.play_next(ctx, player.filename, seed_data=data),
                    self.bot.loop
                )
            except Exception as e:
                print(f"❌ after_playing error: {e}")

        if not ctx.voice_client:
            return await ctx.send("🚫 No estoy conectado a voz. Usa `.join` primero.")

        ctx.voice_client.play(player, after=after_playing)
        await self.send_panel(ctx, player)

        if st.queue:
            self.bot.loop.create_task(self.preload_next(st.queue[0]))

    async def stop_all(self, ctx, leave_panel=True):
        st = self.musica.state
        st.queue = []

        if self.panel_task:
            self.panel_task.cancel()
            self.panel_task = None

        if st.preloaded_player and getattr(st.preloaded_player, "filename", None):
            self.cleanup_file(st.preloaded_player.filename)
        st.preloaded_player = None
        st.preloaded_query = None

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

        if leave_panel and self.panel_msg:
            try:
                if self.panel_view:
                    for item in self.panel_view.children:
                        if hasattr(item, "disabled"):
                            item.disabled = True
                await self.panel_msg.edit(view=self.panel_view)
            except Exception:
                pass

        self.panel_msg = None
        self.panel_ctx = None
        self.panel_data = None