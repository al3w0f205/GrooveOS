import discord
from discord.ext import commands
import aiosqlite
import os

class Perfiles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "grooveos.db"

    @commands.Cog.listener()
    async def on_ready(self):
        """Crea la base de datos y las tablas si no existen."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS usuarios (
                    user_id INTEGER PRIMARY KEY,
                    canciones_pedidas INTEGER DEFAULT 0,
                    nivel INTEGER DEFAULT 1,
                    xp INTEGER DEFAULT 0
                )
            ''')
            await db.commit()
        print("🗄️ Base de datos lista y conectada.")

    async def actualizar_stats(self, user_id):
        """Incrementa el contador de canciones de un usuario."""
        async with aiosqlite.connect(self.db_path) as db:
            # Si el usuario no existe, lo crea; si existe, suma 1
            await db.execute('''
                INSERT INTO usuarios (user_id, canciones_pedidas) 
                VALUES (?, 1)
                ON CONFLICT(user_id) DO UPDATE SET canciones_pedidas = canciones_pedidas + 1
            ''', (user_id,))
            await db.commit()

    @commands.command(name='perfil', aliases=['p-stats'])
    async def perfil(self, ctx, member: discord.Member = None):
        """Muestra las estadísticas musicales de un usuario."""
        member = member or ctx.author
        
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute('SELECT canciones_pedidas, nivel FROM usuarios WHERE user_id = ?', (member.id,)) as cursor:
                row = await cursor.fetchone()
                
        pedidas = row[0] if row else 0
        nivel = row[1] if row else 1

        embed = discord.Embed(title=f"📊 Perfil de {member.display_name}", color=discord.Color.purple())
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="🎶 Canciones Pedidas", value=f"`{pedidas}`", inline=True)
        embed.add_field(name="⭐ Nivel Musical", value=f"`{nivel}`", inline=True)
        embed.set_footer(text="GrooveOS 2.0 - Sistema de Persistencia")
        await ctx.send(embed=embed)
        
    @commands.command(name='top', aliases=['leaderboard', 'dj-top'])
    async def top(self, ctx):
        """Muestra el Top 5 de usuarios que más canciones han pedido."""
        async with aiosqlite.connect(self.db_path) as db:
            # Ordenamos de mayor a menor y limitamos a 5
            async with db.execute(
                'SELECT user_id, canciones_pedidas FROM usuarios ORDER BY canciones_pedidas DESC LIMIT 5'
            ) as cursor:
                usuarios_top = await cursor.fetchall()

        if not usuarios_top:
            return await ctx.send("📉 Aún no hay datos suficientes para el ranking.")

        embed = discord.Embed(
            title="🏆 Hall de la Fama - GrooveOS",
            description="Los DJs más activos del servidor",
            color=discord.Color.gold()
        )

        for i, (user_id, total) in enumerate(usuarios_top, start=1):
            usuario = self.bot.get_user(user_id)
            nombre = usuario.display_name if usuario else f"ID: {user_id}"
            
            medalla = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🎵"
            embed.add_field(
                name=f"{medalla} Puesto #{i}",
                value=f"**{nombre}** — `{total}` canciones",
                inline=False
            )

        embed.set_footer(text="¡Sigue pidiendo música para subir en el ranking!")
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Perfiles(bot))