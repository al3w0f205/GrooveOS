import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite
import time
import datetime
import asyncio
import contextlib
from typing import Optional

# Fallback de utilidad
try:
    from .utilidad import THEME, build_embed
except ImportError:
    THEME = {"danger": 0xFF0000, "warning": 0xFFA500, "success": 0x00FF00}
    def build_embed(title, desc, color): 
        return discord.Embed(title=title, description=desc, color=color)

# -----------------------
# Utilidades locales
# -----------------------
def is_slash(ctx: commands.Context) -> bool:
    return getattr(ctx, "interaction", None) is not None

async def safe_reply(ctx: commands.Context, content: Optional[str] = None, *,
                     embed: Optional[discord.Embed] = None, ephemeral: bool = False):
    """Responde correctamente en híbrido. 
       - Slash: usa interaction (efímero si se pide).
       - Prefijo: usa ctx.send (ignora efímero)."""
    if is_slash(ctx):
        if not ctx.interaction.response.is_done():
            await ctx.interaction.response.send_message(content=content, embed=embed, ephemeral=ephemeral)
        else:
            await ctx.interaction.followup.send(content=content, embed=embed, ephemeral=ephemeral)
    else:
        await ctx.send(content=content, embed=embed)

def user_is_timed_out(member: discord.Member) -> bool:
    # Compatibilidad entre versiones
    fn = getattr(member, "is_timed_out", None)
    if callable(fn):
        try:
            return bool(fn())
        except Exception:
            pass
    return bool(getattr(member, "timed_out_until", None))

MAX_TIMEOUT_MINUTES = 28 * 24 * 60  # 28 días


class Moderacion(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "grooveos.db"

    @commands.Cog.listener()
    async def on_ready(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS advertencias (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    guild_id INTEGER,
                    reason TEXT,
                    moderator_id INTEGER,
                    timestamp INTEGER
                )
            """)
            # Índices para rendimiento (no rompen tu base)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_adv_user_guild ON advertencias(user_id, guild_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_adv_guild ON advertencias(guild_id)")
            await db.commit()
        print("🛡️ Moderación: Tablas verificadas y listas.")

    # ==========================================
    # 🧹 CLEAR
    # ==========================================
    @commands.hybrid_command(name="clear", description="Borra mensajes (Máx 100). Ignora mensajes > 14 días.")
    @commands.has_permissions(manage_messages=True)
    @app_commands.describe(cantidad="Cantidad de mensajes a borrar")
    async def clear(self, ctx, cantidad: int):
        if cantidad < 1 or cantidad > 100:
            return await safe_reply(ctx, "⚠️ La cantidad debe ser entre 1 y 100.", ephemeral=True)

        if is_slash(ctx):
            await ctx.interaction.response.defer(ephemeral=True)

        if not is_slash(ctx):
            with contextlib.suppress(Exception):
                await ctx.message.delete()

        try:
            deleted = await ctx.channel.purge(limit=cantidad)
            msg = f"✅ **{len(deleted)}** mensajes eliminados."
        except discord.HTTPException:
            msg = "⚠️ Error: No puedo borrar mensajes con más de 14 días de antigüedad."
        except Exception as e:
            msg = f"❌ Error desconocido: {e}"

        if is_slash(ctx):
            await ctx.interaction.followup.send(msg)
        else:
            m = await ctx.send(msg)
            await asyncio.sleep(5)
            with contextlib.suppress(Exception):
                await m.delete()

    # ==========================================
    # ⏳ TIMEOUT (AISLAMIENTO)
    # ==========================================
    @commands.hybrid_command(name="timeout", description="Aísla temporalmente a un usuario.")
    @commands.has_permissions(moderate_members=True)
    async def timeout(self, ctx, usuario: discord.Member, minutos: int, razon: str = "Sin motivo"):
        if is_slash(ctx):
            await ctx.interaction.response.defer(ephemeral=True)

        if minutos <= 0:
            return await safe_reply(ctx, "❌ El tiempo debe ser mayor a 0 minutos.", ephemeral=True)
        if minutos > MAX_TIMEOUT_MINUTES:
            return await safe_reply(ctx, "⏳ Máximo permitido: 28 días.", ephemeral=True)
        if usuario.id == ctx.author.id:
            return await safe_reply(ctx, "❌ No te puedes aislar a ti mismo.", ephemeral=True)
        if usuario.bot:
            return await safe_reply(ctx, "🤖 No se puede aislar a bots.", ephemeral=True)
        if ctx.guild and usuario.id == ctx.guild.owner_id:
            return await safe_reply(ctx, "👑 No puedes aislar al dueño del servidor.", ephemeral=True)

        # Jerarquía: autor vs objetivo
        if usuario.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await safe_reply(ctx, "❌ No puedes moderar a alguien con igual o mayor rango que tú.", ephemeral=True)

        # Jerarquía: bot vs objetivo (mantengo tu estilo con ctx.guild.me)
        if usuario.top_role >= ctx.guild.me.top_role:
            return await safe_reply(ctx, "❌ Mi rol está por debajo del usuario, no puedo aislarlo.", ephemeral=True)

        try:
            tiempo = datetime.timedelta(minutes=minutos)
            await usuario.timeout(tiempo, reason=f"{razon} (Mod: {ctx.author.name})")
            embed = build_embed("⏳ Usuario Aislado", f"{usuario.mention} aislado por **{minutos} min**.", THEME["warning"])
            embed.add_field(name="Razón", value=razon)
            await safe_reply(ctx, embed=embed)
        except Exception as e:
            await safe_reply(ctx, f"❌ Error al aislar: {e}")

    # ==========================================
    # 🔓 UNTIMEOUT
    # ==========================================
    @commands.hybrid_command(name="untimeout", description="Retira el aislamiento.")
    @commands.has_permissions(moderate_members=True)
    async def untimeout(self, ctx, usuario: discord.Member):
        if is_slash(ctx):
            await ctx.interaction.response.defer(ephemeral=True)

        if not user_is_timed_out(usuario):
            return await safe_reply(ctx, "ℹ️ Este usuario no está aislado.", ephemeral=True)

        try:
            await usuario.timeout(None)
            await safe_reply(ctx, f"🔊 Aislamiento retirado a **{usuario.name}**.")
        except Exception as e:
            await safe_reply(ctx, f"❌ Error: {e}")

    # ==========================================
    # 🦵 KICK
    # ==========================================
    @commands.hybrid_command(name="kick", description="Expulsa a un miembro del servidor.")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx, usuario: discord.Member, *, razon: str = "Sin razón"):
        if is_slash(ctx):
            await ctx.interaction.response.defer(ephemeral=True)

        if usuario.bot:
            return await safe_reply(ctx, "🤖 No se puede expulsar a bots.", ephemeral=True)
        if ctx.guild and usuario.id == ctx.guild.owner_id:
            return await safe_reply(ctx, "👑 No puedes expulsar al dueño del servidor.", ephemeral=True)
        if usuario.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await safe_reply(ctx, "❌ Rango insuficiente.", ephemeral=True)
        if usuario.top_role >= ctx.guild.me.top_role:
            return await safe_reply(ctx, "❌ Mi rol está por debajo del usuario.", ephemeral=True)

        try:
            await usuario.kick(reason=f"{razon} (Por: {ctx.author.name})")
            await safe_reply(ctx, f"👢 **{usuario.name}** ha sido expulsado.")
        except Exception as e:
            await safe_reply(ctx, f"❌ Error: {e}")

    # ==========================================
    # 🔨 BAN
    # ==========================================
    @commands.hybrid_command(name="ban", description="Banea a un miembro del servidor.")
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx, usuario: discord.Member, *, razon: str = "Sin razón"):
        if is_slash(ctx):
            await ctx.interaction.response.defer(ephemeral=True)

        if usuario.bot:
            return await safe_reply(ctx, "🤖 No se puede banear a bots.", ephemeral=True)
        if ctx.guild and usuario.id == ctx.guild.owner_id:
            return await safe_reply(ctx, "👑 No puedes banear al dueño del servidor.", ephemeral=True)
        if usuario.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await safe_reply(ctx, "❌ Rango insuficiente.", ephemeral=True)
        if usuario.top_role >= ctx.guild.me.top_role:
            return await safe_reply(ctx, "❌ Mi rol está por debajo del usuario.", ephemeral=True)

        try:
            await usuario.ban(reason=f"{razon} (Por: {ctx.author.name})")
            await safe_reply(ctx, f"🔨 **{usuario.name}** ha sido baneado permanentemente.")
        except Exception as e:
            await safe_reply(ctx, f"❌ Error: {e}")

    # ==========================================
    # 🔓 UNBAN
    # ==========================================
    @commands.hybrid_command(name="unban", description="Desbanea a un usuario por ID.")
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx, user_id: str):
        if is_slash(ctx):
            await ctx.interaction.response.defer(ephemeral=True)

        try:
            user = await self.bot.fetch_user(int(user_id))
            await ctx.guild.unban(user)
            await safe_reply(ctx, f"✅ **{user.name}** desbaneado.")
        except discord.NotFound:
            await safe_reply(ctx, "❌ Usuario no encontrado o no estaba baneado.")
        except Exception as e:
            await safe_reply(ctx, f"❌ Error: {e}")

    # ==========================================
    # ⚠️ WARN
    # ==========================================
    @commands.hybrid_command(name="warn", description="Registra una advertencia.")
    @commands.has_permissions(manage_messages=True)
    async def warn(self, ctx, usuario: discord.Member, *, razon: str = "No especificada"):
        if is_slash(ctx):
            await ctx.interaction.response.defer(ephemeral=True)

        if usuario.bot:
            return await safe_reply(ctx, "🤖 Los bots no pueden ser advertidos.", ephemeral=True)
        if usuario.top_role >= ctx.author.top_role and ctx.author.id != ctx.guild.owner_id:
            return await safe_reply(ctx, "❌ Rango insuficiente.", ephemeral=True)

        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO advertencias (user_id, guild_id, reason, moderator_id, timestamp) VALUES (?, ?, ?, ?, ?)",
                (usuario.id, ctx.guild.id, razon, ctx.author.id, int(time.time()))
            )
            await db.commit()

        embed = build_embed("⚠️ Advertencia", f"Usuario: {usuario.mention}", THEME["warning"])
        embed.add_field(name="Razón", value=razon)
        embed.add_field(name="Mod", value=ctx.author.mention)
        await safe_reply(ctx, embed=embed)

        # DM al advertido (silencioso)
        with contextlib.suppress(Exception):
            await usuario.send(f"⚠️ Has sido advertido en **{ctx.guild.name}** por: {razon}")

    # ==========================================
    # 📄 WARNS (listado)
    # ==========================================
    @commands.hybrid_command(name="warns", description="Ver historial de advertencias.")
    async def warns(self, ctx, usuario: discord.Member):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT id, reason, moderator_id, timestamp FROM advertencias WHERE user_id = ? AND guild_id = ? ORDER BY id DESC LIMIT 10",
                (usuario.id, ctx.guild.id)
            )
            rows = await cursor.fetchall()

        if not rows:
            return await safe_reply(ctx, f"✅ **{usuario.name}** no tiene advertencias recientes.")

        embed = build_embed(f"Expediente: {usuario.name}", "Últimas 10 advertencias", THEME["danger"])
        for (wid, razon, mod_id, ts) in rows:
            mod = ctx.guild.get_member(mod_id)
            mod_name = mod.name if mod else "Desconocido"
            embed.add_field(
                name=f"🆔 {wid} | <t:{ts}:d>",
                value=f"**Razón:** {razon}\n**Mod:** {mod_name}",
                inline=False
            )
        await safe_reply(ctx, embed=embed)

    # ==========================================
    # 🧽 UNWARN
    # ==========================================
    @commands.hybrid_command(name="unwarn", description="Borra una advertencia por ID.")
    @commands.has_permissions(manage_messages=True)
    async def unwarn(self, ctx, warn_id: int):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT id FROM advertencias WHERE id = ? AND guild_id = ?", (warn_id, ctx.guild.id))
            row = await cursor.fetchone()
            if not row:
                return await safe_reply(ctx, "❌ ID de advertencia no encontrado.", ephemeral=True)
            
            await db.execute("DELETE FROM advertencias WHERE id = ? AND guild_id = ?", (warn_id, ctx.guild.id))
            await db.commit()
        
        await safe_reply(ctx, f"✅ Advertencia **#{warn_id}** eliminada.")

async def setup(bot):
    await bot.add_cog(Moderacion(bot))