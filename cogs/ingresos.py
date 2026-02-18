import discord
from discord.ext import commands
import sqlite3
import random
import asyncio

class Ingresos(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "economia.db"

    def update_balance(self, user_id, amount):
        """Actualiza el saldo (suma o resta)."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Aseguramos que el usuario existe
            cursor.execute("INSERT OR IGNORE INTO usuarios (user_id, balance) VALUES (?, 0)", (user_id,))
            cursor.execute("UPDATE usuarios SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            conn.commit()

    def get_balance(self, user_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT balance FROM usuarios WHERE user_id = ?", (user_id,))
            res = cursor.fetchone()
            return res[0] if res else 0

    @commands.hybrid_command(name="chambear", description="Trabaja honestamente para ganar algo de dinero.")
    @commands.cooldown(1, 3600, commands.BucketType.user) # 1 uso cada hora (3600 seg)
    async def chambear(self, ctx):
        trabajos = [
            "limpiando los baños de la estación espacial",
            "programando en Python (pero mal)",
            "vendiendo limonada en Minecraft",
            "ayudando a señoras a cruzar la calle",
            "reparando el servidor del bot"
        ]
        ganancia = random.randint(50, 150)
        
        self.update_balance(ctx.author.id, ganancia)
        
        embed = discord.Embed(
            description=f"💼 Has trabajado **{random.choice(trabajos)}** y ganaste **{ganancia}** monedas.",
            color=discord.Color.green()
        )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="crimen", description="Arriésgate a robar. Puedes ganar mucho o perder dinero.")
    @commands.cooldown(1, 7200, commands.BucketType.user) # 1 uso cada 2 horas
    async def crimen(self, ctx):
        saldo = self.get_balance(ctx.author.id)
        if saldo < 200:
            return await ctx.send("❌ Necesitas al menos 200 monedas para comprar equipo de ladrón.", ephemeral=True)

        resultado = random.randint(1, 100)
        
        if resultado > 40: # 60% de éxito
            botin = random.randint(300, 800)
            self.update_balance(ctx.author.id, botin)
            escenarios = ["Robaste un banco", "Hackeaste una cuenta de Discord", "Atracaste a un Creeper"]
            embed = discord.Embed(description=f"🔫 **¡Éxito!** {random.choice(escenarios)}. Te llevas **{botin}** monedas.", color=discord.Color.dark_green())
        else: # 40% de fallo
            multa = random.randint(200, saldo // 2) # Pierdes entre 200 y la mitad de tu dinero
            self.update_balance(ctx.author.id, -multa)
            embed = discord.Embed(description=f"🚨 **¡Te atrapó la policía!** Tuviste que pagar una fianza de **{multa}** monedas.", color=discord.Color.red())
        
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="pescar", description="Prueba suerte en el lago.")
    @commands.cooldown(1, 1800, commands.BucketType.user) # 30 min
    async def pescar(self, ctx):
        peces = [
            {"nombre": "🐟 Pez Payaso", "valor": 30, "prob": 40},
            {"nombre": "🐠 Salmón Dorado", "valor": 150, "prob": 20},
            {"nombre": "🐡 Pez Globo (Te pinchaste)", "valor": 0, "prob": 15},
            {"nombre": "👢 Bota Vieja", "valor": 5, "prob": 20},
            {"nombre": "💎 Tesoro Hundido", "valor": 1000, "prob": 5}
        ]
        
        # Algoritmo de probabilidad simple
        eleccion = random.choices(peces, weights=[p['prob'] for p in peces], k=1)[0]
        
        self.update_balance(ctx.author.id, eleccion['valor'])
        
        emoji = "🎉" if eleccion['valor'] > 100 else "🎣"
        desc = f"{emoji} Lanzaste el anzuelo y sacaste: **{eleccion['nombre']}**"
        
        if eleccion['valor'] > 0:
            desc += f"\nLo vendiste por **{eleccion['valor']}** monedas."
        else:
            desc += "\nNo vale nada."

        await ctx.send(embed=discord.Embed(description=desc, color=discord.Color.blue()))

    @chambear.error
    @crimen.error
    @pescar.error
    async def cooldown_error(self, ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            # Formatear tiempo restante
            tiempo = int(error.retry_after)
            minutos, segundos = divmod(tiempo, 60)
            horas, minutos = divmod(minutos, 60)
            msg = f"⏳ ¡Estás cansado! Inténtalo de nuevo en "
            if horas > 0: msg += f"**{horas}h {minutos}m**."
            else: msg += f"**{minutos}m {segundos}s**."
            await ctx.send(msg, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Ingresos(bot))