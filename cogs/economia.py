import discord
from discord.ext import commands
import sqlite3
import random
from datetime import datetime, timedelta

class Economia(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "economia.db"
        self._crear_tabla()

    def _crear_tabla(self):
        """Crea la base de datos y las tablas necesarias si no existen."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    user_id INTEGER PRIMARY KEY,
                    balance INTEGER DEFAULT 0,
                    xp INTEGER DEFAULT 0,
                    nivel INTEGER DEFAULT 1,
                    ultimo_daily TEXT
                )
            """)
            conn.commit()

    def get_user_data(self, user_id):
        """Obtiene o crea los datos de un usuario en la base de datos."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT balance, xp, nivel, ultimo_daily FROM usuarios WHERE user_id = ?", (user_id,))
            data = cursor.fetchone()
            
            if data is None:
                cursor.execute("INSERT INTO usuarios (user_id, balance, xp, nivel) VALUES (?, 0, 0, 1)", (user_id,))
                conn.commit()
                return 0, 0, 1, None
            return data

    def update_user(self, user_id, balance_change=0, xp_change=0, nivel_new=None, daily_update=None):
        """Actualiza de forma precisa los valores del usuario."""
        balance, xp, nivel, daily = self.get_user_data(user_id)
        
        nuevo_balance = balance + balance_change
        nuevo_xp = xp + xp_change
        nuevo_nivel = nivel_new if nivel_new else nivel
        nuevo_daily = daily_update if daily_update else daily

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE usuarios 
                SET balance = ?, xp = ?, nivel = ?, ultimo_daily = ? 
                WHERE user_id = ?
            """, (nuevo_balance, nuevo_xp, nuevo_nivel, nuevo_daily, user_id))
            conn.commit()

    @commands.Cog.listener()
    async def on_message(self, message):
        """Sistema pasivo: Gana XP y monedas por hablar."""
        if message.author.bot:
            return

        # Evitamos spam de XP con una probabilidad o cooldown interno
        xp_ganado = random.randint(5, 15)
        monedas_ganadas = random.randint(1, 5)
    
        balance, xp, nivel, daily = self.get_user_data(message.author.id)

        nuevo_xp = xp + xp_ganado
        xp_necesario = nivel * 100 # Fórmula simple de nivel

        if nuevo_xp >= xp_necesario:
            nuevo_nivel = nivel + 1
            self.update_user(message.author.id, balance_change=monedas_ganadas, xp_change=xp_ganado, nivel_new=nuevo_nivel)
            try:
                await message.channel.send(f"¡Felicidades {message.author.mention}! Has subido al **Nivel {nuevo_nivel}**.")
            except discord.Forbidden:
                pass
        else:
            self.update_user(message.author.id, balance_change=monedas_ganadas, xp_change=xp_ganado)

    @commands.hybrid_command(name="daily", description="Reclama tus GrooveCoins diarias.")
    async def daily(self, ctx):
        """Comando para obtener dinero cada 24 horas."""
        user_id = ctx.author.id
        balance, xp, nivel, ultimo_daily_str = self.get_user_data(user_id)

        ahora = datetime.now()
        recompensa = 200

        if ultimo_daily_str:
            ultimo_daily = datetime.strptime(ultimo_daily_str, '%Y-%m-%d %H:%M:%S.%f')
            if ahora < ultimo_daily + timedelta(days=1):
                tiempo_restante = (ultimo_daily + timedelta(days=1)) - ahora
                horas, segundos = divmod(int(tiempo_restante.total_seconds()), 3600)
                minutos, _ = divmod(segundos, 60)
                return await ctx.send(f"Ya has reclamado tu recompensa. Vuelve en **{horas}h {minutos}m**.")

        self.update_user(user_id, balance_change=recompensa, daily_update=str(ahora))
        await ctx.send(f"💰 ¡Has recibido **{recompensa} GrooveCoins**! Tu balance actual es de **{balance + recompensa}**.")

    @commands.hybrid_command(name="balance", description="Mira cuánto dinero y XP tienes.")
    async def balance(self, ctx, miembro: discord.Member = None):
        """Muestra el estado financiero y de nivel del usuario."""
        miembro = miembro or ctx.author
        balance, xp, nivel, _ = self.get_user_data(miembro.id)
        xp_sig = nivel * 100

        embed = discord.Embed(title=f"Cartera de {miembro.display_name}", color=discord.Color.gold())
        if miembro.avatar:
            embed.set_thumbnail(url=miembro.avatar.url)

        embed.add_field(name="💰 GrooveCoins", value=f"`{balance}`", inline=True)
        embed.add_field(name="⭐ Nivel", value=f"`{nivel}`", inline=True)
        embed.add_field(name="📊 Progreso XP", value=f"`{xp}/{xp_sig}`", inline=False)
        embed.set_footer(text="Sigue activo para ganar más.")

        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Economia(bot))