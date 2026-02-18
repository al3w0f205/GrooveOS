import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import random

class Mercado(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "economia.db"
        
        # --- CONFIGURACIÓN DE LA TIENDA ---
        # Formato: "Nombre del Item": {"costo": Precio, "role_id": ID_del_Rol, "desc": "Descripción"}
        self.shop_items = {
            "vip": {
                "costo": 5000, 
                "role_id": 123456789012345678, # <--- CAMBIA ESTO POR UN ID REAL
                "desc": "Obtén el rol VIP y destaca en el chat."
            },
            "dj": {
                "costo": 2500, 
                "role_id": 987654321098765432, # <--- CAMBIA ESTO POR UN ID REAL
                "desc": "Rol de DJ para controlar la música."
            },
            "rico": {
                "costo": 10000, 
                "role_id": 112233445566778899, # <--- CAMBIA ESTO POR UN ID REAL
                "desc": "Demuestra que te sobran las monedas."
            }
        }

    def get_balance(self, user_id):
        """Lee el saldo directamente de la DB."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT balance FROM usuarios WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
            return result[0] if result else 0

    def update_balance(self, user_id, amount):
        """Suma o resta dinero (amount puede ser negativo)."""
        current = self.get_balance(user_id)
        new_balance = current + amount
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE usuarios SET balance = ? WHERE user_id = ?", (new_balance, user_id))
            conn.commit()
        return new_balance

    # --- 1. COMERCIO (Transferencias) ---
    @commands.hybrid_command(name="pagar", description="Transfiere monedas a otro usuario.")
    async def pagar(self, ctx, destinatario: discord.Member, cantidad: int):
        """Permite pagar a otro usuario por servicios o regalos."""
        if destinatario.bot:
            return await ctx.send("❌ No puedes enviar dinero a los bots.", ephemeral=True)
        if destinatario.id == ctx.author.id:
            return await ctx.send("❌ No puedes pagarte a ti mismo.", ephemeral=True)
        if cantidad <= 0:
            return await ctx.send("❌ La cantidad debe ser positiva.", ephemeral=True)

        saldo = self.get_balance(ctx.author.id)
        
        if saldo < cantidad:
            return await ctx.send(f"❌ No tienes suficientes fondos. Tienes `{saldo}` monedas.", ephemeral=True)

        # Realizar transacción
        self.update_balance(ctx.author.id, -cantidad) # Restar al que envía
        
        # Asegurar que el destinatario existe en la DB (sumando 0 primero crea el registro si no existe)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR IGNORE INTO usuarios (user_id, balance) VALUES (?, 0)", (destinatario.id,))
        
        self.update_balance(destinatario.id, cantidad) # Sumar al que recibe

        await ctx.send(f"💸 **Transferencia exitosa:** {ctx.author.mention} pagó `{cantidad}` monedas a {destinatario.mention}.")

    # --- 2. JUEGOS (Tragaperras) ---
    @commands.hybrid_command(name="apostar", description="Juega a las tragaperras (Slots).")
    async def apostar(self, ctx, cantidad: int):
        """Apuesta dinero. x2 si sacas 2 iguales, x5 si sacas 3 iguales."""
        if cantidad < 10:
            return await ctx.send("❌ La apuesta mínima es de 10 monedas.", ephemeral=True)

        saldo = self.get_balance(ctx.author.id)
        if saldo < cantidad:
            return await ctx.send("❌ No tienes dinero suficiente.", ephemeral=True)

        # Restamos la apuesta inicial
        self.update_balance(ctx.author.id, -cantidad)

        # Lógica del juego
        emojis = ["🍒", "🍋", "🍇", "💎", "7️⃣"]
        slots = [random.choice(emojis) for _ in range(3)]
        
        resultado_visual = f"🎰 | {' | '.join(slots)} | 🎰"
        
        ganancia = 0
        mensaje = ""

        if slots[0] == slots[1] == slots[2]:
            ganancia = cantidad * 5
            mensaje = f"¡JACKPOT! Has ganado **{ganancia}** monedas. 🎉"
        elif slots[0] == slots[1] or slots[1] == slots[2] or slots[0] == slots[2]:
            ganancia = cantidad * 2
            mensaje = f"¡Par! Has ganado **{ganancia}** monedas."
        else:
            mensaje = "Has perdido todo. 📉"

        if ganancia > 0:
            self.update_balance(ctx.author.id, ganancia)

        embed = discord.Embed(title="Casino GrooveOS", description=f"{resultado_visual}\n\n{mensaje}", color=discord.Color.purple())
        await ctx.send(embed=embed)

    # --- 3. TIENDA (Comprar Roles) ---
    @commands.hybrid_command(name="tienda", description="Muestra los objetos disponibles para comprar.")
    async def tienda(self, ctx):
        """Lista los items configurados en el bot."""
        embed = discord.Embed(title="🛒 Tienda del Servidor", description="Usa `/comprar [nombre]` para adquirir un item.", color=discord.Color.green())
        
        for key, item in self.shop_items.items():
            rol = ctx.guild.get_role(item['role_id'])
            nombre_rol = rol.name if rol else "Rol Desconocido"
            embed.add_field(
                name=f"🏷️ {key.upper()} - ${item['costo']}",
                value=f"**Rol:** {nombre_rol}\n*{item['desc']}*",
                inline=False
            )
        await ctx.send(embed=embed)

    @commands.hybrid_command(name="comprar", description="Compra un rol de la tienda.")
    @app_commands.describe(articulo="El nombre del artículo (ej: vip, dj)")
    async def comprar(self, ctx, articulo: str):
        """Permite gastar monedas a cambio de roles."""
        item_key = articulo.lower()
        
        if item_key not in self.shop_items:
            return await ctx.send(f"❌ El artículo `{articulo}` no existe. Mira la `/tienda`.", ephemeral=True)

        item = self.shop_items[item_key]
        costo = item['costo']
        role_id = item['role_id']
        rol = ctx.guild.get_role(role_id)

        if not rol:
            return await ctx.send("❌ Error de configuración: El rol no existe en el servidor. Contacta al admin.", ephemeral=True)

        if rol in ctx.author.roles:
            return await ctx.send("⚠️ Ya tienes este artículo comprado.", ephemeral=True)

        saldo = self.get_balance(ctx.author.id)
        if saldo < costo:
            return await ctx.send(f"❌ Te faltan `{costo - saldo}` monedas para comprar esto.", ephemeral=True)

        # Transacción final
        try:
            self.update_balance(ctx.author.id, -costo)
            await ctx.author.add_roles(rol)
            await ctx.send(f"✅ ¡Compra exitosa! Ahora tienes el rol **{rol.name}**.")
        except discord.Forbidden:
            # Devolvemos el dinero si el bot no tiene permisos
            self.update_balance(ctx.author.id, costo)
            await ctx.send("❌ No tengo permisos para darte ese rol (asegúrate de que mi rol 'GrooveOS' esté por encima del rol que intentas comprar).")

async def setup(bot):
    await bot.add_cog(Mercado(bot))