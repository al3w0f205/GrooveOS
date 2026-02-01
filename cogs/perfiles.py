import discord
from discord.ext import commands
import aiosqlite
import os
import random
import time

class Perfiles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "grooveos.db"
        self.last_xp_time = {} 

    @commands.Cog.listener()
    async def on_ready(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS usuarios (
                    user_id INTEGER PRIMARY KEY,
                    canciones_pedidas INTEGER DEFAULT 0,
                    nivel INTEGER DEFAULT 1,
                    xp INTEGER DEFAULT 0,
                    segundos_escuchados INTEGER DEFAULT 0,
                    xp_chat INTEGER DEFAULT 0,
                    xp_musica INTEGER DEFAULT 0
                )
            ''')
            # Migración automática si faltan columnas
            try:
                await db.execute('ALTER TABLE usuarios ADD COLUMN xp_chat INTEGER DEFAULT 0')
                await db.execute('ALTER TABLE usuarios ADD COLUMN xp_musica INTEGER DEFAULT 0')
                print("📊 Columnas XP Chat/Musica añadidas.")
            except: pass
            await db.commit()
        print("🗄️ Base de datos Perfiles lista.")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.content.startswith('.'): return
        
        user_id = message.author.id
        ahora = time.time()
        
        # Cooldown de 60 segundos
        if ahora - self.last_xp_time.get(user_id, 0) < 60: return

        # Sumar XP de Chat
        xp = random.randint(15, 25)
        await self.actualizar_stats(message, xp_ganado=xp, fuente='chat')
        self.last_xp_time[user_id] = ahora

    # --- [CORRECCIÓN CRÍTICA AQUÍ] ---
    # Aceptamos 'es_musica' para compatibilidad con tu musica.py actual
    async def actualizar_stats(self, ctx_or_msg, duracion=0, xp_ganado=0, fuente='musica', es_musica=False):
        
        # Parche de compatibilidad: Si musica.py manda es_musica=True, forzamos fuente='musica'
        if es_musica: 
            fuente = 'musica'
            
        user_id = ctx_or_msg.author.id
        
        # XP por defecto para música si no se especifica
        if xp_ganado == 0 and fuente == 'musica':
            xp_ganado = 10 

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT * FROM usuarios WHERE user_id = ?', (user_id,))
            row = await cursor.fetchone()
            
            if not row:
                # Crear usuario nuevo
                pedidas = 1 if fuente == 'musica' else 0
                xp_c = xp_ganado if fuente == 'chat' else 0
                xp_m = xp_ganado if fuente == 'musica' else 0
                await db.execute('INSERT INTO usuarios VALUES (?, ?, 1, ?, ?, ?, ?)', 
                               (user_id, pedidas, xp_ganado, duracion, xp_c, xp_m))
            else:
                # Actualizar usuario existente
                # Desempaquetamos según las 7 columnas que definimos
                uid, pedidas, nivel, xp_total, tiempo, xp_chat, xp_musica = row
                
                # Sumamos valores nuevos
                xp_total += xp_ganado
                if fuente == 'musica':
                    pedidas += 1
                    tiempo += duracion
                    xp_musica += xp_ganado
                else:
                    xp_chat += xp_ganado

                # Lógica de Nivel
                xp_meta = nivel * 100
                if xp_total >= xp_meta:
                    nivel += 1
                    xp_total -= xp_meta
                    try:
                        await ctx_or_msg.channel.send(
                            embed=discord.Embed(
                                description=f"🎉 **{ctx_or_msg.author.mention} subió al Nivel {nivel}!**",
                                color=discord.Color.gold()
                            )
                        )
                    except: pass

                await db.execute('''
                    UPDATE usuarios SET canciones_pedidas=?, nivel=?, xp=?, segundos_escuchados=?, xp_chat=?, xp_musica=?
                    WHERE user_id=?
                ''', (pedidas, nivel, xp_total, tiempo, xp_chat, xp_musica, user_id))
            
            await db.commit()

    @commands.command(name='perfil', aliases=['p-stats', 'profile', 'pstats'])
    async def perfil(self, ctx, member: discord.Member = None):
        member = member or ctx.author
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT * FROM usuarios WHERE user_id = ?', (member.id,))
            row = await cursor.fetchone()

        if not row: return await ctx.send("📉 Sin datos registrados.")

        # Desempaquetar datos seguros
        _, pedidas, nivel, xp_act, seg, xp_c, xp_m = row
        
        xp_meta = nivel * 100
        pct = int((xp_act / xp_meta) * 100) if xp_meta > 0 else 0
        
        # [CORRECCIÓN ERROR 'BLOCKS'] Usamos 'bloques' consistente
        bloques = int(pct / 10)
        barra = "▰" * bloques + "▱" * (10 - bloques)

        # Formato de tiempo
        h = seg // 3600
        m = (seg % 3600) // 60

        embed = discord.Embed(title=f"📊 {member.display_name}", color=discord.Color.purple())
        embed.set_thumbnail(url=member.display_avatar.url)
        
        embed.add_field(name="Nivel", value=f"⭐ **{nivel}**", inline=True)
        embed.add_field(name="Tiempo", value=f"⏳ {h}h {m}m", inline=True)
        embed.add_field(name="Canciones", value=f"💿 {pedidas}", inline=True)
        
        embed.add_field(
            name=f"Experiencia: {xp_act}/{xp_meta} ({pct}%)", 
            value=f"`{barra}`\n💬 Chat: {xp_c} | 🎵 Música: {xp_m}", 
            inline=False
        )
        await ctx.send(embed=embed)

    @commands.command(name='top')
    async def top(self, ctx):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT user_id, nivel, xp FROM usuarios ORDER BY nivel DESC, xp DESC LIMIT 5')
            rows = await cursor.fetchall()
        
        embed = discord.Embed(title="🏆 Top Global", color=discord.Color.gold())
        for i, (uid, lvl, xp) in enumerate(rows, 1):
            u = self.bot.get_user(uid)
            name = u.display_name if u else "Usuario"
            embed.add_field(name=f"#{i} {name}", value=f"Nivel {lvl} • {xp} XP", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name='stats')
    async def stats(self, ctx):
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT SUM(canciones_pedidas), SUM(segundos_escuchados), COUNT(*) FROM usuarios')
            row = await cursor.fetchone()
        
        if not row: return
        total_c, total_s, usuarios = row
        h = (total_s or 0) // 3600
        
        embed = discord.Embed(title="🌐 Estadísticas del Servidor", color=discord.Color.blue())
        embed.add_field(name="Canciones Totales", value=str(total_c))
        embed.add_field(name="Horas Reproducidas", value=f"{h} horas")
        embed.add_field(name="Usuarios Activos", value=str(usuarios))
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Perfiles(bot))