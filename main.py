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

# ✅ Archivos que NO son extensiones (helpers)
SKIP_FILES = {'__init__.py', 'utilidad.py'}

# 3. Función para cargar automáticamente los cogs en /cogs
async def load_extensions():
    for filename in os.listdir('./cogs'):
        if not filename.endswith('.py') or filename in SKIP_FILES:
            continue

        try:
            await bot.load_extension(f'cogs.{filename[:-3]}')
            print(f"✅ Módulo cargado con éxito: {filename}")
        except Exception as e:
            print(f"❌ Error al cargar {filename}: {e}")

@bot.event
async def on_ready():
    print('---')
    print(f'🚀 {bot.user} está ONLINE y Modularizado')
    print('---')

# ✅ HELP AUTOMÁTICO
@bot.command(name="help")
async def custom_help(ctx):
    """Help automático: agrupa comandos por Cog y muestra uso + descripción."""
    prefix = "."

    embed = discord.Embed(
        title="📚 Guía de Comandos - GrooveOS",
        description=f"Prefijo actual: `{prefix}`\nUsa `{prefix}help` para ver esto.",
        color=discord.Color.blurple()
    )

    cogs = {}
    for cmd in bot.commands:
        if cmd.hidden:
            continue
        cog_name = cmd.cog_name or "Otros"
        cogs.setdefault(cog_name, []).append(cmd)

    for cog_name, cmds in sorted(cogs.items(), key=lambda x: x[0].lower()):
        lines = []
        for cmd in sorted(cmds, key=lambda c: c.name):
            usage = f"{prefix}{cmd.name}"
            if cmd.signature:
                usage += f" {cmd.signature}"

            alias_txt = ""
            if cmd.aliases:
                alias_txt = " (alias: " + ", ".join([f"`{prefix}{a}`" for a in cmd.aliases]) + ")"

            short = (cmd.help or "Sin descripción").strip().split("\n")[0]
            lines.append(f"**`{usage}`**{alias_txt}\n└ {short}")

        value = "\n".join(lines)
        if len(value) > 1024:
            value = value[:1020] + "…"

        embed.add_field(name=f"📦 {cog_name}", value=value, inline=False)

    embed.set_footer(text=f"Solicitado por {ctx.author}", icon_url=ctx.author.display_avatar.url)
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