import discord
from discord.ext import commands
from discord import app_commands
import os
import json
import asyncio
import re
import inspect
import unicodedata
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
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("—", "-").replace("–", "-")
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s

def _normaliza_separador(linea: str) -> str:
    """
    Reemplaza separadores raros por ' - ' de forma conservadora.
    No usa esto para 'arreglar' líneas con artista erróneo.
    """
    # normalizamos espacios y guiones unicode
    linea = linea.replace("—", "-").replace("–", "-")
    # sustituye ' : ' por ' - ' (básico); la validación estricta decidirá si se acepta o no
    linea = re.sub(r"\s*:\s*", " - ", linea)
    # colapsa espacios
    linea = re.sub(r"\s+", " ", linea).strip()
    return linea

def _clave_cancion(linea: str) -> Tuple[str, str]:
    """
    Espera 'Artista - Título'. Devuelve (artista_norm, titulo_norm) sin adornos.
    Maneja entradas mal formateadas con fallback.
    """
    linea = _simplifica_texto(linea)
    if " - " in linea:
        artista, titulo = linea.split(" - ", 1)
    else:
        artista, titulo = "", linea

    # Normaliza 'feat/ft' a ' feat ' y elimina paréntesis/corchetes
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
    """Elimina casi-duplicados para el mismo artista."""
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
    return re.sub(r"\s+", " ", s.strip().lower())


# =========================
# Alias de artistas (extiende aquí lo que necesites)
# =========================

ALIAS_ARTISTAS: Dict[str, Set[str]] = {
    "feid": {"feid", "ferxxo"},
    # "bad bunny": {"bad bunny", "san benito"},
    # "alejandro sanz": {"alejandro sanz"},
}

def _alias_set_para(artista: str) -> Tuple[str, Set[str]]:
    """
    Devuelve (canonical, alias_set). Si no hay canonical conocido, usa el nombre normalizado.
    """
    v = _normaliza_artista(artista)
    for canonical, aliases in ALIAS_ARTISTAS.items():
        if v == canonical or v in aliases:
            return canonical, set(aliases) | {canonical}
    return v, {v}


# =========================
# Validaciones estrictas por artista
# =========================

def _valida_formato_linea(linea: str) -> bool:
    # Debe contener " - " y ambos lados con longitud mínima
    if " - " not in linea:
        return False
    art, tit = linea.split(" - ", 1)
    return len(art.strip()) >= 2 and len(tit.strip()) >= 2

def _solo_artista_principal(linea: str, alias_validos: Set[str]) -> bool:
    """
    ACEPTA solo si el "artista principal" (antes de ' - ') coincide EXACTO con los alias válidos.
    Rechaza si viene 'artista1 & artista2', 'artista x artista', ',', ';', ' feat ', ' ft ' en el campo artista.
    """
    artist_raw = linea.split(" - ", 1)[0].strip().lower()

    # Rechazo si el campo de artista trae separadores de múltiple artista
    if any(sep in artist_raw for sep in ["&", " x ", ",", ";", " feat ", " ft "]):
        return False

    return artist_raw in alias_validos

def _filtra_por_artista_estricto(canciones: List[str], alias_validos: Set[str]) -> Tuple[List[str], int]:
    """
    Devuelve (filtradas, descartadas).
    - Normaliza separadores.
    - Exige formato y artista exacto.
    """
    filtradas = []
    descartadas = 0

    for original in canciones:
        c = _normaliza_separador(original)

        # Si no hay ' - ', descarta
        if " - " not in c:
            descartadas += 1
            print(f"[DJ] DESCARTADA (sin separador válido): {original}")
            continue

        # Validación de formato mínimo
        if not _valida_formato_linea(c):
            descartadas += 1
            print(f"[DJ] DESCARTADA (formato inválido): {original}")
            continue

        # Artista exacto (alias)
        if not _solo_artista_principal(c, alias_validos):
            descartadas += 1
            print(f"[DJ] DESCARTADA (artista distinto a alias): {original}")
            continue

        filtradas.append(c)

    return filtradas, descartadas


# =========================
# Cog principal
# =========================

class IAMusica(commands.Cog):
    """
    Crea playlists con Groq, modo ARTISTA ESTRICTO:
      - JSON estricto {"artista": "...", "canciones": ["Artista - Título", ...]}
      - Filtrado por artista principal exacto + dedupe
      - Reintento con prompt ultra-estricto si no alcanza la cantidad pedida
    """

    def __init__(self, bot):
        self.bot = bot
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            print("⚠️ ADVERTENCIA: No se encontró GROQ_API_KEY. El módulo IA_Musica no funcionará.")
            self.client = None
        else:
            self.client = Groq(api_key=api_key)
            self.model = "llama-3.3-70b-versatile"

        # Dedup por sesión (por servidor)
        self._cola_keys_por_guild: Dict[int, Set[Tuple[str, str]]] = {}

    # ------------ helpers de sesión ------------

    def _get_guild_set(self, guild_id: int) -> Set[Tuple[str, str]]:
        if guild_id not in self._cola_keys_por_guild:
            self._cola_keys_por_guild[guild_id] = set()
        return self._cola_keys_por_guild[guild_id]

    async def _is_slash(self, ctx) -> bool:
        return getattr(ctx, "interaction", None) is not None

    # ------------ parseo JSON ------------

    def _extraer_json_objeto(self, contenido: str) -> Optional[dict]:
        """
        Espera objeto {"artista": "...", "canciones": ["Artista - Título", ...]}.
        Si no, intenta rescatar un array bajo la clave 'canciones'.
        """
        contenido = contenido.replace("```json", "").replace("```", "").strip()
        try:
            data = json.loads(contenido)
            if isinstance(data, dict):
                if "canciones" in data and isinstance(data["canciones"], list):
                    # artista puede venir None si no lo envió
                    if "artista" in data and data["artista"] is not None:
                        data["artista"] = str(data["artista"])
                    return data
        except Exception:
            pass

        # Fallback: si vino un array plano, lo adaptamos
        try:
            arr = json.loads(contenido)
            if isinstance(arr, list):
                return {"artista": None, "canciones": [str(x) for x in arr]}
        except Exception:
            pass

        # Último recurso: capturar primer [...]
        m = re.search(r"\[.*?\]", contenido, flags=re.S)
        if m:
            try:
                arr = json.loads(m.group(0))
                if isinstance(arr, list):
                    return {"artista": None, "canciones": [str(x) for x in arr]}
            except Exception:
                return None
        return None

    # ------------ IA ------------

    async def _llamar_groq(self, messages, max_tokens: int = 1500) -> str:
        """Llama al endpoint; si falla JSON mode, reintenta sin él."""
        if not self.client:
            raise RuntimeError("Groq client no inicializado")

        try:
            completion = await asyncio.to_thread(
                self.client.chat.completions.create,
                messages=messages,
                model=self.model,
                temperature=0.12,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            return completion.choices[0].message.content.strip()
        except Exception as e:
            print(f"[Groq] Aviso: reintento sin response_format por error: {e}")
            completion = await asyncio.to_thread(
                self.client.chat.completions.create,
                messages=messages,
                model=self.model,
                temperature=0.12,
                max_tokens=max_tokens,
            )
            return completion.choices[0].message.content.strip()

    async def _consultar_artist_strict(self, artista_usuario: str, cantidad: int, intento: int, alias_validos: Set[str]) -> dict:
        """
        Construye prompts estrictos por ARTISTA y devuelve el objeto JSON parseado (o {}).
        """
        canonical, alias_set = _alias_set_para(artista_usuario)
        alias_texto = ", ".join(sorted(alias_validos))

        sistema = (
            "Eres un generador de listas de reproducción. DEVUELVES SOLO JSON válido.\n"
            "MODO: ARTISTA ESTRICTO.\n"
            f"- Devuelve EXACTAMENTE {cantidad} canciones.\n"
            "- TODAS las canciones deben tener como artista principal el artista indicado.\n"
            "- Formato exacto de cada elemento: \"Artista Principal - Título\".\n"
            "- El campo de artista principal NO puede contener '&', 'x', ',', ';', 'feat', 'ft'.\n"
            "- 'feat/ft' puede ir en el TÍTULO si aplica.\n"
            "- NO respondas con nada fuera del JSON.\n"
            'Estructura JSON: {"artista": "NOMBRE EXACTO DEL ARTISTA", "canciones": ["Artista - Título", ...]}\n'
        )

        if intento == 1:
            usuario = (
                f"Artista objetivo: '{artista_usuario}'. "
                f"Alias aceptados (artista principal exacto): {alias_texto}. "
                f"Devuelve la lista ahora."
            )
        else:
            usuario = (
                f"REINTENTO ESTRICTO.\n"
                f"Artista objetivo: '{artista_usuario}'. "
                f"Alias aceptados: {alias_texto}.\n"
                "PROHIBIDO (ejemplos): "
                "\"Nicky Jam - Ferxxo 105\", \"ATEEZ - Guerrilla\", "
                "\"Artista1 & Artista2 - ...\", \"Artista1 x Artista2 - ...\".\n"
                "Devuelve SOLO canciones cuyo artista principal sea EXACTAMENTE uno de los alias aceptados."
            )

        contenido = await self._llamar_groq(
            messages=[{"role": "system", "content": sistema},
                      {"role": "user", "content": usuario}],
            max_tokens=1800
        )
        data = self._extraer_json_objeto(contenido) or {}
        return data

    async def generar_playlist(self, artista: str, cantidad: int = 30) -> Tuple[List[str], int]:
        """
        Genera una lista por ARTISTA ESTRICTO.
        Devuelve (canciones_filtradas, descartadas_por_artista).
        """
        if not self.client:
            return [], 0

        cantidad = max(1, min(int(cantidad), 50))  # seguridad
        canonical, alias_validos = _alias_set_para(artista)

        # --- Primer intento ---
        data = await self._consultar_artist_strict(canonical, cantidad, intento=1, alias_validos=alias_validos)
        crudas = [str(x) for x in (data.get("canciones") or [])]

        # 1) Dedup básico y normalización previa
        crudas = _dedupe_basico([_normaliza_separador(c) for c in crudas])

        # 2) Filtrado por artista principal exacto
        depuradas, descartadas = _filtra_por_artista_estricto(crudas, alias_validos)

        # 3) Fuzzy-dedupe y recorte
        depuradas = _fuzzy_dedupe(depuradas, umbral=0.92)
        if len(depuradas) > cantidad:
            depuradas = depuradas[:cantidad]

        # --- Reintento si faltan ---
        if len(depuradas) < cantidad:
            faltan = cantidad - len(depuradas)
            print(f"[DJ] Faltan {faltan} temas tras filtro estricto. Reintentando…")
            data2 = await self._consultar_artist_strict(canonical, faltan, intento=2, alias_validos=alias_validos)
            nuevas = [str(x) for x in (data2.get("canciones") or [])]
            nuevas = _dedupe_basico([_normaliza_separador(c) for c in nuevas])
            nuevas, desc2 = _filtra_por_artista_estricto(nuevas, alias_validos)
            descartadas += desc2
            nuevas = _fuzzy_dedupe(nuevas, umbral=0.92)
            unidas = _dedupe_basico(depuradas + nuevas)
            unidas = _fuzzy_dedupe(unidas, umbral=0.92)
            if len(unidas) > cantidad:
                unidas = unidas[:cantidad]
            depuradas = unidas

        return depuradas, descartadas

    # ------------ util para armar embeds ------------

    def _embeds_para_lista(self, titulo: str, canciones: List[str], descartadas: int) -> List[discord.Embed]:
        """
        Crea uno o más embeds con la lista completa (sin cortar campos).
        """
        embeds: List[discord.Embed] = []
        desc = "Añadiendo a la cola…"
        if descartadas:
            desc += f"\n🔒 Estricto por artista: **{descartadas}** descartadas."

        embed = discord.Embed(
            title=f"💿 Playlist: {titulo}",
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
        embed.set_footer(text=f"Generado con {self.model}")
        embeds.append(embed)
        return embeds

    # ------------ localizar parámetro de play ------------

    def _resolver_param_play(self, play_cmd: commands.Command) -> Optional[str]:
        """
        Detecta el primer parámetro útil del comando play,
        ignorando 'self', 'ctx' (o 'interaction').
        """
        try:
            sig = inspect.signature(play_cmd.callback)
            for p in sig.parameters.keys():
                if p not in ("self", "ctx", "interaction"):
                    return p
        except Exception as e:
            print(f"⚠️ No se pudo inspeccionar la firma de play: {e}")
        return None

    # ------------ comando principal ------------

    @commands.hybrid_command(
        name="dj",
        description="Crea una playlist por ARTISTA (estricto) con IA (Groq)."
    )
    @app_commands.describe(
        artista="Nombre del ARTISTA (ej: 'Feid', 'Bad Bunny', 'Alejandro Sanz')",
        cantidad="¿Cuántas canciones? (1–50, por defecto 30)"
    )
    async def dj(self, ctx: commands.Context, *, artista: str, cantidad: int = 30):
        # 0) Validaciones simples
        if not isinstance(artista, str) or len(artista.strip()) < 2:
            return await ctx.send("❌ Especifica un ARTISTA válido (mínimo 2 caracteres).")

        cantidad = max(1, min(int(cantidad), 50))
        canonical, alias_validos = _alias_set_para(artista)

        # 1) Verificación de voz
        if not getattr(ctx.author, "voice", None):
            if await self._is_slash(ctx):
                return await ctx.interaction.response.send_message(
                    "❌ ¡Entra a un canal de voz primero!", ephemeral=True
                )
            else:
                return await ctx.send("❌ ¡Entra a un canal de voz primero!")

        # 2) Defer / mensaje inicial
        if await self._is_slash(ctx):
            await ctx.defer(ephemeral=False)
            msg_inicial = await ctx.followup.send(
                embed=discord.Embed(
                    description=f"🎧 **DJ GrooveOS** está preparando *{cantidad}* temas de *'{canonical}'*…",
                    color=discord.Color.purple()
                )
            )
        else:
            msg_inicial = await ctx.send(
                embed=discord.Embed(
                    description=f"🎧 **DJ GrooveOS** está preparando *{cantidad}* temas de *'{canonical}'*…",
                    color=discord.Color.purple()
                )
            )

        # 3) Generación IA (estricta por artista)
        canciones, descartadas = await self.generar_playlist(canonical, cantidad=cantidad)
        if not canciones:
            return await msg_inicial.edit(
                content="⚠️ No se pudo generar una lista estricta por artista. Intenta con el nombre exacto o añade alias.",
                embed=None
            )

        # 4) Dedup por sesión (no re-encolar en este guild lo que ya está en la sesión)
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
            canciones_sin_sesion = canciones  # fallback, aunque serán repetidas en sesión

        # 5) Embeds
        embeds = self._embeds_para_lista(canonical, canciones_sin_sesion, descartadas)
        await msg_inicial.edit(embed=embeds[0])
        for extra in embeds[1:]:
            await ctx.send(embed=extra)

        # 6) Encolar canciones automáticamente (forzando el artista en el query)
        play_cmd = self.bot.get_command('play')
        if not play_cmd:
            aviso = ("❌ Error técnico: No encuentro el comando `.play` como comando de texto/híbrido.\n"
                     "Asegúrate de que `play` sea `@commands.hybrid_command` o `@commands.command`.")
            if await self._is_slash(ctx):
                await ctx.followup.send(aviso)
            else:
                await ctx.send(aviso)
            return

        arg_name = self._resolver_param_play(play_cmd)
        if not arg_name:
            msg = "❌ No pude determinar el parámetro del comando `play` (busqueda/query/song/url)."
            if await self._is_slash(ctx):
                await ctx.followup.send(msg)
            else:
                await ctx.send(msg)
            return

        errores = 0
        encoladas = 0
        for cancion in canciones_sin_sesion:
            try:
                # Fuerza el "artista - título" para la búsqueda
                art_norm, tit_norm = _clave_cancion(cancion)
                query = f"{canonical} - {tit_norm}"  # ← se impone el artista
                kwargs = {arg_name: query}
                await ctx.invoke(play_cmd, **kwargs)
                encoladas += 1
                await asyncio.sleep(2)  # rate-limit básico
            except Exception as e:
                print(f"Error al encolar {cancion}: {e}")
                errores += 1

        # 7) Reporte final
        if errores == len(canciones_sin_sesion):
            if await self._is_slash(ctx):
                await ctx.followup.send("❌ Hubo un fallo total al intentar reproducir las canciones.")
            else:
                await ctx.send("❌ Hubo un fallo total al intentar reproducir las canciones.")
        else:
            resumen = f"✅ Encoladas: **{encoladas}**"
            if saltadas:
                resumen += f" · 🔁 Omitidas por repetidas en esta sesión: **{saltadas}**"
            if descartadas:
                resumen += f" · 🔒 Descartadas por artista: **{descartadas}**"
            await ctx.send(resumen)

    # (Opcional) Limpia el dedupe de la sesión manualmente
    @commands.hybrid_command(
        name="djclear",
        description="Limpia el registro de duplicados de la sesión de DJ en este servidor."
    )
    async def djclear(self, ctx: commands.Context):
        self._cola_keys_por_guild.pop(ctx.guild.id, None)
        await ctx.send("🧹 Registro de duplicados limpiado para este servidor.")


async def setup(bot):
    await bot.add_cog(IAMusica(bot))