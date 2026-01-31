import discord
from discord.ext import commands

class Comandos(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name='hola')
    async def hola(self, ctx):
        """Un saludo amistoso del bot"""
        await ctx.send(f'👋 ¡Hola, {ctx.author.name}! ¿En qué puedo ayudarte hoy?')

    @commands.command(name='info')
    async def info(self, ctx):
        """Muestra información básica de GrooveOS 2.0"""
        embed = discord.Embed(
            title="🤖 GrooveOS 2.0",
            description="Tu bot personal de música y utilidad, optimizado y modular.",
            color=discord.Color.blue()
        )
        embed.add_field(name="Versión", value="2.0.0-Beta", inline=True)
        embed.add_field(name="Prefijo", value="`.`", inline=True)
        embed.add_field(name="Desarrollador", value="Alejandro", inline=False)
        embed.set_footer(text="Proyecto personal de ingeniería.")
        await ctx.send(embed=embed)

    @commands.command(name='queue', aliases=['q', 'cola'])
    async def queue(self, ctx):
        """Muestra las canciones que están en la cola de reproducción"""
        # Accedemos al Cog de música para obtener la lista
        musica_cog = self.bot.get_cog('Musica')
        
        if not musica_cog or not musica_cog.song_queue:
            return await ctx.send("📭 La cola está vacía actualmente.")

        # Construimos la lista de canciones
        lista_cola = ""
        for i, song in enumerate(musica_cog.song_queue[:10], start=1):
            lista_cola += f"**{i}.** {song}\n"

        if len(musica_cog.song_queue) > 10:
            lista_cola += f"\n*...y {len(musica_cog.song_queue) - 10} canciones más.*"

        embed = discord.Embed(
            title="🎶 Cola de Reproducción",
            description=lista_cola,
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Comandos(bot))