import discord
from discord.ext import commands
import os
import sys
import asyncio

class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="restart", aliases=["reiniciar", "reboot"])
    @commands.is_owner()  # SEGURIDAD: Solo tú (el dueño) puedes usarlo
    async def restart(self, ctx):
        """
        Reinicia el bot por completo reemplazando el proceso actual.
        Recarga todos los archivos, cogs y configuraciones.
        """
        # 1. Avisar visualmente
        embed = discord.Embed(
            title="🔄 Reiniciando Sistema...",
            description="El bot se está reiniciando. Vuelvo en unos segundos...",
            color=discord.Color.orange()
        )
        await ctx.send(embed=embed)

        # 2. (Opcional) Guardar cosas en BD si hiciera falta aquí
        # await self.bot.db.commit()

        print("--- EJECUTANDO REINICIO INTERNO (os.execv) ---")
        
        # 3. El truco nuclear: Reemplaza el proceso actual por uno nuevo
        # sys.executable = ruta a tu python (ej: /usr/bin/python3)
        # sys.argv = argumentos usados (ej: ['main.py'])
        os.execv(sys.executable, [sys.executable] + sys.argv)

async def setup(bot):
    await bot.add_cog(Admin(bot))