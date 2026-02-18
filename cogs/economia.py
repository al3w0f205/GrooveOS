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
            # Hemos quitado xp y nivel de la creación de la tabla
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    user_id INTEGER PRIMARY KEY,
                    balance INTEGER DEFAULT 0,
                    ultimo_daily TEXT
                )
            """)
            conn.commit()

    def get_user_data(self, user_id):
        """Obtiene o crea los datos de un usuario en la base de datos."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Solo seleccionamos balance y daily
            cursor.execute("SELECT balance, ultimo_daily FROM usuarios WHERE user_id = ?", (user_id,))
            data = cursor.fetchone()
            
            if data is None:
                # Insertamos solo el usuario y el balance inicial
                cursor.execute("INSERT INTO usuarios (user_id, balance) VALUES (?, 0)", (user_id,))
                conn.commit()
                return 0, None
            return data

    def update_user(self, user_id, balance_change=0, daily_update=None):
        """Actualiza de forma precisa los valores del usuario (Solo dinero)."""
        balance, daily = self.get_user_data(user_id)
        
        nuevo_balance = balance + balance_change
        nuevo_daily = daily_update if daily_update else daily

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE usuarios 
                SET balance = ?, ultimo_daily = ? 
                WHERE user_id = ?
            """, (nuevo_balance, nuevo_daily, user_id))
            conn.commit()

    @commands.Cog.listener()
    async def on_message(self, message):
        """Sistema pasivo: Gana monedas por hablar (Sin XP)."""
        if message.author.bot:
            return

        # Probabilidad o cantidad aleatoria de monedas
        monedas_ganadas = random.randint(1, 5)
        
        # Simplemente actualizamos el balance, sin calcular niveles
        self.update_user(message.author.id, balance_change=monedas_ganadas)

    @commands.hybrid_command(name="daily", description="Reclama tus GrooveCoins diarias.")
    async def daily(self, ctx):
        """Comando para obtener dinero cada 24 horas."""
        user_id = ctx.author.id
        # Ajustado para recibir solo 2 valores
        balance, ultimo_daily_str = self.get_user_data(user_id)

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

    @commands.hybrid_command(name="balance", description="Mira cuánto dinero tienes.")
    async def balance(self, ctx, miembro: discord.Member = None):
        """Muestra el estado financiero del usuario."""
        miembro = miembro or ctx.author
        balance, _ = self.get_user_data(miembro.id)

        embed = discord.Embed(title=f"Billetera de {miembro.display_name}", color=discord.Color.gold())
        if miembro.avatar:
            embed.set_thumbnail(url=miembro.avatar.url)
        
        # Eliminados los campos de Nivel y XP del embed
        embed.add_field(name="💰 GrooveCoins", value=f"`{balance}`", inline=True)
        embed.set_footer(text="Gana monedas participando en el chat.")
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Economia(bot))