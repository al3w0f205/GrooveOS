import discord
from discord.ext import commands
import datetime

class Utilidad(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Reemplaza esto con el ID real de tu canal de logs
        self.ID_CANAL_LOGS = 1467098761049407603 

    async def enviar_log(self, titulo, descripcion, color=discord.Color.blue()):
        """Función interna para enviar reportes al canal de logs"""
        canal = self.bot.get_channel(self.ID_CANAL_LOGS)
        if canal:
            embed = discord.Embed(
                title=titulo,
                description=descripcion,
                color=color,
                timestamp=datetime.datetime.utcnow()
            )
            embed.set_footer(text="GrooveOS Monitoring")
            await canal.send(embed=embed)

    @commands.Cog.listener()
    async def on_command(self, ctx):
        """Registra cada vez que alguien usa un comando"""
        log_msg = f"👤 **Usuario:** {ctx.author}\n💻 **Comando:** `{ctx.command}`\n📍 **Canal:** {ctx.channel.name}"
        await self.enviar_log("📝 Comando Ejecutado", log_msg)

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        """Captura errores y los reporta al canal privado"""
        if isinstance(error, commands.CommandNotFound):
            return

        error_msg = f"❌ **Error en:** `{ctx.command}`\n⚠️ **Detalle:** `{error}`"
        await self.enviar_log("🚨 Error Detectado", error_msg, color=discord.Color.red())
        
        # Feedback al usuario en el canal público
        await ctx.send(f"⚠️ Hubo un problema al ejecutar el comando. El error ha sido reportado a Alejandro.")

    @commands.command(name='clear')
    @commands.has_permissions(manage_messages=True)
    async def clear(self, ctx, cantidad: int):
        """Limpia el chat (Útil para canales de música)"""
        await ctx.channel.purge(limit=cantidad + 1)
        msg = await ctx.send(f"🧹 Se han borrado {cantidad} mensajes.", delete_after=5)

async def setup(bot):
    await bot.add_cog(Utilidad(bot))