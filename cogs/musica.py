import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
import ctypes.util

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
# 🎵 CLASE DE FUENTE DE AUDIO
# ==========================================
class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.filename = ytdl.prepare_filename(data)

    @classmethod
    async def from_query(cls, query, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        try:
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=True))
            if 'entries' in data: data = data['entries'][0]
            filename = ytdl.prepare_filename(data)
            return cls(discord.FFmpegPCMAudio(filename, **FFMPEG_OPTIONS), data=data)
        except Exception as e:
            print(f"❌ Error en descarga: {e}")
            return None

# ==========================================
# 🎧 MÓDULO DE MÚSICA (COG)
# ==========================================
class Musica(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.song_queue = []
        
        # Cargar Opus para que no de error de audio en la terminal de Proxmox
        opus_path = ctypes.util.find_library('opus')
        if opus_path:
            try: discord.opus.load_opus(opus_path)
            except: pass

    def cleanup_file(self, filename):
        """Borra la canción del disco después de sonar."""
        if filename and os.path.exists(filename):
            try: os.remove(filename)
            except: pass

    async def play_next(self, ctx, last_filename=None):
        """Pasa a la siguiente canción en la cola."""
        if last_filename: self.cleanup_file(last_filename)
        if len(self.song_queue) > 0:
            await self.play_music(ctx, self.song_queue.pop(0))

    async def play_music(self, ctx, query):
        """Lógica principal de reproducción."""
        msg = await ctx.send(f"💿 Cargando: `{query}`...")
        player = await YTDLSource.from_query(query, loop=self.bot.loop)
        
        if not player:
            return await msg.edit(content="❌ Error de descarga.")
        
        await msg.delete()

        # Esperar a que el bot se estabilice en el canal
        for i in range(10): 
            if ctx.voice_client and ctx.voice_client.is_connected(): break
            await asyncio.sleep(0.5)

        def after_playing(error):
            if error: print(f"Audio Error: {error}")
            asyncio.run_coroutine_threadsafe(self.play_next(ctx, player.filename), self.bot.loop)

        try:
            ctx.voice_client.play(player, after=after_playing)
            await ctx.send(f"🎶 Sonando: **{player.title}**")
        except Exception as e:
            await ctx.send(f"❌ Error Audio: {e}")

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
        if not ctx.voice_client: await ctx.invoke(self.join)
        
        if ctx.voice_client.is_playing(): 
            self.song_queue.append(query)
            await ctx.send(f"✅ En cola: `{query}`")
        else:
            await self.play_music(ctx, query)

    @commands.command(name='stop')
    async def stop(self, ctx):
        self.song_queue = []
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("🛑 Música detenida.")
        else:
            await ctx.send("No estoy conectado a voz.")

async def setup(bot):
    await bot.add_cog(Musica(bot))
