import discord
from discord.ext import commands
import sqlite3
import random

class BlackjackView(discord.ui.View):
    def __init__(self, autor_id, apuesta, cog_ref):
        super().__init__(timeout=60)
        self.autor_id = autor_id
        self.apuesta = apuesta
        self.cog_ref = cog_ref
        self.mazo = [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 11] * 4 # Simplificado (J,Q,K valen 10, As vale 11)
        random.shuffle(self.mazo)
        
        self.mano_jugador = [self.sacar_carta(), self.sacar_carta()]
        self.mano_dealer = [self.sacar_carta(), self.sacar_carta()]
        self.terminado = False

    def sacar_carta(self):
        return self.mazo.pop()

    def calcular_mano(self, mano):
        total = sum(mano)
        ases = mano.count(11)
        while total > 21 and ases:
            total -= 10
            ases -= 1
        return total

    def crear_embed(self, final=False):
        total_jugador = self.calcular_mano(self.mano_jugador)
        
        # Si no ha terminado, ocultamos la segunda carta del dealer
        if not final:
            texto_dealer = f"🂠 {self.mano_dealer[0]} + ?"
        else:
            total_dealer = self.calcular_mano(self.mano_dealer)
            texto_dealer = f"🃏 {total_dealer} ({' - '.join(map(str, self.mano_dealer))})"

        embed = discord.Embed(title="♠️ Blackjack ♣️", color=discord.Color.dark_grey())
        embed.add_field(name="Tu Mano", value=f"🃏 **{total_jugador}** ({' - '.join(map(str, self.mano_jugador))})", inline=True)
        embed.add_field(name="Dealer", value=texto_dealer, inline=True)
        embed.set_footer(text=f"Apuesta: {self.apuesta} monedas")
        return embed

    async def finalizar_juego(self, interaction, razon, color, ganancia_neta):
        self.terminado = True
        
        # Actualizar dinero
        # Si ganancia_neta es positiva, se suma. Si es 0, no pasa nada. Si es negativa, ya se restó al inicio.
        if ganancia_neta > 0:
             self.cog_ref.update_balance(self.autor_id, ganancia_neta)
        
        embed = self.crear_embed(final=True)
        embed.description = f"**{razon}**"
        embed.color = color
        
        # Desactivar botones
        for child in self.children:
            child.disabled = True
        
        if interaction.response.is_done():
            await interaction.message.edit(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="Pedir (Hit)", style=discord.ButtonStyle.primary, emoji="🃏")
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.autor_id: return
        
        self.mano_jugador.append(self.sacar_carta())
        total = self.calcular_mano(self.mano_jugador)
        
        if total > 21:
            await self.finalizar_juego(interaction, "¡Te pasaste! Has perdido.", discord.Color.red(), 0)
        elif total == 21:
            # Auto-plantarse si llega a 21
            await self.stand.callback(interaction)
        else:
            await interaction.response.edit_message(embed=self.crear_embed(), view=self)

    @discord.ui.button(label="Plantarse (Stand)", style=discord.ButtonStyle.success, emoji="🛑")
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.autor_id: return
        
        # Turno del Dealer
        total_jugador = self.calcular_mano(self.mano_jugador)
        while self.calcular_mano(self.mano_dealer) < 17:
            self.mano_dealer.append(self.sacar_carta())
            
        total_dealer = self.calcular_mano(self.mano_dealer)
        
        if total_dealer > 21:
            pago = self.apuesta * 2
            await self.finalizar_juego(interaction, f"El Dealer se pasó. ¡Ganas **{pago}**!", discord.Color.green(), pago)
        elif total_dealer > total_jugador:
            await self.finalizar_juego(interaction, "El Dealer tiene una mano mejor. Pierdes.", discord.Color.red(), 0)
        elif total_dealer < total_jugador:
            pago = self.apuesta * 2
            await self.finalizar_juego(interaction, f"¡Tienes mejor mano! Ganas **{pago}**.", discord.Color.green(), pago)
        else:
            await self.finalizar_juego(interaction, "Empate. Recuperas tu apuesta.", discord.Color.gold(), self.apuesta)

class Blackjack(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_path = "economia.db"

    def get_balance(self, user_id):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            res = cursor.execute("SELECT balance FROM usuarios WHERE user_id = ?", (user_id,)).fetchone()
            return res[0] if res else 0

    def update_balance(self, user_id, amount):
        with sqlite3.connect(self.db_path) as conn:
             conn.execute("UPDATE usuarios SET balance = balance + ? WHERE user_id = ?", (amount, user_id))

    @commands.hybrid_command(name="blackjack", aliases=['bj', '21'], description="Juega al 21 contra el bot.")
    async def blackjack(self, ctx, apuesta: int):
        """Inicia una partida de Blackjack."""
        if apuesta < 50:
            return await ctx.send("❌ La apuesta mínima es de 50 monedas.", ephemeral=True)
            
        saldo = self.get_balance(ctx.author.id)
        if saldo < apuesta:
            return await ctx.send(f"❌ No tienes dinero suficiente. Tienes {saldo}.", ephemeral=True)

        # Cobrar la apuesta al inicio
        self.update_balance(ctx.author.id, -apuesta)

        view = BlackjackView(ctx.author.id, apuesta, self)
        embed = view.crear_embed()
        await ctx.send(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(Blackjack(bot))