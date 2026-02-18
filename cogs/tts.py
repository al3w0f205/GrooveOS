import discord
from discord import app_commands
from discord.ext import commands
import edge_tts
import os
import asyncio

class TTS(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        # --- CONFIGURACIÓN ---
        # Voces disponibles comunes:
        # 'es-MX-JorgeNeural' (Hombre México)
        # 'es-ES-AlvaroNeural' (Hombre España)
        # 'es-MX-DaliaNeural' (Mujer México)
        self.DEFAULT_VOICE = 'es-MX-JorgeNeural' 
        
        # Velocidad de lectura
        self.DEFAULT_RATE = '-5%'
        # ---------------------

        # Rutas absolutas para compatibilidad con Linux/LXC
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.root_dir = os.path.dirname(self.base_dir)
        self.audio_folder = os.path.join(self.root_dir, "tmp_audio")
        self.audio_path = os.path.join(self.audio_folder, "tts_edge.mp3")
        
        # Crear carpeta si no existe
        if not os.path.exists(self.audio_folder):
            os.makedirs(self.audio_folder)

    async def generar_audio_edge(self, texto, voz, velocidad):
        """Genera el audio usando Microsoft Edge TTS."""
        try:
            communicate = edge_tts.Communicate(texto, voz, rate=velocidad)
            await communicate.save(self.audio_path)
            return True
        except Exception as e:
            print(f"[TTS] Error generando archivo: {e}")
            return False

    @commands.hybrid_command(name="tts", description="Habla en el chat de voz.")
    async def tts(self, ctx, *, texto: str):
        """Dice el texto en el canal de voz y borra el archivo al terminar."""
        
        # 1. Verificar si el usuario está en un canal
        if not ctx.author.voice:
            return await ctx.send("❌ ¡Entra a un canal de voz primero!", ephemeral=True)

        canal_usuario = ctx.author.voice.channel
        voice_client = ctx.guild.voice_client

        # 2. Conectar o mover al bot
        try:
            if voice_client is None:
                voice_client = await canal_usuario.connect()
            elif voice_client.channel != canal_usuario:
                await voice_client.move_to(canal_usuario)
        except Exception as e:
            return await ctx.send(f"❌ Error de conexión: {e}")

        # 3. Notificación visual
        await ctx.send(f"🎙️ **Diciendo:** {texto}", ephemeral=True)

        # 4. Si ya está hablando, lo callamos primero
        if voice_client.is_playing():
            voice_client.stop()

        # 5. Generar audio nuevo
        exito = await self.generar_audio_edge(texto, self.DEFAULT_VOICE, self.DEFAULT_RATE)

        if not exito:
            return await ctx.send("❌ Error generando el audio.")

        # 6. Reproducir y limpiar
        if os.path.exists(self.audio_path):
            source = discord.FFmpegPCMAudio(self.audio_path)
            
            # Función local para borrar el archivo al terminar
            def limpiar_archivo(error):
                if error:
                    print(f"[TTS] Error en reproducción: {error}")
                try:
                    if os.path.exists(self.audio_path):
                        os.remove(self.audio_path)
                        # print("[TTS] Archivo temporal eliminado.")
                except Exception as e:
                    print(f"[TTS] No se pudo borrar el archivo temporal: {e}")

            # 'after' ejecuta la limpieza cuando el audio termina o se detiene
            voice_client.play(source, after=limpiar_archivo)

    @commands.hybrid_command(name="stoptts", aliases=["shh", "callate"], description="Detiene el audio actual inmediatamente.")
    async def stoptts(self, ctx):
        """Detiene la reproducción de voz al instante."""
        voice_client = ctx.guild.voice_client
        
        if voice_client and voice_client.is_playing():
            voice_client.stop() # Esto disparará 'limpiar_archivo' automáticamente
            await ctx.send("🤫 Silencio.", ephemeral=True)
        else:
            await ctx.send("❌ No estoy diciendo nada ahora.", ephemeral=True)

    @commands.hybrid_command(name="cambiar_voz", description="Cambia la voz del bot.")
    @app_commands.choices(voz=[
        app_commands.Choice(name="🇲🇽 Jorge (Hombre)", value="es-MX-JorgeNeural"),
        app_commands.Choice(name="🇪🇸 Alvaro (Hombre)", value="es-ES-AlvaroNeural"),
        app_commands.Choice(name="🇲🇽 Dalia (Mujer)", value="es-MX-DaliaNeural"),
        app_commands.Choice(name="🇪🇸 Elvira (Mujer)", value="es-ES-ElviraNeural")
    ])
    async def cambiar_voz(self, ctx, voz: app_commands.Choice[str]):
        """Permite cambiar la voz sin reiniciar el bot."""
        self.DEFAULT_VOICE = voz.value
        await ctx.send(f"✅ Voz cambiada a: **{voz.name}**")

    @commands.hybrid_command(name="leave_tts", description="Desconecta al bot.")
    async def leave_tts(self, ctx):
        if ctx.guild.voice_client:
            await ctx.guild.voice_client.disconnect()
            await ctx.send("👋")

async def setup(bot):
    await bot.add_cog(TTS(bot))