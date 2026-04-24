import discord
from discord.ext import commands
import asyncio
import logging
import aiosqlite
import os
import re
import random
from datetime import datetime
from collections import deque, Counter
import yt_dlp

from dotenv import load_dotenv
load_dotenv()

# =========================================
# CONFIG
# =========================================

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "TU_TOKEN_AQUI")

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

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

# Configuración base de yt-dlp
YTDL_OPTIONS = {
    'format': 'bestaudio/best',
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0', 
    'cookiesfrombrowser': ('chrome',),
}

ytdl = yt_dlp.YoutubeDL(YTDL_OPTIONS)

# =========================================
# MUSIC INTELLIGENCE ENGINE
# 100% autónomo — sin dependencias de IA externa
# =========================================

# Mapa de géneros → palabras clave (artistas + términos del género)
GENRE_KEYWORDS: dict[str, list[str]] = {
    "reggaeton":           ["reggaeton", "perreo", "dembow", "bad bunny", "j balvin", "maluma",
                            "ozuna", "daddy yankee", "anuel", "karol g", "myke towers", "feid",
                            "rauw alejandro", "jhay cortez", "quevedo"],
    "trap latino":         ["trap", "latin trap", "bryant myers", "arcangel", "de la ghetto",
                            "eladio carrion", "jhay", "mora", "juhn"],
    "salsa":               ["salsa", "marc anthony", "gilberto santa rosa", "celia cruz",
                            "willie colon", "hector lavoe", "victor manuel", "grupo niche",
                            "guayacan", "oscar de leon"],
    "bachata":             ["bachata", "romeo santos", "prince royce", "aventura", "frank reyes",
                            "toby love", "grupo extra", "zacarias ferreira"],
    "merengue":            ["merengue", "juan luis guerra", "wilfrido vargas", "milly quezada",
                            "las chicas del can"],
    "cumbia":              ["cumbia", "carlos vives", "los palmeras", "aniceto molina",
                            "celso pina", "los yonics"],
    "pop latino":          ["pop", "shakira", "ricky martin", "enrique iglesias", "juanes",
                            "alejandro sanz", "pablo alboran", "camilo", "sebastian yatra",
                            "nicky jam", "wisin", "yandel", "luis fonsi"],
    "rock en espanol":     ["rock", "mana", "soda stereo", "los fabulosos cadillacs",
                            "cafe tacvba", "los bunkers", "babasónicos", "divididos",
                            "rata blanca", "heroes del silencio", "attaque 77"],
    "pop ingles":          ["taylor swift", "ed sheeran", "ariana grande", "billie eilish",
                            "harry styles", "olivia rodrigo", "doja cat", "the weeknd",
                            "post malone", "sabrina carpenter", "charli xcx"],
    "rap hip hop":         ["rap", "hip hop", "eminem", "drake", "kendrick lamar", "j cole",
                            "travis scott", "21 savage", "lil baby", "nicki minaj", "cardi b",
                            "future", "lil uzi"],
    "r&b soul":            ["r&b", "soul", "beyonce", "frank ocean", "sza", "daniel caesar",
                            "her", "usher", "alicia keys", "john legend", "giveon", "brent faiyaz"],
    "electronica":         ["edm", "house", "techno", "electronic", "calvin harris",
                            "martin garrix", "tiesto", "avicii", "david guetta", "marshmello",
                            "dj snake", "skrillex", "deadmau5"],
    "indie alternativo":   ["indie", "alternativo", "arctic monkeys", "tame impala",
                            "the strokes", "vampire weekend", "the 1975", "mac demarco",
                            "rex orange county", "clairo", "beabadoobee"],
    "metal hard rock":     ["metal", "hard rock", "metallica", "iron maiden", "black sabbath",
                            "slayer", "tool", "system of a down", "acdc", "guns n roses",
                            "pantera", "megadeth"],
    "clasica instrumental": ["clasica", "classical", "mozart", "beethoven", "bach", "piano",
                              "orchestra", "symphony", "instrumental", "chopin", "vivaldi"],
    "jazz blues":          ["jazz", "blues", "miles davis", "john coltrane", "bill evans",
                            "bb king", "eric clapton", "ray charles", "billie holiday",
                            "louis armstrong"],
    "country":             ["country", "johnny cash", "luke combs", "morgan wallen",
                            "chris stapleton", "zac brown", "kenny chesney", "blake shelton"],
    "kpop":                ["kpop", "k-pop", "bts", "blackpink", "twice", "exo", "stray kids",
                            "itzy", "aespa", "nct", "enhypen", "txt", "ive", "newjeans"],
    "flamenco":            ["flamenco", "palo", "cajon", "camaron", "paco de lucia",
                            "rosalia", "tangos", "bulerias", "rumba"],
}

# Plantillas de búsqueda para autoplay según género
AUTOPLAY_TEMPLATES: dict[str, list[str]] = {
    "reggaeton":          ["{artist} canciones nuevas", "reggaeton hits {year}", "lo mejor reggaeton {year}"],
    "trap latino":        ["{artist} mix", "trap latino {year}", "latin trap nuevos"],
    "salsa":              ["{artist} exitos", "salsa clasicos mix", "salsa romantica playlist"],
    "bachata":            ["{artist} mejores canciones", "bachata romantica {year}", "bachata mix"],
    "pop latino":         ["{artist} nuevas canciones", "pop latino {year}", "latin pop hits"],
    "rock en espanol":    ["{artist} grandes exitos", "rock en espanol clasicos", "rock latino mix"],
    "pop ingles":         ["{artist} latest songs", "pop hits {year}", "top pop songs {year}"],
    "rap hip hop":        ["{artist} best songs", "hip hop hits {year}", "rap mix {year}"],
    "r&b soul":           ["{artist} mix", "r&b hits {year}", "soul playlist"],
    "electronica":        ["{artist} mix set", "edm hits {year}", "electronic dance mix"],
    "indie alternativo":  ["{artist} best songs", "indie playlist {year}", "alternative hits"],
    "metal hard rock":    ["{artist} greatest hits", "heavy metal mix", "hard rock classics"],
    "kpop":               ["{artist} best songs", "kpop hits {year}", "kpop playlist {year}"],
    "jazz blues":         ["{artist} best", "jazz classics mix", "blues hits playlist"],
    "cumbia":             ["{artist} exitos", "cumbia mix", "lo mejor cumbia"],
    "merengue":           ["{artist} exitos", "merengue clasico mix", "merengue playlist"],
    "country":            ["{artist} best songs", "country hits {year}", "country playlist"],
    "flamenco":           ["{artist} actuaciones", "flamenco mix", "flamenco clasico"],
    "clasica instrumental": ["{artist} best pieces", "classical music mix", "piano instrumental"],
    "_default":           ["{artist} best songs", "{artist} mix", "similar to {title} music"],
}

# Palabras irrelevantes para extraer artista del título
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
    return (
        template
        .replace("{artist}", top_artist)
        .replace("{title}",  last_title)
        .replace("{year}",   str(year))
    )


def get_recommendations(history: list[str], genre_filter: str | None = None) -> list[str]:
    queries: list[str] = []
    year = datetime.utcnow().year

    if genre_filter:
        gf = genre_filter.lower()
        matched = next(
            (g for g, kws in GENRE_KEYWORDS.items() if gf in g or any(gf in kw for kw in kws)),
            None
        )
        if matched:
            artists = [kw for kw in GENRE_KEYWORDS[matched] if len(kw.split()) <= 3][:10]
            random.shuffle(artists)
            queries = [f"{a} best songs" for a in artists[:5]]
        else:
            queries = [f"top {genre_filter} songs {year - i // 2}" for i in range(5)]
    else:
        if not history:
            return ["top music hits", f"best songs {year}", "popular music playlist",
                    f"music hits {year}", "top tracks"]
        genre   = detect_genre(history)
        recent  = history[-10:]
        artists = list({extract_artist(t) for t in recent})
        random.shuffle(artists)

        for a in artists[:3]:
            queries.append(f"{a} mix")

        templates = AUTOPLAY_TEMPLATES.get(genre, AUTOPLAY_TEMPLATES["_default"])
        for tmpl in random.sample(templates, min(2, len(templates))):
            q = (tmpl
                 .replace("{artist}", artists[0] if artists else "music")
                 .replace("{title}",  history[-1])
                 .replace("{year}",   str(year)))
            queries.append(q)

    return queries[:5]


# ── Chat engine integrado ───────────────────────────────────────────────────

_CHAT_DB: list[tuple[list[str], str]] = [
    (["hola", "hey", "buenas", "saludos", "hi", "ola"],
     "¡Hola! 👋 Soy **Nation Bot**, tu asistente de música para Discord. "
     "Usa `!help` para ver todo lo que puedo hacer."),

    (["comandos", "que puedes", "ayuda", "help", "funciones", "que haces"],
     "Mis comandos principales:\n"
     "🎵 `!play`, `!pause`, `!resume`, `!skip`, `!stop`, `!queue`, `!nowplaying`\n"
     "🎛️ `!shuffle`, `!loop`, `!autoplay`, `!volume`, `!remove`, `!clearqueue`\n"
     "⭐ `!favadd`, `!favlist`, `!favplay`, `!favremove`\n"
     "🎯 `!recommend [género]` — basado en historial del servidor\n"
     "📊 `!stats` — estadísticas"),

    (["autoplay", "reproduccion automatica", "auto play", "autoreproduce"],
     "**`!autoplay`** activa un sistema propio que detecta el género y artistas "
     "que estás escuchando y busca canciones similares en YouTube cuando la cola termina. "
     "No depende de ninguna IA externa — funciona con el historial del servidor. 🔮"),

    (["recommend", "recomendaciones", "recomienda", "sugiere", "sugerencias"],
     "Usa **`!recommend`** para recomendaciones basadas en lo que han escuchado en el servidor. "
     "También puedes pedir género: `!recommend reggaeton`, `!recommend jazz`, `!recommend kpop`, etc."),

    (["volumen", "volume", "subir", "bajar", "mas alto", "mas bajo"],
     "Cambia el volumen con **`!volume <0-100>`**. Ejemplo: `!volume 70`. "
     "Requiere rol DJ o ser administrador."),

    (["loop", "repetir", "bucle", "repeticion", "repeat"],
     "Modos de loop con **`!loop`**:\n"
     "🔂 `!loop track` — repite la canción actual\n"
     "🔁 `!loop queue` — repite toda la cola\n"
     "➡️ `!loop off` — sin repetición"),

    (["playlist", "favoritos", "fav", "guardar", "lista"],
     "Guarda canciones con **`!favadd`** mientras suenan. "
     "Ve tu lista con `!favlist` y reprodúcela con `!favplay` o `!favplay <número>`."),

    (["dj", "permisos", "rol", "quien puede", "acceso"],
     "Comandos como `skip`, `stop`, `volume`, `loop` requieren el rol **DJ**. "
     "Un administrador puede asignarlo con `!djrole @rol`."),

    (["stats", "estadisticas", "cuantas canciones", "historial"],
     "Usa **`!stats`** para ver canciones reproducidas, miembros y el género dominante detectado hoy."),

    (["genero", "estilo", "tipo de musica", "que suena"],
     "El bot detecta automáticamente el género dominante analizando los títulos del historial. "
     "Puedes verlo en `!nowplaying`, `!stats` o al activar `!autoplay`."),

    (["gracias", "thanks", "thank you", "genial", "excelente", "bueno", "chevere"],
     "¡De nada! 🎶 Que disfrutes la música."),

    (["quien eres", "que eres", "como te llamas", "nombre", "presentate"],
     "Soy **Nation Bot** 🎧 — bot de música para Discord hecho 100% a medida. "
     "Reproduzco música de YouTube, gestiono colas, favoritos y hago recomendaciones "
     "inteligentes sin depender de ninguna API de IA externa."),

    (["skip votar", "voteskip", "voto", "votar saltar"],
     "Por ahora `!skip` requiere rol DJ. Si quieres un sistema de votación, "
     "dile al admin que lo configure con `!djrole`."),
]


def process_chat(mensaje: str) -> str:
    msg = _norm(mensaje)
    best_score, best_resp = 0, None
    for keywords, response in _CHAT_DB:
        score = sum(1 for kw in keywords if kw in msg)
        if score > best_score:
            best_score, best_resp = score, response
    if best_resp:
        return best_resp
    return (
        "No entendí eso del todo 🤔 Pero puedo ayudarte con música. "
        "Prueba `!help` para ver los comandos disponibles, o `!recommend` para descubrir música nueva."
    )


# =========================================
# YT-DLP HELPERS
# =========================================

def get_audio_url(url: str) -> tuple[str, dict]:
    info = ytdl.extract_info(url, download=False)
    if 'entries' in info:  # En caso de que se envíe una lista y se procese el primero
        info = info['entries'][0]
    
    stream_url = info.get('url')
    if not stream_url:
        raise Exception("No se encontró stream de audio.")
        
    return stream_url, {
        "title":     info.get("title", "Unknown"),
        "url":       info.get("webpage_url", url),
        "duration":  info.get("duration", 0),
        "thumbnail": info.get("thumbnail", None),
    }


def search_youtube(query: str) -> dict:
    info = ytdl.extract_info(f"ytsearch1:{query}", download=False)
    if 'entries' not in info or not info['entries']:
        raise Exception("No se encontraron resultados.")
    
    v = info['entries'][0]
    return {
        "title": v.get("title", "Unknown"), 
        "url": v.get("webpage_url", v.get("url")), 
        "duration": v.get("duration", 0), 
        "thumbnail": v.get("thumbnail")
    }

def search_multiple(query: str, count: int = 5) -> list[dict]:
    """Helper para buscar múltiples resultados para autoplay/recommend"""
    info = ytdl.extract_info(f"ytsearch{count}:{query}", download=False)
    results = []
    if 'entries' in info:
        for v in info['entries']:
            if v:
                results.append({
                    "title": v.get("title", "Unknown"),
                    "url": v.get("webpage_url", v.get("url")),
                    "duration": v.get("duration", 0),
                    "thumbnail": v.get("thumbnail")
                })
    return results


def get_playlist_entries(url: str) -> tuple[list[dict], str]:
    opts = YTDL_OPTIONS.copy()
    opts['extract_flat'] = 'in_playlist'
    opts['noplaylist'] = False
    
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if 'entries' not in info:
            raise Exception("No es una playlist o no se pudo cargar.")
        
        entries = []
        for v in info['entries']:
            if not v:
                continue
            video_url = v.get("url", "")
            # Manejo de URLs relativas en extracciones planas
            if video_url and not video_url.startswith('http'):
                video_url = f"https://www.youtube.com/watch?v={video_url}"
                
            entries.append({
                "title": v.get("title", "Unknown"),
                "url": video_url,
                "duration": v.get("duration", 0),
                "thumbnail": v.get("thumbnails", [{}])[0].get("url") if v.get("thumbnails") else None
            })
        return entries, info.get("title", "Playlist")


def format_duration(seconds: int | None) -> str:
    if not seconds:
        return "??:??"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"


# =========================================
# ESTADO POR SERVIDOR
# =========================================

class GuildPlayer:
    def __init__(self):
        self.queue:      deque       = deque()
        self.current:    dict | None = None
        self.volume:     float       = 0.5
        self.volume_pct: int         = 50
        self.loop_mode:  str         = "off"
        self.autoplay:   bool        = False
        self.history:    list[str]   = []   # máx. 30 títulos

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
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                name       TEXT    NOT NULL DEFAULT 'Mis Favoritos',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, name)
            );

            CREATE TABLE IF NOT EXISTS playlist_songs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                playlist_id INTEGER NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
                title       TEXT    NOT NULL,
                url         TEXT,
                position    INTEGER NOT NULL DEFAULT 0,
                added_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS stats (
                guild_id     INTEGER PRIMARY KEY,
                songs_played INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS dj_roles (
                guild_id INTEGER PRIMARY KEY,
                role_id  INTEGER
            );
        """)
        await self.db.commit()
        logger.info("Base de datos lista.")

    async def _get_or_create_playlist(self, user_id: int, name: str = "Mis Favoritos") -> int:
        await self.db.execute(
            "INSERT OR IGNORE INTO playlists(user_id, name) VALUES(?, ?)", (user_id, name)
        )
        await self.db.commit()
        async with self.db.execute(
            "SELECT id FROM playlists WHERE user_id=? AND name=?", (user_id, name)
        ) as cur:
            return (await cur.fetchone())["id"]

    async def favadd(self, user_id: int, title: str, url: str | None = None,
                     playlist: str = "Mis Favoritos") -> int:
        pid = await self._get_or_create_playlist(user_id, playlist)
        async with self.db.execute(
            "SELECT COALESCE(MAX(position), 0) + 1 FROM playlist_songs WHERE playlist_id=?", (pid,)
        ) as cur:
            next_pos = (await cur.fetchone())[0]
        await self.db.execute(
            "INSERT INTO playlist_songs(playlist_id, title, url, position) VALUES(?,?,?,?)",
            (pid, title, url, next_pos),
        )
        await self.db.commit()
        return next_pos

    async def favlist(self, user_id: int, playlist: str = "Mis Favoritos") -> list[dict]:
        pid = await self._get_or_create_playlist(user_id, playlist)
        async with self.db.execute(
            "SELECT position, title, url FROM playlist_songs WHERE playlist_id=? ORDER BY position", (pid,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def favremove(self, user_id: int, title: str, playlist: str = "Mis Favoritos") -> bool:
        pid = await self._get_or_create_playlist(user_id, playlist)
        async with self.db.execute(
            "DELETE FROM playlist_songs WHERE playlist_id=? AND lower(title)=lower(?)", (pid, title)
        ) as cur:
            deleted = cur.rowcount
        await self.db.commit()
        return deleted > 0

    async def add_stat(self, guild_id: int):
        await self.db.execute(
            "INSERT INTO stats(guild_id, songs_played) VALUES(?,1) "
            "ON CONFLICT(guild_id) DO UPDATE SET songs_played = songs_played + 1",
            (guild_id,)
        )
        await self.db.commit()

    async def get_stats(self, guild_id: int) -> int:
        async with self.db.execute(
            "SELECT songs_played FROM stats WHERE guild_id=?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async def set_dj_role(self, guild_id: int, role_id: int):
        await self.db.execute(
            "INSERT INTO dj_roles VALUES(?,?) ON CONFLICT(guild_id) DO UPDATE SET role_id=?",
            (guild_id, role_id, role_id)
        )
        await self.db.commit()

    async def get_dj_role(self, guild_id: int) -> int | None:
        async with self.db.execute(
            "SELECT role_id FROM dj_roles WHERE guild_id=?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

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
    elif vc.channel != ctx.author.voice.channel:
        await vc.move_to(ctx.author.voice.channel)
    return vc


# =========================================
# REPRODUCCIÓN INTERNA
# =========================================

async def play_next(ctx, vc: discord.VoiceClient):
    gp = get_guild_player(ctx.guild.id)

    if not vc.is_connected():
        gp.current = None
        gp.queue.clear()
        return

    if gp.loop_mode == "track" and gp.current:
        gp.queue.appendleft(gp.current)
    elif gp.loop_mode == "queue" and gp.current:
        gp.queue.append(gp.current)

    # ── AUTOPLAY ─────────────────────────────────────────────────────────────
    if not gp.queue and gp.autoplay and gp.loop_mode == "off":
        query = build_autoplay_query(gp.history)
        try:
            loop = asyncio.get_event_loop()
            videos = await loop.run_in_executor(None, lambda: search_multiple(query, 6))
            recent_set = set(gp.history[-10:])
            
            data = next((v for v in videos if v['title'] not in recent_set), None)
            
            if not data and videos:
                data = videos[0]
                
            if data:
                gp.queue.append(data)
                genre = detect_genre(gp.history)
                embed = discord.Embed(
                    title="🔮 Autoplay",
                    description=f"[{data['title']}]({data['url']})",
                    color=0x9B59B6,
                )
                embed.add_field(name="Género detectado", value=genre.replace("_", " ").title())
                embed.add_field(name="Historial analizado", value=f"{len(gp.history)} canciones")
                embed.set_footer(text=f"Query: {query}")
                if data.get("thumbnail"):
                    embed.set_thumbnail(url=data["thumbnail"])
                await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error autoplay: {e}")

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

        # Registrar en historial
        gp.history.append(data["title"])
        if len(gp.history) > 30:
            gp.history.pop(0)

        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(stream_url, **FFMPEG_OPTIONS),
            volume=gp.volume,
        )

        def after_play(error):
            if error:
                logger.error(f"Playback error: {error}")
            if vc.is_connected():
                asyncio.run_coroutine_threadsafe(play_next(ctx, vc), ctx.bot.loop)

        vc.play(source, after=after_play)
        await db.add_stat(ctx.guild.id)

        embed = discord.Embed(
            title="🎵 Reproduciendo",
            description=f"[{data['title']}]({data['url']})",
            color=0x1DB954,
        )
        embed.add_field(name="Duración", value=format_duration(data.get("duration", 0)))
        if gp.autoplay:
            embed.add_field(name="Autoplay", value="🔮 On")
        if data.get("thumbnail"):
            embed.set_thumbnail(url=data["thumbnail"])
        await ctx.send(embed=embed)

    except Exception as e:
        logger.error(f"Error cargando canción: {e}")
        await ctx.send(f"❌ No pude reproducir `{entry.get('title', '??')}`: {e}")
        if gp.queue:
            await play_next(ctx, vc)
        else:
            gp.current = None


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
            activity=discord.Activity(type=discord.ActivityType.listening, name="!help | Nation Bot")
        )

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Argumento faltante: `{error.param.name}`")
        elif isinstance(error, commands.CommandNotFound):
            pass
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"❌ Argumento inválido: {error}")
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ No tienes permisos para ejecutar este comando.")
        else:
            logger.error(f"Error en comando: {error}", exc_info=True)
            await ctx.send(f"❌ Error inesperado: {error}")

bot = NationBot()


# =========================================
# HELP
# =========================================

@bot.hybrid_command(name="help", description="Muestra todos los comandos")
async def help_cmd(ctx):
    embed = discord.Embed(title="🎧 Nation Bot — Comandos", color=0x1DB954, timestamp=datetime.utcnow())
    embed.add_field(name="🎵 Música", value=(
        "`!play <búsqueda/URL>` — Reproducir/añadir a cola\n"
        "`!pause` / `!resume` — Pausar / Reanudar\n"
        "`!skip` — Saltar canción\n"
        "`!stop` — Detener y desconectar\n"
        "`!queue` — Ver cola\n"
        "`!nowplaying` — Canción actual\n"
        "`!volume <0-100>` — Cambiar volumen"
    ), inline=False)
    embed.add_field(name="🎛️ DJ", value=(
        "`!shuffle` — Mezclar cola\n"
        "`!loop <off/track/queue>` — Modo loop\n"
        "`!autoplay` — Activar/desactivar autoplay inteligente 🔮\n"
        "`!remove <n>` — Eliminar de cola\n"
        "`!clearqueue` — Limpiar cola\n"
        "`!djrole <@rol>` — Asignar rol DJ (admin)"
    ), inline=False)
    embed.add_field(name="⭐ Favoritos", value=(
        "`!favadd` — Guardar canción actual\n"
        "`!favlist` — Ver tu playlist\n"
        "`!favremove <título>` — Eliminar de tu playlist\n"
        "`!favplay [número]` — Reproducir desde tu playlist"
    ), inline=False)
    embed.add_field(name="🎯 Descubrimiento", value=(
        "`!recommend [género]` — Recomendaciones por historial\n"
        "`!chat <pregunta>` — Ayuda y preguntas sobre el bot\n"
        "`!clearchat` — Limpiar historial del servidor"
    ), inline=False)
    embed.add_field(name="📊 Stats", value="`!stats` — Estadísticas + género dominante", inline=False)
    embed.set_footer(text="Nation Bot — 100% autónomo, sin IA externa ni APIs de pago")
    await ctx.send(embed=embed)


# =========================================
# MÚSICA
# =========================================

@bot.hybrid_command(name="play", description="Reproduce o añade una canción/playlist")
async def play(ctx, *, query: str):
    vc = await ensure_connected(ctx)
    if not vc:
        return
    if not ctx.interaction or not ctx.interaction.response.is_done():
        await ctx.defer()

    gp = get_guild_player(ctx.guild.id)
    try:
        loop = asyncio.get_event_loop()
        if "playlist?list=" in query or ("list=" in query and "youtube" in query):
            entries, pl_name = await loop.run_in_executor(None, lambda: get_playlist_entries(query))
            if not entries:
                return await ctx.send("❌ La playlist está vacía o no se pudo cargar.")
            for e in entries:
                gp.queue.append(e)
            await ctx.send(f"📋 Playlist añadida: **{pl_name}** ({len(entries)} canciones)")
        else:
            if query.startswith("http"):
                _, data = await loop.run_in_executor(None, lambda: get_audio_url(query))
            else:
                data = await loop.run_in_executor(None, lambda: search_youtube(query))

            if vc.is_playing() or vc.is_paused():
                gp.queue.append(data)
                embed = discord.Embed(title="➕ Añadido a la cola",
                                      description=f"[{data['title']}]({data['url']})", color=0x1DB954)
                embed.add_field(name="Duración", value=format_duration(data.get("duration", 0)))
                embed.add_field(name="Posición en cola", value=str(len(gp.queue)))
                return await ctx.send(embed=embed)
            gp.queue.append(data)
    except Exception as e:
        logger.error(f"Error en play: {e}", exc_info=True)
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
    if not vc or not vc.is_paused():
        return await ctx.send("❌ No hay reproducción pausada.")
    vc.resume()
    await ctx.send("▶ Reanudado.")


@bot.hybrid_command(name="skip", description="Salta la canción actual")
async def skip(ctx):
    if not await check_dj(ctx):
        return
    vc: discord.VoiceClient = ctx.guild.voice_client
    if not vc or not (vc.is_playing() or vc.is_paused()):
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
    if vc.is_playing() or vc.is_paused():
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
        title = t.get("title", "??")
        title_display = (title[:60] + "…") if len(title) > 60 else title
        desc += f"`{i}.` [{title_display}]({t.get('url','')}) — {format_duration(t.get('duration',0))}\n"
    if len(items) > 15:
        desc += f"\n*...y {len(items)-15} más*"
    embed = discord.Embed(title="📋 Cola de reproducción", description=desc or "*(vacía)*", color=0x1DB954)
    if gp.current:
        embed.set_author(name=f"Sonando: {gp.current.get('title','??')[:60]}")
    embed.set_footer(text=f"{len(items)} canciones • Autoplay {'🔮 On' if gp.autoplay else 'Off'}")
    await ctx.send(embed=embed)


@bot.hybrid_command(name="nowplaying", description="Muestra la canción actual")
async def nowplaying(ctx):
    gp = get_guild_player(ctx.guild.id)
    vc: discord.VoiceClient = ctx.guild.voice_client
    if not gp.current or not vc or not (vc.is_playing() or vc.is_paused()):
        return await ctx.send("❌ No hay nada reproduciéndose.")
    track = gp.current
    genre = detect_genre(gp.history).replace("_", " ").title() if gp.history else "—"
    embed = discord.Embed(title="🎵 Sonando ahora", color=0x1DB954)
    embed.description = f"**[{track.get('title','??')}]({track.get('url','')})**"
    embed.add_field(name="Duración", value=format_duration(track.get("duration", 0)))
    embed.add_field(name="Volumen",  value=f"{gp.volume_pct}%")
    embed.add_field(name="Loop",     value=gp.loop_mode)
    embed.add_field(name="Autoplay", value="🔮 On" if gp.autoplay else "Off")
    embed.add_field(name="Género",   value=genre)
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
    if not vc:
        return await ctx.send("❌ No estoy en ningún canal.")
    gp = get_guild_player(ctx.guild.id)
    gp.volume, gp.volume_pct = vol / 100, vol
    if vc.source:
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
async def loop_cmd(ctx, mode: str = "off"):
    if not await check_dj(ctx):
        return
    if mode not in ("off", "track", "queue"):
        return await ctx.send("❌ Modos válidos: `off`, `track`, `queue`")
    gp = get_guild_player(ctx.guild.id)
    gp.loop_mode = mode
    await ctx.send(f"{'➡️' if mode=='off' else '🔂' if mode=='track' else '🔁'} Loop: **{mode}**")


@bot.hybrid_command(name="autoplay", description="Activa/desactivar autoplay inteligente por historial")
async def autoplay_cmd(ctx):
    if not await check_dj(ctx):
        return
    gp = get_guild_player(ctx.guild.id)
    gp.autoplay = not gp.autoplay

    if gp.autoplay:
        genre = detect_genre(gp.history).replace("_", " ").title() if gp.history else "aún no detectado"
        embed = discord.Embed(
            title="🔮 Autoplay activado",
            description=(
                "Cuando la cola termine, el bot analizará el historial del servidor "
                "y buscará canciones del mismo género y artistas automáticamente.\n\n"
                f"**Historial:** {len(gp.history)} canciones registradas\n"
                f"**Género dominante:** {genre}"
            ),
            color=0x9B59B6,
        )
        embed.set_footer(text="Sin IA externa — algoritmo propio • !autoplay para desactivar")
    else:
        embed = discord.Embed(
            title="⏹ Autoplay desactivado",
            description="El bot ya no añadirá canciones automáticamente.",
            color=0x95A5A6,
        )
    await ctx.send(embed=embed)


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
    get_guild_player(ctx.guild.id).queue.clear()
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
    pos = await db.favadd(ctx.author.id, gp.current.get("title", "??"), gp.current.get("url"))
    await ctx.send(f"⭐ Guardado en posición **#{pos}**: **{gp.current.get('title','??')}**")


@bot.hybrid_command(name="favlist", description="Muestra tu playlist personal")
async def favlist(ctx):
    songs = await db.favlist(ctx.author.id)
    if not songs:
        return await ctx.send("📭 Tu playlist está vacía. Usa `!favadd` mientras suena algo.")
    lines = "\n".join(f"{s['position']}. {s['title'][:50]}" for s in songs[:30])
    embed = discord.Embed(
        title=f"⭐ Playlist de {ctx.author.display_name}",
        description=f"```\n{lines}\n```",
        color=0xFFD700,
    )
    embed.set_footer(text=f"{len(songs)} canciones • Usa !favplay <número> para reproducir")
    await ctx.send(embed=embed)


@bot.hybrid_command(name="favremove", description="Elimina una canción de tu playlist")
async def favremove(ctx, *, titulo: str):
    if await db.favremove(ctx.author.id, titulo):
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
        return await ctx.invoke(bot.get_command("play"), query=song["url"] or song["title"])

    vc = await ensure_connected(ctx)
    if not vc:
        return
    gp = get_guild_player(ctx.guild.id)
    for song in songs:
        gp.queue.append({"title": song["title"], "url": song["url"], "duration": None, "thumbnail": None})
    await ctx.send(f"⭐ Playlist cargada: **{len(songs)} canciones** añadidas a la cola.")
    if not vc.is_playing() and not vc.is_paused():
        await play_next(ctx, vc)


# =========================================
# DESCUBRIMIENTO — SIN IA EXTERNA
# =========================================

@bot.hybrid_command(name="recommend", description="Recomendaciones basadas en el historial del servidor")
async def recommend(ctx, *, genero: str = ""):
    await ctx.defer()
    gp      = get_guild_player(ctx.guild.id)
    queries = get_recommendations(gp.history, genero.strip() or None)
    loop    = asyncio.get_event_loop()
    results: list[dict] = []
    seen    = set(gp.history[-20:])

    for query in queries:
        try:
            videos = await loop.run_in_executor(None, lambda q=query: search_multiple(q, 3))
            for v in videos:
                if v['title'] not in seen and len(results) < 5:
                    results.append(v)
                    seen.add(v['title'])
            if len(results) >= 5:
                break
        except Exception as e:
            logger.warning(f"Recommend query '{query}' falló: {e}")

    if not results:
        return await ctx.send("❌ No encontré recomendaciones. Intenta reproducir algo primero.")

    genre_label = genero.strip() or (detect_genre(gp.history).replace("_", " ").title() if gp.history else "variado")
    desc = "".join(
        f"`{i}.` [{r['title'][:55]}]({r['url']}) — {format_duration(r.get('duration'))}\n"
        for i, r in enumerate(results, 1)
    )
    embed = discord.Embed(title=f"🎯 Recomendaciones — {genre_label}", description=desc, color=0x1DB954)
    embed.set_footer(text="Usa !play <URL o título> para añadir • Basado en historial del servidor")
    await ctx.send(embed=embed)


@bot.hybrid_command(name="chat", description="Pregúntame sobre música o comandos del bot")
async def chat(ctx, *, mensaje: str):
    response = process_chat(mensaje)
    embed = discord.Embed(description=response, color=0x7289DA)
    embed.set_author(name="Nation Bot", icon_url=bot.user.display_avatar.url)
    embed.set_footer(text="Respuestas integradas — sin APIs externas")
    await ctx.send(embed=embed)


@bot.hybrid_command(name="clearchat", description="Limpia el historial de reproducción del servidor")
async def clearchat(ctx):
    get_guild_player(ctx.guild.id).history.clear()
    await ctx.send("🧹 Historial limpiado. Autoplay y recomendaciones empezarán desde cero.")


# =========================================
# STATS
# =========================================

@bot.hybrid_command(name="stats", description="Muestra estadísticas del servidor")
async def stats(ctx):
    total = await db.get_stats(ctx.guild.id)
    gp    = get_guild_player(ctx.guild.id)
    genre = detect_genre(gp.history).replace("_", " ").title() if gp.history else "—"
    embed = discord.Embed(title=f"📊 Stats — {ctx.guild.name}", color=0x1DB954)
    embed.add_field(name="Canciones reproducidas", value=str(total))
    embed.add_field(name="Miembros",               value=str(ctx.guild.member_count))
    embed.add_field(name="Género dominante",        value=genre)
    embed.add_field(name="Historial en memoria",    value=f"{len(gp.history)} canciones")
    if ctx.guild.icon:
        embed.set_thumbnail(url=ctx.guild.icon.url)
    await ctx.send(embed=embed)


# =========================================
# AUTO-DISCONNECT
# =========================================

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    vc: discord.VoiceClient = member.guild.voice_client
    if not vc or not vc.channel:
        return
    if not any(m for m in vc.channel.members if not m.bot):
        gp = get_guild_player(member.guild.id)
        gp.queue.clear()
        gp.current = None
        if vc.is_playing() or vc.is_paused():
            vc.stop()
        await vc.disconnect()
        logger.info(f"Auto-desconectado de {vc.channel} (canal vacío).")


# =========================================
# ARRANQUE
# =========================================

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
