import discord
from discord.ext import commands
import aiosqlite
import os
import random

class Perfiles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "grooveos.db"

    @commands.Cog.listener()
    async def on_ready(self):
        """Crea la base de datos y añade columnas nuevas si es necesario."""
        async with aiosqlite.connect(self.db_path) as db:
            # 1. Crear la tabla base si no existe
            await db.execute('''
                CREATE TABLE IF NOT EXISTS usuarios (
                    user_id INTEGER PRIMARY KEY,
                    canciones_pedidas INTEGER DEFAULT 0,
                    nivel INTEGER DEFAULT 1,
                    xp INTEGER DEFAULT 0
                )
            ''')
            
            # 2. Intentar agregar la columna de tiempo (segundos_escuchados)
            try:
                await db.execute('ALTER TABLE usuarios ADD COLUMN segundos_escuchados INTEGER DEFAULT 0')
                print("📊 Columna 'segundos_escuchados' añadida exitosamente.")
            except aiosqlite.OperationalError:
                # Si entra aquí es porque la columna ya existe
                pass
                
            await db.commit()
        print("🗄️ Base de datos Perfiles actualizada y conectada.")

    async def actualizar_stats(self, ctx, duracion=0):
        """Incrementa canciones, suma XP, gestiona niveles y acumula tiempo de escucha."""
        user_id = ctx.author.id
        xp_ganado = random.randint(15, 25)

        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                'SELECT xp, nivel, segundos_escuchados FROM usuarios WHERE user_id = ?', 
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
            
            if not row:
                await db.execute('''
                    INSERT INTO usuarios (user_id, canciones_pedidas, xp, nivel, segundos_escuchados) 
                    VALUES (?, 1, ?, 1, ?)
                ''', (user_id, xp_ganado, duracion))
            else:
                xp_actual, nivel_actual, tiempo_actual = row[0], row[1], row[2] or 0
                nuevo_xp = xp_actual + xp_ganado
                nuevo_tiempo = tiempo_actual + duracion
                xp_necesario = nivel_actual * 100

                if nuevo_xp >= xp_necesario:
                    nuevo_nivel = nivel_actual + 1
                    await db.execute('''
                        UPDATE usuarios 
                        SET canciones_pedidas = canciones_pedidas + 1, 
                            xp = ?, 
                            nivel = ?,
                            segundos_escuchados = ?
                        WHERE user_id = ?
                    ''', (nuevo_xp - xp_necesario, nuevo_nivel, nuevo_tiempo, user_id))
                    
                    embed = discord.Embed(
                        title="✨ ¡SUBIDA DE NIVEL! ✨",
                        description=f"¡Felicidades {ctx.author.mention}! Has alcanzado el **Nivel {nuevo_nivel}**.",
                        color=discord.Color.gold()
                    )
                    await ctx.send(embed=embed)
                else:
                    await db.execute('''
                        UPDATE usuarios 
                        SET canciones_pedidas = canciones_pedidas + 1, 
                            xp = ?,
                            segundos_escuchados = ?
                        WHERE user_id = ?
                    ''', (nuevo_xp, nuevo_tiempo, user_id))
            
            await db.commit()

    @commands.command(name='perfil', aliases=['p-stats'])
    async def perfil(self, ctx, member: discord.Member = None):
        """Muestra las estadísticas musicales con barra de progreso."""
        member = member or ctx.author
        
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                'SELECT canciones_pedidas, nivel, xp, segundos_escuchados FROM usuarios WHERE user_id = ?', 
                (member.id,)
            ) as cursor:
                row = await cursor.fetchone()
                
        pedidas = row[0] if row else 0
        nivel = row[1] if row else 1
        xp_actual = row[2] if row else 0
        segundos = row[3] if row and row[3] else 0 
        
        xp_sig_nivel = nivel * 100
        bloques_totales = 10
        progreso = int((xp_actual / xp_sig_nivel) * bloques_totales)
        barra = "▰" * progreso + "▱" * (bloques_totales - progreso)
        porcentaje = int((xp_actual / xp_sig_nivel) * 100)

        horas = segundos // 3600
        minutos = (segundos % 3600) // 60

        embed = discord.Embed(
            title=f"📊 Perfil de {member.display_name}", 
            description=f"**Rango:** {self.obtener_rango(nivel)}",
            color=discord.Color.purple()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        
        embed.add_field(name="🎶 Pedidas", value=f"`{pedidas}`", inline=True)
        embed.add_field(name="⭐ Nivel", value=f"`{nivel}`", inline=True)
        embed.add_field(name="⏳ Tiempo Escuchado", value=f"`{horas}h {minutos}m`", inline=True)
        
        # CORREGIDO: Se eliminó el parámetro name duplicado
        embed.add_field(
            name=f"🧬 XP: {xp_actual} / {xp_sig_nivel} ({porcentaje}%)", 
            value=f"`{barra}`", 
            inline=False
        )
        embed.set_footer(text="GrooveOS 2.0 - Sistema de Persistencia")
        await ctx.send(embed=embed)

    def obtener_rango(self, nivel):
        if nivel < 3: return "🎧 Oyente Novato"
        if nivel < 7: return "🎸 Melómano en Proceso"
        if nivel < 12: return "💿 DJ del Barrio"
        if nivel < 20: return "🎹 Maestro de la Cola"
        return "👑 Leyenda del Groove"
        
    @commands.command(name='top', aliases=['leaderboard', 'dj-top'])
    async def top(self, ctx):
        """Muestra el Top 5 de usuarios con corrección de nombres."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                'SELECT user_id, canciones_pedidas FROM usuarios ORDER BY canciones_pedidas DESC LIMIT 5'
            ) as cursor:
                usuarios_top = await cursor.fetchall()

        if not usuarios_top:
            return await ctx.send("📉 Aún no hay datos suficientes.")

        embed = discord.Embed(title="🏆 Hall de la Fama - GrooveOS", color=discord.Color.gold())

        for i, (user_id, total) in enumerate(usuarios_top, start=1):
            usuario = self.bot.get_user(user_id)
            if usuario is None:
                try: usuario = await self.bot.fetch_user(user_id)
                except: usuario = None

            nombre = usuario.display_name if usuario else f"Desconocido ({user_id})"
            medalla = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🎵"
            embed.add_field(name=f"{medalla} #{i} {nombre}", value=f"`{total}` canciones", inline=False)

        await ctx.send(embed=embed)
        
    @commands.command(name='stats')
    async def stats_global(self, ctx):
        """Muestra la analítica global del bot acumulada en la base de datos."""
        perfiles_cog = self.bot.get_cog('Perfiles')
        if not perfiles_cog:
            return await ctx.send("❌ El módulo de base de datos no está activo.")

        async with aiosqlite.connect(perfiles_cog.db_path) as db:
            # Consultas de agregación SQL para máxima eficiencia
            async with db.execute('''
                SELECT 
                    SUM(canciones_pedidas), 
                    SUM(segundos_escuchados), 
                    COUNT(user_id),
                    AVG(nivel)
                FROM usuarios
            ''') as cursor:
                row = await cursor.fetchone()

        if not row or row[0] is None:
            return await ctx.send("📈 Aún no hay datos globales para mostrar.")

        total_canciones, total_segundos, total_usuarios, nivel_promedio = row
        
        # Conversión de tiempo global a formato legible
        horas = total_segundos // 3600
        minutos = (total_segundos % 3600) // 60

        embed = discord.Embed(
            title="🌐 Estadísticas Globales - GrooveOS 2.0",
            color=discord.Color.blue(),
            timestamp=ctx.message.created_at
        )
        
        embed.add_field(name="🎶 Total Canciones", value=f"`{total_canciones}`", inline=True)
        embed.add_field(name="👥 Usuarios Registrados", value=f"`{total_usuarios}`", inline=True)
        embed.add_field(name="⏳ Tiempo de Aire", value=f"`{horas}h {minutos}m`", inline=False)
        embed.add_field(name="⭐ Nivel Promedio", value=f"`{nivel_promedio:.1f}`", inline=True)
        
        embed.set_footer(text="Analítica de servidor Proxmox")
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Perfiles(bot))