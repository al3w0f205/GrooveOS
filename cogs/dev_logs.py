import discord
from discord.ext import commands, tasks
import aiosqlite
import aiohttp
import datetime

class DevLogs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        # --- CONFIGURACIÓN ---
        self.REPO_OWNER = "al3w0f205"  # Ejemplo: "Google"
        self.REPO_NAME = "GrooveOS"          # El nombre exacto del repo
        self.BRANCH = "main"                 # O "master", según uses
        self.CHANNEL_ID = 1473514396167831825 # ID del canal donde avisará
        # ---------------------
        
        self.last_commit_sha = None
        self.db_path = "dev_logs.db" # Base de datos pequeña para recordar el último commit

    async def cog_load(self):
        """Se ejecuta al cargar el cog. Inicia la DB y el bucle."""
        await self._init_db()
        self.check_commits.start()

    async def cog_unload(self):
        """Se ejecuta al descargar el cog. Detiene el bucle."""
        self.check_commits.cancel()

    async def _init_db(self):
        """Crea la tabla para guardar el último commit visto."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS github_logs (
                    repo_name TEXT PRIMARY KEY,
                    last_commit TEXT
                )
            """)
            await db.commit()
            
            # Cargar el último commit en memoria
            cursor = await db.execute("SELECT last_commit FROM github_logs WHERE repo_name = ?", (self.REPO_NAME,))
            row = await cursor.fetchone()
            if row:
                self.last_commit_sha = row[0]

    async def _save_last_commit(self, sha):
        """Guarda el nuevo commit en la DB."""
        self.last_commit_sha = sha
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO github_logs (repo_name, last_commit) 
                VALUES (?, ?)
            """, (self.REPO_NAME, sha))
            await db.commit()

    @tasks.loop(minutes=5)
    async def check_commits(self):
        """Revisa GitHub cada 5 minutos."""
        await self.bot.wait_until_ready()
        
        url = f"https://api.github.com/repos/{self.REPO_OWNER}/{self.REPO_NAME}/commits/{self.BRANCH}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status != 200:
                    print(f"[DevLogs] Error al conectar con GitHub: {response.status}")
                    return
                
                data = await response.json()
                latest_sha = data['sha']
                
                # Si es la primera vez que corre, solo guardamos sin notificar para evitar spam
                if self.last_commit_sha is None:
                    await self._save_last_commit(latest_sha)
                    return

                # Si hay un commit nuevo (SHA diferente)
                if latest_sha != self.last_commit_sha:
                    await self._post_update(data)
                    await self._save_last_commit(latest_sha)

    async def _post_update(self, commit_data):
        """Construye y envía el Embed al canal."""
        channel = self.bot.get_channel(self.CHANNEL_ID)
        if not channel:
            return

        commit_msg = commit_data['commit']['message']
        author_name = commit_data['commit']['author']['name']
        author_url = commit_data['author']['html_url'] if commit_data['author'] else ""
        avatar_url = commit_data['author']['avatar_url'] if commit_data['author'] else ""
        commit_url = commit_data['html_url']
        timestamp = commit_data['commit']['author']['date'] # Formato ISO

        # Convertir fecha a objeto datetime
        dt = datetime.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))

        embed = discord.Embed(
            title=f"🔨 Nueva Actualización: {self.REPO_NAME}",
            description=f"Se han detectado cambios en la rama `{self.BRANCH}`.",
            url=commit_url,
            color=discord.Color.brand_green(),
            timestamp=dt
        )
        
        embed.set_author(name=author_name, url=author_url, icon_url=avatar_url)
        embed.add_field(name="📝 Cambio:", value=f"```\n{commit_msg}\n```", inline=False)
        embed.set_footer(text=f"Commit: {commit_data['sha'][:7]}")

        await channel.send(embed=embed)

    @commands.command()
    @commands.is_owner()
    async def forzar_check(self, ctx):
        """Comando manual para forzar la revisión de actualizaciones."""
        await ctx.send("🔍 Verificando GitHub manualmente...")
        # Reiniciamos la tarea para que ejecute ahora
        self.check_commits.restart()

async def setup(bot):
    await bot.add_cog(DevLogs(bot))