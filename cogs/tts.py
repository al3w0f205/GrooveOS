import discord
from discord.ext import commands
from gtts import gTTS
import os
import asyncio
import functools

class TTS(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Usamos la carpeta que ya tienes en tu estructura
        self.audio_path = "./tmp_audio/tts_temp.mp3"
        self._check_folder()

    def _check_folder(self):
        """Asegura que la carpeta temporal exista."""
        if not os.path.exists("./tmp_audio"):
            os.makedirs("./tmp_audio")

    def generar_audio(self, texto, idioma='es'):
        """Función bloqueante que genera el archivo de audio."""
        tts = gTTS(text=texto, lang=idioma)
        tts.save(self.audio_path)

    @commands.hybrid_command(name="tts", description="El bot entra al canal y lee tu mensaje.")
    async def tts(self, ctx, *, texto: str):
        """Convierte texto a voz y lo reproduce en el canal."""
        
        # 1. Verificar si el usuario está en un canal de voz
        if not ctx.author.voice:
            return await ctx.send("❌ Debes estar en un canal de voz para usar este comando.", ephemeral=True)

        canal_usuario = ctx.author.voice.channel
        voice_client = ctx.voice_client

        # 2. Conexión o movimiento del bot
        if voice_client is None:
            voice_client = await canal_usuario.connect()
        elif voice_client.channel != canal_usuario:
            await voice_client.move_to(canal_usuario)

        # 3. Informar al usuario
        await ctx.send(f"🗣️ **Diciendo:** {texto}", ephemeral=True)

        # 4. Generar el audio (en un hilo separado para no bloquear el bot)
        # Esto es crucial para que el bot no se 'cuelgue' mientras Google procesa el audio
        try:
            func = functools.partial(self.generar_audio, texto, 'es')
            await self.bot.loop.run_in_executor(None, func)
        except Exception as e:
            return await ctx.send(f"⚠️ Error generando el audio: {e}")

        # 5. Reproducir el audio
        if voice_client.is_playing():
            voice_client.stop()

        source = discord.FFmpegPCMAudio(self.audio_path)
        
        # Usamos 'after' para limpiar errores o logs si fuera necesario, 
        # pero no borramos el archivo inmediatamente para evitar conflictos de bloqueo de archivos.
        voice_client.play(source, after=lambda e: print(f"Error en TTS: {e}") if e else None)

    @commands.hybrid_command(name="leave", description="Saca al bot del canal de voz.")
    async def leave(self, ctx):
        """Comando de utilidad para desconectar al bot."""
        if ctx.voice_client:
            await ctx.voice_client.disconnect()
            await ctx.send("👋 Desconectado.")
        else:
            await ctx.send("❌ No estoy conectado a ningún canal de voz.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(TTS(bot))