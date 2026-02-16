import os
import asyncio
import traceback
import logging

import discord
from discord.ext import commands
from dotenv import load_dotenv

# =========================
#  Logging
# =========================
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("grooveos")
discord_log = logging.getLogger("discord")
discord_log.setLevel(logging.INFO)  # usa DEBUG si quieres verbosidad máxima

# =========================
#  Config
# =========================
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
# Si estás probando en un solo servidor, pon aquí su ID o en .env DEV_GUILD_ID=1234567890
DEV_GUILD_ID = int(os.getenv("DEV_GUILD_ID", "0"))

# =========================
#  Intents & Bot
# =========================
intents = discord.Intents.all()  # incluye message_content, members, guilds, etc.
bot = commands.Bot(command_prefix=".", intents=intents, help_command=None)

# Archivos de /cogs que NO se cargan como extensiones
SKIP_FILES = {"__init__.py", "utilidad.py"}

# =========================
#  Carga de COGs
# =========================
async def load_extensions():
    log.info("📂 Cargando módulos (cogs)...")
    if not os.path.isdir("./cogs"):
        log.warning("⚠️ No existe la carpeta ./cogs")
        return

    for filename in os.listdir("./cogs"):
        if filename.endswith(".py") and filename not in SKIP_FILES:
            mod = f"cogs.{filename[:-3]}"
            try:
                log.info("   -> Intentando cargar: %s", mod)
                await bot.load_extension(mod)
                log.info("✅  Cargado: %s", mod)
            except Exception:
                log.error("❌  Error al cargar %s:", mod)
                traceback.print_exc()

# =========================
#  setup_hook = lugar correcto para preparar el bot
# =========================
@bot.event
async def setup_hook():
    # 1) Cargar COGs
    await load_extensions()
    # 2) Sincronizar slash
    try:
        if DEV_GUILD_ID:
            # Sync SOLO en tu servidor (aparecen al instante, ideal para pruebas)
            guild = discord.Object(id=DEV_GUILD_ID)
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            log.info("[SYNC] Guild %s: %d slash commands registrados.", DEV_GUILD_ID, len(synced))
        else:
            # Sync global (puede tardar en propagarse la primera vez)
            synced = await bot.tree.sync()
            log.info("[SYNC] Global: %d slash commands registrados.", len(synced))
    except Exception as e:
        log.error("[SYNC][ERROR] %s", e)

# =========================
#  Eventos
# =========================
@bot.event
async def on_ready():
    print('---')
    print('✅ GrooveOS 2.0 en línea')
    print(f'🤖 Usuario: {bot.user}')
    print(f'🆔 ID: {bot.user.id}')
    print('---')

# =========================
#  Comandos de administración
# =========================
@bot.command(name="sync")
@commands.is_owner()
async def sync(ctx: commands.Context):
    """Sincroniza manualmente los slash (global o por guild si DEV_GUILD_ID está seteado)."""
    msg = await ctx.send("⏳ **Sincronizando comandos con el servidor de Discord...**")
    try:
        if DEV_GUILD_ID:
            guild = discord.Object(id=DEV_GUILD_ID)
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            await msg.edit(content=f"✅ **¡ÉXITO!** (guild {DEV_GUILD_ID}) `{len(synced)}` comandos.")
        else:
            synced = await bot.tree.sync()
            await msg.edit(content=f"✅ **¡ÉXITO!** (global) `{len(synced)}` comandos.")
        log.info("Sincronización manual por %s: %d comandos.", ctx.author, len(synced))
    except Exception as e:
        await msg.edit(content=f"❌ **Error durante la sincronización:**\n`{e}`")

# =========================
#  Help híbrido (.help / /help)
# =========================
@bot.hybrid_command(
    name="help",
    description="Muestra la lista de comandos disponibles de GrooveOS 2.0"
)
async def custom_help(ctx: commands.Context):
    """Guía interactiva de comandos organizada por categorías."""
    prefix = ctx.prefix if ctx.prefix else "/"

    embed = discord.Embed(
        title="📚 Centro de Ayuda - GrooveOS",
        description=(
            f"¡Hola! Puedes usar mis comandos con `{prefix}` o con `/`.\n"
            "Aquí tienes mi lista de funcionalidades disponibles:"
        ),
        color=discord.Color.blurple()
    )

    # Agrupamos comandos por Cog
    categories = {}
    for cmd in bot.commands:
        # Mientras debug, puedes comentar este filtro:
        # if cmd.hidden:
        #     continue
        cog_name = cmd.cog_name if cmd.cog_name else "General"
        categories.setdefault(cog_name, []).append(cmd)

    # Construimos los campos del embed por categoría
    for cog, cmds in sorted(categories.items()):
        lines = []
        for c in sorted(cmds, key=lambda x: x.name):
            desc = (c.help or c.description or "Sin descripción").split("\n")[0]
            # Formato: .comando <args> / /comando
            usage = f"**`{prefix}{c.name}`** | **`/{c.name}`**"

            # Marca si el usuario probablemente puede ejecutarlo
            mark = "?"
            try:
                can_run = await c.can_run(ctx)
                mark = "✅" if can_run else "⛔"
            except Exception:
                mark = "⛔"

            lines.append(f"{usage} {mark}\n└ *{desc}*")

        field_content = "\n".join(lines) or "_(sin comandos)_"
        if len(field_content) > 1024:
            field_content = field_content[:1020] + "..."
        embed.add_field(name=f"📦 {cog}", value=field_content, inline=False)

    embed.set_footer(
        text=f"Solicitado por {ctx.author.display_name} • Proyecto de Ingeniería",
        icon_url=ctx.author.display_avatar.url
    )
    await ctx.send(embed=embed)

# =========================
#  Debug opcional (útil ahora)
# =========================
@bot.command(name="debugcmds")
@commands.is_owner()
async def debugcmds(ctx: commands.Context):
    """Lista lo que bot.commands tiene registrado (prefijo/híbrido)."""
    lines = []
    for c in bot.commands:
        lines.append(f"- {c.qualified_name}  (cog={c.cog_name}, hidden={c.hidden}, cls={c.__class__.__name__})")
    text = "Comandos registrados:\n" + "\n".join(sorted(lines))
    if len(text) < 1900:
        await ctx.send(f"```\n{text}\n```")
    else:
        chunks = [text[i:i+1800] for i in range(0, len(text), 1800)]
        for ch in chunks:
            await ctx.send(f"```\n{ch}\n```")

@bot.command(name="debugslash")
@commands.is_owner()
async def debugslash(ctx: commands.Context):
    """Lista los slash globales (si usas sync por guild, usa fetch_commands(guild=...))."""
    if DEV_GUILD_ID:
        guild = discord.Object(id=DEV_GUILD_ID)
        cmds = await bot.tree.fetch_commands(guild=guild)  # slash del guild
        scope = f"guild {DEV_GUILD_ID}"
    else:
        cmds = await bot.tree.fetch_commands()  # slash globales
        scope = "global"
    lines = [f"- /{c.name} (type={c.type}, default_perms={c.default_member_permissions})" for c in cmds]
    text = f"Slash ({scope}):\n" + "\n".join(lines or ["(vacío)"])
    await ctx.send(f"```\n{text}\n```")

# =========================
#  Run
# =========================
async def main():
    if not TOKEN:
        print("❌ CRÍTICO: No se encontró DISCORD_TOKEN en .env")
        return
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 GrooveOS ha sido apagado manualmente.")
    except Exception:
        print("❌ Error fatal al iniciar:")
        traceback.print_exc()