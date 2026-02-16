import discord
from discord.ext import commands, tasks
import os
import platform
import shutil
import time
import datetime
import asyncio

class Sistema(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()
        # Iniciamos las tareas en segundo plano
        self.afk_watchdog.start()
        self.auto_cleaner.start()

    def cog_unload(self):
        self.afk_watchdog.cancel()
        self.auto_cleaner.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        print("🛠️ Módulo Sistema: Monitor de recursos y limpieza activo.")
        # Limpieza inicial al arrancar (borra basura de sesiones anteriores)
        await self.limpiar_archivos_temporales()

    # ==========================================
    # 🕵️ TAREAS EN SEGUNDO PLANO (BACKGROUND TASKS)
    # ==========================================
    
    @tasks.loop(minutes=5)
    async def afk_watchdog(self):
        """Revisa si el bot está solo en un canal de voz y lo desconecta."""
        for voice_client in self.bot.voice_clients:
            # Si hay 1 solo miembro (el bot) en el canal
            if len(voice_client.channel.members) == 1:
                await voice_client.disconnect()
                print(f"💤 Desconectado por inactividad de: {voice_client.channel.name}")
                
                # Intentamos avisar en un canal de texto si es posible
                for guild in self.bot.guilds:
                    if guild.id == voice_client.guild.id:
                        channel = discord.utils.get(guild.text_channels, name="comandos")
                        if channel:
                            try:
                                await channel.send(f"💤 Me desconecté de **{voice_client.channel.name}** porque me dejaron solo. ¡Ahorrando RAM!")
                            except: pass

    @tasks.loop(hours=6)
    async def auto_cleaner(self):
        """Tarea programada para limpiar el disco cada 6 horas."""
        await self.limpiar_archivos_temporales()

    async def limpiar_archivos_temporales(self):
        """Borra archivos de audio huérfanos (.webm, .mp3, .m4a)."""
        extensions = ['.webm', '.mp3', '.m4a', '.part', '.ytdl']
        count = 0
        size_freed = 0
        
        current_dir = os.getcwd()
        for filename in os.listdir(current_dir):
            if any(filename.endswith(ext) for ext in extensions):
                try:
                    file_path = os.path.join(current_dir, filename)
                    size_freed += os.path.getsize(file_path)
                    os.remove(file_path)
                    count += 1
                except Exception as e:
                    print(f"⚠️ Error borrando {filename}: {e}")
        
        if count > 0:
            mb_freed = size_freed / (1024 * 1024)
            print(f"🧹 Limpieza automática: {count} archivos borrados ({mb_freed:.2f} MB liberados).")

    # ==========================================
    # 🖥️ COMANDOS DE DIAGNÓSTICO
    # ==========================================

    @commands.hybrid_command(name='ping', description="Muestra la latencia técnica del bot")
    async def ping(self, ctx):
        """Muestra la latencia técnica de la conexión."""
        start = time.perf_counter()
        # Usamos defer() implícito o un mensaje inicial
        msg = await ctx.send("🏓 Calculando latencia...")
        end = time.perf_counter()
        
        api_latency = (end - start) * 1000
        ws_latency = self.bot.latency * 1000
        
        embed = discord.Embed(title="🏓 Pong!", color=discord.Color.green())
        embed.add_field(name="📡 API Discord", value=f"`{api_latency:.2f}ms`", inline=True)
        embed.add_field(name="💓 Websocket", value=f"`{ws_latency:.2f}ms`", inline=True)
        
        await msg.edit(content=None, embed=embed)

    @commands.hybrid_command(
        name='sys', 
        aliases=['neofetch', 'host'], 
        description="Muestra el estado del servidor y recursos del sistema"
    )
    async def system_status(self, ctx):
        """Dashboard de estado del servidor (Proxmox Container)."""
        
        # 1. Uptime
        current_time = time.time()
        uptime_seconds = int(current_time - self.start_time)
        uptime_str = str(datetime.timedelta(seconds=uptime_seconds))
        
        # 2. Información del Sistema (Linux)
        sistema_op = f"{platform.system()} {platform.release()}"
        
        # 3. Disco Duro (Espacio en el contenedor)
        total, used, free = shutil.disk_usage("/")
        gb_free = free / (1024**3)
        gb_total = total / (1024**3)
        percent_used = (used / total) * 100
        
        # 4. Carga del Procesador
        try:
            load1, load5, load15 = os.getloadavg()
            cpu_status = f"1m: {load1:.2f} | 5m: {load5:.2f}"
        except:
            cpu_status = "No disponible (Windows?)"

        # Barra de progreso del disco
        bloques = 10
        llenos = int((used / total) * bloques)
        barra_disco = "█" * llenos + "░" * (bloques - llenos)

        embed = discord.Embed(title="🖥️ Estado del Sistema GrooveOS", color=discord.Color.blue())
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        
        embed.add_field(name="⏱️ Uptime Bot", value=f"`{uptime_str}`", inline=True)
        embed.add_field(name="🐧 OS / Kernel", value=f"`{sistema_op}`", inline=True)
        
        embed.add_field(name="💾 Disco (Proxmox)", value=f"`{gb_free:.2f} GB` libres de `{gb_total:.2f} GB`\n`{barra_disco}` ({percent_used:.1f}%)", inline=False)
        
        embed.add_field(name="🧠 CPU Load Avg", value=f"`{cpu_status}`", inline=True)
        embed.add_field(name="🐍 Python Ver", value=f"`{platform.python_version()}`", inline=True)
        
        embed.set_footer(text=f"Solicitado por {ctx.author.display_name} | Mantenimiento Automático Activo")
        
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name='limpiar', 
        description="Fuerza la limpieza de archivos temporales de audio"
    )
    @commands.has_permissions(administrator=True)
    async def force_clean(self, ctx):
        """Fuerza la limpieza de archivos temporales (Solo Admins)."""
        await ctx.send("🧹 Iniciando protocolo de limpieza forzada...")
        await self.limpiar_archivos_temporales()
        await ctx.send("✅ **Sistema limpio.** Archivos temporales eliminados.")

async def setup(bot):
    await bot.add_cog(Sistema(bot))