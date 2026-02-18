import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import random
import asyncio

class BotonesDuelo(discord.ui.View):
    """Botones para aceptar o rechazar un duelo."""
    def __init__(self, retador, oponente, cantidad, db_path, cog_ref):
        super().__init__(timeout=60)
        self.retador = retador
        self.oponente = oponente
        self.cantidad = cantidad
        self.db_path = db_path
        self.cog_ref = cog_ref # Referencia al Cog para usar sus funciones
        self.value = None

    @discord.ui.button(label="Aceptar Desafío", style=discord.ButtonStyle.success, emoji="⚔️")
    async def aceptar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.oponente:
            return await interaction.response.send_message("No puedes aceptar un duelo que no es para ti.", ephemeral=True)

        # Verificar fondos del oponente antes de aceptar
        saldo_oponente = self.cog_ref.get_balance(self.oponente.id)
        if saldo_oponente < self.cantidad:
            return await interaction.response.send_message("No tienes dinero suficiente para aceptar.", ephemeral=True)

        self.value = True
        self.stop() # Detenemos la vista para procesar el juego
        await interaction.response.defer() # Evita que la interacción falle

    @discord.ui.button(label="Huir", style=discord.ButtonStyle.danger, emoji="🏃")
    async def rechazar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user != self.oponente:
            return await interaction.response.send_message("No te metas.", ephemeral=True)
        
        self.value = False
        self.stop()
        await interaction.response.send_message(f"{self.oponente.mention} ha rechazado el duelo (cobarde).")

class Juegos(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "economia.db"

    def get_balance(self, user_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT balance FROM usuarios WHERE user_id = ?", (user_id,))
            result = cursor.fetchone()
            return result[0] if result else 0

    def update_balance(self, user_id, amount):
        current = self.get_balance(user_id)
        new_balance = current + amount
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("INSERT OR IGNORE INTO usuarios (user_id, balance) VALUES (?, 0)", (user_id,))
            conn.execute("UPDATE usuarios SET balance = ? WHERE user_id = ?", (new_balance, user_id))
            conn.commit()
        return new_balance

    # --- 1. RULETA (PvE) ---
    @commands.hybrid_command(name="ruleta", description="Apuesta al rojo (x2), negro (x2) o verde (x14).")
    @app_commands.describe(color="rojo, negro, o verde", cantidad="Dinero a apostar")
    @app_commands.choices(color=[
        app_commands.Choice(name="🔴 Rojo (x2)", value="rojo"),
        app_commands.Choice(name="⚫ Negro (x2)", value="negro"),
        app_commands.Choice(name="🟢 Verde (x14)", value="verde")
    ])
    async def ruleta(self, ctx, color: app_commands.Choice[str], cantidad: int):
        """Juego clásico de casino."""
        if cantidad <= 0: return await ctx.send("Apuesta positiva, por favor.", ephemeral=True)
        
        saldo = self.get_balance(ctx.author.id)
        if saldo < cantidad: return await ctx.send("No tienes suficientes monedas.", ephemeral=True)

        # Quitamos el dinero primero
        self.update_balance(ctx.author.id, -cantidad)

        # Lógica de la ruleta
        # 0 = Verde, 1-14 = Rojo, 15-28 = Negro (Simplificado)
        resultado_num = random.randint(0, 28)
        
        color_ganador = ""
        emoji_ganador = ""
        multiplicador = 0

        if resultado_num == 0:
            color_ganador = "verde"
            emoji_ganador = "🟢"
            multiplicador = 14
        elif 1 <= resultado_num <= 14:
            color_ganador = "rojo"
            emoji_ganador = "🔴"
            multiplicador = 2
        else:
            color_ganador = "negro"
            emoji_ganador = "⚫"
            multiplicador = 2

        # Comprobar victoria
        ganancia = 0
        mensaje_final = ""
        
        if color.value == color_ganador:
            ganancia = cantidad * multiplicador
            self.update_balance(ctx.author.id, ganancia)
            mensaje_final = f"**¡GANASTE!** La bola cayó en {emoji_ganador}. Te llevas **{ganancia}** monedas."
        else:
            mensaje_final = f"Perdiste. La bola cayó en {emoji_ganador} ({color_ganador})."

        embed = discord.Embed(title="🎡 Ruleta GrooveOS", description=mensaje_final, color=discord.Color.red())
        await ctx.send(embed=embed)

    # --- 2. DADOS (PvE) ---
    @commands.hybrid_command(name="dados", description="Tira los dados contra el bot. Si sacas más, ganas.")
    async def dados(self, ctx, cantidad: int):
        """Juego simple de dados contra la máquina."""
        if cantidad <= 0: return await ctx.send("Debes apostar algo.", ephemeral=True)
        saldo = self.get_balance(ctx.author.id)
        if saldo < cantidad: return await ctx.send("No tienes dinero.", ephemeral=True)

        # Restamos apuesta
        self.update_balance(ctx.author.id, -cantidad)

        dado_usuario = random.randint(1, 12)
        dado_bot = random.randint(1, 12)

        mensaje = f"Tú tiraste: 🎲 **{dado_usuario}**\nYo tiré: 🎲 **{dado_bot}**\n\n"

        if dado_usuario > dado_bot:
            premio = cantidad * 2
            self.update_balance(ctx.author.id, premio)
            mensaje += f"¡Me ganaste! Te llevas **{premio}** monedas."
            color = discord.Color.green()
        elif dado_usuario < dado_bot:
            mensaje += "¡Te gané! Me quedo con tu dinero."
            color = discord.Color.red()
        else:
            self.update_balance(ctx.author.id, cantidad) # Devolver dinero
            mensaje += "Empate. Te devuelvo tu apuesta."
            color = discord.Color.gold()

        embed = discord.Embed(title="🎲 Duelo de Dados", description=mensaje, color=color)
        await ctx.send(embed=embed)

    # --- 3. DUELO A MUERTE (PvP) ---
    @commands.hybrid_command(name="duelo", description="Desafía a otro usuario por dinero.")
    async def duelo(self, ctx, oponente: discord.Member, cantidad: int):
        """Apuestas 1v1 entre usuarios reales."""
        if oponente.bot or oponente == ctx.author:
            return await ctx.send("No puedes jugar contra bots o contra ti mismo en este modo.", ephemeral=True)
        if cantidad <= 0: return await ctx.send("La apuesta debe ser mayor a 0.", ephemeral=True)

        # Verificar dinero del RETADOR
        saldo_retador = self.get_balance(ctx.author.id)
        if saldo_retador < cantidad:
            return await ctx.send("No tienes dinero para este duelo.", ephemeral=True)

        # Verificar dinero del OPONENTE (preliminar)
        saldo_oponente = self.get_balance(oponente.id)
        if saldo_oponente < cantidad:
            return await ctx.send(f"{oponente.display_name} es demasiado pobre para aceptar esta apuesta.", ephemeral=True)

        # Enviar desafío
        view = BotonesDuelo(ctx.author, oponente, cantidad, self.db_path, self)
        embed = discord.Embed(
            title="⚔️ ¡Desafío de Duelo!",
            description=f"{ctx.author.mention} ha desafiado a {oponente.mention} por **{cantidad} monedas**.\n\n¿Aceptas el reto?",
            color=discord.Color.orange()
        )
        msg = await ctx.send(content=oponente.mention, embed=embed, view=view)

        # Esperar respuesta
        await view.wait()

        if view.value is None:
            await ctx.send(f"El duelo ha expirado. Nadie pierde dinero.")
        elif view.value is True:
            # DUELO ACEPTADO: Lógica de combate
            # 1. Comprobar saldos una ultima vez (por seguridad)
            if self.get_balance(ctx.author.id) < cantidad or self.get_balance(oponente.id) < cantidad:
                return await ctx.send("Alguien se gastó el dinero antes del duelo. Cancelado.")

            # 2. Restar dinero a ambos
            self.update_balance(ctx.author.id, -cantidad)
            self.update_balance(oponente.id, -cantidad)

            # 3. Decidir ganador (50/50)
            ganador = random.choice([ctx.author, oponente])
            perdedor = oponente if ganador == ctx.author else ctx.author
            bote_total = cantidad * 2

            # 4. Pagar al ganador
            self.update_balance(ganador.id, bote_total)

            embed_win = discord.Embed(
                title="🏆 Resultado del Duelo",
                description=f"¡**{ganador.display_name}** ha destrozado a **{perdedor.display_name}**!\n\nSe lleva el bote de **{bote_total}** monedas.",
                color=discord.Color.gold()
            )
            embed_win.set_thumbnail(url=ganador.avatar.url if ganador.avatar else None)
            await ctx.send(embed=embed_win)

async def setup(bot):
    await bot.add_cog(Juegos(bot))