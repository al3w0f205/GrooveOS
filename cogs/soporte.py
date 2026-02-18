import discord
from discord.ext import commands
from discord import app_commands

class TicketControl(discord.ui.View):
    """Botones dentro del ticket para cerrarlo."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Cerrar Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket", emoji="🔒")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Este ticket se cerrará en 5 segundos...")
        await discord.utils.sleep_until(discord.utils.utcnow() + discord.utils.timedelta(seconds=5))
        await interaction.channel.delete()

class TicketLauncher(discord.ui.View):
    """Botón principal para abrir un ticket."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Abrir Ticket de Soporte", style=discord.ButtonStyle.primary, custom_id="launcher_ticket", emoji="📩")
    async def launch(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user

        # Verificar si ya existe un canal para este usuario
        existing_ticket = discord.utils.get(guild.channels, name=f"ticket-{user.name.lower()}")
        if existing_ticket:
            return await interaction.response.send_message(f"Ya tienes un ticket abierto en {existing_ticket.mention}", ephemeral=True)

        # Permisos para el nuevo canal
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        # Crear el canal
        ticket_channel = await guild.create_text_channel(
            name=f"ticket-{user.name.lower()}",
            overwrites=overwrites,
            topic=f"Ticket de soporte para {user.display_name} (ID: {user.id})"
        )

        await interaction.response.send_message(f"Ticket creado con éxito en {ticket_channel.mention}", ephemeral=True)

        # Mensaje de bienvenida dentro del ticket
        embed = discord.Embed(
            title="🎫 Soporte de GrooveOS",
            description=f"Hola {user.mention}, describe tu problema o duda detalladamente.\nUn moderador te atenderá pronto.",
            color=discord.Color.blue()
        )
        embed.set_footer(text="Usa el botón de abajo para cerrar este ticket.")
        
        await ticket_channel.send(embed=embed, view=TicketControl())

class Soporte(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        # Esto asegura que los botones sigan funcionando después de reiniciar el bot
        self.bot.add_view(TicketLauncher())
        self.bot.add_view(TicketControl())

    @commands.hybrid_command(name="setup_tickets", description="Configura el mensaje de tickets en un canal.")
    @commands.has_permissions(administrator=True)
    async def setup_tickets(self, ctx):
        """Crea el mensaje con el botón para abrir tickets."""
        embed = discord.Embed(
            title="📩 Centro de Soporte",
            description=(
                "¿Necesitas ayuda con los comandos de música?\n"
                "¿Has encontrado un error en el sistema de economía?\n"
                "¿Problemas con el servidor de Minecraft?\n\n"
                "Haz clic en el botón de abajo para abrir un canal privado con el equipo."
            ),
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=self.bot.user.avatar.url if self.bot.user.avatar else None)
        
        await ctx.send(embed=embed, view=TicketLauncher())
        await ctx.send("✅ Sistema de tickets configurado.", ephemeral=True)

async def setup(bot):
    await bot.add_cog(Soporte(bot))