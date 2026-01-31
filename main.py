import discord
from discord.ext import commands
import os
import asyncio
from dotenv import load_dotenv

# 1. Cargamos las variables del archivo .env que tienes en la raíz
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# 2. Configuración del Bot (Prefijo y permisos)
# Se desactiva el help por defecto para usar el personalizado
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='.', intents=intents, help_command=None)

# 3. Función para cargar automáticamente musica.py y minecraft.py de la carpeta /cogs
async def load_extensions():
    # Asegúrate de que la carpeta cogs existe en /root/
    for filename in os.listdir('./cogs'):
        if filename.endswith('.py') and filename != '__init__.py':
            try:
                # Esto carga cada "rama" de código
                await bot.load_extension(f'cogs.{filename[:-3]}')
                print(f"✅ Módulo cargado con éxito: {filename}")
            except Exception as e:
                print(f"❌ Error al cargar {filename}: {e}")

@bot.event
async def on_ready():
    print('---')
    print(f'🚀 {bot.user} está ONLINE y Modularizado')
    print('---')

# COMANDO AYUDA - HELP PERSONALIZADO
@bot.command(name="help")
async def custom_help(ctx):
    """Despliega la lista de comandos disponibles de forma organizada."""
    embed = discord.Embed(
        title="📚 Guía de Comandos - GrooveOS",
        description="Lista de funciones para gestionar el servidor y la música.",
        color=0x3498db  # Color azul pro
    )

    # Sección de Minecraft
    embed.add_field(
        name="🎮 Servidor Minecraft",
        value="`.mc` o `.minecraft` - Panel de control iniciar el server de minecraft.",
        inline=False
    )

    # Sección de Música
    embed.add_field(
        name="🎶 Música",
        value=(
            "`.p [nombre/url]` - Reproduce Spotify, Apple Music o YouTube.\n"
            "`.join` - Une al bot al canal.\n"
            "`.stop` - Detiene la música y limpia la cola.\n"
            "`.skip` - Salta a la siguiente canción.\n"
        ),
        inline=False
    )

    # Pie de página con avatar del usuario
    avatar_url = ctx.author.avatar.url if ctx.author.avatar else None
    embed.set_footer(text=f"Solicitado por {ctx.author.name}", icon_url=avatar_url)
    
    await ctx.send(embed=embed)

# 4. Función principal de arranque
async def main():
    if not TOKEN:
        print("❌ Error: No se encontró DISCORD_TOKEN en el archivo .env")
        return

    async with bot:
        await load_extensions()
        await bot.start(TOKEN)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot apagado manualmente.")