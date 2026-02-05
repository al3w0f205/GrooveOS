import discord
from discord.ext import commands
from .utilidad import THEME, user_footer, build_embed, clean_query

class Comandos(commands.Cog):
    def __init__(self, bot):
        self.bot = bot



    @commands.command(name='info')
    async def info(self, ctx):
        embed = build_embed(
            "🤖 GrooveOS 2.0",
            "Tu bot personal de música y utilidad, optimizado y modular.",
            color=THEME["primary"]
        )
        embed.add_field(name="Versión", value="2.0.0-Beta", inline=True)
        embed.add_field(name="Prefijo", value="`.`", inline=True)
        embed.add_field(name="Desarrollador", value="Alejandro", inline=False)
        embed.set_footer(**user_footer(ctx, "Proyecto personal de ingeniería"))
        await ctx.send(embed=embed)

    @commands.command(name='queue', aliases=['q', 'cola'])
    async def queue(self, ctx):
        """Cola actual de canciones"""
        musica_cog = self.bot.get_cog('Musica')
        if not musica_cog:
            return await ctx.send("⚠️ No encontré el módulo de música cargado.")

        if not musica_cog.song_queue:
            embed = build_embed(
                "📭 Cola Vacía",
                "No hay canciones en espera.\nUsa `.p <nombre/url>` para agregar música.",
                color=THEME["warning"]
            )
            embed.set_footer(**user_footer(ctx))
            return await ctx.send(embed=embed)

        max_items = 10
        items = musica_cog.song_queue[:max_items]

        lista_cola = "\n".join([f"**{i}.** {clean_query(song)}" for i, song in enumerate(items, start=1)])
        extra = len(musica_cog.song_queue) - max_items
        if extra > 0:
            lista_cola += f"\n\n*…y **{extra}** canciones más.*"

        ahora = getattr(musica_cog, "current_track", None)
        ahora_txt = f"🎧 **Ahora sonando:** `{clean_query(ahora)}`\n\n" if ahora else ""

        embed = build_embed(
            "🎶 Cola de Reproducción",
            ahora_txt + lista_cola,
            color=THEME["success"]
        )
        embed.set_footer(**user_footer(ctx))
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Comandos(bot))