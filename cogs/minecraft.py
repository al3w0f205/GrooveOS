import discord
from discord.ext import commands
import os
import requests
from proxmoxer import ProxmoxAPI
import urllib3
import asyncio

# --- CONFIGURACIÓN DE SEGURIDAD ---
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==========================================
# 🎨 CLASE DE INTERFAZ (BOTONES)
# ==========================================
class SimpleLauncher(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="🚀 Iniciar Servidor Survival", style=discord.ButtonStyle.green, emoji="🌲")
    async def start_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        for child in self.children: child.disabled = True
        await interaction.response.edit_message(view=self)
        
        # Llamamos a la lógica que está en el Cog
        await self.cog.start_logic_direct(interaction)
        
        for child in self.children: child.disabled = False

    @discord.ui.button(label="Estado Proxmox", style=discord.ButtonStyle.secondary, emoji="📊")
    async def status_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            status = self.cog.proxmox.nodes(self.cog.NODE_NAME).lxc(self.cog.CRAFTY_LXC_ID).status.current.get()
            await interaction.response.send_message(f"Info: LXC {self.cog.CRAFTY_LXC_ID} está **{status.get('status')}**", ephemeral=True)
        except:
            await interaction.response.send_message("❌ Sin conexión a Proxmox", ephemeral=True)

# ==========================================
# 🧠 MÓDULO DE MINECRAFT (COG)
# ==========================================
class Minecraft(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        # Cargamos credenciales del archivo .env
        self.PROX_SECRET = os.getenv('PROX_SECRET')
        self.CRAFTY_TOKEN = os.getenv('CRAFTY_TOKEN')
        
        # Configuración fija (se queda aquí)
        self.PROX_HOST = '192.168.100.218'
        self.PROX_USER = 'root@pam'
        self.PROX_TOKEN_ID = 'bot-discord'
        self.NODE_NAME = 'pve'
        self.CRAFTY_LXC_ID = 104 
        self.CRAFTY_URL = "https://192.168.100.220:8443" 
        self.SERVER_UUID = "30e9e767-7e85-4a3d-a8f3-a8868c189f83"

        # Conexión inicial a Proxmox
        self.proxmox = ProxmoxAPI(
            self.PROX_HOST, 
            user=self.PROX_USER, 
            token_name=self.PROX_TOKEN_ID, 
            token_value=self.PROX_SECRET, 
            verify_ssl=False
        )

    async def wait_for_crafty(self, message_to_edit):
        """Espera a que Crafty responda. Definida aquí para evitar errores de 'not defined'."""
        headers = {"Authorization": f"Bearer {self.CRAFTY_TOKEN}"}
        for i in range(30): 
            try:
                response = requests.get(f"{self.CRAFTY_URL}/api/v2/auth/verify", headers=headers, verify=False, timeout=3)
                if response.status_code == 200: return True
            except: pass
            
            if i % 3 == 0:
                try: await message_to_edit.edit(content=f"🔄 **Despertando a Crafty...** (Intento {i+1}/30)")
                except: pass
            await asyncio.sleep(3)
        return False

    async def start_logic_direct(self, interaction):
        """Secuencia de arranque directa."""
        msg = await interaction.followup.send("🚀 **Iniciando secuencia de arranque...**")

        try:
            status = self.proxmox.nodes(self.NODE_NAME).lxc(self.CRAFTY_LXC_ID).status.current.get()
            if status.get('status') == 'stopped':
                await msg.edit(content=f"🔌 **Fase 1:** Encendiendo Contenedor LXC {self.CRAFTY_LXC_ID}...")
                self.proxmox.nodes(self.NODE_NAME).lxc(self.CRAFTY_LXC_ID).status.start.post()
                await asyncio.sleep(5) 
            else:
                await msg.edit(content="⚡ **Fase 1:** Proxmox ya estaba activo.")
        except Exception as e:
            return await msg.edit(content=f"❌ Error Proxmox: {e}")

        is_ready = await self.wait_for_crafty(msg)
        if not is_ready:
            await msg.edit(content="⚠️ Crafty no respondió, intentando forzar inicio...")
        else:
            await msg.edit(content="🟢 **Fase 2:** Conexión establecida. Iniciando Minecraft...")

        try:
            url = f"{self.CRAFTY_URL}/api/v2/servers/{self.SERVER_UUID}/action/start_server"
            headers = {"Authorization": f"Bearer {self.CRAFTY_TOKEN}"}
            response = requests.post(url, headers=headers, verify=False, timeout=15)
            
            if response.status_code == 200:
                await msg.edit(content="✅ **¡ÉXITO TOTAL!**\nEl servidor **Survival** ha recibido la orden.")
            else:
                await msg.edit(content=f"⚠️ Error Crafty: {response.status_code}")
        except Exception as e:
            await msg.edit(content=f"❌ Error final: {e}")

    @commands.command(name="minecraft", aliases=['mc'])
    async def panel_mc(self, ctx):
        """Comando para desplegar el panel."""
        embed = discord.Embed(
            title="🎮 Centro de Control Minecraft", 
            description="Presiona para encender el servidor Survival.", 
            color=0x00ff00
        )
        view = SimpleLauncher(self)
        await ctx.send(embed=embed, view=view)

# Función obligatoria para cargar el Cog
async def setup(bot):
    await bot.add_cog(Minecraft(bot))
