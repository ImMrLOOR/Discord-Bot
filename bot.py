import discord
from discord.ext import commands
from google import genai
import asyncio
import logging
import asyncpg
import os
import random
from datetime import datetime
from collections import deque
from pytubefix import YouTube, Search, Playlist

from dotenv import load_dotenv
load_dotenv()

# =========================================
# CONFIG
# =========================================

DISCORD_TOKEN   = os.getenv("DISCORD_TOKEN", "")
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")

if not DISCORD_TOKEN or not GEMINI_API_KEY:
    raise EnvironmentError(
        "Faltan variables de entorno. Crea un archivo .env con:\n"
        "DISCORD_TOKEN=tu_token\n"
        "GEMINI_API_KEY=tu_api_key"
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("NationBot")

ai_client   = genai.Client(api_key=GEMINI_API_KEY)
AI_MODEL    = "gemini-2.0-flash"
ai_sessions = {}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

# =========================================
# PYTUBEFIX HELPERS
# =========================================

def get_audio_url(url: str) -> tuple[str, dict]:
    yt = YouTube(url)
    stream = yt.streams.filter(only_audio=True).order_by("abr").last()
    if not stream:
        raise Exception("No se encontró stream de audio.")
    return stream.url, {
        "title":     yt.title,
        "url":       url,
        "duration":  yt.length,
        "thumbnail": yt.thumbnail_url,
    }

def search_youtube(query: str) -> dict:
    results = Search(query).videos
    if not results:
        raise Exception("No se encontraron resultados.")
    video = results[0]
    return {
        "title":     video.title,
        "url":       video.watch_url,
        "duration":  video.length,
        "thumbnail": video.thumbnail_url,
    }

def get_playlist_entries(url: str) -> tuple[list[dict], str]:
    pl = Playlist(url)
    entries = []
    for video in pl.videos:
        entries.append({
            "title":     video.title,
            "url":       video.watch_url,
            "duration":  video.length,
            "thumbnail": video.thumbnail_url,
        })
    return entries, pl.title

def format_duration(seconds: int) -> str:
    if not seconds:
        return "??:??"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02}:{s:02}"
    return f"{m}:{s:02}"


# =========================================
# ESTADO POR SERVIDOR
# =========================================

class GuildPlayer:
    def __init__(self):
        self.queue:      deque     = deque()
        self.current:    dict|None = None
        self.volume:     float     = 0.5
        self.volume_pct: int       = 50
        self.loop_mode:  str       = "off"

guild_players: dict[int, GuildPlayer] = {}

def get_guild_player(guild_id: int) -> GuildPlayer:
    if guild_id not in guild_players:
        guild_players[guild_id] = GuildPlayer()
    return guild_players[guild_id]


# =========================================
# BASE DE DATOS
# =========================================

class Database:
    def __init__(self):
        self.db = None

    async def connect(self):
        db_url = os.getenv("DATABASE_URL", "").replace("postgres://", "postgresql://")
        logger.info(f"Conectando a: {db_url[:30]}...")
        self.db = await asyncpg.create_pool(db_url)
        await self.db.execute("""
            CREATE TABLE IF NOT EXISTS playlists (
                id         SERIAL PRIMARY KEY,
                user_id    BIGINT NOT NULL,
                name       TEXT   NOT NULL DEFAULT 'Mis Favoritos',
                created_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(user_id, name)
            );
            CREATE TABLE IF NOT EXISTS playlist_songs (
                id          SERIAL PRIMARY KEY,
                playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                title       TEXT    NOT NULL,
                url         TEXT,
                position    INTEGER NOT NULL DEFAULT 0,
                added_at    TIMESTAMP DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS stats (
                guild_id     BIGINT PRIMARY KEY,
                songs_played INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS dj_roles (
                guild_id BIGINT PRIMARY KEY,
                role_id  BIGINT
            );
        """)
        logger.info("Base de datos lista.")

    # ── Helpers internos ──────────────────────────────────────────────────────

    async def _get_or_create_playlist(self, user_id: int, name: str = "Mis Favoritos") -> int:
        await self.db.execute(
            "INSERT INTO playlists(user_id, name) VALUES($1, $2) ON CONFLICT DO NOTHING",
            user_id, name,
        )
        row = await self.db.fetchrow(
            "SELECT id FROM playlists WHERE user_id=$1 AND name=$2", user_id, name
        )
        return row["id"]

    # ── Favoritos / Playlist ──────────────────────────────────────────────────

    async def favadd(self, user_id: int, title: str, url: str | None = None, playlist: str = "Mis Favoritos") -> int:
        playlist_id = await self._get_or_create_playlist(user_id, playlist)
        next_pos = await self.db.fetchval(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM playlist_songs WHERE playlist_id=$1",
            playlist_id,
        )
        await self.db.execute(
            "INSERT INTO playlist_songs(playlist_id, title, url, position) VALUES($1,$2,$3,$4)",
            playlist_id, title, url, next_pos,
        )
        return next_pos

    async def favlist(self, user_id: int, playlist: str = "Mis Favoritos") -> list[dict]:
        playlist_id = await self._get_or_create_playlist(user_id, playlist)
        rows = await self.db.fetch(
            "SELECT position, title, url FROM playlist_songs WHERE playlist_id=$1 ORDER BY position",
            playlist_id,
        )
        return [dict(r) for r in rows]

    async def favremove(self, user_id: int, title: str, playlist: str = "Mis Favoritos") -> bool:
        playlist_id = await self._get_or_create_playlist(user_id, playlist)
        result = await self.db.execute(
            "DELETE FROM playlist_songs WHERE playlist_id=$1 AND lower(title)=lower($2)",
            playlist_id, title,
        )
        return result != "DELETE 0"

    async def favplay(self, user_id: int, position: int, playlist: str = "Mis Favoritos") -> dict | None:
        playlist_id = await self._get_or_create_playlist(user_id, playlist)
        row = await self.db.fetchrow(
            "SELECT title, url FROM playlist_songs WHERE playlist_id=$1 AND position=$2",
            playlist_id, position,
        )
        return dict(row) if row else None

    # ── Stats ─────────────────────────────────────────────────────────────────

    async def add_stat(self, guild_id: int):
        await self.db.execute(
            "INSERT INTO stats(guild_id, songs_played) VALUES($1, 1) "
            "ON CONFLICT(guild_id) DO UPDATE SET songs_played = stats.songs_played + 1",
            guild_id,
        )

    async def get_stats(self, guild_id: int) -> int:
        row = await self.db.fetchrow(
            "SELECT songs_played FROM stats WHERE guild_id=$1", guild_id
        )
        return row["songs_played"] if row else 0

    # ── DJ Role ───────────────────────────────────────────────────────────────

    async def set_dj_role(self, guild_id: int, role_id: int):
        await self.db.execute(
            "INSERT INTO dj_roles VALUES($1,$2) ON CONFLICT(guild_id) DO UPDATE SET role_id=$3",
            guild_id, role_id, role_id,
        )

    async def get_dj_role(self, guild_id: int) -> int | None:
        row = await self.db.fetchrow(
            "SELECT role_id FROM dj_roles WHERE guild_id=$1", guild_id
        )
        return row["role_id"] if row else None

db = Database()


# =========================================
# CHECKS
# =========================================

async def check_voice(ctx) -> bool:
    if not ctx.author.voice:
        await ctx.send("❌ Debes estar en un canal de voz.")
        return False
    return True

async def check_dj(ctx) -> bool:
    if ctx.author.guild_permissions.administrator:
        return True
    role_id = await db.get_dj_role(ctx.guild.id)
    if role_id and any(r.id == role_id for r in ctx.author.roles):
        return True
    await ctx.send("❌ Necesitas el rol DJ para esto.")
    return False

async def ensure_connected(ctx) -> discord.VoiceClient | None:
    if not await check_voice(ctx):
        return None
    vc: discord.VoiceClient = ctx.guild.voice_client
    if not vc:
        try:
            vc = await ctx.author.voice.channel.connect()
        except Exception as e:
            await ctx.send(f"❌ No pude conectarme: {e}")
            return None
    return vc


# =========================================
# REPRODUCCIÓN INTERNA
# =========================================

async def play_next(ctx, vc: discord.VoiceClient):
    gp = get_guild_player(ctx.guild.id)

    if gp.loop_mode == "track" and gp.current:
        gp.queue.appendleft(gp.current)
    elif gp.loop_mode == "queue" and gp.current:
        gp.queue.append(gp.current)

    if not gp.queue:
        gp.current = None
        return

    entry = gp.queue.popleft()
    gp.current = entry

    try:
        loop = asyncio.get_event_loop()
        stream_url, data = await loop.run_in_executor(
            None, lambda: get_audio_url(entry["url"])
        )
        gp.current = data

        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS),
            volume=gp.volume
        )

        def after_play(error):
            if error:
                logger.error(f"Error en reproducción: {error}")
            asyncio.run_coroutine_threadsafe(play_next(ctx, vc), ctx.bot.loop)

        vc.play(source, after=after_play)
        await db.add_stat(ctx.guild.id)

        embed = discord.Embed(
            title="🎵 Reproduciendo",
            description=f"[{data['title']}]({data['url']})",
            color=0x1DB954
        )
        embed.add_field(name="Duración", value=format_duration(data.get("duration", 0)))
        if data.get("thumbnail"):
            embed.set_thumbnail(url=data["thumbnail"])
        await ctx.send(embed=embed)

    except Exception as e:
        logger.error(f"Error cargando canción: {e}")
        await ctx.send(f"❌ No pude reproducir `{entry.get('title', '??')}`: {e}")
        await play_next(ctx, vc)


# =========================================
# BOT
# =========================================

class NationBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.voice_states = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self):
        await db.connect()
        await self.tree.sync()
        logger.info("Slash commands sincronizados.")

    async def on_ready(self):
        logger.info(f"Bot listo: {self.user} (ID: {self.user.id})")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name="!help | Nation Bot"
            )
        )

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Argumento faltante: `{error.param.name}`")
        elif isinstance(error, commands.CommandNotFound):
            pass
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"❌ Argumento inválido: {error}")
        else:
            logger.error(f"Error en comando: {error}", exc_info=True)
            await ctx.send(f"❌ Error inesperado: {error}")

bot = NationBot()


# =========================================
# HELP
# =========================================

@bot.hybrid_command(name="help", description="Muestra todos los comandos")
async def help_cmd(ctx):
    embed = discord.Embed(
        title="🎧 Nation Bot — Comandos",
        color=0x1DB954,
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="🎵 Música", value=(
        "`!play <búsqueda/URL>` — Reproducir/añadir a cola\n"
        "`!pause` — Pausar\n"
        "`!resume` — Reanudar\n"
        "`!skip` — Saltar canción\n"
        "`!stop` — Detener y desconectar\n"
        "`!queue` — Ver cola\n"
        "`!nowplaying` — Canción actual\n"
        "`!volume <0-100>` — Cambiar volumen"
    ), inline=False)
    embed.add_field(name="🎛️ DJ", value=(
        "`!shuffle` — Mezclar cola\n"
        "`!loop <off/track/queue>` — Modo loop\n"
        "`!remove <número>` — Eliminar de cola\n"
        "`!clearqueue` — Limpiar cola\n"
        "`!djrole <@rol>` — Asignar rol DJ (admin)"
    ), inline=False)
    embed.add_field(name="⭐ Favoritos", value=(
        "`!favadd` — Guardar canción actual en tu playlist\n"
        "`!favlist` — Ver tu playlist numerada\n"
        "`!favremove <título>` — Eliminar de tu playlist\n"
        "`!favplay` — Reproducir toda tu playlist\n"
        "`!favplay <número>` — Reproducir una canción específica"
    ), inline=False)
    embed.add_field(name="🧠 IA", value=(
        "`!chat <mensaje>` — Chatear con IA\n"
        "`!recommend [género]` — Recomendar música\n"
        "`!clearchat` — Limpiar sesión IA"
    ), inline=False)
    embed.add_field(name="📊 Stats", value="`!stats` — Estadísticas del servidor", inline=False)
    embed.set_footer(text="Nation Bot — powered by pytubefix")
    await ctx.send(embed=embed)


# =========================================
# MÚSICA
# =========================================

@bot.hybrid_command(name="play", description="Reproduce o añade una canción/playlist")
async def play(ctx, *, query: str):
    vc = await ensure_connected(ctx)
    if not vc:
        return

    await ctx.defer()
    gp = get_guild_player(ctx.guild.id)

    try:
        loop = asyncio.get_event_loop()

        if "playlist?list=" in query or ("list=" in query and "youtube" in query):
            entries, pl_name = await loop.run_in_executor(
                None, lambda: get_playlist_entries(query)
            )
            for e in entries:
                gp.queue.append(e)
            await ctx.send(f"📋 Playlist añadida: **{pl_name}** ({len(entries)} canciones)")

        else:
            if query.startswith("http"):
                _, data = await loop.run_in_executor(
                    None, lambda: get_audio_url(query)
                )
            else:
                data = await loop.run_in_executor(
                    None, lambda: search_youtube(query)
                )

            if vc.is_playing() or vc.is_paused():
                gp.queue.append(data)
                embed = discord.Embed(
                    title="➕ Añadido a la cola",
                    description=f"[{data['title']}]({data['url']})",
                    color=0x1DB954
                )
                embed.add_field(name="Duración", value=format_duration(data.get("duration", 0)))
                embed.add_field(name="Posición en cola", value=str(len(gp.queue)))
                await ctx.send(embed=embed)
                return

            gp.queue.append(data)

    except Exception as e:
        return await ctx.send(f"❌ Error buscando: {e}")

    if not vc.is_playing() and not vc.is_paused():
        await play_next(ctx, vc)


@bot.hybrid_command(name="pause", description="Pausa la reproducción")
async def pause(ctx):
    vc: discord.VoiceClient = ctx.guild.voice_client
    if not vc or not vc.is_playing():
        return await ctx.send("❌ No hay nada reproduciéndose.")
    vc.pause()
    await ctx.send("⏸ Pausado.")


@bot.hybrid_command(name="resume", description="Reanuda la reproducción")
async def resume(ctx):
    vc: discord.VoiceClient = ctx.guild.voice_client
    if not vc:
        return await ctx.send("❌ No hay player activo.")
    vc.resume()
    await ctx.send("▶ Reanudado.")


@bot.hybrid_command(name="skip", description="Salta la canción actual")
async def skip(ctx):
    if not await check_dj(ctx):
        return
    vc: discord.VoiceClient = ctx.guild.voice_client
    if not vc or not vc.is_playing():
        return await ctx.send("❌ No hay nada reproduciéndose.")
    vc.stop()
    await ctx.send("⏭ Saltado.")


@bot.hybrid_command(name="stop", description="Detiene la música y desconecta")
async def stop(ctx):
    if not await check_dj(ctx):
        return
    vc: discord.VoiceClient = ctx.guild.voice_client
    if not vc:
        return await ctx.send("❌ No estoy en ningún canal.")
    gp = get_guild_player(ctx.guild.id)
    gp.queue.clear()
    gp.current = None
    vc.stop()
    await vc.disconnect()
    await ctx.send("🛑 Detenido y desconectado.")


@bot.hybrid_command(name="queue", description="Muestra la cola de reproducción")
async def queue_cmd(ctx):
    gp = get_guild_player(ctx.guild.id)
    if not gp.queue and not gp.current:
        return await ctx.send("📭 La cola está vacía.")

    items = list(gp.queue)
    desc = ""
    for i, t in enumerate(items[:15], 1):
        desc += f"`{i}.` [{t.get('title','??')}]({t.get('url','')}) — {format_duration(t.get('duration',0))}\n"
    if len(items) > 15:
        desc += f"\n*...y {len(items)-15} más*"

    embed = discord.Embed(title="📋 Cola de reproducción", description=desc or "*(vacía)*", color=0x1DB954)
    if gp.current:
        embed.set_author(name=f"Sonando: {gp.current.get('title','??')}")
    embed.set_footer(text=f"{len(items)} canciones en cola")
    await ctx.send(embed=embed)


@bot.hybrid_command(name="nowplaying", description="Muestra la canción actual")
async def nowplaying(ctx):
    gp = get_guild_player(ctx.guild.id)
    vc: discord.VoiceClient = ctx.guild.voice_client
    if not gp.current or not vc or not vc.is_playing():
        return await ctx.send("❌ No hay nada reproduciéndose.")

    track = gp.current
    embed = discord.Embed(title="🎵 Sonando ahora", color=0x1DB954)
    embed.description = f"**[{track.get('title','??')}]({track.get('url','')})**"
    embed.add_field(name="Duración", value=format_duration(track.get("duration", 0)))
    embed.add_field(name="Volumen", value=f"{gp.volume_pct}%")
    embed.add_field(name="Loop", value=gp.loop_mode)
    if track.get("thumbnail"):
        embed.set_thumbnail(url=track["thumbnail"])
    await ctx.send(embed=embed)


@bot.hybrid_command(name="volume", description="Cambia el volumen (0-100)")
async def volume(ctx, vol: int):
    if not await check_dj(ctx):
        return
    if not 0 <= vol <= 100:
        return await ctx.send("❌ El volumen debe estar entre 0 y 100.")
    vc: discord.VoiceClient = ctx.guild.voice_client
    if not vc or not vc.source:
        return await ctx.send("❌ No hay player activo.")
    gp = get_guild_player(ctx.guild.id)
    gp.volume = vol / 100
    gp.volume_pct = vol
    vc.source.volume = gp.volume
    await ctx.send(f"🔊 Volumen: {vol}%")


# =========================================
# DJ COMMANDS
# =========================================

@bot.hybrid_command(name="shuffle", description="Mezcla la cola aleatoriamente")
async def shuffle(ctx):
    if not await check_dj(ctx):
        return
    gp = get_guild_player(ctx.guild.id)
    if not gp.queue:
        return await ctx.send("❌ La cola está vacía.")
    items = list(gp.queue)
    random.shuffle(items)
    gp.queue = deque(items)
    await ctx.send("🔀 Cola mezclada.")


@bot.hybrid_command(name="loop", description="Cambia el modo de loop")
async def loop(ctx, mode: str = "off"):
    if not await check_dj(ctx):
        return
    if mode not in ("off", "track", "queue"):
        return await ctx.send("❌ Modos válidos: `off`, `track`, `queue`")
    gp = get_guild_player(ctx.guild.id)
    gp.loop_mode = mode
    emojis = {"off": "➡️", "track": "🔂", "queue": "🔁"}
    await ctx.send(f"{emojis[mode]} Loop: **{mode}**")


@bot.hybrid_command(name="remove", description="Elimina una canción de la cola por número")
async def remove(ctx, numero: int):
    if not await check_dj(ctx):
        return
    gp = get_guild_player(ctx.guild.id)
    items = list(gp.queue)
    if not items:
        return await ctx.send("❌ La cola está vacía.")
    if not 1 <= numero <= len(items):
        return await ctx.send(f"❌ Número inválido. La cola tiene {len(items)} canciones.")
    removed = items.pop(numero - 1)
    gp.queue = deque(items)
    await ctx.send(f"🗑️ Eliminado: **{removed.get('title','??')}**")


@bot.hybrid_command(name="clearqueue", description="Limpia toda la cola")
async def clearqueue(ctx):
    if not await check_dj(ctx):
        return
    gp = get_guild_player(ctx.guild.id)
    gp.queue.clear()
    await ctx.send("🗑️ Cola limpiada.")


@bot.hybrid_command(name="djrole", description="Asigna el rol DJ (solo admins)")
@commands.has_permissions(administrator=True)
async def djrole(ctx, rol: discord.Role):
    await db.set_dj_role(ctx.guild.id, rol.id)
    await ctx.send(f"✅ Rol DJ asignado a {rol.mention}")


# =========================================
# FAVORITOS
# =========================================

@bot.hybrid_command(name="favadd", description="Guarda la canción actual en tu playlist")
async def favadd(ctx):
    gp = get_guild_player(ctx.guild.id)
    if not gp.current:
        return await ctx.send("❌ No hay nada reproduciéndose.")
    title = gp.current.get("title", "??")
    url   = gp.current.get("url")
    pos   = await db.favadd(ctx.author.id, title, url)
    await ctx.send(f"⭐ Guardado en posición **#{pos}**: **{title}**")


@bot.hybrid_command(name="favlist", description="Muestra tu playlist personal")
async def favlist(ctx):
    songs = await db.favlist(ctx.author.id)
    if not songs:
        return await ctx.send("📭 Tu playlist está vacía. Usa `!favadd` mientras suena algo.")
    lines = "\n".join([f"{s['position']}. {s['title']}" for s in songs[:30]])
    embed = discord.Embed(
        title=f"⭐ Playlist de {ctx.author.display_name}",
        description=f"```\n{lines}\n```",
        color=0xFFD700
    )
    embed.set_footer(text=f"{len(songs)} canciones • Usa !favplay <número> para una sola o !favplay para todas")
    await ctx.send(embed=embed)


@bot.hybrid_command(name="favremove", description="Elimina una canción de tu playlist")
async def favremove(ctx, *, titulo: str):
    removed = await db.favremove(ctx.author.id, titulo)
    if removed:
        await ctx.send(f"🗑️ Eliminado: **{titulo}**")
    else:
        await ctx.send(f"❌ No encontré `{titulo}` en tu playlist.")


@bot.hybrid_command(name="favplay", description="Reproduce toda tu playlist o una canción por número")
async def favplay(ctx, numero: int = None):
    songs = await db.favlist(ctx.author.id)
    if not songs:
        return await ctx.send("📭 Tu playlist está vacía.")

    if numero is not None:
        if not 1 <= numero <= len(songs):
            return await ctx.send(f"❌ Número inválido. Tu playlist tiene {len(songs)} canciones.")
        song = songs[numero - 1]
        query = song["url"] if song.get("url") else song["title"]
        return await ctx.invoke(bot.get_command("play"), query=query)

    # Sin número → carga toda la playlist en la cola
    vc = await ensure_connected(ctx)
    if not vc:
        return

    gp = get_guild_player(ctx.guild.id)
    for song in songs:
        gp.queue.append({
            "title":     song["title"],
            "url":       song["url"],
            "duration":  None,
            "thumbnail": None,
        })

    await ctx.send(f"⭐ Playlist cargada: **{len(songs)} canciones** añadidas a la cola.")

    if not vc.is_playing() and not vc.is_paused():
        await play_next(ctx, vc)


# =========================================
# IA
# =========================================

@bot.hybrid_command(name="chat", description="Chatea con la IA")
async def chat(ctx, *, mensaje: str):
    await ctx.defer()
    try:
        if ctx.author.id not in ai_sessions:
            ai_sessions[ctx.author.id] = ai_client.chats.create(model=AI_MODEL)
        response = await asyncio.to_thread(
            ai_sessions[ctx.author.id].send_message, mensaje
        )
        embed = discord.Embed(description=response.text[:2000], color=0x7289DA)
        embed.set_author(name="Nation AI", icon_url=bot.user.display_avatar.url)
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Error en IA: {e}")
        await ctx.send(f"❌ Error con la IA: {e}")


@bot.hybrid_command(name="recommend", description="Pide recomendaciones musicales a la IA")
async def recommend(ctx, *, genero: str = "variado"):
    await ctx.defer()
    try:
        if ctx.author.id not in ai_sessions:
            ai_sessions[ctx.author.id] = ai_client.chats.create(model=AI_MODEL)
        prompt = (
            f"Recomiéndame 5 canciones de {genero}. "
            "Para cada una incluye: nombre, artista y por qué la recomiendas. "
            "Formato breve y amigable."
        )
        response = await asyncio.to_thread(
            ai_sessions[ctx.author.id].send_message, prompt
        )
        embed = discord.Embed(
            title=f"🎵 Recomendaciones — {genero}",
            description=response.text[:2000],
            color=0x1DB954
        )
        await ctx.send(embed=embed)
    except Exception as e:
        await ctx.send(f"❌ Error con la IA: {e}")


@bot.hybrid_command(name="clearchat", description="Borra tu sesión de IA")
async def clearchat(ctx):
    ai_sessions.pop(ctx.author.id, None)
    await ctx.send("🧹 Sesión de IA limpiada.")


# =========================================
# STATS
# =========================================

@bot.hybrid_command(name="stats", description="Muestra estadísticas del servidor")
async def stats(ctx):
    total = await db.get_stats(ctx.guild.id)
    embed = discord.Embed(title=f"📊 Stats — {ctx.guild.name}", color=0x1DB954)
    embed.add_field(name="Canciones reproducidas", value=str(total))
    embed.add_field(name="Miembros", value=str(ctx.guild.member_count))
    if ctx.guild.icon:
        embed.set_thumbnail(url=ctx.guild.icon.url)
    await ctx.send(embed=embed)


# =========================================
# ARRANQUE
# =========================================

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
