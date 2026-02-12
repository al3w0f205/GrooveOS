# cogs/musica.py
from __future__ import annotations

import os
import discord
from discord.ext import commands

# Imports de tu lógica de música (que SÍ funciona)
from musicbot.downloader import YTDLDownloader
from musicbot.spotify import SpotifyResolver
from musicbot.player import MusicService, Track

# Usamos tu utilidad.py que está perfecta
from .utilidad import clean_query, progress_bar, fmt_time

# ==========================================================
# 1. RECUPERAMOS LOS CONTROLES (ESTO FALTABA)
# ==========================================================

def build_player_embed(guild, player):
    """Recreamos el diseño visual del reproductor aquí mismo."""
    embed = discord.Embed(color=discord.Color.blurple())

    if not player or not player.is_connected():
        embed.title = "🔇 Nada reproduciéndose"
        embed.description = "Usa `.play <canción>` para empezar."
        return embed

    current = player.current
    if not current:
        embed.title = "zzZ Inactivo"
        embed.description = "Cola vacía. Esperando música..."
        return embed

    # Estado (Pausa/Play)
    status_icon = "⏸️" if player.is_paused() else "▶️"
    embed.title = f"{status_icon} {clean_query(current.title)}"
    embed.url = current.webpage_url if current.webpage_url else None
    
    # Barra de tiempo (Usando tu utilidad.py)
    duration = current.duration
    played = player._time_played_seconds()
    
    # Generamos la barrita visual
    bar, pct = progress_bar(played, duration)
    
    embed.description = (
        f"`{fmt_time(played)}` {bar} `{fmt_time(duration)}`\n\n"
        f"👤 **Pedido por:** {current.requester_name}"
    )

    if current.thumbnail:
        embed.set_thumbnail(url=current.thumbnail)

    # Pie de página con info de cola
    queue_len = len(player.queue)
    loop_txt = ""
    if player.loop_track: loop_txt = "🔂 Loop Canción"
    elif player.loop_queue: loop_txt = "🔁 Loop Cola"

    footer_text = f"En cola: {queue_len} canciones"
    if loop_txt:
        footer_text += f" • {loop_txt}"

    embed.set_footer(text=footer_text)
    return embed


class MusicControls(discord.ui.View):
    """Los botones interactivos para controlar la música."""
    def __init__(self, cog_musica):
        super().__init__(timeout=None)
        self.cog = cog_musica

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.voice: return
        player = self.cog.service.get_player(interaction.guild.id)
        await player.toggle_pause()
        await interaction.response.edit_message(embed=build_player_embed(interaction.guild, player), view=self)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.voice: return
        player = self.cog.service.get_player(interaction.guild.id)
        await player.skip()
        await interaction.response.defer() # Solo confirmamos, el bot actualiza solo

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.voice: return
        player = self.cog.service.get_player(interaction.guild.id)
        await player.stop()
        await interaction.response.edit_message(content="🛑 **Detenido.**", embed=None, view=None)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary)
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.voice: return
        player = self.cog.service.get_player(interaction.guild.id)
        state = player.toggle_loop_mode()
        await interaction.response.send_message(f"🔄 **{state}**", ephemeral=True)
        await self.cog.refresh_panel(interaction.guild)


# ==========================================================
# 2. TU CÓDIGO ORIGINAL (MODIFICADO PARA USAR LO DE ARRIBA)
# ==========================================================

class _MiniCtx:
    """Helper para estadísticas."""
    def __init__(self, author: discord.abc.User, channel: discord.abc.Messageable):
        self.author = author
        self.channel = channel

class Musica(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.downloader = YTDLDownloader()

        # Inicialización de Spotify (con protección por si fallan las claves)
        try:
            self.spotify = SpotifyResolver()
            print("[Musica] Spotify habilitado.")
        except Exception as e:
            self.spotify = None
            print(f"[Musica] Spotify deshabilitado: {e}")

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

        # Aquí cargamos los controles que definimos arriba
        self.controls = MusicControls(self)
        self.song_queue = []
        self.current_track = None
        self.panel_message: dict[int, discord.Message] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        # Registramos la vista para que los botones funcionen al reiniciar
        self.bot.add_view(self.controls)
        print("🎵 Musica lista para la acción.")

    # ---------------- Panel ----------------
    async def refresh_panel(self, guild: discord.Guild):
        player = self.service.get_player(guild.id)
        self.song_queue = [t.title if t.title else t.query for t in list(player.queue)]
        self.current_track = player.current.title if player.current else None

        msg = self.panel_message.get(guild.id)
        if not msg: return
        try:
            # Usamos la función local build_player_embed
            await msg.edit(embed=build_player_embed(guild, player), view=self.controls)
        except Exception: pass

    async def ensure_panel(self, ctx: commands.Context):
        if ctx.guild.id in self.panel_message: return
        player = self.service.get_player(ctx.guild.id)
        # Usamos la función local build_player_embed
        msg = await ctx.send(embed=build_player_embed(ctx.guild, player), view=self.controls)
        self.panel_message[ctx.guild.id] = msg

    # ---------------- Hooks (Eventos) ----------------
    async def _on_state_change(self, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        if guild: await self.refresh_panel(guild)

    async def _on_track_started(self, guild_id: int, track: Track):
        pass

    async def _on_track_finished(self, guild_id: int, track: Track, played_seconds: int, ended_naturally: bool):
        # Conexión con Perfiles para dar XP
        perfiles = self.bot.get_cog("Perfiles")
        if not perfiles: return

        guild = self.bot.get_guild(guild_id)
        if not guild: return

        member = guild.get_member(track.requester_id) if track.requester_id else None

        # Intentamos recuperar el canal original, si no, el del panel
        channel = guild.get_channel(track.text_channel_id) if track.text_channel_id else None
        if not channel:
            panel = self.panel_message.get(guild_id)
            channel = panel.channel if panel else None

        if not member or not channel or played_seconds <= 0: return

        mini = _MiniCtx(author=member, channel=channel)
        try:
            await perfiles.actualizar_stats(
                mini, duracion=played_seconds, xp_ganado=0, es_musica=True, contar_pedido=False
            )
        except Exception: pass

    # ---------------- Comandos ----------------
    @commands.command(name="panel")
    async def panel(self, ctx: commands.Context):
        player = self.service.get_player(ctx.guild.id)
        msg = await ctx.send(embed=build_player_embed(ctx.guild, player), view=self.controls)
        self.panel_message[ctx.guild.id] = msg

    @commands.command(name="join", aliases=["j"])
    async def join(self, ctx: commands.Context):
        if not ctx.author.voice: return await ctx.send("🎧 Entra a un canal de voz primero.")
        player = self.service.get_player(ctx.guild.id)
        await player.ensure_voice(ctx.author.voice.channel)
        await self.ensure_panel(ctx)
        await ctx.send("✅ Conectado.")
        await self.refresh_panel(ctx.guild)

    @commands.command(name="play", aliases=["p"])
    async def play(self, ctx: commands.Context, *, query: str):
        if not ctx.author.voice: return await ctx.send("🎧 Entra a un canal de voz primero.")
        player = self.service.get_player(ctx.guild.id)
        await player.ensure_voice(ctx.author.voice.channel)
        await self.ensure_panel(ctx)

        # Lógica de Spotify (integrada correctamente)
        spotify_url = self.spotify.is_spotify_url(query) if self.spotify else None
        tracks: list[Track] = []

        if spotify_url:
            await ctx.send("🟢 Enlace de Spotify detectado...")
            items = await self.spotify.resolve(spotify_url)
            if not items: return await ctx.send("⚠️ No pude leer ese enlace de Spotify.")

            for it in items:
                tracks.append(Track(
                    query=it.query, source="spotify", title=it.title,
                    requester_id=ctx.author.id, requester_name=ctx.author.display_name,
                    text_channel_id=ctx.channel.id
                ))
            await ctx.send(f"✅ **{len(tracks)}** canciones de Spotify añadidas a la cola.")
        else:
            tracks = [Track(
                query=query, source="youtube", title=query,
                requester_id=ctx.author.id, requester_name=ctx.author.display_name,
                text_channel_id=ctx.channel.id
            )]
            await ctx.send(f"✅ Añadido: **{clean_query(query)}**")

        # XP inicial (solo una vez)
        perfiles = self.bot.get_cog("Perfiles")
        if perfiles:
            try:
                await perfiles.actualizar_stats(ctx, duracion=0, xp_ganado=10, es_musica=True, contar_pedido=True)
            except: pass

        await player.enqueue(tracks)
        await self.refresh_panel(ctx.guild)

    @commands.command(name="skip", aliases=["s"])
    async def skip(self, ctx: commands.Context):
        player = self.service.get_player(ctx.guild.id)
        ok, msg = await player.skip()
        await ctx.send(("✅ " if ok else "ℹ️ ") + msg)

    @commands.command(name="stop")
    async def stop(self, ctx: commands.Context):
        player = self.service.get_player(ctx.guild.id)
        ok, msg = await player.stop()
        await ctx.send(("✅ " if ok else "ℹ️ ") + msg)

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