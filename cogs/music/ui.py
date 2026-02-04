# cogs/music/ui.py
import discord
import random
import asyncio


class ControlesMusica(discord.ui.View):
    """
    View robusta:
    - Solo deja usar botones a usuarios en el MISMO canal de voz que el bot
    - Evita spam de edits con lock
    - Siempre sincroniza el estilo del botón loop
    """

    def __init__(self, ctx, cog, query: str = ""):
        super().__init__(timeout=None)
        self.ctx = ctx
        self.cog = cog
        self.query = query
        self._lock = asyncio.Lock()
        self._sync_loop_style()

    def _sync_loop_style(self):
        for child in self.children:
            if isinstance(child, discord.ui.Button) and str(child.emoji) == "🔁":
                child.style = discord.ButtonStyle.primary if self.cog.loop_enabled else discord.ButtonStyle.secondary

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Debe ser el mismo guild
        if not interaction.guild or not self.ctx.guild or interaction.guild.id != self.ctx.guild.id:
            return False

        vc = interaction.guild.voice_client
        if not vc or not vc.channel:
            try:
                await interaction.response.send_message("🚫 No estoy conectado a un canal de voz.", ephemeral=True)
            except Exception:
                pass
            return False

        # Usuario debe estar en el mismo canal de voz
        user_v = getattr(interaction.user, "voice", None)
        if not user_v or not user_v.channel or user_v.channel.id != vc.channel.id:
            try:
                await interaction.response.send_message(
                    "🎧 Debes estar en el **mismo canal de voz** que yo para usar estos botones.",
                    ephemeral=True
                )
            except Exception:
                pass
            return False

        return True

    async def refresh_panel(self):
        async with self._lock:
            if not self.cog.panel_msg or not self.cog.panel_data:
                return
            vc = self.ctx.voice_client
            paused = vc.is_paused() if vc else False

            self._sync_loop_style()
            embed = self.cog.build_now_playing_embed(self.ctx, paused=paused)

            try:
                await self.cog.panel_msg.edit(embed=embed, view=self)
            except Exception:
                pass

    # ---------------- Buttons ----------------

    @discord.ui.button(emoji="⏯️", style=discord.ButtonStyle.secondary, row=0)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        vc = interaction.guild.voice_client if interaction.guild else None
        if not vc:
            return
        if vc.is_paused():
            vc.resume()
        elif vc.is_playing():
            vc.pause()
        await self.refresh_panel()

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, row=0)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        vc = interaction.guild.voice_client if interaction.guild else None
        if vc:
            vc.stop()

    @discord.ui.button(emoji="🔁", style=discord.ButtonStyle.secondary, row=0)
    async def loop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        # toggle loop
        self.cog.loop_enabled = not self.cog.loop_enabled
        self._sync_loop_style()
        try:
            await interaction.response.edit_message(view=self)
        except Exception:
            # si ya hiciste defer o algo
            pass
        await self.refresh_panel()

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.secondary, row=0)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.cog.stop_all(self.ctx, leave_panel=True)

    @discord.ui.button(emoji="🔀", style=discord.ButtonStyle.secondary, row=0)
    async def shuffle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        if len(self.cog.song_queue) < 2:
            return
        random.shuffle(self.cog.song_queue)
        await self.refresh_panel()