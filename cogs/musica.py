# cogs/musica.py
from __future__ import annotations

import os
import random
import discord
from discord.ext import commands, tasks  # <--- IMPORTANTE: Agregamos tasks

# Imports de tu lógica de música
from musicbot.downloader import YTDLDownloader
from musicbot.spotify import SpotifyResolver
from musicbot.player import MusicService, Track

# Usamos tu utilidad.py
from .utilidad import clean_query, progress_bar, fmt_time

# ==========================================================
# 1. DISEÑO VISUAL
# ==========================================================

def build_player_embed(guild, player):
    """Recreamos el diseño visual del reproductor con vista previa de cola."""
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

    # --- Estado Actual ---
    status_icon = "⏸️" if player.is_paused() else "▶️"
    embed.title = f"{status_icon} {clean_query(current.title)}"
    embed.url = current.webpage_url if current.webpage_url else None
    
    # Barra de tiempo (Dinámica)
    duration = current.duration
    played = player._time_played_seconds()
    
    # Generamos la barrita visual
    bar, pct = progress_bar(played, duration)
    
    embed.description = (
        f"`{fmt_time(played)}` {bar} `{fmt_time(duration)}`\n"
        f"👤 **Pedido por:** {current.requester_name}"
    )

    if current.thumbnail:
        embed.set_thumbnail(url=current.thumbnail)

    # --- Sección: A continuación (Mini Cola) ---
    queue_len = len(player.queue)
    if queue_len > 0:
        next_songs = []
        for i, track in enumerate(player.queue[:3], 1):
            next_songs.append(f"`{i}.` {clean_query(track.title)}")
        
        texto_cola = "\n".join(next_songs)
        if queue_len > 3:
            texto_cola += f"\n*...y {queue_len - 3} más.*"
        
        embed.add_field(name="🔜 A continuación:", value=texto_cola, inline=False)

    # --- Pie de página ---
    loop_txt = ""
    if player.loop_track: loop_txt = "🔂 Loop Canción"
    elif player.loop_queue: loop_txt = "🔁 Loop Cola"

    footer_text = f"Total en cola: {queue_len}"
    if loop_txt:
        footer_text += f" • {loop_txt}"

    embed.set_footer(text=footer_text)
    return embed


class MusicControls(discord.ui.View):
    """Los botones interactivos."""
    def __init__(self, cog_musica):
        super().__init__(timeout=None)
        self.cog = cog_musica

    # Fila 1: Controles
    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.primary, row=0)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.voice: return await interaction.response.send_message("❌ Entra a voz.", ephemeral=True)
        player = self.cog.service.get_player(interaction.guild.id)
        await player.toggle_pause()
        await self.cog.refresh_panel(interaction.guild) # Forzamos update inmediato
        await interaction.response.defer()

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.voice: return await interaction.response.send_message("❌ Entra a voz.", ephemeral=True)
        player = self.cog.service.get_player(interaction.guild.id)
        await player.skip()
        await interaction.response.defer()

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.danger, row=0)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.voice: return await interaction.response.send_message("❌ Entra a voz.", ephemeral=True)
        player = self.cog.service.get_player(interaction.guild.id)
        await player.stop()
        await interaction.response.edit_message(content="🛑 **Detenido.**", embed=None, view=None)

    # Fila 2: Gestión
    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, row=1)
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.voice: return await interaction.response.send_message("❌ Entra a voz.", ephemeral=True)
        player = self.cog.service.get_player(interaction.guild.id)
        state = player.toggle_loop_mode()
        await interaction.response.send_message(f"🔄 **{state}**", ephemeral=True)
        await self.cog.refresh_panel(interaction.guild)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.success, row=1)
    async def shuffle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.voice: return await interaction.response.send_message("❌ Entra a voz.", ephemeral=True)
        player = self.cog.service.get_player(interaction.guild.id)
        if len(player.queue) < 2:
            return await interaction.response.send_message("⚠️ Necesito al menos 2 canciones para mezclar.", ephemeral=True)
        random.shuffle(player.queue)
        await interaction.response.send_message("🔀 **Cola mezclada.**", ephemeral=True)
        await self.cog.refresh_panel(interaction.guild)

    @discord.ui.button(emoji="📜", style=discord.ButtonStyle.secondary, row=1)
    async def queue_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        player = self.cog.service.get_player(interaction.guild.id)
        if not player.queue:
            return await interaction.response.send_message("🕳️ La cola está vacía.", ephemeral=True)
        lines = [f"**{i}.** {t.title}" for i, t in enumerate(player.queue, 1)]
        full_text = "\n".join(lines)
        if len(full_text) > 1900: full_text = full_text[:1900] + "\n... (lista cortada)"
        embed = discord.Embed(title="📜 Cola de Reproducción", description=full_text, color=discord.Color.light_grey())
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ==========================================================
# 2. LOGICA DEL COG
# ==========================================================

class _MiniCtx:
    def __init__(self, author: discord.abc.User, channel: discord.abc.Messageable):
        self.author = author
        self.channel = channel

class Musica(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.downloader = YTDLDownloader()

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

        self.controls = MusicControls(self)
        self.song_queue = []
        self.current_track = None
        self.panel_message: dict[int, discord.Message] = {}

        # --- CORRECCIÓN AQUÍ: Iniciamos el loop inmediatamente ---
        # El decorador @before_loop se encargará de esperar a que el bot esté listo
        self.check_progress.start()

    def cog_unload(self):
        # Cancelamos el loop si el cog se descarga para evitar errores
        self.check_progress.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        # Solo añadimos la vista persistente
        self.bot.add_view(self.controls)
        print("🎵 Musica lista para la acción.")

    # ---------------- Bucle de Actualización (Corrección) ----------------
    
    @tasks.loop(seconds=5.0)
    async def check_progress(self):
        """Revisa todos los servidores activos y actualiza su panel."""
        # Copiamos la lista con list(...) para evitar errores si el diccionario cambia mientras iteramos
        for guild_id, message in list(self.panel_message.items()):
            try:
                guild = self.bot.get_guild(guild_id)
                if not guild: continue
                
                player = self.service.get_player(guild_id)
                
                # Verificamos condiciones: conectado, tocando, y NO pausado
                if player and player.is_connected() and player.current and not player.is_paused():
                    # Actualizamos el mensaje con la nueva barra de tiempo
                    await message.edit(embed=build_player_embed(guild, player), view=self.controls)
                    
            except discord.NotFound:
                # Si borraron el mensaje manual, lo sacamos de la lista
                del self.panel_message[guild_id]
            except Exception as e:
                # Logueamos el error pero NO detenemos el loop
                print(f"[AutoUpdate Error] Guild {guild_id}: {e}")

    @check_progress.before_loop
    async def before_check_progress(self):
        # Esperamos a que el bot esté 100% conectado antes de empezar a actualizar
        await self.bot.wait_until_ready()

    # ---------------- Panel ----------------
    async def refresh_panel(self, guild: discord.Guild):
        player = self.service.get_player(guild.id)
        msg = self.panel_message.get(guild.id)
        if not msg: return
        try:
            await msg.edit(embed=build_player_embed(guild, player), view=self.controls)
        except Exception: pass

    async def ensure_panel(self, ctx: commands.Context):
        if ctx.guild.id in self.panel_message: return
        player = self.service.get_player(ctx.guild.id)
        msg = await ctx.send(embed=build_player_embed(ctx.guild, player), view=self.controls)
        self.panel_message[ctx.guild.id] = msg

    # ---------------- Hooks ----------------
    async def _on_state_change(self, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        if guild: await self.refresh_panel(guild)

    async def _on_track_started(self, guild_id: int, track: Track):
        pass

    async def _on_track_finished(self, guild_id: int, track: Track, played_seconds: int, ended_naturally: bool):
        perfiles = self.bot.get_cog("Perfiles")
        if not perfiles: return

        guild = self.bot.get_guild(guild_id)
        if not guild: return
        member = guild.get_member(track.requester_id) if track.requester_id else None
        
        # Recuperación robusta del canal
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
    @commands.hybrid_command(name="panel", description="Muestra el panel de control musical")
    async def panel(self, ctx: commands.Context):
        player = self.service.get_player(ctx.guild.id)
        # Si ya había un panel viejo, intentamos borrarlo para no tener duplicados
        if ctx.guild.id in self.panel_message:
            try: await self.panel_message[ctx.guild.id].delete()
            except: pass
            
        msg = await ctx.send(embed=build_player_embed(ctx.guild, player), view=self.controls)
        self.panel_message[ctx.guild.id] = msg

    @commands.hybrid_command(name="join", aliases=["j"], description="Conecta el bot a tu canal de voz")
    async def join(self, ctx: commands.Context):
        if not ctx.author.voice: return await ctx.send("🎧 Entra a un canal de voz primero.")
        player = self.service.get_player(ctx.guild.id)
        await player.ensure_voice(ctx.author.voice.channel)
        await self.ensure_panel(ctx)
        await ctx.send("✅ Conectado.")
        await self.refresh_panel(ctx.guild)

    @commands.hybrid_command(name="play", aliases=["p"], description="Reproduce música desde YouTube o Spotify")
    async def play(self, ctx: commands.Context, *, query: str):
        if not ctx.author.voice: return await ctx.send("🎧 Entra a un canal de voz primero.")
        player = self.service.get_player(ctx.guild.id)
        await player.ensure_voice(ctx.author.voice.channel)
        await self.ensure_panel(ctx)

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

        perfiles = self.bot.get_cog("Perfiles")
        if perfiles:
            try:
                await perfiles.actualizar_stats(ctx, duracion=0, xp_ganado=10, es_musica=True, contar_pedido=True)
            except: pass

        await player.enqueue(tracks)
        await self.refresh_panel(ctx.guild)

    @commands.hybrid_command(name="skip", aliases=["s"], description="Salta a la siguiente canción")
    async def skip(self, ctx: commands.Context):
        player = self.service.get_player(ctx.guild.id)
        ok, msg = await player.skip()
        await ctx.send(("✅ " if ok else "ℹ️ ") + msg)

    @commands.hybrid_command(name="stop", description="Detiene la música y limpia la cola")
    async def stop(self, ctx: commands.Context):
        player = self.service.get_player(ctx.guild.id)
        ok, msg = await player.stop()
        await ctx.send(("✅ " if ok else "ℹ️ ") + msg)

    @commands.hybrid_command(name="loop", description="Alterna entre los modos de repetición")
    async def loop(self, ctx: commands.Context):
        player = self.service.get_player(ctx.guild.id)
        state = player.toggle_loop_mode()
        await ctx.send("🔁 " + state)
        await self.refresh_panel(ctx.guild)

    @commands.hybrid_command(name="pause", description="Pausa la reproducción actual")
    async def pause(self, ctx: commands.Context):
        player = self.service.get_player(ctx.guild.id)
        ok, msg = await player.toggle_pause()
        await ctx.send(("✅ " if ok else "ℹ️ ") + msg)
        await self.refresh_panel(ctx.guild)

    @commands.hybrid_command(name="resume", description="Reanuda la música pausada")
    async def resume(self, ctx: commands.Context):
        player = self.service.get_player(ctx.guild.id)
        ok, msg = await player.toggle_pause()
        await ctx.send(("✅ " if ok else "ℹ️ ") + msg)
        await self.refresh_panel(ctx.guild)

    @commands.hybrid_command(name="shuffle", description="Mezcla aleatoriamente las canciones en la cola")
    async def shuffle(self, ctx: commands.Context):
        player = self.service.get_player(ctx.guild.id)
        if len(player.queue) < 2:
            return await ctx.send("⚠️ Necesito al menos 2 canciones para mezclar.")
        random.shuffle(player.queue)
        await ctx.send("🔀 **Cola mezclada.**")
        await self.refresh_panel(ctx.guild)

    @commands.hybrid_command(name="queue", aliases=["q", "cola"], description="Muestra la lista de canciones en cola")
    async def queue(self, ctx: commands.Context):
        player = self.service.get_player(ctx.guild.id)
        if not player.queue:
            return await ctx.send("🕳️ La cola está vacía.")
        
        embed = discord.Embed(title="📜 Cola de Reproducción", color=discord.Color.blue())
        description = ""
        for i, track in enumerate(player.queue, 1):
            line = f"**{i}.** {clean_query(track.title)} (`{track.requester_name}`)\n"
            if len(description) + len(line) > 2000:
                description += f"\n...y {len(player.queue) - (i-1)} más."
                break
            description += line
        embed.description = description
        embed.set_footer(text=f"Total: {len(player.queue)} canciones")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Musica(bot))