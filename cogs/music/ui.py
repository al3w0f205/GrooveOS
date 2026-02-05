# cogs/music/services/ui.py
from __future__ import annotations
import discord

class ControlesMusica(discord.ui.View):
    def __init__(self, ctx, musica_cog):
        super().__init__(timeout=None)
        self.ctx = ctx
        self.musica = musica_cog

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.ctx.author:
            await interaction.response.send_message(
                "⚠️ Solo quien ejecutó el comando puede usar estos botones.",
                ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="⏯️ Pausa/Resume", style=discord.ButtonStyle.primary)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.ctx.voice_client
        if not vc:
            return await interaction.response.send_message("🚫 No estoy en voz.", ephemeral=True)

        if vc.is_paused():
            vc.resume()
        elif vc.is_playing():
            vc.pause()

        await interaction.response.defer()

    @discord.ui.button(label="⏭️ Skip", style=discord.ButtonStyle.secondary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = self.ctx.voice_client
        if vc and (vc.is_playing() or vc.is_paused()):
            vc.stop()
        await interaction.response.defer()

    @discord.ui.button(label="🔁 Loop", style=discord.ButtonStyle.secondary)
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = self.musica.state
        st.loop_enabled = not st.loop_enabled
        await interaction.response.send_message(
            f"🔁 Loop: {'✅ ON' if st.loop_enabled else '❌ OFF'}",
            ephemeral=True
        )

    @discord.ui.button(label="📻 Auto", style=discord.ButtonStyle.secondary)
    async def autoplay(self, interaction: discord.Interaction, button: discord.ui.Button):
        st = self.musica.state
        st.autoplay_enabled = not st.autoplay_enabled
        await interaction.response.send_message(
            f"📻 Autoplay: {'✅ ON' if st.autoplay_enabled else '❌ OFF'}",
            ephemeral=True
        )

    @discord.ui.button(label="⏹️ Stop", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.musica.player.stop_all(self.ctx, leave_panel=True)
        await interaction.response.defer()