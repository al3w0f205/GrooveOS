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


class Musica(commands.Cog):
    """Música modular: Spotify->YouTube, prefetch, panel y comandos."""

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
            on_track_finished=self._on_track_finished,
        )

        # View persistente
        self.controls = MusicControls(self)

        # Estado público para tu comando .queue actual
        self.song_queue = []
        self.current_track = None

        # Mensaje panel por guild
        self.panel_message: dict[int, discord.Message] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        # Registrar View persistente (crítico para botones)
        try:
            self.bot.add_view(self.controls)
        except Exception:
            pass
        print("🎵 Musica (modular) cargado: comandos + panel + prefetch.")

    # ------------------------
    # Hooks del player
    # ------------------------

    async def _on_state_change(self, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        if guild:
            await self.refresh_panel(guild)

    async def _on_track_started(self, guild_id: int, track: Track):
        # Integración Perfiles (opcional)
        perfiles = self.bot.get_cog("Perfiles")
        if perfiles:
            try:
                # suma xp + registra duración estimada al terminar la pista (en finished hook)
                # aquí puedes sumar “pedido” si quieres, pero tu Perfiles ya lo hace cuando le pasas es_musica=True
                pass
            except Exception:
                pass

    async def _on_track_finished(self, guild_id: int, track: Track):
        # Integración Perfiles: ahora sí podemos sumar duración reproducida (aprox)
        perfiles = self.bot.get_cog("Perfiles")
        if perfiles:
            try:
                # usamos un contexto simulado mínimo: el método usa ctx_or_msg.author/channel.
                # Para evitar inventar ctx, solo hacemos XP simple si quieres.
                # Si deseas contabilizar exacto, dime y lo adaptamos con canal del panel.
                pass
            except Exception:
                pass

    # ------------------------
    # Panel helpers
    # ------------------------

    async def refresh_panel(self, guild: discord.Guild):
        player = self.service.get_player(guild.id)

        # sync público para .queue
        self.song_queue = [t.title if t.title else t.query for t in list(player.queue)]
        self.current_track = player.current.title if player.current else None

        msg = self.panel_message.get(guild.id)
        if not msg:
            return

        try:
            embed = build_player_embed(guild, player)
            await msg.edit(embed=embed, view=self.controls)
        except Exception:
            pass

    async def ensure_panel(self, ctx: commands.Context):
        if ctx.guild.id in self.panel_message:
            return
        embed = build_player_embed(ctx.guild, self.service.get_player(ctx.guild.id))
        msg = await ctx.send(embed=embed, view=self.controls)
        self.panel_message[ctx.guild.id] = msg

    # ------------------------
    # Comandos (prefijo .)
    # ------------------------

    @commands.command(name="panel")
    async def panel(self, ctx: commands.Context):
        """Crea o reasigna el panel en este canal."""
        embed = build_player_embed(ctx.guild, self.service.get_player(ctx.guild.id))
        msg = await ctx.send(embed=embed, view=self.controls)
        self.panel_message[ctx.guild.id] = msg

    @commands.command(name="join", aliases=["j"])
    async def join(self, ctx: commands.Context):
        """Conecta al canal de voz del autor."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("🎧 Entra a un canal de voz primero.")
        player = self.service.get_player(ctx.guild.id)
        await player.ensure_voice(ctx.author.voice.channel)
        await self.ensure_panel(ctx)
        await ctx.send("✅ Conectado.")
        await self.refresh_panel(ctx.guild)

    @commands.command(name="play", aliases=["p"])
    async def play(self, ctx: commands.Context, *, query: str):
        """Reproduce/encola YouTube o Spotify (track/playlist)."""
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("🎧 Entra a un canal de voz primero.")

        player = self.service.get_player(ctx.guild.id)
        await player.ensure_voice(ctx.author.voice.channel)
        await self.ensure_panel(ctx)

        spotify_url = self.spotify.is_spotify_url(query)

        tracks: list[Track] = []
        if spotify_url:
            await ctx.send("🟢 Spotify detectado. Resolviendo → YouTube…")
            items = await self.spotify.resolve(spotify_url)
            if not items:
                return await ctx.send("⚠️ No pude leer ese enlace de Spotify.")
            for it in items:
                tracks.append(
                    Track(
                        query=it.query,
                        source="spotify",
                        title=it.title,
                        requester_id=ctx.author.id,
                        requester_name=ctx.author.display_name,
                    )
                )
            await ctx.send(f"✅ Encoladas **{len(tracks)}** pistas desde Spotify.")
        else:
            tracks = [Track(
                query=query,
                source="youtube",
                title=query,
                requester_id=ctx.author.id,
                requester_name=ctx.author.display_name
            )]
            await ctx.send(f"✅ En cola: **{clean_query(query)}**")

        await player.enqueue(tracks)
        await self.refresh_panel(ctx.guild)

    @commands.command(name="skip", aliases=["s"])
    async def skip(self, ctx: commands.Context):
        """Salta la pista actual."""
        player = self.service.get_player(ctx.guild.id)
        ok, msg = await player.skip()
        await ctx.send(("✅ " if ok else "ℹ️ ") + msg)
        await self.refresh_panel(ctx.guild)

    @commands.command(name="stop")
    async def stop(self, ctx: commands.Context):
        """Detiene, limpia cola y temporales."""
        player = self.service.get_player(ctx.guild.id)
        ok, msg = await player.stop()
        await ctx.send(("✅ " if ok else "ℹ️ ") + msg)
        await self.refresh_panel(ctx.guild)

    @commands.command(name="loop")
    async def loop(self, ctx: commands.Context):
        """Alterna loop OFF->Track->Queue->OFF."""
        player = self.service.get_player(ctx.guild.id)
        state = player.toggle_loop_mode()
        await ctx.send("🔁 " + state)
        await self.refresh_panel(ctx.guild)

    @commands.command(name="pause")
    async def pause(self, ctx: commands.Context):
        """Pausa."""
        player = self.service.get_player(ctx.guild.id)
        ok, msg = await player.toggle_pause()
        await ctx.send(("✅ " if ok else "ℹ️ ") + msg)
        await self.refresh_panel(ctx.guild)

    @commands.command(name="resume")
    async def resume(self, ctx: commands.Context):
        """Reanuda (alias de toggle si está pausado)."""
        player = self.service.get_player(ctx.guild.id)
        ok, msg = await player.toggle_pause()
        await ctx.send(("✅ " if ok else "ℹ️ ") + msg)
        await self.refresh_panel(ctx.guild)


async def setup(bot: commands.Bot):
    await bot.add_cog(Musica(bot))