import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import ctypes.util
import requests
from bs4 import BeautifulSoup
import random
import time

# ==========================================
# ⚙️ CONFIGURACIÓN DE AUDIO
# ==========================================
YTDL_OPTIONS = {
    "format": "bestaudio/best",
    "outtmpl": "%(extractor)s-%(id)s-%(title)s.%(ext)s",
    "restrictfilenames": True,
    "noplaylist": True,
    "nocheckcertificate": True,
    "ignoreerrors": False,
    "quiet": True,
    "no_warnings": True,
    "default_search": "auto",
    "source_address": "0.0.0.0",
}

# Recomendado: agrega reconexión para streams si algún link cae
FFMPEG_OPTIONS = {
    "options": "-vn -loglevel quiet -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)


# ==========================================
# 🎵 FUENTE DE AUDIO
# ==========================================
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
            # Descarga física del audio
            data = await loop.run_in_executor(
                None, lambda: ytdl.extract_info(query, download=True)
            )
            if "entries" in data:
                data = data["entries"][0]
            filename = ytdl.prepare_filename(data)
            return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)
        except Exception as e:
            print(f"❌ Error YTDL: {e}")
            return None


# ==========================================
# 🎮 CLASE DE BOTONES INTERACTIVOS (UI)
# ==========================================
class ControlesMusica(discord.ui.View):
    def __init__(self, ctx, cog, query):
        super().__init__(timeout=None)
        self.ctx = ctx
        self.cog = cog
        self.query = query

        # Ajustar color inicial del botón Loop
        for child in self.children:
            if isinstance(child, discord.ui.Button) and str(child.emoji) == "🔁":
                child.style = (
                    discord.ButtonStyle.primary
                    if getattr(self.cog, "loop_enabled", False)
                    else discord.ButtonStyle.secondary
                )

    @discord.ui.button(emoji="⏮️", style=discord.ButtonStyle.secondary)
    async def replay(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Reinicia la canción actual."""
        if not self.ctx.voice_client:
            return await interaction.response.send_message(
                "🚫 No estoy conectado a voz.", ephemeral=True
            )

        # Insertamos la canción actual al inicio de la cola y hacemos stop para disparar after()
        self.cog.song_queue.insert(0, self.query)
        self.ctx.voice_client.stop()
        await interaction.response.send_message(
            "⏮️ **Reiniciando canción...**", ephemeral=True
        )

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.secondary)
    async def pause_resume(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Alterna entre Pausa y Reanudar."""
        vc = self.ctx.voice_client
        if not vc:
            return await interaction.response.send_message(
                "🚫 No estoy conectado a voz.", ephemeral=True
            )

        if vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ **Reanudado**", ephemeral=True)
        elif vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸️ **Pausado**", ephemeral=True)
        else:
            await interaction.response.send_message(
                "ℹ️ No hay nada reproduciéndose.", ephemeral=True
            )

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Salta a la siguiente canción."""
        if not self.ctx.voice_client:
            return await interaction.response.send_message(
                "🚫 No estoy conectado a voz.", ephemeral=True
            )

        self.ctx.voice_client.stop()
        await interaction.response.send_message("⏭️ **Saltando...**", ephemeral=True)

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, row=1)
    async def loop_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Activa/Desactiva bucle."""
        estado = getattr(self.cog, "loop_enabled", False)
        self.cog.loop_enabled = not estado

        if self.cog.loop_enabled:
            button.style = discord.ButtonStyle.primary
            msg = "🔄 **Bucle ACTIVADO**"
        else:
            button.style = discord.ButtonStyle.secondary
            msg = "➡️ **Bucle DESACTIVADO**"

        await interaction.response.edit_message(view=self)
        await interaction.followup.send(msg, ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.secondary)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Detiene todo y desconecta."""
        self.cog.song_queue = []
        self.cog.preloaded_player = None
        self.cog.preloaded_query = None

        vc = self.ctx.voice_client
        if vc:
            try:
                vc.stop()
            except Exception:
                pass
            try:
                await vc.disconnect()
            except Exception:
                pass

        await interaction.response.send_message("⏹️ **Desconectado.**", ephemeral=True)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary)
    async def shuffle_btn(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        """Mezcla la cola."""
        if len(self.cog.song_queue) < 2:
            return await interaction.response.send_message(
                "📉 Faltan canciones para mezclar.", ephemeral=True
            )

        random.shuffle(self.cog.song_queue)
        await interaction.response.send_message(
            "🔀 **¡Cola mezclada!** La siguiente canción será una sorpresa.",
            ephemeral=True,
        )


# ==========================================
# 🎧 MÓDULO DE MÚSICA (COG)
# ==========================================
class Musica(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.song_queue = []
        self.loop_enabled = False

        # Pre-carga (Buffering)
        self.preloaded_player = None
        self.preloaded_query = None

        # Barra de progreso
        self.barra_task = None

        # Track actual
        self.current_track = None

        # Cargar Opus (Linux)
        opus_path = ctypes.util.find_library("opus")
        if opus_path:
            try:
                discord.opus.load_opus(opus_path)
            except Exception:
                pass

    # -------------------
    # Utilidades
    # -------------------
    def crear_barra_visual(self, actual, total):
        """Crea un string visual tipo: ▬▬▬🔘▬▬▬▬"""
        longitud = 15
        if total <= 0:
            return "🔘" + "▬" * longitud

        porcentaje = actual / total
        if porcentaje > 1:
            porcentaje = 1

        bloques = int(porcentaje * longitud)
        bloques = max(0, min(bloques, longitud - 1))
        return "▬" * bloques + "🔘" + "▬" * (longitud - 1 - bloques)

    def cleanup_file(self, filename):
        """Borra la canción del disco para ahorrar espacio."""
        if filename and os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception:
                pass

    async def preload_next(self, query):
        """Descarga la siguiente canción en segundo plano sin reproducirla aún."""
        try:
            if self.preloaded_query == query and self.preloaded_player:
                return

            # Si vamos a reemplazar un preload anterior, limpiamos su archivo
            if self.preloaded_player:
                try:
                    self.cleanup_file(self.preloaded_player.filename)
                except Exception:
                    pass

            print(f"📥 Iniciando pre-carga de: {query}")
            player = await YTDLSource.from_query(query, loop=self.bot.loop)
            if player:
                self.preloaded_player = player
                self.preloaded_query = query
                print(f"✅ Pre-carga lista: {player.title}")
        except Exception as e:
            print(f"❌ Error en pre-carga: {e}")

    async def play_next(self, ctx, last_file=None):
        """Limpia el archivo anterior y toca el siguiente de la cola."""
        if self.barra_task:
            self.barra_task.cancel()

        if last_file:
            self.cleanup_file(last_file)

        if len(self.song_queue) > 0:
            await self.play_music(ctx, self.song_queue.pop(0))

    async def play_music(self, ctx, query):
        """Maneja la descarga, reproducción y envía un Embed estilo Spotify."""
        self.current_track = query

        # Cancelar barra anterior por seguridad
        if self.barra_task:
            self.barra_task.cancel()

        # 1) Obtener reproductor
        if self.preloaded_query == query and self.preloaded_player:
            player = self.preloaded_player
            self.preloaded_player = None
            self.preloaded_query = None
        else:
            msg = await ctx.send("💿 **Cargando...**")
            player = await YTDLSource.from_query(query, loop=self.bot.loop)
            if not player:
                return await msg.edit(content="❌ Error de descarga.")
            await msg.delete()

        # 2) Registrar estadísticas (si existe Cog Perfiles)
        duracion_segundos = player.data.get("duration", 0)
        perfiles_cog = self.bot.get_cog("Perfiles")
        if perfiles_cog:
            try:
                await perfiles_cog.actualizar_stats(ctx, duracion=duracion_segundos, es_musica=True)
            except Exception:
                try:
                    await perfiles_cog.actualizar_stats(ctx, duracion=duracion_segundos)
                except Exception:
                    pass

        # 3) Callback al terminar
        def after_playing(error):
            try:
                if self.barra_task:
                    self.barra_task.cancel()

                if error:
                    print(f"Error: {error}")

                # Loop: reinsertar track actual al inicio de cola
                if self.loop_enabled and self.current_track:
                    self.song_queue.insert(0, self.current_track)

                asyncio.run_coroutine_threadsafe(
                    self.play_next(ctx, player.filename), self.bot.loop
                )
            except Exception as e:
                print(f"❌ Error en after_playing: {e}")

        # 4) Reproducir
        if not ctx.voice_client:
            return await ctx.send("🚫 No estoy conectado a voz. Usa `!join` primero.")

        ctx.voice_client.play(player, after=after_playing)

        # 5) Enviar panel con barra
        await self.enviar_panel_animado(ctx, player)

        # 6) Pre-carga siguiente (solo una vez)
        if len(self.song_queue) > 0:
            self.bot.loop.create_task(self.preload_next(self.song_queue[0]))

    async def enviar_panel_animado(self, ctx, player):
        """Crea el embed inicial y lanza la tarea que actualiza la barra."""
        data = player.data
        titulo = data.get("title", "Desconocido")
        url = data.get("webpage_url", "")
        duracion = data.get("duration", 0)
        thumbnail = data.get("thumbnail")

        start_time = time.time()
        barra_inicial = self.crear_barra_visual(0, duracion)

        # timestamp unix del final (relativo)
        tiempo_final = int(start_time + duracion)

        embed = discord.Embed(
            title=titulo,
            url=url,
            color=discord.Color.from_rgb(255, 0, 0),
        )

        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        embed.add_field(name="👤 Artista", value=f"**{data.get('uploader', 'Desconocido')}**", inline=True)
        embed.add_field(name="💿 Pedido por", value=ctx.author.mention, inline=True)

        embed.add_field(
            name="⏱️ Progreso",
            value=f"{barra_inicial}\n**Restante:** <t:{tiempo_final}:R>",
            inline=False,
        )
        embed.add_field(name="🔴 Estado", value="`🔴 EN VIVO`", inline=False)

        view = ControlesMusica(ctx, self, url)
        mensaje = await ctx.send(embed=embed, view=view)

        # Tarea en segundo plano
        self.barra_task = self.bot.loop.create_task(
            self.actualizar_barra_loop(mensaje, embed, start_time, duracion, view)
        )

    async def actualizar_barra_loop(self, mensaje, embed, start_time, duracion_total, view):
        """Actualiza la barra cada 15s."""
        try:
            while True:
                await asyncio.sleep(15)

                tiempo_actual = time.time() - start_time
                if tiempo_actual > duracion_total:
                    break

                nueva_barra = self.crear_barra_visual(tiempo_actual, duracion_total)
                tiempo_final = int(start_time + duracion_total)

                # Campo index 2 = Progreso (0: artista, 1: pedido, 2: progreso, 3: estado)
                embed.set_field_at(
                    2,
                    name="⏱️ Progreso",
                    value=f"{nueva_barra}\n**Restante:** <t:{tiempo_final}:R>",
                    inline=False,
                )

                await mensaje.edit(embed=embed, view=view)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Error barra: {e}")

    # -------------------
    # COMANDOS
    # -------------------
    @commands.command(name="join")
    async def join(self, ctx):
        """Conecta al bot al canal de voz del autor."""
        if ctx.author.voice:
            canal = ctx.author.voice.channel
            if ctx.voice_client:
                await ctx.voice_client.move_to(canal)
            else:
                await canal.connect()

            embed = discord.Embed(
                description=f"🔊 **Conectado exitosamente a:** `{canal.name}`\nListo para el Groove.",
                color=discord.Color.green(),
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send(
                embed=discord.Embed(
                    description="🚫 **Error:** Debes estar en un canal de voz primero.",
                    color=discord.Color.red(),
                )
            )

    @commands.command(name="p")
    async def play(self, ctx, *, query: str):
        """Reproduce YouTube o extrae de Spotify/Apple Music con soporte de pre-carga."""
        if not ctx.voice_client:
            await ctx.invoke(self.join)

        if not ctx.voice_client:
            return await ctx.send("🚫 No pude conectarme a tu canal de voz.")

        # ¿Está pre-cargada?
        is_preloaded = (
            self.preloaded_query == query and self.preloaded_player is not None
        )

        # Spotify / Apple (scraping simple)
        if (not is_preloaded) and ("spotify.com" in query or "apple.com" in query):
            msg_espera = await ctx.send(
                "🕵️ Extrayendo nombres de la playlist... (Esto puede tardar un poco)"
            )
            try:
                headers = {
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/91.0.4472.124 Safari/537.36"
                    )
                }
                res = requests.get(query, headers=headers, timeout=10)
                soup = BeautifulSoup(res.text, "html.parser")

                song_names = [
                    s.get("content")
                    for s in soup.find_all("meta", property="music:song")
                    if s.get("content")
                ]

                if not song_names:
                    song_names = [
                        t.text.split(" · song")[0]
                        for t in soup.find_all("title")
                        if "song" in t.text.lower()
                    ]

                if not song_names:
                    await msg_espera.edit(
                        content="⚠️ No pude leer la lista. Intentando reproducir el link directamente..."
                    )
                else:
                    # Quitar duplicados manteniendo orden
                    song_names = list(dict.fromkeys([s for s in song_names if s]))

                    for song in song_names:
                        self.song_queue.append(song)

                    await msg_espera.edit(
                        content=f"✅ ¡Éxito! Añadidas **{len(song_names)}** canciones a la cola."
                    )

                    if not ctx.voice_client.is_playing():
                        perfiles_cog = self.bot.get_cog("Perfiles")
                        if perfiles_cog:
                            try:
                                await perfiles_cog.actualizar_stats(ctx)
                            except Exception:
                                pass

                        await self.play_music(ctx, self.song_queue.pop(0))
                    return

            except Exception as e:
                print(f"Error scraping: {e}")

        # YouTube normal + cola
        if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
            self.song_queue.append(query)
            await ctx.send(f"✅ En cola: `{query}`")

            # Si es el primero en cola, precargarlo
            if len(self.song_queue) == 1:
                self.bot.loop.create_task(self.preload_next(self.song_queue[0]))
        else:
            await self.play_music(ctx, query)

    @commands.command(name="stop")
    async def stop_cmd(self, ctx):
        """Detiene todo y desconecta."""
        self.song_queue = []

        # limpiar buffer
        if self.preloaded_player:
            try:
                self.cleanup_file(self.preloaded_player.filename)
            except Exception:
                pass

        self.preloaded_player = None
        self.preloaded_query = None

        # cancelar barra
        if self.barra_task:
            self.barra_task.cancel()
            self.barra_task = None

        if ctx.voice_client:
            try:
                ctx.voice_client.stop()
            except Exception:
                pass
            try:
                await ctx.voice_client.disconnect()
            except Exception:
                pass
            await ctx.send("🛑 Música detenida.")
        else:
            await ctx.send("No estoy conectado a voz.")

    @commands.command(name="skip")
    async def skip_cmd(self, ctx):
        """Salta la canción actual."""
        if ctx.voice_client and (ctx.voice_client.is_playing() or ctx.voice_client.is_paused()):
            ctx.voice_client.stop()
            await ctx.send("⏭️ **Saltando canción...**")
        else:
            await ctx.send("🚫 No hay ninguna canción reproduciéndose ahora mismo.")

    @commands.command(name="shuffle", aliases=["mix", "random"])
    async def shuffle(self, ctx):
        """Mezcla aleatoriamente las canciones en espera."""
        if len(self.song_queue) < 2:
            return await ctx.send(
                "📉 **Error:** Necesito al menos 2 canciones en la cola para mezclar."
            )

        random.shuffle(self.song_queue)
        await ctx.send(
            f"🔀 **Cola Mezclada.** Hay {len(self.song_queue)} canciones listas para sorprenderte."
        )


async def setup(bot):
    await bot.add_cog(Musica(bot))