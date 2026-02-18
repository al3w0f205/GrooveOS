import discord
from discord.ext import commands
from discord import app_commands
import os
import json
import asyncio
import re
import inspect
import unicodedata
import aiohttp
from difflib import SequenceMatcher
from typing import List, Tuple, Optional, Dict, Set
from groq import Groq

# =========================
# Utilidades de normalización y dedupe
# =========================

RE_PAREN = re.compile(r"\s*[\(\[][^)\]]{0,40}[\)\]]")   # (Live) [Official Video] etc.
RE_FEAT = re.compile(r"\s+(feat\.?|ft\.?)\s+", flags=re.I)

def _simplifica_texto(s: str) -> str:
    """Normaliza unicode, tildes y espacios para comparar."""
    if not s: return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("—", "-").replace("–", "-")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s

def _normaliza_separador(linea: str) -> str:
    linea = linea.replace("—", "-").replace("–", "-")
    linea = re.sub(r"\s*:\s*", " - ", linea)
    linea = re.sub(r"\s+", " ", linea).strip()
    return linea

def _clave_cancion(linea: str) -> Tuple[str, str]:
    linea = _simplifica_texto(linea)
    if " - " in linea:
        artista, titulo = linea.split(" - ", 1)
    else:
        artista, titulo = "", linea

    titulo = RE_FEAT.sub(" feat ", titulo)
    titulo_base = RE_PAREN.sub("", titulo).strip()
    return artista.strip(), titulo_base.strip()

def _parecido(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

def _dedupe_basico(canciones: List[str]) -> List[str]:
    vistos: Set[Tuple[str, str]] = set()
    resultado: List[str] = []
    for c in canciones:
        c_limpia = re.sub(r"\s+", " ", str(c)).strip()
        if not c_limpia:
            continue
        artista, titulo = _clave_cancion(c_limpia)
        clave = (artista, titulo)
        if clave in vistos:
            continue
        vistos.add(clave)
        resultado.append(c_limpia)
    return resultado

def _fuzzy_dedupe(canciones: List[str], umbral: float = 0.92) -> List[str]:
    resultado: List[str] = []
    claves_guardadas: List[Tuple[str, str]] = []
    for c in canciones:
        a, t = _clave_cancion(c)
        es_dup = any((a == a2 and _parecido(t, t2) >= umbral) for (a2, t2) in claves_guardadas)
        if not es_dup:
            resultado.append(c)
            claves_guardadas.append((a, t))
    return resultado

def _normaliza_artista(s: str) -> str:
    # Usamos _simplifica_texto para ser consistentes con la limpieza de acentos
    return _simplifica_texto(s)

# =========================
# Alias de artistas
# =========================

ALIAS_ARTISTAS: Dict[str, Set[str]] = {
    "feid": {"feid", "ferxxo"},
    "mora": {"mora"},
    "bad bunny": {"bad bunny", "benito"},
}

def _alias_set_para(artista: str) -> Tuple[str, Set[str]]:
    v = _normaliza_artista(artista)
    for canonical, aliases in ALIAS_ARTISTAS.items():
        if v == canonical or v in aliases:
            # Normalizamos también los aliases del diccionario para asegurar match
            norm_aliases = {_normaliza_artista(a) for a in aliases}
            return canonical, norm_aliases | {canonical}
    return v, {v}

# =========================
# Validaciones estrictas
# =========================

def _valida_formato_linea(linea: str) -> bool:
    if " - " not in linea:
        return False
    art, tit = linea.split(" - ", 1)
    return len(art.strip()) >= 1 and len(tit.strip()) >= 1

def _solo_artista_principal(linea: str, alias_validos: Set[str]) -> bool:
    """
    ACEPTA solo si uno de los artistas listados coincide EXACTAMENTE con los alias.
    Separa por 'feat', '&', ',', 'x' para analizar cada colaborador individualmente.
    """
    parts = linea.split(" - ", 1)
    if not parts:
        return False
    
    # Normalizamos el string completo del artista
    artist_full = _simplifica_texto(parts[0])
    
    # Reemplazamos todos los separadores posibles por uno único "||"
    # Ojo: el orden importa (primero los más largos)
    separadores = [" feat. ", " feat ", " ft. ", " ft ", " & ", " , ", ", ", " x ", " / "]
    
    temp_artist = artist_full
    for sep in separadores:
        temp_artist = temp_artist.replace(sep, "||")
    
    # Dividimos en una lista de sub-artistas
    sub_artistas = [s.strip() for s in temp_artist.split("||") if s.strip()]
    
    # Verificamos si ALGUNO de los sub-artistas es exactamente uno de los alias
    for sub in sub_artistas:
        if sub in alias_validos:
            return True
            
    return False

def _filtra_por_artista_estricto(canciones: List[str], alias_validos: Set[str]) -> Tuple[List[str], int]:
    filtradas = []
    descartadas = 0
    for original in canciones:
        c = _normaliza_separador(original)
        if " - " not in c:
            descartadas += 1
            continue
        if not _valida_formato_linea(c):
            descartadas += 1
            continue
        if not _solo_artista_principal(c, alias_validos):
            descartadas += 1
            # Debug opcional: ver qué se está descartando
            # print(f"Descartada por artista: {c}") 
            continue
        filtradas.append(c)
    return filtradas, descartadas


# =========================
# Cog principal
# =========================

class IAMusica(commands.Cog):
    """
    Crea playlists buscando DATOS REALES en internet (API Deezer)
    y usa lógica estricta para asegurar que correspondan al artista.
    """

    def __init__(self, bot):
        self.bot = bot
        api_key = os.getenv("GROQ_API_KEY") or os.getenv("API_Musica_IA")
        if api_key:
            self.client = Groq(api_key=api_key.strip())
            self.model = "llama-3.3-70b-versatile"
        else:
            self.client = None
            
        self._cola_keys_por_guild: Dict[int, Set[Tuple[str, str]]] = {}

    # ------------ helpers de sesión ------------

    def _get_guild_set(self, guild_id: int) -> Set[Tuple[str, str]]:
        if guild_id not in self._cola_keys_por_guild:
            self._cola_keys_por_guild[guild_id] = set()
        return self._cola_keys_por_guild[guild_id]

    async def _is_slash(self, ctx) -> bool:
        return getattr(ctx, "interaction", None) is not None

    # ------------ BÚSQUEDA EN INTERNET (DEEZER API) ------------

    async def _buscar_en_deezer(self, artista_busqueda: str, cantidad_objetivo: int) -> List[str]:
        """
        Consulta la API pública de Deezer.
        """
        # Pedimos bastantes para tener de sobra tras filtrar
        limite_api = min(cantidad_objetivo * 4, 100) 
        # Usamos comillas dobles en la query de la API para intentar ser más exactos desde el origen
        url = f"https://api.deezer.com/search?q=artist:\"{artista_busqueda}\"&order=RANKING&limit={limite_api}"
        
        canciones_raw = []
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'data' in data:
                            for track in data['data']:
                                nombre_artista = track['artist']['name']
                                titulo_cancion = track['title']
                                linea = f"{nombre_artista} - {titulo_cancion}"
                                canciones_raw.append(linea)
                    else:
                        print(f"[API] Error conectando a Deezer: {response.status}")
        except Exception as e:
            print(f"[API] Excepción buscando en Deezer: {e}")
        
        return canciones_raw

    async def generar_playlist(self, artista: str, cantidad: int = 30) -> Tuple[List[str], int]:
        cantidad = max(1, min(int(cantidad), 50))
        canonical, alias_validos = _alias_set_para(artista)

        # 1. Búsqueda
        crudas = await self._buscar_en_deezer(canonical, cantidad)
        
        if not crudas:
            # Fallback sin canonical si falla
            crudas = await self._buscar_en_deezer(artista, cantidad)

        # 2. Dedup básico
        crudas = _dedupe_basico([_normaliza_separador(c) for c in crudas])

        # 3. Filtrado ESTRICTO mejorado
        depuradas, descartadas = _filtra_por_artista_estricto(crudas, alias_validos)

        # 4. Fuzzy-dedupe
        depuradas = _fuzzy_dedupe(depuradas, umbral=0.92)
        
        if len(depuradas) > cantidad:
            depuradas = depuradas[:cantidad]

        return depuradas, descartadas

    # ------------ util para armar embeds ------------

    def _embeds_para_lista(self, titulo: str, canciones: List[str], descartadas: int) -> List[discord.Embed]:
        embeds: List[discord.Embed] = []
        desc = "Añadiendo a la cola…"
        if descartadas:
            desc += f"\n🔒 Filtrado estricto: **{descartadas}** descartadas (otros artistas)."

        embed = discord.Embed(
            title=f"💿 Playlist Real: {titulo}",
            description=desc,
            color=discord.Color.green()
        )

        buffer = []
        char_count = 0
        idx = 0

        def _flush():
            nonlocal embed, embeds, buffer, char_count, idx
            if not buffer:
                return
            idx_ini = idx - len(buffer) + 1
            idx_fin = idx
            valor = "\n".join(buffer)
            embed.add_field(
                name=f"Canciones {idx_ini}–{idx_fin}",
                value=valor,
                inline=False
            )
            buffer = []
            char_count = 0

        for i, c in enumerate(canciones, start=1):
            linea = f"🎵 {c}"
            if (char_count + len(linea) + 1) > 1000 or len(buffer) >= 15:
                _flush()
            buffer.append(linea)
            char_count += len(linea) + 1
            idx = i

        _flush()
        embed.set_footer(text=f"Fuente: Deezer API | Verificado")
        embeds.append(embed)
        return embeds

    # ------------ localizar parámetro de play ------------

    def _resolver_param_play(self, play_cmd: commands.Command) -> Optional[str]:
        try:
            sig = inspect.signature(play_cmd.callback)
            for p in sig.parameters.keys():
                if p not in ("self", "ctx", "interaction"):
                    return p
        except Exception:
            return None
        return None

    # ------------ comando principal ------------

    @commands.hybrid_command(
        name="dj",
        description="Crea una playlist 100% REAL buscando en internet (Deezer)."
    )
    @app_commands.describe(
        artista="Nombre del ARTISTA (ej: 'Feid', 'Bad Bunny', 'Alejandro Sanz')",
        cantidad="¿Cuántas canciones? (1–50, por defecto 30)"
    )
    async def dj(self, ctx: commands.Context, *, artista: str, cantidad: int = 30):
        # 0) Validaciones
        if not isinstance(artista, str) or len(artista.strip()) < 2:
            return await ctx.send("❌ Especifica un ARTISTA válido (mínimo 2 caracteres).")

        cantidad = max(1, min(int(cantidad), 50))
        canonical, alias_validos = _alias_set_para(artista)

        # 1) Voz
        if not getattr(ctx.author, "voice", None):
            msg = "❌ ¡Entra a un canal de voz primero!"
            if await self._is_slash(ctx):
                return await ctx.interaction.response.send_message(msg, ephemeral=True)
            else:
                return await ctx.send(msg)

        # 2) Defer
        if await self._is_slash(ctx):
            await ctx.defer(ephemeral=False)
            msg_inicial = await ctx.followup.send(
                embed=discord.Embed(
                    description=f"🌍 Buscando éxitos verificados de **'{canonical}'**...",
                    color=discord.Color.blue()
                )
            )
        else:
            msg_inicial = await ctx.send(
                embed=discord.Embed(
                    description=f"🌍 Buscando éxitos verificados de **'{canonical}'**...",
                    color=discord.Color.blue()
                )
            )

        # 3) Generación
        canciones, descartadas = await self.generar_playlist(canonical, cantidad=cantidad)
        
        if not canciones:
            return await msg_inicial.edit(
                content=f"⚠️ No encontré canciones exactas de **{canonical}**. Intenta ser más específico.",
                embed=None
            )

        # 4) Dedup sesión
        gset = self._get_guild_set(ctx.guild.id)
        canciones_sin_sesion = []
        saltadas = 0
        for c in canciones:
            a, t = _clave_cancion(c)
            clave = (a, t)
            if clave in gset:
                saltadas += 1
                continue
            gset.add(clave)
            canciones_sin_sesion.append(c)

        if not canciones_sin_sesion:
            canciones_sin_sesion = canciones

        # 5) Embeds
        embeds = self._embeds_para_lista(canonical, canciones_sin_sesion, descartadas)
        await msg_inicial.edit(embed=embeds[0])
        for extra in embeds[1:]:
            await ctx.send(embed=extra)

        # 6) Encolar
        play_cmd = self.bot.get_command('play')
        if not play_cmd:
            aviso = "❌ Error: No encuentro el comando `.play`."
            if await self._is_slash(ctx):
                await ctx.followup.send(aviso)
            else:
                await ctx.send(aviso)
            return

        arg_name = self._resolver_param_play(play_cmd) or "query"

        errores = 0
        encoladas = 0
        for cancion in canciones_sin_sesion:
            try:
                art_norm, tit_norm = _clave_cancion(cancion)
                query = f"{art_norm} - {tit_norm} audio" 
                kwargs = {arg_name: query}
                
                await ctx.invoke(play_cmd, **kwargs)
                encoladas += 1
                await asyncio.sleep(1.5)
            except Exception as e:
                print(f"Error al encolar {cancion}: {e}")
                errores += 1

        # 7) Final
        if errores == len(canciones_sin_sesion):
            msg_fail = "❌ Hubo un fallo total al intentar reproducir."
            if await self._is_slash(ctx):
                await ctx.followup.send(msg_fail)
            else:
                await ctx.send(msg_fail)
        else:
            resumen = f"✅ **{encoladas}** canciones agregadas."
            if saltadas:
                resumen += f" (Omitidas por repetidas: {saltadas})"
            await ctx.send(resumen)

    @commands.hybrid_command(name="djclear")
    async def djclear(self, ctx: commands.Context):
        self._cola_keys_por_guild.pop(ctx.guild.id, None)
        await ctx.send("🧹 Registro de duplicados limpiado.")

async def setup(bot):
    await bot.add_cog(IAMusica(bot))