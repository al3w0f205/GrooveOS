import discord
from discord.ext import commands
from discord import app_commands

class HelpDropdown(discord.ui.Select):
    def __init__(self, bot, author):
        self.bot = bot
        self.author = author
        
        options = [
            discord.SelectOption(
                label="Inicio", 
                description="Menú principal y resumen.", 
                emoji="🏠", 
                value="inicio"
            ),
            discord.SelectOption(
                label="Música & DJ", 
                description="Reproducción, Listas y DJ con IA.", 
                emoji="🎵", 
                value="musica"
            ),
            discord.SelectOption(
                label="Economía & Casino", 
                description="Dinero, Tienda, Blackjack y Apuestas.", 
                emoji="🎰", 
                value="economia"
            ),
            discord.SelectOption(
                label="Social, Perfiles & IA", 
                description="Niveles, ChatBot, TTS y Rankings.", 
                emoji="🗣️", 
                value="social"
            ),
            discord.SelectOption(
                label="Moderación & Sistemas", 
                description="Admin, Minecraft, Warns y Config.", 
                emoji="🛡️", 
                value="sistemas"
            ),
        ]
        
        super().__init__(
            placeholder="Selecciona una categoría...",
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: discord.Interaction):
        if interaction.user != self.author:
            return await interaction.response.send_message("❌ Este menú es para quien solicitó la ayuda.", ephemeral=True)

        # Lógica para cambiar el Embed según la selección
        if self.values[0] == "inicio":
            embed = self.embed_inicio()
        elif self.values[0] == "musica":
            embed = self.embed_musica()
        elif self.values[0] == "economia":
            embed = self.embed_economia()
        elif self.values[0] == "social":
            embed = self.embed_social()
        elif self.values[0] == "sistemas":
            embed = self.embed_sistemas()
        
        await interaction.response.edit_message(embed=embed, view=self.view)

    # --- DEFINICIÓN DE EMBEDS ---

    def embed_inicio(self):
        embed = discord.Embed(
            title="📘 Manual de Usuario - GrooveOS",
            description=(
                "Bienvenido. **GrooveOS** es un sistema integral de gestión para tu servidor.\n"
                "Desde música de alta calidad y economía, hasta moderación avanzada y servidores de Minecraft.\n\n"
                "👇 **Selecciona una categoría abajo para ver los comandos.**"
            ),
            color=discord.Color.blurple()
        )
        if self.bot.user.avatar:
            embed.set_thumbnail(url=self.bot.user.avatar.url)
        
        embed.add_field(name="📅 Eventos Diarios", value="Usa `/daily` para cobrar tu sueldo.", inline=True)
        embed.add_field(name="🧠 Inteligencia Artificial", value="Chat con Llama 3 y DJ Automático.", inline=True)
        embed.add_field(name="⛏️ Minecraft", value="Control de servidor Survival integrado.", inline=True)
        
        return embed

    def embed_musica(self):
        embed = discord.Embed(title="🎵 Música y DJ", color=discord.Color.purple())
        
        embed.add_field(
            name="🎧 Reproducción Básica",
            value=(
                "• **`/play <busqueda>`**: Reproduce desde YouTube/Spotify.\n"
                "• **`/pause`** / **`/resume`**: Pausar o continuar.\n"
                "• **`/skip`**: Saltar canción.\n"
                "• **`/stop`**: Desconectar y borrar cola.\n"
                "• **`/loop`**: Alternar bucle (Canción/Cola)."
            ), inline=False
        )
        embed.add_field(
            name="🤖 Funciones Inteligentes",
            value=(
                "• **`/dj <artista>`**: La IA genera una playlist experta de ese artista.\n"
                "• **`/djclear`**: Limpia el historial de duplicados del DJ.\n"
                "• **`/panel`**: Muestra los botones de control."
            ), inline=False
        )
        return embed

    def embed_economia(self):
        embed = discord.Embed(title="💰 Economía y Casino", color=discord.Color.gold())
        
        embed.add_field(
            name="💵 Finanzas",
            value=(
                "• **`/daily`**: Reclama 200 monedas cada 24h.\n"
                "• **`/balance`**: Ver tu saldo actual.\n"
                "• **`/pagar @usuario <cantidad>`**: Transferir dinero.\n"
                "• **`/tienda`** y **`/comprar`**: Adquirir roles VIP."
            ), inline=False
        )
        embed.add_field(
            name="🎰 Casino (Juegos de Azar)",
            value=(
                "• **`/blackjack <apuesta>`**: Juega al 21 contra el bot.\n"
                "• **`/ruleta <color> <apuesta>`**: Rojo/Negro (x2) o Verde (x14).\n"
                "• **`/dados <apuesta>`**: Tira los dados contra la casa.\n"
                "• **`/duelo @usuario <apuesta>`**: PvP a muerte por dinero.\n"
                "• **`/apostar <cantidad>`**: Tragaperras clásica (Slots)."
            ), inline=False
        )
        return embed

    def embed_social(self):
        embed = discord.Embed(title="🗣️ Social, Perfiles e IA", color=discord.Color.blue())
        
        embed.add_field(
            name="🧠 Chat IA (Groq)",
            value=(
                "• **`/ia <mensaje>`**: Habla con el asistente inteligente.\n"
                "• **`/ia_reset`**: Borra la memoria de tu conversación."
            ), inline=False
        )
        embed.add_field(
            name="📊 Perfiles y Niveles",
            value=(
                "• **`/perfil`**: Mira tu Nivel, XP y tiempo escuchado.\n"
                "• **`/top`**: Ranking de usuarios con más nivel.\n"
                "• **`/stats`**: Estadísticas globales del servidor."
            ), inline=False
        )
        embed.add_field(
            name="🎙️ Texto a Voz (TTS)",
            value=(
                "• **`/tts <texto>`**: El bot lee tu mensaje en voz alta.\n"
                "• **`/cambiar_voz`**: Elige voces (Mexicano, Español, etc).\n"
                "• **`/stoptts`**: Calla al bot inmediatamente."
            ), inline=False
        )
        return embed

    def embed_sistemas(self):
        embed = discord.Embed(title="🛡️ Moderación y Sistemas", color=discord.Color.dark_grey())
        
        embed.add_field(
            name="🔨 Moderación",
            value=(
                "• **`/warn @user`** / **`/unwarn`**: Gestionar advertencias.\n"
                "• **`/warns @user`**: Ver historial de sanciones.\n"
                "• **`/timeout`** / **`/untimeout`**: Aislar temporalmente.\n"
                "• **`/kick`** / **`/ban`** / **`/unban`**: Expulsiones.\n"
                "• **`/clear <n>`**: Borrar mensajes masivamente."
            ), inline=False
        )
        embed.add_field(
            name="⚙️ Admin y Utilidad",
            value=(
                "• **`/minecraft`**: Panel de control del servidor Survival.\n"
                "• **`/setup_tickets`**: Crear panel de soporte.\n"
                "• **`/setup_roles`**: Crear menú de auto-roles.\n"
                "• **`/sys`**: Ver estado (CPU/RAM) del VPS.\n"
                "• **`/ping`**: Ver latencia."
            ), inline=False
        )
        return embed

class HelpView(discord.ui.View):
    def __init__(self, bot, author):
        super().__init__(timeout=180)
        self.add_item(HelpDropdown(bot, author))

class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        # Eliminamos el comando help por defecto para usar el nuestro
        self.bot.remove_command('help')

    @commands.hybrid_command(name="help", description="Guía interactiva de GrooveOS.")
    async def help(self, ctx):
        """Muestra el menú de ayuda interactivo."""
        view = HelpView(self.bot, ctx.author)
        # Enviamos el embed de "Inicio" por defecto
        embed = view.children[0].embed_inicio() 
        await ctx.send(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(Help(bot))