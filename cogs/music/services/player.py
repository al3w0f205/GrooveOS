# cogs/music/services/player.py
import os
import time
import asyncio
import random
import discord

from ..source import YTDLSource
from ..ui import ControlesMusica
from ..config import YTDL_OPTIONS
from ...utilidad import THEME, user_footer, fmt_time, short_queue_preview

class PlayerService:
    def __init__(self, mgr):
        self.mgr = mgr

    # -------- utils
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

    def has_listeners(self, vc: discord.VoiceClient) -> bool:
        try:
            if not vc or not vc.channel:
                return False
            humans = [m for m in vc.channel.members if not m.bot]
            return len(humans) > 0
        except Exception:
            return False

    # -------- preload
    async def preload_next(self, st, query):
        try:
            if st.preloaded_query == query and st.preloaded_player:
                return

            if st.preloaded_player and getattr(st.preloaded_player, "filename", None):
                self.cleanup_file(st.preloaded_player.filename)

            player = await YTDLSource.from_query(query, loop=self.mgr.bot.loop)
            if player:
                st.preloaded_player = player
                st.preloaded_query = query
        except Exception as e:
            print(f"❌ Error en pre-carga: {e}")

    # -------- panel embed
    def build_now_playing_embed(self, ctx, st, paused=False):
        data = st.panel_data or {}
        duracion = int(st.panel_duration or 0)
        start_time = float(st.panel_start_time or time.time())

        titulo = data.get("title", "Desconocido")
        url = data.get("webpage_url", "")
        thumbnail = data.get("thumbnail")
        uploader = data.get("uploader", "Desconocido")

        elapsed = int(time.time() - start_time)
        elapsed = max(0, min(elapsed, duracion)) if duracion else max(0, elapsed)
        remaining = max(0, duracion - elapsed) if duracion else 0

        estado = "⏸️ Pausado" if paused else "▶️ Reproduciendo"
        color = THEME["warning"] if paused else THEME["primary"]
        loop_txt = "ON ✅" if st.loop_enabled else "OFF ❌"
        auto_txt = "ON ✅" if st.autoplay_enabled else "OFF ❌"

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

        preview = short_queue_preview(st.song_queue, limit=3)
        embed.add_field(
            name="📜 Próximas",
            value=f"{preview}\n\u200b",
            inline=False
        )

        embed.set_footer(**user_footer(ctx, f"Loop: {loop_txt} • Auto: {auto_txt}"))
        return embed

    async def actualizar_panel_loop(self, st):
        try:
            while True:
                await asyncio.sleep(10)
                if not st.panel_msg or not st.panel_ctx or not st.panel_data:
                    break
                vc = st.panel_ctx.voice_client
                if not vc:
                    break
                embed = self.build_now_playing_embed(st.panel_ctx, st, paused=vc.is_paused())
                await st.panel_msg.edit(embed=embed, view=st.panel_view)

                if st.panel_duration and (time.time() - st.panel_start_time) > st.panel_duration:
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Error panel: {e}")

    async def enviar_panel(self, ctx, st, player):
        data = player.data
        st.panel_ctx = ctx
        st.panel_data = data
        st.panel_duration = int(data.get("duration", 0))
        st.panel_start_time = time.time()

        view = ControlesMusica(ctx, self.mgr, st)  # <- UI modular
        st.panel_view = view

        embed = self.build_now_playing_embed(ctx, st, paused=False)
        msg = await ctx.send(embed=embed, view=view)
        st.panel_msg = msg

        if st.barra_task:
            st.barra_task.cancel()
        st.barra_task = self.mgr.bot.loop.create_task(self.actualizar_panel_loop(st))

    # -------- play flow
    async def play_next(self, ctx, st, last_file=None, seed_data=None):
        if st.barra_task:
            st.barra_task.cancel()

        if last_file:
            self.cleanup_file(last_file)

        if st.song_queue:
            await self.play_music(ctx, st, st.song_queue.pop(0))
        else:
            # autoplay si toca
            if seed_data and st.autoplay_enabled and not st.loop_enabled:
                await self.mgr.autoplay.ensure(ctx, st, seed_data, self.has_listeners)

    async def play_music(self, ctx, st, query):
        self.purge_old_cache()

        if st.preloaded_query == query and st.preloaded_player:
            player = st.preloaded_player
            st.preloaded_player = None
            st.preloaded_query = None
        else:
            msg = await ctx.send("💿 **Cargando...**")
            player = await YTDLSource.from_query(query, loop=self.mgr.bot.loop)
            if not player:
                return await msg.edit(content="❌ Error de descarga.")
            await msg.delete()

        # registrar autoplay
        try:
            data = player.data or {}
            url_now = (data.get("webpage_url") or data.get("url") or "").strip()
            st.current_track = url_now or query
            self.mgr.autoplay.register_now_playing(st, data)
        except Exception as e:
            print(f"⚠️ Error set current_track/register: {e}")
            st.current_track = query

        def after_playing(error):
            try:
                if st.barra_task:
                    st.barra_task.cancel()

                if error:
                    print(f"Error: {error}")

                if st.loop_enabled and st.current_track:
                    st.song_queue.insert(0, st.current_track)

                asyncio.run_coroutine_threadsafe(
                    self.play_next(ctx, st, player.filename, seed_data=player.data),
                    self.mgr.bot.loop
                )
            except Exception as e:
                print(f"❌ Error en after_playing: {e}")

        if not ctx.voice_client:
            return await ctx.send("🚫 No estoy conectado a voz. Usa `.join` primero.")

        ctx.voice_client.play(player, after=after_playing)
        await self.enviar_panel(ctx, st, player)

        if st.song_queue:
            self.mgr.bot.loop.create_task(self.preload_next(st, st.song_queue[0]))

    async def stop_all(self, ctx, st, leave_panel: bool = True):
        st.song_queue = []

        if st.barra_task:
            st.barra_task.cancel()
            st.barra_task = None

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

        if leave_panel and st.panel_msg and st.panel_ctx:
            try:
                embed = self.build_now_playing_embed(st.panel_ctx, st, paused=False)
                if embed.description:
                    embed.description = embed.description.replace("▶️ Reproduciendo", "🛑 Detenido")
                    embed.description = embed.description.replace("⏸️ Pausado", "🛑 Detenido")
                embed.color = THEME["neutral"]

                if st.panel_view:
                    for item in st.panel_view.children:
                        if hasattr(item, "disabled"):
                            item.disabled = True

                await st.panel_msg.edit(embed=embed, view=st.panel_view)
            except Exception:
                pass

        st.panel_data = None
        st.panel_ctx = None