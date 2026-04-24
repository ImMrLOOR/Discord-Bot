import discord
from discord.ext import commands
import asyncio
import logging
import aiosqlite
import os
import re
import random
from datetime import datetime
from collections import Counter
import wavelink

from dotenv import load_dotenv
load_dotenv()

# =========================================
# CONFIG
# =========================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")

if not DISCORD_TOKEN:
    raise EnvironmentError(
        "Falta variable de entorno. Crea un archivo .env con:\n"
        "DISCORD_TOKEN=tu_token"
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("NationBot")

# =========================================
# MUSIC INTELLIGENCE ENGINE (Custom)
# =========================================

GENRE_KEYWORDS: dict[str, list[str]] = {
    "reggaeton":           ["reggaeton", "perreo", "dembow", "bad bunny", "j balvin", "maluma",
                            "ozuna", "daddy yankee", "anuel", "karol g", "myke towers", "feid",
                            "rauw alejandro", "jhay cortez", "quevedo"],
    "trap latino":         ["trap", "latin trap", "bryant myers", "arcangel", "de la ghetto",
                            "eladio carrion", "jhay", "mora", "juhn"],
    "salsa":               ["salsa", "marc anthony", "gilberto santa rosa", "celia cruz",
                            "willie colon", "hector lavoe", "victor manuel", "grupo niche"],
    "bachata":             ["bachata", "romeo santos", "prince royce", "aventura", "frank reyes"],
    "merengue":            ["merengue", "juan luis guerra", "wilfrido vargas", "milly quezada"],
    "cumbia":              ["cumbia", "carlos vives", "los palmeras", "aniceto molina"],
    "pop latino":          ["pop", "shakira", "ricky martin", "enrique iglesias", "juanes",
                            "alejandro sanz", "pablo alboran", "camilo", "sebastian yatra"],
    "rock en espanol":     ["rock", "mana", "soda stereo", "los fabulosos cadillacs",
                            "cafe tacvba", "los bunkers", "babasónicos", "divididos"],
    "pop ingles":          ["taylor swift", "ed sheeran", "ariana grande", "billie eilish",
                            "harry styles", "olivia rodrigo", "doja cat", "the weeknd"],
    "rap hip hop":         ["rap", "hip hop", "eminem", "drake", "kendrick lamar", "j cole",
                            "travis scott", "21 savage", "lil baby", "nicki minaj"],
    "r&b soul":            ["r&b", "soul", "beyonce", "frank ocean", "sza", "daniel caesar"],
    "electronica":         ["edm", "house", "techno", "electronic", "calvin harris",
                            "martin garrix", "tiesto", "avicii", "david guetta"],
    "indie alternativo":   ["indie", "alternativo", "arctic monkeys", "tame impala",
                            "the strokes", "vampire weekend", "the 1975"],
    "metal hard rock":     ["metal", "hard rock", "metallica", "iron maiden", "black sabbath",
                            "slayer", "tool", "system of a down", "acdc", "guns n roses"],
    "clasica instrumental": ["clasica", "classical", "mozart", "beethoven", "bach", "piano"],
    "jazz blues":          ["jazz", "blues", "miles davis", "john coltrane", "bill evans"],
    "country":             ["country", "johnny cash", "luke combs", "morgan wallen"],
    "kpop":                ["kpop", "k-pop", "bts", "blackpink", "twice", "exo", "stray kids"],
    "flamenco":            ["flamenco", "palo", "cajon", "camaron", "paco de lucia", "rosalia"],
}

AUTOPLAY_TEMPLATES: dict[str, list[str]] = {
    "reggaeton":          ["{artist} canciones nuevas", "reggaeton hits {year}", "lo mejor reggaeton {year}"],
    "trap latino":        ["{artist} mix", "trap latino {year}", "latin trap nuevos"],
    "pop ingles":         ["{artist} latest songs", "pop hits {year}", "top pop songs {year}"],
    "electronica":        ["{artist} mix set", "edm hits {year}", "electronic dance mix"],
    "_default":           ["{artist} best songs", "{artist} mix", "similar to {title} music"],
}

_NOISE = {
    "official", "video", "audio", "lyrics", "lyric", "hd", "4k", "ft", "feat",
    "prod", "remix", "mix", "live", "acoustic", "cover", "version", "mv",
    "music", "clip", "explicit", "clean", "extended", "radio", "edit",
    "letra", "con letra", "en vivo", "videoclip", "visualizer",
}

def _norm(text: str) -> str:
    return re.sub(r"[^\w\s]", "", text.lower())

def detect_genre(titles: list[str]) -> str:
    if not titles:
        return "_default"
    combined = _norm(" ".join(titles))
    scores: dict[str, int] = {}
    for genre, keywords in GENRE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in combined)
        if score:
            scores[genre] = score
    return max(scores, key=lambda g: scores[g]) if scores else "_default"

def extract_artist(title: str) -> str:
    if " - " in title:
        candidate = title.split(" - ")[0].strip()
        words = _norm(candidate).split()
        if words and not all(w in _NOISE for w in words):
            return candidate
    tokens = [t for t in title.split() if _norm(t) not in _NOISE]
    return " ".join(tokens[:2]) if tokens else title[:20]

def build_autoplay_query(history: list[str]) -> str:
    if not history:
        return "top music hits"
    genre     = detect_genre(history)
    templates = AUTOPLAY_TEMPLATES.get(genre, AUTOPLAY_TEMPLATES["_default"])
    recent    = history[-8:]
    artists   = [extract_artist(t) for t in recent]
    top_artist = Counter(artists).most_common(1)[0][0] if artists else "music"
    last_title = history[-1]
    year       = datetime.utcnow().year

    template = random.choice(templates)
    return template.replace("{artist}", top_artist).replace("{title}", last_title).replace("{year}", str(year))

def format_duration(milliseconds: int | float | None) -> str:
    if not milliseconds: return "??:??"
    seconds = int(milliseconds / 1000)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


# ── Chat engine integrado ───────────────────────────────────────────────────
_CHAT_DB: list[tuple[list[str], str]] = [
    (["hola", "hey", "buenas", "saludos"], "¡Hola! 👋 Soy **Nation Bot**, tu asistente de música. Usa `!help` para ver qué hago."),
    (["comandos", "ayuda", "help"], "Usa `!help` para ver todos mis comandos de música y favoritos."),
    (["autoplay", "reproduccion automatica"], "**`!autoplay`** busca canciones similares basado en tu historial. ¡Pruébalo!"),
]

def process_chat(mensaje: str) -> str:
    msg = _norm(mensaje)
    for keywords, response in _CHAT_DB:
        if any(kw in msg for kw in keywords): return response
    return "No entendí eso del todo 🤔 Prueba `!help`."


# =========================================
# ESTADO POR SERVIDOR
# =========================================

class GuildPlayer:
    def __init__(self):
        self.autoplay:   bool        = False
        self.history:    list[str]   = []   # máx. 30 títulos
        self.volume_pct: int         = 50

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
        self.db: aiosqlite.Connection | None = None

    async def connect(self):
        self.db = await aiosqlite.connect("nation_music.db")
        self.db.row_factory = aiosqlite.Row
        await self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS playlists (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, name TEXT NOT NULL DEFAULT 'Mis Favoritos', UNIQUE(user_id, name)
            );
            CREATE TABLE IF NOT EXISTS playlist_songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                title TEXT NOT NULL, url TEXT, position INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS stats (guild_id INTEGER PRIMARY KEY, songs_played INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS dj_roles (guild_id INTEGER PRIMARY KEY, role_id INTEGER);
        """)
        await self.db.commit()

    async def _get_or_create_playlist(self, user_id: int, name: str = "Mis Favoritos") -> int:
        await self.db.execute("INSERT OR IGNORE INTO playlists(user_id, name) VALUES(?, ?)", (user_id, name))
        await self.db.commit()
        async with self.db.execute("SELECT id FROM playlists WHERE user_id=? AND name=?", (user_id, name)) as cur:
            return (await cur.fetchone())["id"]

    async def favadd(self, user_id: int, title: str, url: str | None = None) -> int:
        pid = await self._get_or_create_playlist(user_id)
        async with self.db.execute("SELECT COALESCE(MAX(position), 0) + 1 FROM playlist_songs WHERE playlist_id=?", (pid,)) as cur:
            next_pos = (await cur.fetchone())[0]
        await self.db.execute("INSERT INTO playlist_songs(playlist_id, title, url, position) VALUES(?,?,?,?)", (pid, title, url, next_pos))
        await self.db.commit()
        return next_pos

    async def favlist(self, user_id: int) -> list[dict]:
        pid = await self._get_or_create_playlist(user_id)
        async with self.db.execute("SELECT position, title, url FROM playlist_songs WHERE playlist_id=? ORDER BY position", (pid,)) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def add_stat(self, guild_id: int):
        await self.db.execute("INSERT INTO stats(guild_id, songs_played) VALUES(?,1) ON CONFLICT(guild_id) DO UPDATE SET songs_played = songs_played + 1", (guild_id,))
        await self.db.commit()

    async def get_stats(self, guild_id: int) -> int:
        async with self.db.execute("SELECT songs_played FROM stats WHERE guild_id=?", (guild_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async def get_dj_role(self, guild_id: int) -> int | None:
        async with self.db.execute("SELECT role_id FROM dj_roles WHERE guild_id=?", (guild_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

    async def set_dj_role(self, guild_id: int, role_id: int):
        await self.db.execute("INSERT INTO dj_roles VALUES(?,?) ON CONFLICT(guild_id) DO UPDATE SET role_id=?", (guild_id, role_id, role_id))
        await self.db.commit()

db = Database()


# =========================================
# CHECKS & HELPERS
# =========================================

async def check_voice(ctx) -> bool:
    if not ctx.author.voice:
        await ctx.send("❌ Debes estar en un canal de voz.")
        return False
    return True

async def check_dj(ctx) -> bool:
    if ctx.author.guild_permissions.administrator: return True
    role_id = await db.get_dj_role(ctx.guild.id)
    if role_id and any(r.id == role_id for r in ctx.author.roles): return True
    await ctx.send("❌ Necesitas el rol DJ para esto.")
    return False


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
        # CONEXIÓN AL NODO LAVALINK (Cambia uri o password si tu config de Lavalink es diferente)
        nodes = [wavelink.Node(uri="http://127.0.0.1:2333", password="youshallnotpass")]
        await wavelink.Pool.connect(client=self, nodes=nodes)
        
        await self.tree.sync()
        logger.info("Slash commands sincronizados y Lavalink preparado.")

    async def on_ready(self):
        logger.info(f"Bot listo: {self.user} (ID: {self.user.id})")
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.listening, name="!help | Lavalink"))

bot = NationBot()

@bot.event
async def on_wavelink_node_ready(payload: wavelink.NodeReadyEventPayload):
    logger.info(f"✅ Nodo Lavalink '{payload.node.identifier}' conectado y listo.")

@bot.event
async def on_wavelink_track_start(payload: wavelink.TrackStartEventPayload):
    player = payload.player
    if not player: return
    track = payload.track
    
    gp = get_guild_player(player.guild.id)
    gp.history.append(track.title)
    if len(gp.history) > 30:
        gp.history.pop(0)

    await db.add_stat(player.guild.id)
    
    # Busca el canal de texto donde se originó el comando para avisar (Wavelink Player puede guardar contextos custom, o lo enviamos si no)
    # Por simplicidad, se omite el mensaje automático en cada salto para evitar spam, pero puedes agregarlo.

@bot.event
async def on_wavelink_track_end(payload: wavelink.TrackEndEventPayload):
    player = payload.player
    if not player: return

    gp = get_guild_player(player.guild.id)
    
    # SI LA COLA ESTÁ VACÍA Y EL AUTOPLAY CUSTOM ESTÁ ACTIVADO
    if player.queue.is_empty and gp.autoplay:
        query = build_autoplay_query(gp.history)
        try:
            tracks: wavelink.Search = await wavelink.Playable.search(query)
            if tracks:
                # Evitar las últimas canciones repetidas si es posible
                recent_set = set(gp.history[-10:])
                track = next((t for t in tracks if t.title not in recent_set), tracks[0])
                
                await player.queue.put_wait(track)
                await player.play(player.queue.get())
        except Exception as e:
            logger.error(f"Error en Custom Autoplay Lavalink: {e}")


# =========================================
# COMANDOS DE MÚSICA (LAVALINK)
# =========================================

@bot.hybrid_command(name="play", description="Reproduce o añade una canción/playlist")
async def play(ctx, *, query: str):
    if not await check_voice(ctx): return
    if not ctx.interaction or not ctx.interaction.response.is_done(): await ctx.defer()

    # Obtener o conectar el Player de Wavelink
    player: wavelink.Player = getattr(ctx.guild, "voice_client", None)
    if not player:
        try:
            player = await ctx.author.voice.channel.connect(cls=wavelink.Player)
            player.autoplay = wavelink.AutoPlayMode.disabled # Desactivar el de Wavelink para usar el tuyo custom
            await player.set_volume(50)
        except Exception as e:
            return await ctx.send(f"❌ No pude conectarme al canal: {e}")

    # Buscar en Lavalink
    try:
        tracks: wavelink.Search = await wavelink.Playable.search(query)
        if not tracks:
            return await ctx.send("❌ No se encontraron resultados.")
    except Exception as e:
        return await ctx.send(f"❌ Error al buscar en Lavalink: {e}")

    # Manejo de Playlists
    if isinstance(tracks, wavelink.Playlist):
        added = await player.queue.put_wait(tracks.tracks)
        msg = await ctx.send(f"📋 Playlist añadida: **{tracks.name}** ({added} canciones)")
    else:
        track = tracks[0]
        await player.queue.put_wait(track)
        embed = discord.Embed(title="➕ Añadido a la cola", description=f"[{track.title}]({track.uri})", color=0x1DB954)
        embed.add_field(name="Duración", value=format_duration(track.length))
        embed.add_field(name="Posición en cola", value=str(player.queue.count))
        if track.artwork: embed.set_thumbnail(url=track.artwork)
        msg = await ctx.send(embed=embed)

    # Iniciar reproducción si no está sonando nada
    if not player.playing:
        await player.play(player.queue.get())
        
        # Si acabamos de arrancar, mostramos qué empezó a sonar si fue individual
        if not isinstance(tracks, wavelink.Playlist):
            embed.title = "🎵 Reproduciendo"
            await msg.edit(embed=embed)

@bot.hybrid_command(name="pause", description="Pausa la reproducción")
async def pause(ctx):
    player: wavelink.Player = ctx.guild.voice_client
    if not player or not player.playing: return await ctx.send("❌ No hay nada reproduciéndose.")
    await player.pause(True)
    await ctx.send("⏸ Pausado.")

@bot.hybrid_command(name="resume", description="Reanuda la reproducción")
async def resume(ctx):
    player: wavelink.Player = ctx.guild.voice_client
    if not player or not player.paused: return await ctx.send("❌ No está pausado.")
    await player.pause(False)
    await ctx.send("▶ Reanudado.")

@bot.hybrid_command(name="skip", description="Salta la canción actual")
async def skip(ctx):
    if not await check_dj(ctx): return
    player: wavelink.Player = ctx.guild.voice_client
    if not player or not player.playing: return await ctx.send("❌ No hay nada reproduciéndose.")
    await player.skip()
    await ctx.send("⏭ Saltado.")

@bot.hybrid_command(name="stop", description="Detiene la música y desconecta")
async def stop(ctx):
    if not await check_dj(ctx): return
    player: wavelink.Player = ctx.guild.voice_client
    if not player: return await ctx.send("❌ No estoy en ningún canal.")
    await player.disconnect()
    await ctx.send("🛑 Detenido y desconectado.")

@bot.hybrid_command(name="queue", description="Muestra la cola de reproducción")
async def queue_cmd(ctx):
    player: wavelink.Player = ctx.guild.voice_client
    if not player or player.queue.is_empty:
        return await ctx.send("📭 La cola está vacía.")
        
    items = list(player.queue)
    desc = ""
    for i, t in enumerate(items[:15], 1):
        desc += f"`{i}.` [{t.title[:60]}]({t.uri}) — {format_duration(t.length)}\n"
    if len(items) > 15:
        desc += f"\n*...y {len(items)-15} más*"
        
    embed = discord.Embed(title="📋 Cola de reproducción", description=desc, color=0x1DB954)
    if player.current: embed.set_author(name=f"Sonando: {player.current.title[:60]}")
    await ctx.send(embed=embed)

@bot.hybrid_command(name="nowplaying", description="Muestra la canción actual")
async def nowplaying(ctx):
    player: wavelink.Player = ctx.guild.voice_client
    if not player or not player.current: return await ctx.send("❌ No hay nada reproduciéndose.")
    track = player.current
    gp = get_guild_player(ctx.guild.id)
    
    embed = discord.Embed(title="🎵 Sonando ahora", description=f"**[{track.title}]({track.uri})**", color=0x1DB954)
    embed.add_field(name="Duración", value=format_duration(track.length))
    embed.add_field(name="Volumen",  value=f"{gp.volume_pct}%")
    embed.add_field(name="Autoplay", value="🔮 On" if gp.autoplay else "Off")
    if track.artwork: embed.set_thumbnail(url=track.artwork)
    await ctx.send(embed=embed)

@bot.hybrid_command(name="volume", description="Cambia el volumen (0-100)")
async def volume(ctx, vol: int):
    if not await check_dj(ctx): return
    if not 0 <= vol <= 100: return await ctx.send("❌ El volumen debe estar entre 0 y 100.")
    player: wavelink.Player = ctx.guild.voice_client
    if not player: return await ctx.send("❌ No estoy en ningún canal.")
    
    await player.set_volume(vol)
    get_guild_player(ctx.guild.id).volume_pct = vol
    await ctx.send(f"🔊 Volumen establecido al **{vol}%**")

@bot.hybrid_command(name="loop", description="Cambia el modo de loop")
async def loop_cmd(ctx, mode: str = "off"):
    if not await check_dj(ctx): return
    player: wavelink.Player = ctx.guild.voice_client
    if not player: return await ctx.send("❌ No estoy en ningún canal.")

    if mode == "track":
        player.queue.mode = wavelink.QueueMode.loop
    elif mode == "queue":
        player.queue.mode = wavelink.QueueMode.loop_all
    elif mode == "off":
        player.queue.mode = wavelink.QueueMode.normal
    else:
        return await ctx.send("❌ Modos válidos: `off`, `track`, `queue`")
        
    await ctx.send(f"{'➡️' if mode=='off' else '🔂' if mode=='track' else '🔁'} Loop: **{mode}**")

@bot.hybrid_command(name="autoplay", description="Activa/desactivar autoplay inteligente por historial")
async def autoplay_cmd(ctx):
    if not await check_dj(ctx): return
    gp = get_guild_player(ctx.guild.id)
    gp.autoplay = not gp.autoplay

    if gp.autoplay:
        genre = detect_genre(gp.history).replace("_", " ").title() if gp.history else "aún no detectado"
        embed = discord.Embed(title="🔮 Autoplay activado", description=f"Historial: {len(gp.history)} canciones\nGénero dominante: {genre}", color=0x9B59B6)
    else:
        embed = discord.Embed(title="⏹ Autoplay desactivado", color=0x95A5A6)
    await ctx.send(embed=embed)

# =========================================
# FAVORITOS Y OTROS (Simplificados)
# =========================================

@bot.hybrid_command(name="favadd")
async def favadd(ctx):
    player: wavelink.Player = ctx.guild.voice_client
    if not player or not player.current: return await ctx.send("❌ No hay nada.")
    pos = await db.favadd(ctx.author.id, player.current.title, player.current.uri)
    await ctx.send(f"⭐ Guardado en posición **#{pos}**: **{player.current.title}**")

@bot.hybrid_command(name="favlist")
async def favlist(ctx):
    songs = await db.favlist(ctx.author.id)
    if not songs: return await ctx.send("📭 Tu playlist está vacía.")
    lines = "\n".join(f"{s['position']}. {s['title'][:50]}" for s in songs[:30])
    await ctx.send(embed=discord.Embed(title="⭐ Playlist", description=f"```\n{lines}\n```", color=0xFFD700))

@bot.hybrid_command(name="chat")
async def chat(ctx, *, mensaje: str):
    await ctx.send(embed=discord.Embed(description=process_chat(mensaje), color=0x7289DA))

@bot.event
async def on_voice_state_update(member, before, after):
    player: wavelink.Player = member.guild.voice_client
    if not player or not player.channel: return
    if not any(m for m in player.channel.members if not m.bot):
        await player.disconnect()

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
