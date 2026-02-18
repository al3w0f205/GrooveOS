import discord
from discord.ext import commands

class RoleSelect(discord.ui.Select):
    def __init__(self):
        # CONFIGURACIÓN: Aquí defines las opciones del menú.
        # Reemplaza los 'value' con los IDs REALES de los roles de tu servidor.
        options = [
            discord.SelectOption(
                label="Notificaciones Música",
                value="1473513586910433320", # <-- PON TU ID AQUÍ
                description="Recibe alertas sobre novedades musicales",
                emoji="🎵"
            ),
            discord.SelectOption(
                label="Jugador Minecraft",
                value="1473513753214451795", # <-- PON TU ID AQUÍ
                description="Acceso a los canales del servidor de MC",
                emoji="⛏️"
            ),
            discord.SelectOption(
                label="Eventos",
                value="1473513832981991617", # <-- PON TU ID AQUÍ
                emoji="🎉"
            ),
            # Puedes añadir más opciones copiando y pegando la estructura de arriba (hasta 25)
        ]
        # Configuración del menú
        super().__init__(
            placeholder="Selecciona tus roles aquí...",
            min_values=0, # Permite deseleccionar todo
            max_values=len(options), # Permite seleccionar todos a la vez
            custom_id="persistent_role_view:select" # ID único para persistencia
        )

    async def callback(self, interaction: discord.Interaction):
        """Lógica que se ejecuta al seleccionar opciones."""
        guild = interaction.guild
        user = interaction.user

        # Diferir la respuesta para tener tiempo de procesar si hay muchos roles
        await interaction.response.defer(ephemeral=True)

        added_roles = []
        removed_roles = []

        # Obtenemos los IDs seleccionados por el usuario (son strings, convertimos a int)
        selected_values = [int(v) for v in self.values]

        # Iteramos sobre todas las opciones posibles del menú
        for option in self.options:
            role_id = int(option.value)
            role = guild.get_role(role_id)

            if role:
                if role_id in selected_values:
                    # Si el rol fue seleccionado y el usuario NO lo tiene, se lo damos
                    if role not in user.roles:
                        await user.add_roles(role)
                        added_roles.append(role.name)
                else:
                    # Si el rol NO fue seleccionado (o fue deseleccionado) y el usuario SÍ lo tiene, se lo quitamos
                    if role in user.roles:
                        await user.remove_roles(role)
                        removed_roles.append(role.name)

        # Construimos el mensaje de respuesta
        response_text = ""
        if added_roles:
            response_text += f"✅ **Añadido:** {', '.join(added_roles)}\n"
        if removed_roles:
            response_text += f"❌ **Removido:** {', '.join(removed_roles)}\n"

        if not response_text:
            response_text = "No se han realizado cambios en tus roles."

        await interaction.followup.send(response_text, ephemeral=True)

class RoleView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # timeout=None es vital para que no expire
        self.add_item(RoleSelect())

class Roles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Registra la vista persistente al iniciar el bot."""
        # Esto permite que el menú funcione aunque reinicies el bot
        self.bot.add_view(RoleView())

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def setup_roles(self, ctx):
        """Comando para enviar el panel de roles al canal actual."""
        embed = discord.Embed(
            title="🎭 Auto-Asignación de Roles",
            description="Usa el menú de abajo para elegir qué notificaciones o accesos quieres tener en el servidor.",
            color=discord.Color.from_rgb(43, 45, 49) # Color oscuro estilo Discord
        )
        embed.set_footer(text="GrooveOS • Roles")

        await ctx.send(embed=embed, view=RoleView())
        # Borramos el comando del admin para limpiar
        try:
            await ctx.message.delete()
        except:
            pass

async def setup(bot):
    await bot.add_cog(Roles(bot))