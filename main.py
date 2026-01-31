import discord
from discord.ext import commands
import os
import asyncio
from dotenv import load_dotenv

# 1. Cargamos las variables del archivo .env que tienes en la raíz
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# 2. Configuración del Bot (Prefijo y permisos)
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='.', intents=intents, help_command=None)

# 3. Función para cargar automáticamente musica.py y minecraft.py de la carpeta /cogs
async def load_extensions():
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

# 4. Función principal de arranque
async def main():
    async with bot:
        await load_extensions()
        await bot.start(TOKEN)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot apagado manualmente.")