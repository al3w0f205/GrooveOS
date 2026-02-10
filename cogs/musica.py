# cogs/musica.py
from __future__ import annotations

import os
import discord
from discord.ext import commands

from musicbot.downloader import YTDLDownloader
from musicbot.spotify import SpotifyResolver
from musicbot.player import MusicService, Track
from musicbot.views import MusicControls, build_player_embed
from .utilidad import clean_query


class _MiniCtx:
    """Objeto mínimo para Perfiles.actualizar_stats(): tiene author y channel."""
    def __init__(self, author: discord.abc.User, channel: discord.abc.Messageable):
        self.author = author
        self.channel = channel


class Musica(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        self.downloader = YTDLDownloader()
        self.spotify = SpotifyResolver()

        ffmpeg_path = os.getenv("FFMPEG_PATH", "ffmpeg")
        temp_root = os.getenv("MUSIC_TEMP", "tmp_audio")

        self.service = MusicService(
            bot=self.bot,
            downloader=self.downloader,
            ffmpeg_path=ffmpeg_path,
            temp_root=temp_root,
            on_state_change=self._on_state_change,
            on_track_started=self._on_track_started,
            on_track_finished=self._on_track_finished,  # <- ahora incluye played_seconds
        )

        self.controls = MusicControls(self)

        # Para tu .queue existente
        self.song_queue = []
        self.current_track = None

        self.panel_message: dict[int, discord.Message] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            self.bot.add_view(self.controls)
        except Exception:
            pass
        print("🎵 Musica modular lista (UI + comandos + stats reales).")

    # ---------------- Panel ----------------
    async def refresh_panel(self, guild: discord.Guild):
        player = self.service.get_player(guild.id)

        self.song_queue = [t.title if t.title else t.query for t in list(player.queue)]
        self.current_track = player.current.title if player.current else None

        msg = self.panel_message.get(guild.id)
        if not msg:
            return
        try:
            await msg.edit(embed=build_player_embed(guild, player), view=self.controls)
        except Exception:
            pass

    async def ensure_panel(self, ctx: commands.Context):
        if ctx.guild.id in self.panel_message:
            return
        msg = await ctx.send(embed=build_player_embed(ctx.guild, self.service.get_player(ctx.guild.id)), view=self.controls)
        self.panel_message[ctx.guild.id] = msg

    # ---------------- Hooks ----------------
    async def _on_state_change(self, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        if guild:
            await self.refresh_panel(guild)

    async def _on_track_started(self, guild_id: int, track: Track):
        # Aquí podrías anunciar "Now playing" si quieres, pero no es necesario.
        pass

    async def _on_track_finished(self, guild_id: int, track: Track, played_seconds: int, ended_naturally: bool):
        """
        Aquí mandamos los segundos reales escuchados al Cog Perfiles.
        Importante: NO incrementamos pedidos ni XP base otra vez.
        """
        perfiles = self.bot.get_cog("Perfiles")
        if not perfiles:
            return

        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        # miembro (para display / mention y id correcto)
        member = guild.get_member(track.requester_id) if track.requester_id else None

        # canal donde se pidió (o donde está el panel)
        channel = guild.get_channel(track.text_channel_id) if track.text_channel_id else None
        if channel is None:
            # fallback: canal del panel
            panel_msg = self.panel_message.get(guild_id)
            channel = panel_msg.channel if panel_msg else None

        if not member or not channel:
            return

        # Solo registrar duración si escuchó algo razonable (evita 0s spam)
        if played_seconds <= 0:
            return

        mini = _MiniCtx(author=member, channel=channel)
        try:
            await perfiles.actualizar_stats(
                mini,
                duracion=played_seconds,
                xp_ganado=0,             # <- sin xp extra (configurado en Perfiles)
                es_musica=True,
                contar_pedido=False       # <- CRÍTICO: no sumar "canciones pedidas" otra vez
            )
        except Exception:
            pass

    # ---------------- Comandos ----------------
    @commands.command(name="panel")
    async def panel(self, ctx: commands.Context):
        msg = await ctx.send(embed=build_player_embed(ctx.guild, self.service.get_player(ctx.guild.id)), view=self.controls)
        self.panel_message[ctx.guild.id] = msg

    @commands.command(name="join", aliases=["j"])
    async def join(self, ctx: commands.Context):
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("🎧 Entra a un canal de voz primero.")
        player = self.service.get_player(ctx.guild.id)
        await player.ensure_voice(ctx.author.voice.channel)
        await self.ensure_panel(ctx)
        await ctx.send("✅ Conectado.")
        await self.refresh_panel(ctx.guild)

    @commands.command(name="play", aliases=["p"])
    async def play(self, ctx: commands.Context, *, query: str):
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("🎧 Entra a un canal de voz primero.")

        player = self.service.get_player(ctx.guild.id)
        await player.ensure_voice(ctx.author.voice.channel)
        await self.ensure_panel(ctx)

        spotify_url = self.spotify.is_spotify_url(query)

        tracks: list[Track] = []
        if spotify_url:
            await ctx.send("🟢 Spotify detectado.")
            items = await self.spotify.resolve(spotify_url)
            if not items:
                return await ctx.send("⚠️ No pude leer ese enlace de Spotify.")
            for it in items:
                tracks.append(Track(
                    query=it.query,
                    source="spotify",
                    title=it.title,
                    requester_id=ctx.author.id,
                    requester_name=ctx.author.display_name,
                    text_channel_id=ctx.channel.id
                ))
            await ctx.send(f"✅ Encoladas **{len(tracks)}** pistas desde Spotify.")
        else:
            tracks = [Track(
                query=query,
                source="youtube",
                title=query,
                requester_id=ctx.author.id,
                requester_name=ctx.author.display_name,
                text_channel_id=ctx.channel.id
            )]
            await ctx.send(f"✅ Encolado: **{clean_query(query)}**")

        # ✅ Aquí sí sumamos "pedido" + XP base una sola vez:
        perfiles = self.bot.get_cog("Perfiles")
        if perfiles:
            for _t in tracks:
                try:
                    await perfiles.actualizar_stats(
                        ctx, duracion=0, xp_ganado=10, es_musica=True, contar_pedido=True
                    )
                except Exception:
                    pass

        await player.enqueue(tracks)
        await self.refresh_panel(ctx.guild)

    @commands.command(name="skip", aliases=["s"])
    async def skip(self, ctx: commands.Context):
        player = self.service.get_player(ctx.guild.id)
        ok, msg = await player.skip()
        await ctx.send(("✅ " if ok else "ℹ️ ") + msg)
        await self.refresh_panel(ctx.guild)

    @commands.command(name="stop")
    async def stop(self, ctx: commands.Context):
        player = self.service.get_player(ctx.guild.id)
        ok, msg = await player.stop()
        await ctx.send(("✅ " if ok else "ℹ️ ") + msg)
        await self.refresh_panel(ctx.guild)

    @commands.command(name="loop")
    async def loop(self, ctx: commands.Context):
        player = self.service.get_player(ctx.guild.id)
        state = player.toggle_loop_mode()
        await ctx.send("🔁 " + state)
        await self.refresh_panel(ctx.guild)

    @commands.command(name="pause")
    async def pause(self, ctx: commands.Context):
        player = self.service.get_player(ctx.guild.id)
        ok, msg = await player.toggle_pause()
        await ctx.send(("✅ " if ok else "ℹ️ ") + msg)
        await self.refresh_panel(ctx.guild)

    @commands.command(name="resume")
    async def resume(self, ctx: commands.Context):
        player = self.service.get_player(ctx.guild.id)
        ok, msg = await player.toggle_pause()
        await ctx.send(("✅ " if ok else "ℹ️ ") + msg)
        await self.refresh_panel(ctx.guild)


async def setup(bot: commands.Bot):
    await bot.add_cog(Musica(bot))