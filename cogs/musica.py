import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import ctypes.util
import requests
from bs4 import BeautifulSoup

# ==========================================
# ⚙️ CONFIGURACIÓN DE AUDIO
# ==========================================
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0'
}

FFMPEG_OPTIONS = {'options': '-vn -loglevel quiet'}
ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

# ==========================================
# 🎵 FUENTE DE AUDIO
# ==========================================
class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.filename = ytdl.prepare_filename(data)

    @classmethod
    async def from_query(cls, query, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        try:
            # Descarga el audio físicamente al disco del contenedor Proxmox
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=True))
            if 'entries' in data: data = data['entries'][0]
            return cls(discord.FFmpegPCMAudio(ytdl.prepare_filename(data), **FFMPEG_OPTIONS), data=data)
        except Exception as e:
            print(f"❌ Error YTDL: {e}")
            return None

# ==========================================
# 🎧 MÓDULO DE MÚSICA (COG)
# ==========================================
class Musica(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.song_queue = []
        
        # Variables para la Pre-Carga (Buffering)
        self.preloaded_player = None 
        self.preloaded_query = None

        # Cargar Opus para que el audio funcione en Linux
        opus_path = ctypes.util.find_library('opus')
        if opus_path:
            try: discord.opus.load_opus(opus_path)
            except: pass

    def cleanup_file(self, filename):
        """Borra la canción del disco para ahorrar espacio en Proxmox."""
        if filename and os.path.exists(filename):
            try: os.remove(filename)
            except: pass

    async def preload_next(self, query):
        """Descarga la siguiente canción en segundo plano sin reproducirla aún."""
        try:
            # Si ya estamos precargando esa misma, no hacemos nada
            if self.preloaded_query == query and self.preloaded_player:
                return

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
        if last_file: self.cleanup_file(last_file)
        
        if len(self.song_queue) > 0:
            await self.play_music(ctx, self.song_queue.pop(0))

    async def play_music(self, ctx, query):
        """Maneja la descarga, reproducción física y registro de estadísticas."""
        
        # 1. OBTENER EL REPRODUCTOR (Desde Buffer o Descarga)
        if self.preloaded_query == query and self.preloaded_player:
            player = self.preloaded_player
            self.preloaded_player = None 
            self.preloaded_query = None
            await ctx.send(f"⚡ **Reproducción instantánea:** `{player.title}`")
        else:
            msg = await ctx.send(f"💿 Cargando: `{query}`...")
            player = await YTDLSource.from_query(query, loop=self.bot.loop)
            if not player:
                return await msg.edit(content="❌ Error de descarga.")
            await msg.delete()

        # 2. REGISTRO AUTOMÁTICO EN PERFILES
        # Extraemos la duración (en segundos) que viene de los metadatos de yt-dlp
        duracion_segundos = player.data.get('duration', 0)
        
        perfiles_cog = self.bot.get_cog('Perfiles')
        if perfiles_cog:
            # Llamamos a la función que actualizamos antes con el nuevo parámetro
            await perfiles_cog.actualizar_stats(ctx, duracion=duracion_segundos)

        # 3. CONFIGURAR SIGUIENTE PASO (Callback)
        def after_playing(error):
            if error: print(f"Error: {error}")
            asyncio.run_coroutine_threadsafe(self.play_next(ctx, player.filename), self.bot.loop)

        # 4. REPRODUCIR
        ctx.voice_client.play(player, after=after_playing)
        await ctx.send(f"🎶 Sonando: **{player.title}**")

        # 5. DISPARAR PRE-CARGA DE LA SIGUIENTE
        if len(self.song_queue) > 0:
            next_song = self.song_queue[0]
            self.bot.loop.create_task(self.preload_next(next_song))
            
            
    # --- COMANDOS ---

    @commands.command(name='join')
    async def join(self, ctx):
        if ctx.author.voice:
            canal = ctx.author.voice.channel
            if ctx.voice_client: await ctx.voice_client.move_to(canal)
            else: await canal.connect()
            await ctx.send(f"👍 Conectado a **{canal.name}**")
        else:
            await ctx.send("🚫 Debes estar en un canal de voz.")

    @commands.command(name='p')
    async def play(self, ctx, *, query):
        """Reproduce YouTube o extrae de Spotify/Apple Music con soporte de pre-carga."""
        
        # 1. Verificación de conexión a canal de voz
        if not ctx.voice_client:
            await ctx.invoke(self.join)

        # --- LÓGICA DE PRE-CARGA (BUFFER) ---
        is_preloaded = hasattr(self, 'preloaded_query') and self.preloaded_query == query and self.preloaded_player is not None

        # 2. PLAN B: Scraping para Spotify/Apple Music
        if not is_preloaded and ("spotify.com" in query or "apple.com" in query):
            msg_espera = await ctx.send("🕵️ Extrayendo nombres de la playlist... (Esto puede tardar un poco)")
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                res = requests.get(query, headers=headers, timeout=10)
                soup = BeautifulSoup(res.text, 'html.parser')
                
                song_names = [s.get('content') for s in soup.find_all('meta', property="music:song") if s.get('content')]
                
                if not song_names:
                    song_names = [t.text.split(' · song')[0] for t in soup.find_all('title') if "song" in t.text.lower()]
                
                if not song_names:
                    await msg_espera.edit(content="⚠️ No pude leer la lista. Intentando reproducir el link directamente...")
                else:
                    song_names = list(dict.fromkeys([s for s in song_names if s]))
                    for song in song_names:
                        self.song_queue.append(song)
                    
                    await msg_espera.edit(content=f"✅ ¡Éxito! Añadidas **{len(song_names)}** canciones a la cola.")
                    
                    if not ctx.voice_client.is_playing():
                        # REGISTRO DE PERFIL (Para playlists no tenemos duración exacta de cada una aún)
                        perfiles_cog = self.bot.get_cog('Perfiles')
                        if perfiles_cog:
                            await perfiles_cog.actualizar_stats(ctx)
                           
                        await self.play_music(ctx, self.song_queue.pop(0))
                    return 

            except Exception as e:
                print(f"Error scraping: {e}")

        # 3. Lógica Normal de YouTube y Gestión de Cola
        if ctx.voice_client.is_playing():
            self.song_queue.append(query)
            await ctx.send(f"✅ En cola: `{query}`")
            
            if len(self.song_queue) == 1:
                self.bot.loop.create_task(self.preload_next(self.song_queue[0]))
        else:
            # --- INTEGRACIÓN CON PERFILES Y TIEMPO ---
            perfiles_cog = self.bot.get_cog('Perfiles')
            duracion_segundos = 0

            # Si está pre-cargada, sacamos la duración del buffer
            if is_preloaded:
                duracion_segundos = self.preloaded_player.data.get('duration', 0)
            
            # Si no está cargada, la play_music la descargará, pero necesitamos 
            # registrar los stats. Lo ideal es hacerlo dentro de play_music o 
            # extraer la info aquí. Para mantenerlo simple, play_music se encarga:
            await self.play_music(ctx, query)
            
            # Si queremos ser precisos, play_music debería devolver el objeto player
            # para registrar los segundos después de la descarga.
            
            
    @commands.command(name='stop')
    async def stop(self, ctx):
        self.song_queue = []
        # Limpiamos también el buffer si detenemos todo
        self.preloaded_player = None
        self.preloaded_query = None
        
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("🛑 Música detenida.")
        else:
            await ctx.send("No estoy conectado a voz.")

    @commands.command(name='skip')
    async def skip(self, ctx):
        """Salta la canción actual y pasa a la siguiente en la cola."""
        if ctx.voice_client and ctx.voice_client.is_playing():
            ctx.voice_client.stop()
            await ctx.send("⏭️ **Saltando canción...**")
        else:
            await ctx.send("🚫 No hay ninguna canción reproduciéndose ahora mismo.")

async def setup(bot):
    await bot.add_cog(Musica(bot))