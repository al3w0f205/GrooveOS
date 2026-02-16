# cogs/perfiles.py
import discord
from discord.ext import commands
import aiosqlite
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
            await db.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    user_id INTEGER PRIMARY KEY,
                    canciones_pedidas INTEGER DEFAULT 0,
                    nivel INTEGER DEFAULT 1,
                    xp INTEGER DEFAULT 0,
                    segundos_escuchados INTEGER DEFAULT 0,
                    xp_chat INTEGER DEFAULT 0,
                    xp_musica INTEGER DEFAULT 0
                )
            """)
            # Migración segura (si ya existen, ignora)
            try:
                await db.execute("ALTER TABLE usuarios ADD COLUMN xp_chat INTEGER DEFAULT 0")
            except:
                pass
            try:
                await db.execute("ALTER TABLE usuarios ADD COLUMN xp_musica INTEGER DEFAULT 0")
            except:
                pass
            await db.commit()
        print("🗄️ Base de datos Perfiles lista.")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.content.startswith('.'):
            return

        user_id = message.author.id
        ahora = time.time()

        if ahora - self.last_xp_time.get(user_id, 0) < 60:
            return

        xp = random.randint(15, 25)
        await self.actualizar_stats(message, xp_ganado=xp, fuente='chat')
        self.last_xp_time[user_id] = ahora

    async def actualizar_stats(
        self,
        ctx_or_msg,
        duracion: int = 0,
        xp_ganado: int = 0,
        fuente: str = 'musica',
        es_musica: bool = False,
        contar_pedido: bool = True
    ):
        """
        - contar_pedido=True: incrementa canciones_pedidas (solo en música)
        - contar_pedido=False: solo suma duración (y el xp_ganado que le pases)
        """
        if es_musica:
            fuente = 'musica'

        user_id = ctx_or_msg.author.id

        # XP por defecto SOLO cuando es un pedido (para no duplicar al terminar pista)
        if xp_ganado == 0 and fuente == 'musica' and contar_pedido:
            xp_ganado = 10

        duracion = max(0, int(duracion or 0))
        xp_ganado = max(0, int(xp_ganado or 0))

        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT * FROM usuarios WHERE user_id = ?', (user_id,))
            row = await cursor.fetchone()

            if not row:
                pedidas = 1 if (fuente == 'musica' and contar_pedido) else 0
                xp_c = xp_ganado if fuente == 'chat' else 0
                xp_m = xp_ganado if fuente == 'musica' else 0

                await db.execute(
                    'INSERT INTO usuarios VALUES (?, ?, 1, ?, ?, ?, ?)',
                    (user_id, pedidas, xp_ganado, duracion, xp_c, xp_m)
                )
            else:
                uid, pedidas, nivel, xp_total, tiempo, xp_chat, xp_musica = row

                xp_total += xp_ganado

                if fuente == 'musica':
                    if contar_pedido:
                        pedidas += 1
                    tiempo += duracion
                    xp_musica += xp_ganado
                else:
                    xp_chat += xp_ganado

                # Level up
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
                    except:
                        pass

                await db.execute("""
                    UPDATE usuarios
                    SET canciones_pedidas=?, nivel=?, xp=?, segundos_escuchados=?, xp_chat=?, xp_musica=?
                    WHERE user_id=?
                """, (pedidas, nivel, xp_total, tiempo, xp_chat, xp_musica, user_id))

            await db.commit()

    @commands.hybrid_command(
        name='perfil', 
        aliases=['p-stats', 'profile', 'pstats'], 
        description="Muestra tus estadísticas o las de otro miembro"
    )
    async def perfil(self, ctx, member: discord.Member = None):
        """Muestra el nivel, experiencia y tiempo de escucha."""
        member = member or ctx.author
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('SELECT * FROM usuarios WHERE user_id = ?', (member.id,))
            row = await cursor.fetchone()

        if not row:
            return await ctx.send("📉 Sin datos registrados.")

        _, pedidas, nivel, xp_act, seg, xp_c, xp_m = row
        xp_meta = nivel * 100
        pct = int((xp_act / xp_meta) * 100) if xp_meta > 0 else 0

        bloques = int(pct / 10)
        barra = "▰" * bloques + "▱" * (10 - bloques)

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

    @commands.hybrid_command(
        name='top', 
        description="Muestra el ranking de los usuarios con más nivel"
    )
    async def top(self, ctx):
        """Muestra el Top 5 global de GrooveOS."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'SELECT user_id, nivel, xp FROM usuarios ORDER BY nivel DESC, xp DESC LIMIT 5'
            )
            rows = await cursor.fetchall()

        medals = ["🥇", "🥈", "🥉", "🏅", "🏅"]

        embed = discord.Embed(title="🏆 Top Global", color=discord.Color.gold())
        desc_lines = []

        for i, (uid, lvl, xp) in enumerate(rows, 0):
            name = None

            # 1) Preferir miembro del server (display_name real)
            if ctx.guild:
                member = ctx.guild.get_member(uid)
                if member:
                    name = member.display_name

            # 2) Si no está en guild cache, fetch user (API)
            if not name:
                try:
                    user = await self.bot.fetch_user(uid)
                    name = user.name
                except:
                    name = f"Usuario ({uid})"

            medal = medals[i] if i < len(medals) else "🏅"
            desc_lines.append(f"{medal} **#{i+1} {name}** — Nivel **{lvl}** • `{xp}` XP")

        embed.description = "\n".join(desc_lines) if desc_lines else "Sin datos."
        await ctx.send(embed=embed)

    @commands.hybrid_command(
        name='stats', 
        description="Muestra las estadísticas globales del bot en este servidor"
    )
    async def stats(self, ctx):
        """Resumen total de canciones, tiempo y usuarios."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'SELECT SUM(canciones_pedidas), SUM(segundos_escuchados), COUNT(*) FROM usuarios'
            )
            row = await cursor.fetchone()

        if not row:
            return

        total_c, total_s, usuarios = row
        h = (total_s or 0) // 3600

        embed = discord.Embed(title="🌐 Estadísticas del Servidor", color=discord.Color.blue())
        embed.add_field(name="Canciones Totales", value=str(total_c or 0), inline=True)
        embed.add_field(name="Horas Reproducidas", value=f"{h} horas", inline=True)
        embed.add_field(name="Usuarios Activos", value=str(usuarios or 0), inline=True)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Perfiles(bot))