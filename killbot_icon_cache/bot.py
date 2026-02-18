
# bot.py
import os
import re
import json
import asyncio
import hashlib
import html
import difflib
import io
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Dict, List, Tuple, Any
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from dotenv import load_dotenv

# Killbot HTTP + optional image generation
import aiohttp
try:
    from PIL import Image, ImageDraw, ImageFont  # type: ignore
    PIL_OK = True
except ModuleNotFoundError:
    PIL_OK = False

# =========================================================
#                    MUSIC SYSTEM
# =========================================================
try:
    import yt_dlp
    YTDLP_OK = True
except ImportError:
    print("[WARN] yt-dlp yüklenemedi. Müzik özellikleri devre dışı.")
    YTDLP_OK = False

# =========================================================
#                  ACHIEVEMENTS SYSTEM (DEVRE DIŞI)
# =========================================================
# Başarım sistemi kaldırıldı
ACHIEVEMENTS_OK = False

# =========================================================
#                  ALBION ITEM SEARCH
# =========================================================
# Albion Online item veritabanı - /itemara komutu için
# İndirmek için: curl -sL 'https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/formatted/items.txt' -o albion_items.txt

ALBION_ITEMS_FILE = Path(__file__).parent / "albion_items.txt"

_albion_items_db: Dict[str, str] = {}  # item_id -> item_name
_albion_items_loaded: bool = False

def load_albion_items_db() -> bool:
    """Albion item veritabanını yükle."""
    global _albion_items_db, _albion_items_loaded
    
    if _albion_items_loaded:
        return True
    
    if not ALBION_ITEMS_FILE.exists():
        print(f"[ITEM] UYARI: {ALBION_ITEMS_FILE} bulunamadı!")
        return False
    
    try:
        with open(ALBION_ITEMS_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                # Format: "   1: T4_2H_CLAYMORE                    : Claymore"
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    item_id = parts[1].strip()
                    item_name = parts[2].strip()
                    if item_id and item_name:
                        _albion_items_db[item_id] = item_name
        
        _albion_items_loaded = True
        print(f"[ITEM] {len(_albion_items_db)} Albion item yüklendi.")
        return True
    except Exception as e:
        print(f"[ITEM] Yükleme hatası: {e}")
        return False

def search_albion_items(query: str, limit: int = 25) -> List[Tuple[str, str]]:
    """Item ara. Returns: [(item_id, item_name), ...]"""
    if not _albion_items_loaded:
        load_albion_items_db()
    
    query_lower = query.lower().strip()
    results = []
    
    for item_id, item_name in _albion_items_db.items():
        if query_lower in item_name.lower() or query_lower in item_id.lower():
            results.append((item_id, item_name))
            if len(results) >= limit:
                break
    
    return results

def get_albion_item_image_url(item_id: str, quality: int = 1) -> str:
    """Item görsel URL'si döndür."""
    return f"https://render.albiononline.com/v1/item/{item_id}.png?quality={quality}"

# =========================================================
#                  PLAYER LINK SYSTEM (Basit)
# =========================================================
# Discord-Albion bağlama sistemi (başarımlardan bağımsız)
from dataclasses import dataclass, asdict
from pathlib import Path
import json

_LINKS_FILE = Path(__file__).parent / "player_links.json"

@dataclass
class PlayerLink:
    discord_id: int
    albion_name: str
    albion_id: str
    linked_by: int = 0
    linked_at: str = ""

_player_links: Dict[int, PlayerLink] = {}  # discord_id -> PlayerLink
_albion_to_discord: Dict[str, int] = {}  # albion_id -> discord_id

def _load_player_links():
    global _player_links, _albion_to_discord
    try:
        if _LINKS_FILE.exists():
            data = json.loads(_LINKS_FILE.read_text(encoding="utf-8"))
            
            # Liste formatı (yeni format)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        try:
                            link = PlayerLink(
                                discord_id=int(item.get('discord_id', 0)),
                                albion_name=str(item.get('albion_name', '')),
                                albion_id=str(item.get('albion_id', '')),
                                linked_by=int(item.get('linked_by', 0)),
                                linked_at=str(item.get('linked_at', ''))
                            )
                            if link.discord_id and link.albion_id:
                                _player_links[link.discord_id] = link
                                _albion_to_discord[link.albion_id] = link.discord_id
                        except Exception as e:
                            print(f"[LINK] Satır yükleme hatası: {e}")
            
            # Dict formatı (eski format - discord_id -> data)
            elif isinstance(data, dict):
                for discord_id_str, item in data.items():
                    try:
                        if isinstance(item, dict):
                            link = PlayerLink(
                                discord_id=int(discord_id_str),
                                albion_name=str(item.get('albion_name', '')),
                                albion_id=str(item.get('albion_id', '')),
                                linked_by=int(item.get('linked_by', 0)),
                                linked_at=str(item.get('linked_at', ''))
                            )
                        elif isinstance(item, str):
                            # Çok eski format - sadece albion_id string
                            link = PlayerLink(
                                discord_id=int(discord_id_str),
                                albion_name="",
                                albion_id=str(item),
                                linked_by=0,
                                linked_at=""
                            )
                        else:
                            continue
                        
                        if link.discord_id and link.albion_id:
                            _player_links[link.discord_id] = link
                            _albion_to_discord[link.albion_id] = link.discord_id
                    except Exception as e:
                        print(f"[LINK] Satır yükleme hatası ({discord_id_str}): {e}")
            
            print(f"[LINK] {len(_player_links)} oyuncu bağlantısı yüklendi.")
            
            # Yeni formata kaydet
            if _player_links:
                _save_player_links()
    except Exception as e:
        print(f"[LINK] Yükleme hatası: {e}")

def _save_player_links():
    try:
        data = [asdict(link) for link in _player_links.values()]
        _LINKS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"[LINK] Kaydetme hatası: {e}")

def link_player(discord_id: int, albion_name: str, albion_id: str, linked_by: int = 0):
    """Discord-Albion bağlantısı oluşturur."""
    from datetime import datetime
    link = PlayerLink(
        discord_id=discord_id,
        albion_name=albion_name,
        albion_id=albion_id,
        linked_by=linked_by,
        linked_at=datetime.now().isoformat()
    )
    _player_links[discord_id] = link
    _albion_to_discord[albion_id] = discord_id
    _save_player_links()
    print(f"[LINK] Bağlandı: {albion_name} ({albion_id}) <-> Discord {discord_id}")

def unlink_player(discord_id: int):
    """Discord-Albion bağlantısını kaldırır."""
    if discord_id in _player_links:
        link = _player_links[discord_id]
        if link.albion_id in _albion_to_discord:
            del _albion_to_discord[link.albion_id]
        del _player_links[discord_id]
        _save_player_links()
        print(f"[LINK] Bağlantı kaldırıldı: Discord {discord_id}")

def get_link_by_discord(discord_id: int) -> Optional[PlayerLink]:
    """Discord ID'ye göre bağlantıyı döndürür."""
    return _player_links.get(discord_id)

def get_discord_by_albion_id(albion_id: str) -> Optional[int]:
    """Albion ID'ye göre Discord ID döndürür."""
    return _albion_to_discord.get(albion_id)

def get_discord_by_albion_name(albion_name: str) -> Optional[int]:
    """Albion ismine göre Discord ID döndürür."""
    for link in _player_links.values():
        if link.albion_name.lower() == albion_name.lower():
            return link.discord_id
    return None

# Başlangıçta yükle
_load_player_links()

PLAYER_LINK_OK = True

# =========================================================
#                      BASIC SETUP
# =========================================================

# ===== TZ (py3.8 uyumlu) =====
try:
    from zoneinfo import ZoneInfo  # py3.9+
    TR_TZ = ZoneInfo("Europe/Istanbul")
except ModuleNotFoundError:
    import pytz
    TR_TZ = pytz.timezone("Europe/Istanbul")

UTC_TZ = timezone.utc

load_dotenv()

# =========================
# Battleboard (AlbionBB list + AO API rows) - py3.8 safe
# =========================
BATTLEBOARD_CHANNEL_ID = int(os.getenv("BATTLEBOARD_CHANNEL_ID", "1456372978995433706"))
# Uses your guild id already present in env (AO_GUILD_ID). Falls back to CALLIDUS guild id if missing.
_AO_GID = os.getenv("AO_GUILD_ID", "A8Iv8vP2RLOWg5u5rUDZJA")
ALBIONBB_GUILD_BATTLES_URL = os.getenv(
    "ALBIONBB_GUILD_BATTLES_URL",
    "https://europe.albionbb.com/guilds/%s/battles?minPlayers=5" % _AO_GID
)
BATTLEBOARD_POLL_SECONDS = int(os.getenv("BATTLEBOARD_POLL_SECONDS", "60"))
MIN_CALLIDUS_PLAYERS = int(os.getenv("MIN_CALLIDUS_PLAYERS", "6"))
AO_API_BASE = os.getenv("AO_API_BASE", "https://gameinfo-ams.albiononline.com/api/gameinfo").rstrip("/")
_BB_STATE_FILE = os.getenv("BATTLEBOARD_STATE_FILE", "battleboard_state.json")

def _bb_log(msg: str) -> None:
    try:
        print("[BB]", msg)
    except Exception:
        pass

def _bb_load_state() -> Dict[str, Any]:
    try:
        from pathlib import Path
        import json
        return json.loads(Path(_BB_STATE_FILE).read_text(encoding="utf-8"))
    except Exception:
        return {}

def _bb_save_state(st: Dict[str, Any]) -> None:
    try:
        from pathlib import Path
        import json
        Path(_BB_STATE_FILE).write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def _bb_albionbb_link(battle_id: int) -> str:
    return "https://europe.albionbb.com/battles/%s" % int(battle_id)

def _bb_fmt_k(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        return str(n)
    if n >= 1_000_000:
        return ("%0.1fm" % (n / 1_000_000)).rstrip("0").rstrip(".")
    if n >= 1_000:
        return "%dk" % int(round(n / 1000.0))
    return str(n)

async def _bb_http_text(url: str) -> Optional[str]:
    try:
        import aiohttp
        async with aiohttp.ClientSession(headers={"User-Agent": "CALLIDUS-DiscordBot/1.0"}) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                return await resp.text()
    except Exception:
        return None

async def _bb_http_json(url: str) -> Optional[Dict[str, Any]]:
    try:
        import aiohttp
        async with aiohttp.ClientSession(headers={"User-Agent": "CALLIDUS-DiscordBot/1.0"}) as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                j = await resp.json()
                return j if isinstance(j, dict) else None
    except Exception:
        return None

async def _bb_pick_battle_id(n: int) -> Optional[int]:
    """
    n is 1-based: 1=latest, 2=previous, ...
    We only use AlbionBB for LISTING (battle ids) because its battle detail pages are JS-rendered.
    """
    txt = await _bb_http_text(ALBIONBB_GUILD_BATTLES_URL)
    if not txt:
        return None
    ids = re.findall(r"/battles/(\d+)", txt)
    if not ids:
        return None
    seen: List[str] = []
    for x in ids:
        if x not in seen:
            seen.append(x)
    idx = max(0, int(n) - 1)
    if idx >= len(seen):
        return None
    return int(seen[idx])

def _bb_rows_from_ao(detail: Dict[str, Any]) -> List[Dict[str, Any]]:
    guilds = detail.get("guilds") or {}
    players = detail.get("players") or {}
    counts: Dict[str, int] = {}
    for p in players.values():
        gid = (p.get("guildId") or "").strip()
        if gid:
            counts[gid] = counts.get(gid, 0) + 1

    rows: List[Dict[str, Any]] = []
    for gid, g in guilds.items():
        rows.append({
            "guild": g.get("name") or "Unknown",
            "alliance": g.get("alliance") or "-",
            "players": int(counts.get(gid, 0)),
            "kills": int(g.get("kills") or 0),
            "deaths": int(g.get("deaths") or 0),
            "fame": int(g.get("killFame") or 0),
        })
    rows.sort(key=lambda r: (r["fame"], r["kills"]), reverse=True)
    return rows

def _bb_callidus_players(detail: Dict[str, Any]) -> int:
    gid = (os.getenv("AO_GUILD_ID", "") or "").strip() or (globals().get("_AO_GID") or "")
    if not gid:
        return 0
    players = detail.get("players") or {}
    c = 0
    for p in players.values():
        if (p.get("guildId") or "").strip() == gid:
            c += 1
    return c


def _bb_table(rows: List[Dict[str, Any]]) -> str:
    top = rows[:10]
    gw = min(20, max([5] + [len(r["guild"]) for r in top]))
    aw = min(10, max([7] + [len((r.get("alliance") or "-")) for r in top]))
    head = f'{"Guild":<{gw}}  {"Alliance":<{aw}}  {"P":>2}  {"K":>2}  {"D":>2}  {"Fame":>6}'
    lines = [head]
    for r in top:
        g = r["guild"]
        a = r.get("alliance") or "-"
        if len(g) > gw:
            g = g[:gw-1] + "…"
        if len(a) > aw:
            a = a[:aw-1] + "…"
        lines.append(f'{g:<{gw}}  {a:<{aw}}  {r["players"]:>2}  {r["kills"]:>2}  {r["deaths"]:>2}  {_bb_fmt_k(r["fame"]):>6}')
    return "```\n" + "\n".join(lines) + "\n```"

async def _bb_post_battleboard(client: discord.Client, battle_id: int) -> bool:
    detail = await _bb_http_json("%s/battles/%s" % (AO_API_BASE, int(battle_id)))
    if not detail:
        return False
    callidus_p = _bb_callidus_players(detail)
    if callidus_p < MIN_CALLIDUS_PLAYERS:
        return False
    rows = _bb_rows_from_ao(detail)
    if not rows:
        return False

    ch = client.get_channel(BATTLEBOARD_CHANNEL_ID)
    if ch is None:
        return False

    total_fame = int(detail.get("totalFame") or 0)
    total_kills = int(detail.get("totalKills") or 0)

    embed = discord.Embed(
        title="Battle #%s" % int(battle_id),
        description=_bb_table(rows)
    )
    embed.add_field(name="Toplam", value="Fame: **%s** | Öldürme: **%s**" % (_bb_fmt_k(total_fame), total_kills), inline=False)
    embed.add_field(name="Link", value=_bb_albionbb_link(battle_id), inline=False)

    await ch.send(embed=embed)
    return True

async def _bb_worker(client: discord.Client):
    await client.wait_until_ready()
    st = _bb_load_state()
    last = int(st.get("last_battle_id") or 0)

    while not client.is_closed():
        try:
            battle_id = await _bb_pick_battle_id(1)
            if battle_id and battle_id > last:
                ok = await _bb_post_battleboard(client, battle_id)
                # Advance state even if we skip (e.g., CALLIDUS players < threshold)
                last = battle_id
                st["last_battle_id"] = last
                _bb_save_state(st)
        except Exception as e:
            _bb_log("worker error: %r" % (e,))
        await asyncio.sleep(BATTLEBOARD_POLL_SECONDS)



TOKEN = os.getenv("DISCORD_TOKEN", "")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
PING_ROLE_ID = int(os.getenv("PING_ROLE_ID", "0"))

GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON", "")
AVASKIP_SHEET_ID = os.getenv("AVASKIP_SHEET_ID", "")

# Sheet tabs (isimler Sheet'te birebir böyle olmalı)
AVASKIP_SHEET_TAB = os.getenv("AVASKIP_SHEET_TAB", "Sayfa1")
TENMAN_SHEET_TAB = os.getenv("TENMAN_SHEET_TAB", "10MAN")

# Brawl Comp (Sheet)
# Not: Sheet ID public linkten çıkarıldı; istersen .env içinden BRAWLCOMP_SHEET_ID ile override edebilirsin.
DEFAULT_BRAWLCOMP_SHEET_ID = "1u14evQnfGsA0lV5o40et7fg9ook9EVRnfhL423wRIZs"
BRAWLCOMP_SHEET_ID = os.getenv("BRAWLCOMP_SHEET_ID", DEFAULT_BRAWLCOMP_SHEET_ID).strip()
# Sheet tab adı (Sheet'te birebir aynı olmalı)
BRAWLCOMP_SHEET_TAB = os.getenv("BRAWLCOMP_SHEET_TAB", "Browl Comp").strip()
# ===== DYNAMIC SHEET CONTENT (persistent) =====
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DYNAMIC_SHEETS_FILE = os.path.join(BASE_DIR, "dynamic_sheets.json")

# key -> {"name": str, "sheet_id": str, "tab": str, "emoji": str}
DYNAMIC_SHEETS: Dict[str, Dict[str, str]] = {}

def _load_dynamic_sheets() -> None:
    global DYNAMIC_SHEETS
    try:
        if not os.path.exists(DYNAMIC_SHEETS_FILE):
            DYNAMIC_SHEETS = {}
            return
        with open(DYNAMIC_SHEETS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            # normalize
            out: Dict[str, Dict[str, str]] = {}
            for k, v in data.items():
                if not isinstance(k, str) or not isinstance(v, dict):
                    continue
                name = str(v.get("name", k)).strip()
                sheet_id = str(v.get("sheet_id", "")).strip()
                tab = str(v.get("tab", "")).strip()
                emoji = str(v.get("emoji", "📄")).strip() or "📄"
                if name and sheet_id and tab:
                    out[k.strip()] = {"name": name, "sheet_id": sheet_id, "tab": tab, "emoji": emoji}
            DYNAMIC_SHEETS = out
        else:
            DYNAMIC_SHEETS = {}
    except Exception:
        DYNAMIC_SHEETS = {}

def _save_dynamic_sheets() -> None:
    try:
        with open(DYNAMIC_SHEETS_FILE, "w", encoding="utf-8") as f:
            json.dump(DYNAMIC_SHEETS, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _slug_key(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return (s[:32] or "sheet")

def _extract_sheet_id(inp: str) -> str:
    t = (inp or "").strip()
    # URL: .../spreadsheets/d/<ID>/...
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", t)
    if m:
        return m.group(1)
    # sometimes just ID
    m = re.search(r"^([a-zA-Z0-9_-]{20,})$", t)
    if m:
        return m.group(1)
    # last resort: find something ID-like
    m = re.search(r"([a-zA-Z0-9_-]{25,})", t)
    return m.group(1) if m else ""

SHEET_REF_DELIM = "||"

def _make_sheet_ref(sheet_id: str, tab: str) -> str:
    return f"{(sheet_id or '').strip()}{SHEET_REF_DELIM}{(tab or '').strip()}"

def _split_sheet_ref(tab_or_ref: str) -> Tuple[Optional[str], str]:
    s = (tab_or_ref or "").strip()
    if SHEET_REF_DELIM in s:
        left, right = s.split(SHEET_REF_DELIM, 1)
        left = left.strip()
        right = right.strip()
        if left and right and len(left) >= 20:
            return left, right
    return None, s

def _display_tab(tab_or_ref: str) -> str:
    return _split_sheet_ref(tab_or_ref)[1]

def sheet_url_for_tab(tab_or_ref: str) -> str:
    """Return a Google Sheets URL for the given tab or tab-ref."""
    try:
        sid, _tab = _split_sheet_ref(tab_or_ref)
        if not sid:
            sid = _resolve_sheet_id_for_tab(tab_or_ref)
        sid = (sid or '').strip()
        if sid:
            return f"https://docs.google.com/spreadsheets/d/{sid}/edit"
    except Exception:
        pass
    return SHEET_URL


_load_dynamic_sheets()

if not TOKEN or not GUILD_ID:
    raise SystemExit("DISCORD_TOKEN ve GUILD_ID .env içinde olmalı.")

DEFAULT_MOUNT = "T5 Horse"
DEFAULT_AYAR_FALLBACK = "+? Ayar"

# =========================================================
#                   WELCOME / VERIFY / TICKET CONFIG
# =========================================================
WELCOME_CHANNEL_ID = 1431224559125921812
WELCOME_GUILD_NAME = "CALLIDUS"

VERIFY_CHANNEL_ID = 1419391355041615993
VERIFY_ROLE_ID = 1431227867944980490  # recruit rolü

TICKET_CHANNEL_ID = 1445355841015386235
TICKET_CATEGORY_ID = 1445355712254578740
TICKET_STAFF_ROLE_ID = 1427410524693467269

LEAVE_LOG_CHANNEL_ID = 1445358898726047744  # Ayrılan üyeler log kanalı

# =========================================================
#                   ACTIVITY TRACKING CONFIG
# =========================================================
ACTIVITY_STATE_FILE = os.path.join(BASE_DIR, "activity_state.json")
ACTIVITY_INACTIVITY_DAYS = 5  # Kaç gün sonra DM gönderilsin

def _load_activity_state() -> Dict[str, Any]:
    try:
        if os.path.exists(ACTIVITY_STATE_FILE):
            with open(ACTIVITY_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"users": {}, "warned_users": []}

def _save_activity_state(state: Dict[str, Any]) -> None:
    try:
        with open(ACTIVITY_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _get_user_activity(state: Dict[str, Any], user_id: int) -> Dict[str, Any]:
    """Kullanıcının aktivite verisini döndürür, yoksa oluşturur."""
    user_id_str = str(user_id)
    if user_id_str not in state["users"]:
        state["users"][user_id_str] = {
            "content_joins": 0,
            "kills": 0,
            "deaths": 0,
            "kill_fame": 0,
            "voice_minutes": 0,
            "last_activity": None,
            "last_activity_type": None
        }
    return state["users"][user_id_str]

def _update_activity(user_id: int, activity_type: str, **kwargs):
    """Kullanıcının aktivitesini günceller."""
    state = _load_activity_state()
    user_data = _get_user_activity(state, user_id)
    
    now = datetime.now(UTC_TZ).isoformat()
    user_data["last_activity"] = now
    user_data["last_activity_type"] = activity_type
    
    if activity_type == "content":
        user_data["content_joins"] = user_data.get("content_joins", 0) + 1
    elif activity_type == "kill":
        user_data["kills"] = user_data.get("kills", 0) + 1
        user_data["kill_fame"] = user_data.get("kill_fame", 0) + kwargs.get("fame", 0)
    elif activity_type == "death":
        user_data["deaths"] = user_data.get("deaths", 0) + 1
    elif activity_type == "voice":
        user_data["voice_minutes"] = user_data.get("voice_minutes", 0) + kwargs.get("minutes", 0)
    
    # Uyarı listesinden çıkar (aktif oldu)
    user_id_str = str(user_id)
    if user_id_str in state.get("warned_users", []):
        state["warned_users"].remove(user_id_str)
    
    _save_activity_state(state)

# Ticket sayacı için dosya
TICKET_STATE_FILE = os.path.join(BASE_DIR, "ticket_state.json")

def _load_ticket_state() -> Dict[str, Any]:
    try:
        if os.path.exists(TICKET_STATE_FILE):
            with open(TICKET_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"counter": 0}

def _save_ticket_state(state: Dict[str, Any]) -> None:
    try:
        with open(TICKET_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

SHEET_URL = os.getenv(
    "SHEET_URL",
    "https://docs.google.com/spreadsheets/d/182lp2yRDlTNAq9QOwxvwir_jY5ELjFiRBKJcDLOUBYY/edit?usp=sharing",
)

def log(*args):
    print("[BOT]", *args)

# Run blocking I/O in thread (py3.8 uyumlu) - heartbeat bloklamasın
async def run_io(fn, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: fn(*args, **kwargs))

# =========================================================
#                   ALBION KILLBOT CONFIG
# =========================================================
# Albion guild id (string) - Discord guild id ile karışmasın
AO_GUILD_ID = (os.getenv("AO_GUILD_ID") or os.getenv("ALBION_KILLBOT_GUILD_ID") or "A8Iv8vP2RLOWg5u5rUDZJA").strip()

KILLBOARD_CHANNEL_ID = int(os.getenv("KILLBOARD_CHANNEL_ID", "1431253511324045405"))
DEATHBOARD_CHANNEL_ID = int(os.getenv("DEATHBOARD_CHANNEL_ID", "1439314025765666977"))

AO_API_BASE = os.getenv("AO_API_BASE", "https://gameinfo-ams.albiononline.com/api/gameinfo").rstrip("/")
KILLBOT_POLL_SECONDS = int(os.getenv("KILLBOT_POLL_SECONDS", "30"))
KILLBOT_BOOTSTRAP_BACKFILL = int(os.getenv("KILLBOT_BOOTSTRAP_BACKFILL", "0"))  # 1: ilk açılışta son olayı bas

KILLBOT_STATE_FILE = os.getenv("KILLBOT_STATE_FILE", "killbot_state.json")

# Killboard link mode: "albion" (official) or "murder" (MurderLedger)
KILLBOT_LINK_MODE = (os.getenv("KILLBOT_LINK_MODE", "albion") or "albion").strip().lower()
if KILLBOT_LINK_MODE in ("murder", "murderledger", "ml"):
    KILLBOT_LINK_MODE = "murder"
else:
    KILLBOT_LINK_MODE = "albion"

MURDERLEDGER_BASE_URL = (os.getenv("MURDERLEDGER_BASE_URL", "https://murderledger-europe.albiononline2d.com") or "").strip().rstrip("/")
MURDERLEDGER_KILL_URL_TEMPLATE = (os.getenv("MURDERLEDGER_KILL_URL_TEMPLATE", f"{MURDERLEDGER_BASE_URL}/kill/{{event_id}}") or "").strip()

_KB_LINK_MODE = KILLBOT_LINK_MODE
def _kb_set_link_mode(mode: str) -> str:
    global _KB_LINK_MODE
    m = (mode or "").strip().lower()
    if m in ("murder", "murderledger", "ml"):
        _KB_LINK_MODE = "murder"
    else:
        _KB_LINK_MODE = "albion"
    return _KB_LINK_MODE
# Killboard kill source mode:
#   - guild   : Killboard guild events feed'den gelir (eski yöntem)
#   - members : Killboard, guild üye listesi -> player /kills üzerinden gelir
# Deathboard her zaman members üzerinden gelir (daha güvenilir).
KILLBOT_KILL_MODE = os.getenv("KILLBOT_KILL_MODE", os.getenv("KILLBOT_MODE", "guild")).strip().lower()
if KILLBOT_KILL_MODE in ("member", "members", "user", "users", "uye", "üyeler"):
    KILLBOT_KILL_MODE = "members"
else:
    KILLBOT_KILL_MODE = "guild"

KILLBOT_MEMBER_REFRESH_SECONDS = int(os.getenv("KILLBOT_MEMBER_REFRESH_SECONDS", "900"))  # 15 dk
KILLBOT_MEMBER_EVENTS_LIMIT = int(os.getenv("KILLBOT_MEMBER_EVENTS_LIMIT", "10"))        # /kills & /deaths
KILLBOT_MEMBER_CONCURRENCY = int(os.getenv("KILLBOT_MEMBER_CONCURRENCY", "6"))
KILLBOT_MEMBER_SEEN_MAX = int(os.getenv("KILLBOT_MEMBER_SEEN_MAX", "5000"))  # Artırıldı - daha fazla event hatırla
KILLBOT_MEMBER_IDS = os.getenv("KILLBOT_MEMBER_IDS", "").strip()  # opsiyonel: virgülle playerId listesi

# Eski event filtresi - bu süreden eski eventler ATILMAZ (saat cinsinden)
KILLBOT_MAX_EVENT_AGE_HOURS = int(os.getenv("KILLBOT_MAX_EVENT_AGE_HOURS", "24"))  # 24 saat
# State dosyası bozulma koruması
KILLBOT_STATE_BACKUP_FILE = os.getenv("KILLBOT_STATE_BACKUP_FILE", "killbot_state.backup.json")


KILLBOT_RENDER_SIZE = int(os.getenv("KILLBOT_RENDER_SIZE", "72"))
KILLBOT_ICON_CACHE_MAX = int(os.getenv("KILLBOT_ICON_CACHE_MAX", "600"))
KILLBOT_ICON_CONCURRENCY = int(os.getenv("KILLBOT_ICON_CONCURRENCY", "10"))
KILLBOT_ICON_RETRIES = int(os.getenv("KILLBOT_ICON_RETRIES", "2"))
KILLBOT_ICON_DISK_CACHE = os.getenv("KILLBOT_ICON_DISK_CACHE", "1").strip() not in ("0", "false", "False", "no")
KILLBOT_ICON_DISK_DIR = (os.getenv("KILLBOT_ICON_DISK_DIR", "killbot_icon_cache") or "killbot_icon_cache").strip()
KILLBOT_PARTICIPANTS_MAX_LINES = int(os.getenv("KILLBOT_PARTICIPANTS_MAX_LINES", "250"))
KILLBOT_STATS_TOP_DMG = int(os.getenv("KILLBOT_STATS_TOP_DMG", "8"))
KILLBOT_STATS_TOP_HEAL = int(os.getenv("KILLBOT_STATS_TOP_HEAL", "5"))

KILLBOT_MAX_LOST_LINES = int(os.getenv("KILLBOT_MAX_LOST_LINES", "28"))
# =========================
# Battleboard (AO data + AlbionBB link)
# =========================
BATTLEBOARD_CHANNEL_ID = int(os.getenv("BATTLEBOARD_CHANNEL_ID", "1456372978995433706"))
BATTLEBOARD_POLL_SECONDS = int(os.getenv("BATTLEBOARD_POLL_SECONDS", "60"))
BATTLEBOARD_STATE_FILE = os.getenv("BATTLEBOARD_STATE_FILE", "battleboard_state.json")
BATTLEBOARD_MIN_GUILD_PLAYERS = int(os.getenv("BATTLEBOARD_MIN_GUILD_PLAYERS", "5"))
BATTLEBOARD_MIN_TOTAL_FAME = int(os.getenv("BATTLEBOARD_MIN_TOTAL_FAME", "0"))
ALBIONBB_BASE = os.getenv("ALBIONBB_BASE", "https://europe.albionbb.com").rstrip("/")


KILLBOT_IMAGE_ENABLED = os.getenv("KILLBOT_IMAGE_ENABLED", "1").strip() not in ("0", "false", "False", "no")
KILLBOT_GUILD_LOGO_FILE = os.getenv("KILLBOT_GUILD_LOGO_FILE", "guild.png")


# =========================================================
#                TRANSLATION CHANNEL (AUTO)
# =========================================================
# İstersen .env:
#   TRANSLATE_CHANNEL_IDS=123,456
# veya:
#   TRANSLATE_CHANNEL_ID=123
TRANSLATE_CHANNEL_ID = int(os.getenv("TRANSLATE_CHANNEL_ID", "0"))
TRANSLATE_CHANNEL_IDS = os.getenv("TRANSLATE_CHANNEL_IDS", "").strip()
LOCALIZATION_PAIRS_TSV = os.getenv("LOCALIZATION_PAIRS_TSV", "pairs.tsv")

LOC_TUID: Dict[str, Tuple[str, str]] = {}       # "@KEY" -> (en, tr)
LOC_EN_NORM: Dict[str, Tuple[str, str]] = {}    # norm(en) -> (en, tr)
LOC_TR_NORM: Dict[str, Tuple[str, str]] = {}    # norm(tr) -> (en, tr)
LOC_EN_BUCKET: Dict[str, List[str]] = {}        # firstchar -> [norm_en,...]
LOC_LOADED = False

def _unesc_cell(s: str) -> str:
    return (s or "").replace("\\n", "\n").strip()

def _norm_text(s: str) -> str:
    s = _unesc_cell(s)
    s = html.unescape(s)
    s = s.lower().strip()
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s\-\+\.\'’/]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def load_localization_pairs(path: str) -> None:
    global LOC_LOADED
    if LOC_LOADED:
        return
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    continue

                parts = line.split("\t")
                if len(parts) < 2:
                    continue

                tuid = ""
                en = ""
                tr = ""

                if len(parts) >= 3:
                    tuid = (parts[0] or "").strip()
                    en = _unesc_cell(parts[1])
                    tr = _unesc_cell(parts[2])
                else:
                    en = _unesc_cell(parts[0])
                    tr = _unesc_cell(parts[1])

                if (en.lower() == "en" and tr.lower() == "tr") or (tuid.lower() == "tuid" and en.lower() == "en"):
                    continue
                if not en or not tr:
                    continue

                if tuid and tuid.startswith("@") and tuid not in LOC_TUID:
                    LOC_TUID[tuid] = (en, tr)

                ne = _norm_text(en)
                nt = _norm_text(tr)

                if ne and ne not in LOC_EN_NORM:
                    LOC_EN_NORM[ne] = (en, tr)
                    LOC_EN_BUCKET.setdefault(ne[:1], []).append(ne)

                if nt and nt not in LOC_TR_NORM:
                    LOC_TR_NORM[nt] = (en, tr)

        LOC_LOADED = True
        log(f"✅ Çeviri yüklendi: {path} | EN={len(LOC_EN_NORM)} TR={len(LOC_TR_NORM)} TUID={len(LOC_TUID)}")
    except Exception as e:
        log("❌ Çeviri yüklenemedi:", repr(e))
        LOC_LOADED = False

def lookup_en_tr(query: str) -> Optional[Tuple[str, str, str]]:
    """
    Returns (en, tr, how) or None
    how: "tuid" | "exact-en" | "exact-tr" | "contains" | "fuzzy"
    """
    q = (query or "").strip()
    if not q:
        return None

    if q.startswith("@") and q in LOC_TUID:
        en, tr = LOC_TUID[q]
        return (en, tr, "tuid")

    q = q.splitlines()[0].strip()

    if " / " in q:
        q = q.split(" / ", 1)[0].strip()
    elif "/" in q:
        q = q.split("/", 1)[0].strip()

    nq = _norm_text(q)

    if nq in LOC_EN_NORM:
        en, tr = LOC_EN_NORM[nq]
        return (en, tr, "exact-en")
    if nq in LOC_TR_NORM:
        en, tr = LOC_TR_NORM[nq]
        return (en, tr, "exact-tr")

    if len(nq) >= 4:
        for ne, (en, tr) in LOC_EN_NORM.items():
            if nq in ne:
                return (en, tr, "contains")

    key = nq[:1] if nq else ""
    cand = LOC_EN_BUCKET.get(key, [])
    if cand:
        best = difflib.get_close_matches(nq, cand, n=1, cutoff=0.78)
        if best:
            en, tr = LOC_EN_NORM[best[0]]
            return (en, tr, "fuzzy")

    return None

def _parse_translate_channel_ids() -> List[int]:
    ids: List[int] = []
    if TRANSLATE_CHANNEL_ID:
        ids.append(int(TRANSLATE_CHANNEL_ID))
    if TRANSLATE_CHANNEL_IDS:
        for p in TRANSLATE_CHANNEL_IDS.split(","):
            p = p.strip()
            if not p:
                continue
            try:
                ids.append(int(p))
            except Exception:
                pass
    out = []
    seen = set()
    for i in ids:
        if i and i not in seen:
            out.append(i); seen.add(i)
    return out

TRANSLATE_IDS = _parse_translate_channel_ids()

def is_translation_channel(ch: discord.abc.Messageable) -> bool:
    try:
        if isinstance(ch, discord.TextChannel):
            if ch.id in TRANSLATE_IDS:
                return True
            if not TRANSLATE_IDS:
                nm = (ch.name or "").lower()
                if any(k in nm for k in ("çeviri", "ceviri", "translate", "translation")):
                    return True
    except Exception:
        pass
    return False

# =========================================================
#                    SAFE INTERACTION HELPERS
# =========================================================
async def safe_defer(interaction: discord.Interaction, ephemeral: bool = True) -> bool:
    try:
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=ephemeral)
        return True
    except discord.NotFound:
        return False
    except Exception as e:
        log("safe_defer error:", repr(e))
        return False

async def safe_send(
    interaction: discord.Interaction,
    content: str,
    *,
    ephemeral: bool = True,
    view: Optional[discord.ui.View] = None,
    embed: Optional[discord.Embed] = None,
) -> None:
    kwargs: Dict[str, Any] = {"ephemeral": ephemeral}
    if view is not None:
        kwargs["view"] = view
    if embed is not None:
        kwargs["embed"] = embed

    try:
        if not interaction.response.is_done():
            await interaction.response.send_message(content, **kwargs)
            return
    except discord.NotFound:
        return
    except Exception as e:
        log("safe_send response error:", repr(e))

    try:
        await interaction.followup.send(content, **kwargs)
        return
    except discord.NotFound:
        return
    except Exception as e:
        log("safe_send followup error:", repr(e))

# =========================================================
#                      TIME FORMAT
# =========================================================
def _normalize_time_input(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return s
    if re.fullmatch(r"\d{1,2}\.\d{2}", s):
        return s.replace(".", ":")
    return s

def fmt_time(time_tr: Optional[str]) -> Tuple[str, str]:
    if not time_tr or not str(time_tr).strip():
        return ("BELİRTİLMEMİŞ", "BELİRTİLMEMİŞ")

    raw = str(time_tr).strip()
    s = _normalize_time_input(raw)

    # Serbest yazıysa TR'yi olduğu gibi tut, UTC belirtme
    if not re.fullmatch(r"\d{1,2}:\d{2}", s):
        return (raw, "BELİRTİLMEMİŞ")

    hh, mm = map(int, s.split(":"))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError("Saat 00:00 ile 23:59 arasında olmalı.")

    now_tr = datetime.now(TR_TZ)
    dt_tr = now_tr.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if dt_tr < now_tr - timedelta(minutes=1):
        dt_tr += timedelta(days=1)

    dt_utc = dt_tr.astimezone(UTC_TZ)
    day_shift = (dt_utc.date() - dt_tr.date()).days
    suffix = " (+1d)" if day_shift == 1 else " (-1d)" if day_shift == -1 else ""
    return (dt_tr.strftime("%H:%M"), dt_utc.strftime("%H:%M") + suffix)

# =========================================================
#                 NORMAL EVENT (ROLE MAPPING)
# =========================================================
ROLE_LABELS: Dict[str, str] = {
    "tank": "🛡️ Tank",
    "engage_tank": "🔰 Engage Tank",
    "def_tank": "🔰 Def Tank",
    "dps": "🗡️ DPS",
    "pierce": "🎯 Pierce",
    "healer": "💚 Healer",
    "support": "💠 Support",
    "sc": "🌀 Spirithunter / Shadowcaller",
    "perma": "❄️ Perma",
    "wailing": "🏹 Wailing (BOW)",
    "fill": "🟨 Fill",
}
ROLE_EMOJI: Dict[str, str] = {
    "tank": "🛡️",
    "engage_tank": "🔰",
    "def_tank": "🔰",
    "dps": "🗡️",
    "pierce": "🎯",
    "healer": "💚",
    "support": "💠",
    "sc": "🌀",
    "perma": "❄️",
    "wailing": "🏹",
    "fill": "🟨",
}
THREAD_KEYWORDS: Dict[str, str] = {
    "tank": "tank", "t": "tank",
    "engage": "engage_tank", "engagetank": "engage_tank", "etank": "engage_tank", "e": "engage_tank",
    "def": "def_tank", "deftank": "def_tank", "dtank": "def_tank",
    "dps": "dps", "dd": "dps",
    "pierce": "pierce", "p": "pierce",
    "healer": "healer", "heal": "healer", "h": "healer",
    "support": "support", "sup": "support", "supp": "support",
    "sc": "sc", "spirithunter": "sc", "spirit": "sc", "shadowcaller": "sc", "shadow": "sc", "caller": "sc",
    "perma": "perma",
    "wailing": "wailing", "wail": "wailing", "bow": "wailing", "b": "wailing",
    "fill": "fill",
}

@dataclass(frozen=True)
class EventTemplate:
    key: str
    title: str
    subtitle: str
    thread_name: str
    roles: List[Tuple[str, int]]

PRESETS: Dict[str, EventTemplate] = {
    "infinity": EventTemplate("infinity", "🇦 🇻 🇦 🇱 🇴 🇳", "♾️ I N F I N I T Y G O L D ♾️", "AVALON",
                              [("tank", 1), ("dps", 4), ("pierce", 1), ("healer", 1), ("fill", 999)]),
    "avalon": EventTemplate("avalon", "🇦 🇻 🇦 🇱 🇴 🇳", "", "AVALON",
                            [("tank", 1), ("dps", 4), ("pierce", 1), ("healer", 1), ("fill", 999)]),
    "dungeon": EventTemplate("dungeon", "🇬 🇷 🇴 🇺 🇵 🇩 🇺 🇳 🇬 🇪 🇴 🇳", "", "DUNGEON",
                             [("tank", 1), ("dps", 2), ("pierce", 1), ("healer", 1), ("fill", 999)]),
    "kristal": EventTemplate("kristal", "🇰 🇷 ℹ️ 🇸 🇹 🇦 🇱", "", "KRISTAL",
                             [("tank", 1), ("dps", 7), ("healer", 1), ("fill", 999)]),
    "faction": EventTemplate("faction", "🇫 🇦 🇨 🇹 ℹ️ 🇴 🇳", "", "FACTION",
                             [("engage_tank", 1), ("def_tank", 5), ("dps", 8), ("pierce", 2), ("healer", 4), ("fill", 999)]),
    "track": EventTemplate("track", "🇹 🇷 🇦 🇨 🇰", "", "TRACK",
                           [("tank", 1), ("dps", 4), ("pierce", 1), ("healer", 1), ("fill", 999)]),
    "statik": EventTemplate("statik", "🇸 🇹 🇦 🇹 ℹ️ 🇨", "", "STATIK",
                            [("tank", 1), ("healer", 1), ("sc", 1), ("perma", 1), ("wailing", 3), ("fill", 999)]),    "static_speed": EventTemplate("static_speed", "STATIC SPEED", "", "STATIC SPEED",
                                   [("tank", 1), ("dps", 4), ("pierce", 1), ("healer", 1), ("fill", 2)]),
    "custom_all": EventTemplate("custom_all", "🎮 C U S T O M", "Herkes istediği role katılabilir!", "CUSTOM",
                                [("tank", 999), ("def_tank", 999), ("dps", 999), ("pierce", 999), ("healer", 999)]),

}

@dataclass
class EventState:
    template: EventTemplate
    channel_id: int
    message_id: int
    thread_id: int
    owner_id: int
    roster: Dict[str, List[int]]
    user_role: Dict[int, str]
    toplanma: str
    time_tr: str
    time_utc: str
    mount: str
    ayar: str

EVENTS: Dict[int, EventState] = {}

def mention(guild: discord.Guild, user_id: Optional[int]) -> str:
    if not user_id:
        return ""
    m = guild.get_member(user_id)
    return m.mention if m else f"<@{user_id}>"

def role_capacity(tpl: EventTemplate, role: str) -> int:
    for r, c in tpl.roles:
        if r == role:
            return c
    return 0

def max_total_people(tpl: EventTemplate) -> int:
    total = 0
    for r, c in tpl.roles:
        # fill=999 -> "sınırsız" gibi kullanılıyor; toplam kapasiteyi büyütmesin
        if r == "fill" and c >= 999:
            continue
        total += c
    return total

def current_total_people(state: EventState) -> int:
    return sum(len(state.roster.get(r, [])) for r, _ in state.template.roles)

def build_embed(state: EventState, guild: discord.Guild) -> discord.Embed:
    tpl = state.template
    e = discord.Embed(title=tpl.title, description=(tpl.subtitle or None))
    e.add_field(
        name="Bilgiler",
        value=(
            f"📍 **Toplanma Yeri:** {state.toplanma}\n"
            f"⏰ **Zaman:** {state.time_tr} / {state.time_utc} UTC\n"
            f"🐎 **Binek:** {state.mount}\n"
            f"⚠️ **Ayar:** {state.ayar}\n"
        ),
        inline=False,
    )

    lines: List[str] = []
    
    # Custom All için özel format
    if tpl.key == "custom_all":
        for role, _cap in tpl.roles:
            users = state.roster.get(role, [])
            count = len(users)
            label = ROLE_LABELS.get(role, role)
            # X/X formatı - kaç kişi varsa o kadar göster
            user_list = ", ".join([mention(guild, uid) for uid in users]) if users else "-"
            lines.append(f"{label} ({count}/{count}): {user_list}")
    else:
        # Normal template formatı
        for role, count in tpl.roles:
            if role == "fill":
                continue
            users = state.roster.get(role, [])
            label = ROLE_LABELS.get(role, role)
            if count <= 1:
                lines.append(f"{label}: {mention(guild, users[0])}" if users else f"{label}:")
            else:
                for i in range(count):
                    slot_label = f"{label}-{i+1}"
                    lines.append(f"{slot_label}: {mention(guild, users[i])}" if i < len(users) else f"{slot_label}:")
        fill_users = state.roster.get("fill", [])
        if fill_users:
            for i, uid in enumerate(fill_users, start=1):
                lines.append(f"{ROLE_LABELS['fill']}-{i}: {mention(guild, uid)}")
        else:
            lines.append(f"{ROLE_LABELS['fill']}:")

    curp = current_total_people(state)
    # Custom All için toplam gösterim
    if tpl.key == "custom_all":
        e.add_field(name=f"Kadro (Toplam: {curp})", value="\n".join(lines), inline=False)
        e.set_footer(text="Menüden istediğin role katıl! Çıkmak için ❌ bas.")
    else:
        maxp = max_total_people(tpl)
        e.add_field(name=f"Kadro ({curp}/{maxp})", value="\n".join(lines), inline=False)
        e.set_footer(text="Menüden katılabilir veya thread'e class yazabilirsin. (Yetkili: Edit/Kick/Assign)")
    return e

def remove_user(state: EventState, user_id: int) -> None:
    old = state.user_role.get(user_id)
    if not old:
        return
    state.roster[old] = [u for u in state.roster.get(old, []) if u != user_id]
    state.user_role.pop(user_id, None)

def try_add_user(state: EventState, user_id: int, role: str) -> Tuple[bool, str]:
    tpl = state.template
    cap = role_capacity(tpl, role)
    if cap <= 0:
        return (False, "Bu event'te bu rol yok.")
    if current_total_people(state) >= max_total_people(tpl):
        return (False, "Event dolu.")
    
    # Eğer kullanıcı daha önce bu event'te yoksa, content katılımı say
    was_in_event = user_id in state.user_role
    
    if role == "fill":
        remove_user(state, user_id)
        state.roster.setdefault("fill", []).append(user_id)
        state.user_role[user_id] = "fill"
        if not was_in_event:
            _update_activity(user_id, "content")
        return (True, "OK")

    cur = state.roster.get(role, [])
    if len(cur) >= cap:
        return (False, "Slot dolu.")
    remove_user(state, user_id)
    state.roster.setdefault(role, []).append(user_id)
    state.user_role[user_id] = role
    if not was_in_event:
        _update_activity(user_id, "content")
    return (True, "OK")

def is_event_staff(interaction: discord.Interaction, state: EventState) -> bool:
    if interaction.user.id == state.owner_id:
        return True
    if not interaction.guild:
        return False
    member = interaction.guild.get_member(interaction.user.id)
    if not member:
        return False
    perms = member.guild_permissions
    return perms.administrator or perms.manage_guild or perms.manage_channels

def parse_role_key(text: str) -> Optional[str]:
    content = (text or "").strip().lower()
    if not content:
        return None
    parts = re.split(r"\s+", content)
    if not parts:
        return None
    p0 = parts[0]
    if p0 == "x" and len(parts) >= 2:
        p0 = parts[1]
    p0 = p0.replace("-", "").replace("_", "")
    p0 = re.sub(r"\d+$", "", p0)
    direct_map = {k.replace("_", ""): k for k in ROLE_LABELS.keys()}
    if p0 in direct_map:
        return direct_map[p0]
    return THREAD_KEYWORDS.get(p0)

# =========================================================
#                      CONTENT OYLAMA
# =========================================================
# =========================================================
#              GELİŞMİŞ CONTENT OYLAMA SİSTEMİ
# =========================================================
CONTENT_POLL_CHOICES = [
    ("avalon", "Avalon", "🌀"),
    ("gank", "GANK", "🗡️"),
    ("group_track", "Group Track", "👣"),
    ("statik", "Statik", "⚔️"),
    ("group_dungeon", "Group Dungeon", "🏰"),
    ("infinity", "Infinity", "♾️"),
    ("kristal", "Kristal", "💎"),
    ("t42_fight", "T4.2 Fight", "🥊"),
]
LETTER_EMOJIS = ["🇦", "🇧", "🇨", "🇩", "🇪", "🇫", "🇬", "🇭"]

# Progress bar karakterleri
BAR_FULL = "█"
BAR_EMPTY = "░"
BAR_LENGTH = 12

async def ensure_channel_webhook(channel: discord.TextChannel) -> discord.Webhook:
    hooks = await channel.webhooks()
    for h in hooks:
        if h.name == "Callidus Poll":
            return h
    return await channel.create_webhook(name="Callidus Poll")

def _make_progress_bar(percentage: float) -> str:
    """Yüzdeye göre progress bar oluşturur."""
    filled = int(round(percentage / 100 * BAR_LENGTH))
    empty = BAR_LENGTH - filled
    return BAR_FULL * filled + BAR_EMPTY * empty

def _format_time_remaining(minutes: int, start_time: datetime) -> str:
    """Kalan süreyi formatlar."""
    now = datetime.now(UTC_TZ)
    elapsed = (now - start_time).total_seconds() / 60
    remaining = max(0, minutes - elapsed)
    
    if remaining <= 0:
        return "Süre doldu!"
    elif remaining < 1:
        return f"{int(remaining * 60)} saniye"
    elif remaining < 60:
        return f"{int(remaining)} dakika"
    else:
        hours = int(remaining // 60)
        mins = int(remaining % 60)
        return f"{hours} saat {mins} dk" if mins > 0 else f"{hours} saat"

def build_poll_embed(question: str, author: discord.abc.User, counts: Dict[str, int], 
                     minutes: int, ended: bool = False, start_time: datetime = None,
                     user_choice: Dict[int, str] = None) -> discord.Embed:
    """Gelişmiş oylama embed'i oluşturur."""
    
    # Toplam oy hesapla
    total_votes = sum(counts.values())
    
    # Maksimum oy alan seçeneği bul
    max_votes = max(counts.values()) if counts else 0
    winners = [k for k, v in counts.items() if v == max_votes and v > 0]
    
    # Renk belirleme
    if ended:
        color = 0x2F3136  # Koyu gri - bitti
    elif total_votes == 0:
        color = 0x5865F2  # Discord mavisi - bekliyor
    else:
        color = 0x57F287  # Yeşil - aktif
    
    # Başlık ve açıklama
    if ended:
        title = f"📊 {question} — SONUÇLAR"
        if winners and max_votes > 0:
            winner_names = [label for key, label, _ in CONTENT_POLL_CHOICES if key in winners]
            desc = f"🏆 **Kazanan: {' / '.join(winner_names)}** ({max_votes} oy)"
        else:
            desc = "❌ Hiç oy kullanılmadı."
    else:
        title = f"🎯 {question}"
        desc = "Aşağıdaki butonlardan **tek** seçenek oylayabilirsin.\nOyunu değiştirmek için farklı butona, geri çekmek için aynı butona bas."
    
    e = discord.Embed(title=title, description=desc, color=color)
    e.set_author(name=f"Başlatan: {author.display_name}", icon_url=str(author.display_avatar.url))
    
    # Her seçenek için satır oluştur
    lines = []
    for i, (key, label, emoji) in enumerate(CONTENT_POLL_CHOICES):
        count = counts.get(key, 0)
        percentage = (count / total_votes * 100) if total_votes > 0 else 0
        bar = _make_progress_bar(percentage)
        
        # Kazanan işareti
        winner_mark = " 🏆" if (ended and key in winners and max_votes > 0) else ""
        
        # Satır formatı
        line = f"{LETTER_EMOJIS[i]} {emoji} **{label}**{winner_mark}\n"
        line += f"`{bar}` **{percentage:.0f}%** ({count} oy)"
        lines.append(line)
    
    # Seçenekleri 2 sütuna böl
    mid = (len(lines) + 1) // 2
    left_col = "\n\n".join(lines[:mid])
    right_col = "\n\n".join(lines[mid:])
    
    e.add_field(name="\u200b", value=left_col, inline=True)
    if right_col:
        e.add_field(name="\u200b", value=right_col, inline=True)
    
    # Alt bilgi
    footer_parts = []
    if start_time and not ended:
        remaining = _format_time_remaining(minutes, start_time)
        footer_parts.append(f"⏰ Kalan: {remaining}")
    elif ended:
        footer_parts.append("⛔ Oylama sona erdi")
    else:
        footer_parts.append(f"⏱️ Süre: {minutes} dk")
    
    footer_parts.append(f"👥 {total_votes} oy kullanıldı")
    
    e.set_footer(text=" • ".join(footer_parts))
    
    # Zaman damgası
    if not ended:
        e.timestamp = datetime.now(UTC_TZ)
    
    return e

class ContentPollView(discord.ui.View):
    def __init__(self, author_id: int, minutes: int, question: str, author: discord.abc.User):
        super().__init__(timeout=minutes * 60)
        self.author_id = author_id
        self.minutes = minutes
        self.question = question
        self.author_user = author
        self.counts: Dict[str, int] = {k: 0 for k, _, _ in CONTENT_POLL_CHOICES}
        self.user_choice: Dict[int, str] = {}
        self.webhook_id: Optional[int] = None
        self.start_time: datetime = datetime.now(UTC_TZ)
        self.ended: bool = False
        
        # Oylama butonları (2 satırda)
        for i, (key, label, emoji) in enumerate(CONTENT_POLL_CHOICES):
            self.add_item(ContentPollButton(index=i, choice_key=key, label=label, emoji=emoji))

    def disable_all(self):
        self.ended = True
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

class ContentPollButton(discord.ui.Button):
    def __init__(self, index: int, choice_key: str, label: str, emoji: str):
        super().__init__(
            label=label,
            style=discord.ButtonStyle.secondary,
            emoji=emoji,
            row=0 if index < 4 else 1,
            custom_id=f"poll_choice_{choice_key}"
        )
        self.choice_key = choice_key
        self.choice_label = label
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        view: ContentPollView = self.view  # type: ignore
        if not view:
            return await interaction.response.send_message("❌ Oylama bulunamadı.", ephemeral=True)
        if view.ended:
            return await interaction.response.send_message("⛔ Bu oylama sona erdi.", ephemeral=True)

        uid = interaction.user.id
        old = view.user_choice.get(uid)

        # Oy değişikliği mesajı
        response_msg = ""
        
        if old == self.choice_key:
            # Aynı butona bastı = oy geri çek
            view.user_choice.pop(uid, None)
            view.counts[self.choice_key] = max(0, view.counts.get(self.choice_key, 0) - 1)
            response_msg = f"🗑️ **{self.choice_label}** oyun geri çekildi."
        else:
            if old:
                # Eski oyu sil
                view.counts[old] = max(0, view.counts.get(old, 0) - 1)
                old_label = next((label for k, label, _ in CONTENT_POLL_CHOICES if k == old), old)
                response_msg = f"🔄 Oyun **{old_label}** → **{self.choice_label}** olarak değiştirildi."
            else:
                response_msg = f"✅ **{self.choice_label}** için oy kullandın!"
            
            view.user_choice[uid] = self.choice_key
            view.counts[self.choice_key] = view.counts.get(self.choice_key, 0) + 1

        # Embed güncelle
        embed = build_poll_embed(
            view.question, view.author_user, view.counts, view.minutes,
            ended=view.ended, start_time=view.start_time, user_choice=view.user_choice
        )
        
        try:
            if interaction.message:
                if view.webhook_id and interaction.message.webhook_id:
                    try:
                        wh = await bot.fetch_webhook(view.webhook_id)
                        await wh.edit_message(interaction.message.id, embed=embed, view=view)
                    except Exception as wh_err:
                        log(f"webhook edit error: {repr(wh_err)}")
                        await interaction.message.edit(embed=embed, view=view)
                else:
                    await interaction.message.edit(embed=embed, view=view)
        except Exception as e:
            log(f"poll edit error: {repr(e)}")
        
        await interaction.response.send_message(response_msg, ephemeral=True)


# Aktif oylamaları takip etmek için dictionary
ACTIVE_POLLS: Dict[int, ContentPollView] = {}  # message_id -> view


async def _close_poll_later(message: discord.Message, view: ContentPollView):
    """Oylama süresini takip eder ve bitince kapatır."""
    try:
        await asyncio.sleep(view.minutes * 60)
        view.disable_all()
        
        ended_embed = build_poll_embed(
            view.question, view.author_user, view.counts, view.minutes,
            ended=True, start_time=view.start_time, user_choice=view.user_choice
        )
        
        try:
            if view.webhook_id and message.webhook_id:
                try:
                    wh = await bot.fetch_webhook(view.webhook_id)
                    await wh.edit_message(message.id, embed=ended_embed, view=view)
                except Exception as wh_err:
                    log(f"webhook close edit error: {repr(wh_err)}")
                    await message.edit(embed=ended_embed, view=view)
            else:
                await message.edit(embed=ended_embed, view=view)
        except Exception as e:
            log(f"poll close edit error: {repr(e)}")
            
    except Exception as e:
        log(f"poll close sleep error: {repr(e)}")


class ContentOylamaModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="🎯 Content Oylama Başlat")
        self.minutes_in = discord.ui.TextInput(
            label="Kaç dakika sürsün?",
            required=True,
            placeholder="60",
            max_length=5,
            default="60"
        )
        self.question_in = discord.ui.TextInput(
            label="Başlık (boş bırakabilirsin)",
            required=False,
            placeholder="CONTENT SEÇİMİ",
            max_length=80
        )
        self.add_item(self.minutes_in)
        self.add_item(self.question_in)

    async def on_submit(self, interaction: discord.Interaction):
        raw = (self.minutes_in.value or "").strip()
        try:
            minutes = int(raw)
        except ValueError:
            return await safe_send(interaction, "❌ Dakika sadece sayı olmalı. (örn: 60)", ephemeral=True)

        if minutes < 1:
            return await safe_send(interaction, "❌ Süre en az 1 dakika olmalı.", ephemeral=True)
        if minutes > 10080:
            return await safe_send(interaction, "❌ Çok uzun. Maks 10080 dk (7 gün).", ephemeral=True)

        question = (self.question_in.value or "").strip() or "CONTENT SEÇİMİ"
        await safe_defer(interaction, ephemeral=True)

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            return await safe_send(interaction, "❌ Bu komut sadece text channel içinde çalışır.", ephemeral=True)

        view = ContentPollView(
            author_id=interaction.user.id,
            minutes=minutes,
            question=question,
            author=interaction.user
        )
        embed = build_poll_embed(
            question, interaction.user, view.counts, minutes,
            start_time=view.start_time, user_choice=view.user_choice
        )

        try:
            wh = await ensure_channel_webhook(channel)
            ping_text = f"<@&{PING_ROLE_ID}>" if PING_ROLE_ID else ""
            msg = await wh.send(
                content=ping_text,
                embed=embed,
                view=view,
                username=interaction.user.display_name,
                avatar_url=str(interaction.user.display_avatar.url),
                wait=True,
                allowed_mentions=discord.AllowedMentions(everyone=False, users=False, roles=True),
            )
            view.webhook_id = wh.id
            ACTIVE_POLLS[msg.id] = view  # Tracking'e ekle
            asyncio.create_task(_close_poll_later(msg, view))
            return await safe_send(interaction, "✅ Oylama başlatıldı!", ephemeral=True)
        except Exception as e:
            log(f"poll webhook send error: {repr(e)}")

        try:
            ping_text = f"<@&{PING_ROLE_ID}>" if PING_ROLE_ID else ""
            msg2 = await channel.send(content=ping_text, embed=embed, view=view, allowed_mentions=discord.AllowedMentions(roles=True))
            ACTIVE_POLLS[msg2.id] = view  # Tracking'e ekle
            asyncio.create_task(_close_poll_later(msg2, view))
            return await safe_send(interaction, "✅ Oylama başlatıldı. (Bot mesajı olarak)", ephemeral=True)
        except Exception as e:
            return await safe_send(interaction, f"❌ Hata: {e}", ephemeral=True)

# =========================================================
#                   GOOGLE SHEETS (ASYNC WRAP)
# =========================================================
_gspread_mod = None
_gspread_client = None
_gspread_sheets: Dict[str, Any] = {}

def _get_gspread_module():
    global _gspread_mod
    if _gspread_mod is None:
        import gspread
        _gspread_mod = gspread
    return _gspread_mod




def _resolve_sheet_id_for_tab(tab_name: str) -> str:
    """Resolve which Spreadsheet ID should be used for a given tab name (or tab-ref)."""
    sid, tab = _split_sheet_ref(tab_name)
    if sid:
        return sid

    t = (tab or "").strip().lower()

    bc = (BRAWLCOMP_SHEET_TAB or "").strip().lower()
    if BRAWLCOMP_SHEET_ID and bc and t == bc:
        return (BRAWLCOMP_SHEET_ID or "").strip()

    # dynamic tabs (bot restart sonrası da doğru sheet'i bulsun)
    try:
        hits = [v for v in DYNAMIC_SHEETS.values() if (v.get("tab") or "").strip().lower() == t]
        if len(hits) == 1 and (hits[0].get("sheet_id") or "").strip():
            return (hits[0].get("sheet_id") or "").strip()
    except Exception:
        pass

    return (AVASKIP_SHEET_ID or "").strip()





def _gs_authorize_sync():
    """
    GOOGLE_CREDS_JSON:
      - Eğer "{...}" ile başlıyorsa => JSON content (env'e yapıştırılmış)
      - Yoksa => dosya yolu (/root/infinity-bot/creds.json gibi)
    """
    global _gspread_client
    if _gspread_client is not None:
        return _gspread_client

    if not GOOGLE_CREDS_JSON:
        raise RuntimeError("GOOGLE_CREDS_JSON ayarlı değil.")

    gs = _get_gspread_module()
    src = (GOOGLE_CREDS_JSON or "").strip()

    if src.startswith("{"):
        creds_info = json.loads(src)
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_info(
            creds_info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        gc = gs.authorize(creds)
    else:
        gc = gs.service_account(filename=src)

    _gspread_client = gc
    return gc


def _gs_open_sheet_sync(sheet_id: str):
    global _gspread_sheets
    sid = (sheet_id or "").strip()
    if not sid:
        raise RuntimeError("Sheet ID boş. (.env / vars kontrol et)")

    gc = _gs_authorize_sync()
    sh = _gspread_sheets.get(sid)
    if sh is None:
        sh = gc.open_by_key(sid)
        _gspread_sheets[sid] = sh
    return sh



def _gs_worksheet_sync(tab_name: str):
    sid, tab = _split_sheet_ref(tab_name)
    sheet_id = sid or _resolve_sheet_id_for_tab(tab)
    if not sheet_id:
        raise RuntimeError("Sheet ID bulunamadı.")
    sh = _gs_open_sheet_sync(sheet_id)
    try:
        return sh.worksheet(tab)
    except Exception:
        return sh.get_worksheet(0)


async def gs_get_all_values(tab_name: str) -> List[List[str]]:
    def _do():
        ws = _gs_worksheet_sync(tab_name)
        return ws.get_all_values()
    return await run_io(_do)

async def gs_update_cell(tab_name: str, row: int, col: int, value: str) -> None:
    def _do():
        ws = _gs_worksheet_sync(tab_name)
        ws.update_cell(row, col, value)
    await run_io(_do)

async def gs_update_range(tab_name: str, range_name: str, values: List[List[str]]) -> None:
    def _do():
        ws = _gs_worksheet_sync(tab_name)
        ws.update(range_name=range_name, values=values)
    await run_io(_do)

async def gs_col_values(tab_name: str, col: int) -> List[str]:
    def _do():
        ws = _gs_worksheet_sync(tab_name)
        return ws.col_values(col)
    return await run_io(_do)

# =========================================================
#                    SHEET HELPERS (GENERIC)
# =========================================================
def _norm(s: str) -> str:
    return (s or "").strip().lower()

def _is_nick_header(h: str) -> bool:
    nh = _norm(h)
    return (
        nh in ("nick", "nıck", "nickname", "name", "isim", "adı", "ad", "player", "oyuncu", "ign", "in game name", "in-game name", "ingamename")
        or "nick" in nh
        or nh == "ign"
        or nh.startswith("ign ")
        or nh.endswith(" ign")
    )

def _is_role_header(h: str) -> bool:
    nh = _norm(h)
    return nh in ("role", "rol", "roller", "class", "sinif", "sınıf", "pozisyon", "position") or nh.startswith("role")

def _resolve_col(headers: List[str], kind: str) -> Optional[str]:
    k = _norm(kind)
    if k == "nick":
        for h in headers:
            if _is_nick_header(h):
                return h
    if k == "role":
        for h in headers:
            if _is_role_header(h):
                return h
    for h in headers:
        if _norm(h) == k:
            return h
    return None

def _col_to_letter(col: int) -> str:
    if col <= 0:
        raise ValueError("col must be >= 1")
    letters = ""
    n = col
    while n:
        n, rem = divmod(n - 1, 26)
        letters = chr(65 + rem) + letters
    return letters

@dataclass
class SheetRoleRow:
    role: str
    row_idx: int
    values: Dict[str, str]

SHEET_CACHE: Dict[str, Dict[str, Any]] = {}
SHEET_TTL = 10.0

def _loop_time() -> float:
    try:
        return asyncio.get_event_loop().time()
    except Exception:
        return 0.0

async def load_sheet_rows(tab_name: str, force: bool = False) -> Tuple[List[str], List[SheetRoleRow]]:
    tab_key = f"{_resolve_sheet_id_for_tab(tab_name)}::{tab_name or ''}"
    if tab_key not in SHEET_CACHE:
        SHEET_CACHE[tab_key] = {"ts": 0.0, "headers": [], "rows": []}

    ts = _loop_time()
    cache = SHEET_CACHE[tab_key]
    if (not force) and cache["rows"] and (ts - float(cache["ts"]) < SHEET_TTL):
        return cache["headers"], cache["rows"]

    values = await gs_get_all_values(tab_name)
    if not values or len(values) < 2:
        raise RuntimeError(f"Sheet ({tab_name}) boş (başlık + en az 1 satır olmalı).")

    headers = values[0]
    role_col = _resolve_col(headers, "role")

    rows: List[SheetRoleRow] = []
    for i in range(1, len(values)):
        row_vals = values[i]
        d: Dict[str, str] = {}
        for ci, h in enumerate(headers):
            d[h] = (row_vals[ci].strip() if ci < len(row_vals) and row_vals[ci] is not None else "")

        role_name = ""
        if role_col:
            role_name = d.get(role_col, "").strip()
        if not role_name:
            role_name = (row_vals[0].strip() if row_vals else "")

        if not role_name:
            continue

        rows.append(SheetRoleRow(role=role_name, row_idx=i + 1, values=d))

    cache["ts"] = ts
    cache["headers"] = headers
    cache["rows"] = rows
    return headers, rows

def sheet_user_string(user: discord.abc.User) -> str:
    return f"{user.display_name} | {user.id}"

async def clear_user_from_sheet(tab: str, headers: List[str], user_id: int) -> None:
    nick_col = _resolve_col(headers, "Nick")
    if not nick_col:
        raise RuntimeError("Sheet'te Nick sütunu yok.")
    nick_idx = headers.index(nick_col) + 1

    col_values = await gs_col_values(tab, nick_idx)
    needle = str(user_id)
    for r in range(2, len(col_values) + 1):
        v = (col_values[r - 1] or "").strip()
        if v and needle in v:
            await gs_update_cell(tab, r, nick_idx, "")

async def clear_all_nicks_from_sheet(tab: str, headers: List[str], last_row: int) -> None:
    nick_col = _resolve_col(headers, "Nick")
    if not nick_col:
        raise RuntimeError("Sheet'te Nick sütunu yok.")
    nick_idx = headers.index(nick_col) + 1

    col_letter = _col_to_letter(nick_idx)
    rng = f"{col_letter}2:{col_letter}{last_row}"
    blanks = [[""] for _ in range(max(0, last_row - 1))]
    await gs_update_range(tab, rng, blanks)

async def set_role_nick(tab: str, headers: List[str], role_row: SheetRoleRow, value: str) -> None:
    nick_col = _resolve_col(headers, "Nick")
    if not nick_col:
        raise RuntimeError("Sheet'te Nick sütunu yok.")
    nick_idx = headers.index(nick_col) + 1
    await gs_update_cell(tab, role_row.row_idx, nick_idx, value)

def _raw_val(headers: List[str], row: SheetRoleRow, col_header: str) -> str:
    return (row.values.get(col_header) or "").strip()

def _candidate_sig_headers(headers: List[str]) -> List[str]:
    out: List[str] = []
    for h in headers:
        if not h:
            continue
        if _is_nick_header(h) or _is_role_header(h):
            continue
        out.append(h)
    return out

def _sig_for_row(headers: List[str], row: SheetRoleRow) -> str:
    parts: List[str] = []
    for h in _candidate_sig_headers(headers):
        v = _raw_val(headers, row, h)
        parts.append(_norm(v))
    return "|".join(parts)

def _sig_hash(sig: str) -> str:
    return hashlib.sha1(sig.encode("utf-8")).hexdigest()[:8]

def _role_key(role_name: str) -> str:
    return _norm(role_name)

def _count_rows_in_state(slots: Dict[str, Tuple[str, Optional[int]]], row_indices: List[int]) -> Tuple[int, int]:
    total = len(row_indices)
    filled = 0
    for ri in row_indices:
        _rname, uid = slots.get(str(ri), ("", None))
        if uid:
            filled += 1
    return filled, total

def _build_variant_label(headers: List[str], rows: List['SheetRoleRow'], sig_groups: Dict[str, List['SheetRoleRow']]) -> Dict[str, str]:
    """Simple numbering for duplicated roles (no hash shown in the list)."""
    if len(sig_groups) <= 1:
        only_sig = next(iter(sig_groups.keys()))
        return {only_sig: ""}

    ordered = sorted(sig_groups.keys(), key=lambda s: _sig_hash(s))
    return {sig: str(i + 1) for i, sig in enumerate(ordered)}

@dataclass(frozen=True)
class SheetRoleEntry:
    role_name: str
    role_key: str
    sig: str
    sig8: str
    variant_id: str
    filled: int
    total: int
    label: str

def build_role_entries(tab: str, st_slots: Dict[str, Tuple[str, Optional[int]]], headers: List[str], rows: List[SheetRoleRow]) -> List[SheetRoleEntry]:
    role_groups: Dict[str, List[SheetRoleRow]] = {}
    for r in rows:
        rk = _role_key(r.role)
        role_groups.setdefault(rk, []).append(r)

    entries: List[SheetRoleEntry] = []
    for rk, rrlist in role_groups.items():
        role_name = rrlist[0].role

        sig_groups: Dict[str, List[SheetRoleRow]] = {}
        for rr in rrlist:
            sig = _sig_for_row(headers, rr)
            sig_groups.setdefault(sig, []).append(rr)

        sig_to_suffix = _build_variant_label(headers, rrlist, sig_groups)

        for sig, subrows in sig_groups.items():
            row_idxs = [sr.row_idx for sr in subrows]
            filled, total = _count_rows_in_state(st_slots, row_idxs)

            suffix = sig_to_suffix.get(sig, "")
            label = role_name if not suffix else f"{role_name} ({suffix})"

            sig8 = _sig_hash(sig)
            variant_id = f"{rk}|{sig8}"
            entries.append(SheetRoleEntry(
                role_name=role_name,
                role_key=rk,
                sig=sig,
                sig8=sig8,
                variant_id=variant_id,
                filled=filled,
                total=total,
                label=label
            ))

    entries.sort(key=lambda x: (x.role_name.lower(), x.label.lower()))
    return entries

def _find_rows_for_variant(headers: List[str], rows: List[SheetRoleRow], chosen_role_key: str, chosen_sig8: str) -> List[SheetRoleRow]:
    base_rows = [r for r in rows if _role_key(r.role) == chosen_role_key]
    out: List[SheetRoleRow] = []
    for r in base_rows:
        sig = _sig_for_row(headers, r)
        if _sig_hash(sig) == chosen_sig8:
            out.append(r)
    return out

# =========================================================
#               SHEET EVENT (AVA SKIP + 10MAN)
# =========================================================
SHEET_PAGE_SIZE = 20
CIRCLED = ["①","②","③","④","⑤","⑥","⑦","⑧","⑨","⑩","⑪","⑫","⑬","⑭","⑮","⑯","⑰","⑱","⑲","⑳"]

@dataclass
class SheetEventState:
    sheet_tab: str
    title: str
    channel_id: int
    message_id: int
    thread_id: int
    thread_msg_id: int
    owner_id: int
    toplanma: str
    time_tr: str
    time_utc: str
    mount: str
    ayar: str
    slots: Dict[str, Tuple[str, Optional[int]]]
    user_slot: Dict[int, str]
    page: int

SHEET_EVENTS: Dict[int, SheetEventState] = {}
SHEET_THREAD_TO_MAIN: Dict[int, int] = {}

# ---- Sheet re-activation helpers (bot restart sonrası) ----
_SHEET_TAB_RE = re.compile(r"Tab:\s*\*\*(.+?)\*\*", re.IGNORECASE)

def _parse_sheet_tab_from_embed(embed: discord.Embed) -> Optional[str]:
    try:
        desc = (embed.description or "").strip()
        m = _SHEET_TAB_RE.search(desc)
        if not m:
            return None
        return (m.group(1) or "").strip()
    except Exception:
        return None

_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]{10,})")

def _parse_sheet_id_from_embed(embed: discord.Embed) -> str:
    try:
        u = (getattr(embed, 'url', '') or '').strip()
        m = _SHEET_ID_RE.search(u)
        return (m.group(1) or '').strip() if m else ''
    except Exception:
        return ''


def _parse_sheet_info_from_main_embed(embed: discord.Embed) -> Tuple[str, str, str, str, str, str]:
    """Return (title, sheet_tab, time_tr, time_utc, toplanma, mount, ayar).
    If a field is missing, returns best-effort defaults.
    """
    title = (embed.title or "Sheet").strip()

    sheet_tab = _parse_sheet_tab_from_embed(embed) or ""

    sid = _parse_sheet_id_from_embed(embed)
    if sid and sheet_tab and "||" not in sheet_tab:
        sheet_tab = _make_sheet_ref(sid, sheet_tab)

    toplanma = "BELİRTİLMEMİŞ"
    time_tr = "BELİRTİLMEMİŞ"
    time_utc = "BELİRTİLMEMİŞ"
    mount = DEFAULT_MOUNT
    ayar = DEFAULT_AYAR_FALLBACK

    # build_sheet_main_embed_async -> first field is "Bilgiler"
    try:
        for f in (embed.fields or []):
            if (f.name or "").strip().lower() == "bilgiler":
                val = f.value or ""
                m = re.search(r"\*\*Toplanma Yeri:\*\*\s*([^\n]+)", val, re.IGNORECASE)
                if m: toplanma = m.group(1).strip()

                m = re.search(r"\*\*Zaman:\*\*\s*([^\n]+)", val, re.IGNORECASE)
                if m:
                    tt = m.group(1).strip()
                    if " / " in tt:
                        a, b = tt.split(" / ", 1)
                        time_tr = a.strip()
                        time_utc = b.replace("UTC", "").strip()
                    else:
                        time_tr = tt.strip()

                m = re.search(r"\*\*Binek:\*\*\s*([^\n]+)", val, re.IGNORECASE)
                if m: mount = m.group(1).strip()

                m = re.search(r"\*\*Ayar:\*\*\s*([^\n]+)", val, re.IGNORECASE)
                if m: ayar = m.group(1).strip()
                break
    except Exception:
        pass

    return title, sheet_tab, time_tr, time_utc, toplanma, mount, ayar

async def _sheet_find_thread_main_message_id(th: discord.Thread) -> Optional[int]:
    """Best-effort: oldest message in thread is the starter message (main message id)."""
    try:
        async for m in th.history(limit=1, oldest_first=True):
            return m.id
    except Exception:
        return None

async def _sheet_find_parent_main_message_id(parent: discord.TextChannel, th: discord.Thread) -> Optional[int]:
    """Find the parent-channel message that this thread was created from.
    Bu mesaj genelde **ana embed**'in olduğu mesajdır.
    """
    # Hızlı yol: çoğu thread'de thread id == starter message id
    try:
        m = await parent.fetch_message(th.id)
        if m:
            try:
                if m.thread and m.thread.id == th.id:
                    return m.id
            except Exception:
                pass
            if m.id == th.id:
                return m.id
    except Exception:
        pass

    # Fallback: parent channel geçmişini tara
    try:
        async for m in parent.history(limit=600, oldest_first=False):
            try:
                if m.thread and m.thread.id == th.id:
                    return m.id
            except Exception:
                continue
    except Exception:
        pass
    return None

    return None

async def _sheet_find_thread_panel_message_id(th: discord.Thread, bot_user_id: int) -> Optional[int]:
    """Find the bot's 'Rol Seçimi' panel message inside the thread."""
    try:
        async for m in th.history(limit=80, oldest_first=True):
            if not m.author:
                continue
            if m.author.id != bot_user_id:
                continue
            if not m.embeds:
                continue
            t = (m.embeds[0].title or "")
            if "Rol Seçimi" in t:
                return m.id
        # fallback: latest bot embed
        async for m in th.history(limit=80, oldest_first=False):
            if m.author and m.author.id == bot_user_id and m.embeds:
                return m.id
    except Exception:
        return None
    return None

def _extract_user_id_from_sheet_nick(s: str) -> Optional[int]:
    s = (s or "").strip()
    if not s:
        return None
    # expected: "display_name | 123456789012345678"
    m = re.search(r"\|\s*(\d{8,25})\s*$", s)
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    # fallback: any long digit chunk
    m2 = re.search(r"(\d{8,25})", s)
    if m2:
        try:
            return int(m2.group(1))
        except Exception:
            return None
    return None

async def _rebuild_sheet_state_from_discord(
    bot_client: discord.Client,
    *,
    main_msg: discord.Message,
    th: discord.Thread,
    thread_msg_id: int,
    owner_id: int,
) -> SheetEventState:
    if not main_msg.embeds:
        raise RuntimeError("Ana mesaj embed'i yok.")
    emb0 = main_msg.embeds[0]
    title, sheet_tab, time_tr, time_utc, toplanma, mount, ayar = _parse_sheet_info_from_main_embed(emb0)
    if not sheet_tab:
        raise RuntimeError("Ana mesajdan sheet tab bulunamadı. (Tab: **...** yok)")

    headers, rows = await load_sheet_rows(sheet_tab, force=True)
    if not rows:
        raise RuntimeError(f"Sheet ({sheet_tab})'te rol bulunamadı.")

    nick_col = _resolve_col(headers, "Nick")
    if not nick_col:
        raise RuntimeError("Sheet'te 'Nick' kolonu bulunamadı.")

    slots: Dict[str, Tuple[str, Optional[int]]] = {str(r.row_idx): (r.role, None) for r in rows}
    user_slot: Dict[int, str] = {}

    # rebuild from sheet nick column
    for r in rows:
        sk = str(r.row_idx)
        nick_val = (r.values or {}).get(nick_col, "") if isinstance(r.values, dict) else ""
        uid = _extract_user_id_from_sheet_nick(str(nick_val))
        if uid:
            slots[sk] = (r.role, int(uid))
            user_slot[int(uid)] = sk

    return SheetEventState(
        sheet_tab=sheet_tab,
        title=title,
        channel_id=(main_msg.channel.id if main_msg.channel else 0),
        message_id=main_msg.id,
        thread_id=th.id,
        thread_msg_id=thread_msg_id,
        owner_id=int(owner_id or 0),
        toplanma=toplanma,
        time_tr=time_tr,
        time_utc=time_utc,
        mount=mount,
        ayar=ayar,
        slots=slots,
        user_slot=user_slot,
        page=0,
    )

async def build_sheet_main_embed_async(st: SheetEventState, guild: discord.Guild) -> discord.Embed:
    e = discord.Embed(
        title=st.title,
        description=f"Thread'e girip rol seç.\nTab: **{_display_tab(st.sheet_tab)}**"
    )
    e.url = sheet_url_for_tab(st.sheet_tab)
    e.add_field(
        name="Bilgiler",
        value=(
            f"📍 **Toplanma Yeri:** {st.toplanma}\n"
            f"⏰ **Zaman:** {st.time_tr} / {st.time_utc} UTC\n"
            f"🐎 **Binek:** {st.mount}\n"
            f"⚠️ **Ayar:** {st.ayar}\n"
        ),
        inline=False,
    )

    try:
        headers, rows = await load_sheet_rows(st.sheet_tab, force=True)
        entries = build_role_entries(st.sheet_tab, st.slots, headers, rows)
        lines = []
        for ent in entries[:30]:
            lines.append(f"• **{ent.label}** — **{ent.filled}/{ent.total}**")
        if len(entries) > 30:
            lines.append(f"• … ({len(entries)} rol/varyant)")
        e.add_field(name="Kadro", value="\n".join(lines) if lines else "-", inline=False)
    except Exception as ex:
        e.add_field(name="Kadro", value=f"❌ Sheet okunamadı: {ex}", inline=False)

    e.set_footer(text="Thread'e gir → rol seç")
    return e

async def build_sheet_thread_embed(st: SheetEventState) -> Tuple[discord.Embed, List[SheetRoleEntry], int]:
    headers, rows = await load_sheet_rows(st.sheet_tab, force=True)
    entries = build_role_entries(st.sheet_tab, st.slots, headers, rows)

    total_pages = max(1, (len(entries) + SHEET_PAGE_SIZE - 1) // SHEET_PAGE_SIZE)
    page = max(0, min(st.page, total_pages - 1))
    st.page = page

    start = page * SHEET_PAGE_SIZE
    end = start + SHEET_PAGE_SIZE
    page_entries = entries[start:end]

    e = discord.Embed(
        title=f"{st.title} — Rol Seçimi",
        description="Menüden seç veya 1-10 / rol yaz."
    )
    e.add_field(
        name="Bilgiler",
        value=f"⏰ **{st.time_tr} / {st.time_utc} UTC** • 📍 **{st.toplanma}**",
        inline=False
    )

    lines = []
    for i, ent in enumerate(page_entries, start=1):
        icon = CIRCLED[i-1] if i-1 < len(CIRCLED) else f"{i}."
        lines.append(f"{icon} **{ent.label}** — **{ent.filled}/{ent.total}**")
    e.add_field(
        name=f"Seçenekler (Sayfa {page+1}/{total_pages})",
        value="\n".join(lines) if lines else "-",
        inline=False
    )
    return e, page_entries, total_pages

class SheetMainView(discord.ui.View):
    def __init__(self, st: SheetEventState):
        super().__init__(timeout=None)
        # Link button (always correct for this event)
        self.add_item(discord.ui.Button(label="📄 Sheet", style=discord.ButtonStyle.link, url=sheet_url_for_tab(st.sheet_tab)))

class SheetRoleSelect(discord.ui.Select):
    def __init__(self, st: SheetEventState, page_entries: List[SheetRoleEntry], page_index: int, total_pages: int):
        opts: List[discord.SelectOption] = []
        for i, ent in enumerate(page_entries, start=1):
            label = f"{i}. {ent.label} — {ent.filled}/{ent.total}"
            opts.append(discord.SelectOption(label=label[:100], value=ent.variant_id))
        super().__init__(
            placeholder=f"👇 Rol seç (Sayfa {page_index+1}/{total_pages})",
            min_values=1,
            max_values=1,
            options=opts
        )

    async def callback(self, interaction: discord.Interaction):
        await safe_defer(interaction, ephemeral=True)
        if not interaction.message or not interaction.guild:
            return await safe_send(interaction, "❌ Mesaj/guild yok.", ephemeral=True)

        thread_id = interaction.channel.id if interaction.channel else 0
        main_id = SHEET_THREAD_TO_MAIN.get(thread_id)
        st = SHEET_EVENTS.get(main_id) if main_id else None
        if not st:
            return await safe_send(interaction, "❌ Sheet event state yok.", ephemeral=True)

        chosen_variant_id = self.values[0]
        await sheet_assign_role(interaction, st, chosen_variant_id, source="select")

class SheetThreadView(discord.ui.View):
    def __init__(self, st: SheetEventState, page_entries: List[SheetRoleEntry], total_pages: int):
        super().__init__(timeout=None)
        self.add_item(SheetRoleSelect(st, page_entries, st.page, total_pages))
        if total_pages > 1:
            self.add_item(SheetPrevButton())
            self.add_item(SheetNextButton())

    @discord.ui.button(label="Çık", style=discord.ButtonStyle.danger, emoji="❌")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        await safe_defer(interaction, ephemeral=True)
        thread_id = interaction.channel.id if interaction.channel else 0
        main_id = SHEET_THREAD_TO_MAIN.get(thread_id)
        st = SHEET_EVENTS.get(main_id) if main_id else None
        if not st:
            return await safe_send(interaction, "❌ Sheet event state yok.", ephemeral=True)

        ok, msg = await sheet_leave_user(interaction.client, st, interaction.user.id)
        await safe_send(interaction, "✅ Çıkıldı." if ok else f"❌ {msg}", ephemeral=True)

class SheetPrevButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="⬅️ Önceki", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        thread_id = interaction.channel.id if interaction.channel else 0
        main_id = SHEET_THREAD_TO_MAIN.get(thread_id)
        st = SHEET_EVENTS.get(main_id) if main_id else None
        if not st:
            return await safe_send(interaction, "❌ Sheet event state yok.", ephemeral=True)
        await sheet_swap_page(interaction, st, max(0, st.page - 1))

class SheetNextButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Sonraki ➡️", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        thread_id = interaction.channel.id if interaction.channel else 0
        main_id = SHEET_THREAD_TO_MAIN.get(thread_id)
        st = SHEET_EVENTS.get(main_id) if main_id else None
        if not st:
            return await safe_send(interaction, "❌ Sheet event state yok.", ephemeral=True)

        await sheet_swap_page(interaction, st, st.page + 1)


async def sheet_swap_page(interaction: discord.Interaction, st: SheetEventState, new_page: int):
    await safe_defer(interaction, ephemeral=True)
    st.page = new_page
    try:
        emb, page_entries, total_pages = await build_sheet_thread_embed(st)
        await interaction.message.edit(embed=emb, view=SheetThreadView(st, page_entries, total_pages))  # type: ignore
    except Exception as e:
        log("swap page error:", repr(e))
        await safe_send(interaction, "❌ Sayfa değiştirilemedi.", ephemeral=True)

async def _edit_sheet_messages(bot_client: discord.Client, st: SheetEventState):
    try:
        ch = bot_client.get_channel(st.channel_id)
        if ch is None:
            try:
                ch = await bot_client.fetch_channel(st.channel_id)  # type: ignore
            except Exception:
                ch = None
        if isinstance(ch, discord.TextChannel):
            msg = await ch.fetch_message(st.message_id)
            guild = msg.guild
            emb = await build_sheet_main_embed_async(st, guild)
            await msg.edit(embed=emb, view=SheetMainView(st))
    except Exception as e:
        log("edit main sheet error:", repr(e))

    try:
        th = bot_client.get_channel(st.thread_id)
        if th is None:
            try:
                th = await bot_client.fetch_channel(st.thread_id)  # type: ignore
            except Exception:
                th = None
        if isinstance(th, discord.Thread):
            tmsg = await th.fetch_message(st.thread_msg_id)
            emb, page_entries, total_pages = await build_sheet_thread_embed(st)
            await tmsg.edit(embed=emb, view=SheetThreadView(st, page_entries, total_pages))
    except Exception as e:
        log("edit thread sheet error:", repr(e))

async def sheet_leave_user(bot_client: discord.Client, st: SheetEventState, user_id: int) -> Tuple[bool, str]:
    try:
        headers, _rows = await load_sheet_rows(st.sheet_tab, force=True)
        await clear_user_from_sheet(st.sheet_tab, headers, user_id)
    except Exception as e:
        return (False, f"Sheet hatası: {e}")

    old_slot = st.user_slot.get(user_id)
    if old_slot and old_slot in st.slots:
        role_name, old_uid = st.slots[old_slot]
        if old_uid == user_id:
            st.slots[old_slot] = (role_name, None)
    st.user_slot.pop(user_id, None)

    await _edit_sheet_messages(bot_client, st)
    return (True, "OK")

def _pretty_group_name(g: str) -> str:
    g = g.strip().upper()
    mapping = {
        "WEAPON": "Weapon",
        "OFFHAND": "Offhand",
        "HEAD": "Head",
        "HOOD": "Head",
        "ARMOR": "Armor",
        "SHOES": "Shoes",
        "CAPE": "Cape",
        "POT": "Pot",
        "FOOD": "Food",
    }
    return mapping.get(g, g.title())

def build_set_embeds(role: str, row: SheetRoleRow, headers: List[str], title_prefix: str) -> Tuple[discord.Embed, Optional[discord.Embed]]:
    e = discord.Embed(title=f"{title_prefix} • {role}", description="Setin:")

    def get_any(*cands: str) -> str:
        for c in cands:
            for h in headers:
                if _norm(h) == _norm(c):
                    v = (row.values.get(h) or "").strip()
                    if v:
                        return v
        return ""

    base_fields = [
        ("Weapon", "WEAPON"),
        ("Offhand", "OFFHAND"),
        ("Head", "HEAD"),
        ("Armor", "ARMOR"),
        ("Shoes", "SHOES"),
        ("Cape", "CAPE"),
        ("Pot", "POT"),
        ("Food", "FOOD"),
    ]
    any_base = False
    for label, key in base_fields:
        v = get_any(key)
        if v:
            any_base = True
            e.add_field(name=label, value=v, inline=False)
    if not any_base:
        e.add_field(name="Set", value="(Sheet'te set kolonları bulunamadı ya da boş.)", inline=False)

    swap_cols: Dict[str, List[str]] = {}
    for h in headers:
        m = re.match(r"(?i)^\s*swap[_\-\s]*([a-z0-9]+)", (h or "").strip())
        if not m:
            continue
        grp = m.group(1).upper()
        swap_cols.setdefault(grp, []).append(h)

    for grp in list(swap_cols.keys()):
        swap_cols[grp].sort(key=lambda x: headers.index(x) if x in headers else 9999)

    swap_embed = None
    swap_any = False
    for grp, hs in swap_cols.items():
        vals = []
        for h in hs:
            v = (row.values.get(h) or "").strip()
            if v:
                vals.append(v)
        if vals:
            swap_any = True
            break

    if swap_any:
        swap_embed = discord.Embed(title="🔁 SWAP SETİ", description="Yanına almayı unutma.")
        order = ["WEAPON","OFFHAND","HEAD","ARMOR","SHOES","CAPE","POT","FOOD"]
        ordered_groups = [g for g in order if g in swap_cols] + [g for g in swap_cols.keys() if g not in order]

        for grp in ordered_groups:
            hs = swap_cols[grp]
            vals = []
            for h in hs:
                v = (row.values.get(h) or "").strip()
                if v:
                    vals.append(v)
            if not vals:
                continue
            swap_embed.add_field(name=_pretty_group_name(grp), value="\n".join(vals), inline=False)

    return e, swap_embed

async def sheet_assign_role(interaction: discord.Interaction, st: SheetEventState, chosen_variant_id: str, source: str = "msg") -> None:
    chosen_variant_id = (chosen_variant_id or "").strip()
    if "|" not in chosen_variant_id:
        return await safe_send(interaction, "❌ Seçim hatalı.", ephemeral=True)
    chosen_role_key, chosen_sig8 = chosen_variant_id.split("|", 1)
    chosen_role_key = chosen_role_key.strip()
    chosen_sig8 = chosen_sig8.strip()

    try:
        headers, rows = await load_sheet_rows(st.sheet_tab, force=True)
        role_rows = _find_rows_for_variant(headers, rows, chosen_role_key, chosen_sig8)
        if not role_rows:
            return await safe_send(interaction, "❌ Bu rol/varyant sheet'te bulunamadı.", ephemeral=True)
    except Exception as e:
        return await safe_send(interaction, f"❌ Sheet okuma hatası: {e}", ephemeral=True)

    old_slot = st.user_slot.get(interaction.user.id)
    if old_slot and old_slot in st.slots:
        old_role_name, old_uid = st.slots[old_slot]
        if old_uid == interaction.user.id:
            st.slots[old_slot] = (old_role_name, None)

    chosen_row: Optional[SheetRoleRow] = None
    chosen_slot_key: Optional[str] = None
    for rr in role_rows:
        sk = str(rr.row_idx)
        role_name, uid = st.slots.get(sk, (rr.role, None))
        if uid is None:
            chosen_row = rr
            chosen_slot_key = sk
            break

    if not chosen_row or not chosen_slot_key:
        row_idxs = [rr.row_idx for rr in role_rows]
        filled, total = _count_rows_in_state(st.slots, row_idxs)
        return await safe_send(interaction, f"❌ Slot dolu. ({filled}/{total})", ephemeral=True)

    try:
        headers2, _rows2 = await load_sheet_rows(st.sheet_tab, force=True)
        await clear_user_from_sheet(st.sheet_tab, headers2, interaction.user.id)
        await set_role_nick(st.sheet_tab, headers2, chosen_row, sheet_user_string(interaction.user))
    except Exception as e:
        return await safe_send(interaction, f"❌ Sheet yazma hatası: {e}", ephemeral=True)

    st.slots[chosen_slot_key] = (chosen_row.role, interaction.user.id)
    st.user_slot[interaction.user.id] = chosen_slot_key

    await _edit_sheet_messages(interaction.client, st)

    main_embed, swap_embed = build_set_embeds(chosen_row.role, chosen_row, headers, title_prefix=st.title)
    dm_text = (
        f"✅ **{st.title}** rolün: **{chosen_row.role}**\n"
        f"⏰ **Zaman:** **{st.time_tr} / {st.time_utc} UTC**\n"
        f"📍 **Toplanma Yeri:** **{st.toplanma}**\n"
        f"⚠️ **Geç kalmamaya özen göster.**"
    )
    try:
        await interaction.user.send(content=dm_text, embed=main_embed)
        if swap_embed is not None:
            await interaction.user.send(embed=swap_embed)
        return await safe_send(interaction, "✅ Setin DM’den gönderildi.", ephemeral=True)
    except Exception:
        txt = f"✅ DM kapalıydı. Seti burada gösteriyorum:\n\n{dm_text}"
        await safe_send(interaction, txt, ephemeral=True, embed=main_embed)
        if swap_embed is not None:
            await safe_send(interaction, "🔁 Swap seti:", ephemeral=True, embed=swap_embed)

# =========================================================
#                 /CONTENT (SHEET MODAL)
# =========================================================
class SheetContentModal(discord.ui.Modal):
    def __init__(self, sheet_key: str):
        self.sheet_key = (sheet_key or "").strip()

        title = "Sheet"
        if self.sheet_key == "avaskip":
            title = "AVA SKIP"
        elif self.sheet_key == "10man":
            title = "10MAN"
        elif self.sheet_key == "brawlcomp":
            title = "Brawl Comp"
        elif self.sheet_key.startswith("dyn:"):
            k = self.sheet_key.split(":", 1)[1].strip()
            cfg = DYNAMIC_SHEETS.get(k)
            if cfg:
                title = (cfg.get("name") or "Sheet")[:45]

        super().__init__(title=title)

        self.time = discord.ui.TextInput(label="Saat", required=False, placeholder="00:00", max_length=40)
        self.toplanma = discord.ui.TextInput(label="Toplanma", required=False, placeholder="Martlock", max_length=100)
        self.binek = discord.ui.TextInput(label="Binek", required=False, placeholder=DEFAULT_MOUNT, max_length=60)
        self.ayar = discord.ui.TextInput(label="Ayar", required=False, placeholder=DEFAULT_AYAR_FALLBACK, max_length=60)
        self.add_item(self.time)
        self.add_item(self.toplanma)
        self.add_item(self.binek)
        self.add_item(self.ayar)

    async def on_submit(self, interaction: discord.Interaction):
        await safe_defer(interaction, ephemeral=True)
        try:
            if self.sheet_key == "avaskip":
                await create_sheet_event(
                    interaction,
                    sheet_tab=AVASKIP_SHEET_TAB,
                    title="AVA SKIP",
                    thread_name="AVA SKIP",
                    time=self.time.value,
                    toplanma=self.toplanma.value,
                    binek=self.binek.value,
                    ayar=self.ayar.value,
                )
                return await safe_send(interaction, "✅ Oluşturuldu.", ephemeral=True)

            if self.sheet_key == "10man":
                await create_sheet_event(
                    interaction,
                    sheet_tab=TENMAN_SHEET_TAB,
                    title="10MAN",
                    thread_name="10MAN",
                    time=self.time.value,
                    toplanma=self.toplanma.value,
                    binek=self.binek.value,
                    ayar=self.ayar.value,
                )
                return await safe_send(interaction, "✅ Oluşturuldu.", ephemeral=True)

            if self.sheet_key == "brawlcomp":
                await create_sheet_event(
                    interaction,
                    sheet_tab=BRAWLCOMP_SHEET_TAB,
                    title="Brawl Comp",
                    thread_name="Brawl Comp",
                    time=self.time.value,
                    toplanma=self.toplanma.value,
                    binek=self.binek.value,
                    ayar=self.ayar.value,
                )
                return await safe_send(interaction, "✅ Oluşturuldu.", ephemeral=True)

            if self.sheet_key.startswith("dyn:"):
                dyn_key = self.sheet_key.split(":", 1)[1].strip()
                cfg = DYNAMIC_SHEETS.get(dyn_key)
                if not cfg:
                    return await safe_send(interaction, "❌ Bu içerik yok.", ephemeral=True)

                sheet_id = (cfg.get("sheet_id") or "").strip()
                tab = (cfg.get("tab") or "").strip()
                name = (cfg.get("name") or dyn_key).strip() or dyn_key

                if not sheet_id or not tab:
                    return await safe_send(interaction, "❌ Sheet ayarı eksik.", ephemeral=True)

                await create_sheet_event(
                    interaction,
                    sheet_tab=_make_sheet_ref(sheet_id, tab),
                    title=name,
                    thread_name=name[:90],
                    time=self.time.value,
                    toplanma=self.toplanma.value,
                    binek=self.binek.value,
                    ayar=self.ayar.value,
                )
                return await safe_send(interaction, "✅ Oluşturuldu.", ephemeral=True)

            return await safe_send(interaction, "❌ Bilinmeyen.", ephemeral=True)
        except Exception as e:
            await safe_send(interaction, f"❌ Hata: {e}", ephemeral=True)

# =========================================================
#                       CUSTOM BUILDER
# =========================================================
CUSTOM_ROLES_ORDER = ["tank","engage_tank","def_tank","dps","pierce","healer","support","sc","perma","wailing"]
PENDING_CUSTOM: Dict[int, Dict] = {}

def custom_text(uid: int) -> str:
    d = PENDING_CUSTOM.get(uid, {})
    counts: Dict[str, int] = d.get("counts", {})
    total = sum(int(counts.get(r, 0)) for r in CUSTOM_ROLES_ORDER)
    lines = [
        f"**Custom:** {d.get('title','')} | Thread: {d.get('thread_name','')}",
        f"⏰ {d.get('time','BELİRTİLMEMİŞ')} | 📍 {d.get('toplanma','BELİRTİLMEMİŞ')}",
        f"🐎 {d.get('mount',DEFAULT_MOUNT)} | ⚠️ {d.get('ayar',DEFAULT_AYAR_FALLBACK)}",
        f"✨ Subtitle: {d.get('subtitle','') or '-'}",
        "",
        "**Rol Sayıları:**",
    ]
    for r in CUSTOM_ROLES_ORDER:
        lines.append(f"{ROLE_LABELS[r]} = **{int(counts.get(r,0))}**")
    lines += ["", f"**Toplam kapasite:** **{total}**"]
    return "\n".join(lines)

class CustomBasicsModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Custom Content")
        self.title_in = discord.ui.TextInput(label="Content Adı (Başlık)", required=True, placeholder="Örn: 🇦 🇻 🇦 🇱 🇴 🇳", max_length=80)
        self.thread_in = discord.ui.TextInput(label="Thread Adı", required=True, placeholder="Örnek: AVALON", max_length=40)
        self.time_in = discord.ui.TextInput(label="Saat ", required=False, placeholder="00:00", max_length=40)
        self.top_in = discord.ui.TextInput(label="Toplanma Yeri", required=False, placeholder="Martlock", max_length=100)
        self.mount_in = discord.ui.TextInput(label="Binek", required=False, placeholder=DEFAULT_MOUNT, max_length=60)
        self.add_item(self.title_in); self.add_item(self.thread_in); self.add_item(self.time_in); self.add_item(self.top_in); self.add_item(self.mount_in)

    async def on_submit(self, interaction: discord.Interaction):
        PENDING_CUSTOM[interaction.user.id] = {
            "title": str(self.title_in.value).strip(),
            "thread_name": str(self.thread_in.value).strip(),
            "time": str(self.time_in.value).strip() if self.time_in.value else None,
            "toplanma": str(self.top_in.value).strip() if self.top_in.value else None,
            "mount": str(self.mount_in.value).strip() if self.mount_in.value else DEFAULT_MOUNT,
            "ayar": DEFAULT_AYAR_FALLBACK,
            "subtitle": "",
            "counts": {r: 0 for r in CUSTOM_ROLES_ORDER},
            "selected_role": CUSTOM_ROLES_ORDER[0],
        }
        await safe_send(interaction, custom_text(interaction.user.id), ephemeral=True, view=CustomBuilderView(interaction.user.id))

class CustomExtraModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Custom Extra")
        self.ayar_in = discord.ui.TextInput(label="Ayar", required=False, placeholder=DEFAULT_AYAR_FALLBACK, max_length=60)
        self.sub_in = discord.ui.TextInput(label="Altyazı", required=False, placeholder="Boş bırakabilirsin", max_length=100)
        self.add_item(self.ayar_in); self.add_item(self.sub_in)

    async def on_submit(self, interaction: discord.Interaction):
        d = PENDING_CUSTOM.get(interaction.user.id)
        if not d:
            return await safe_send(interaction, "Custom state yok.", ephemeral=True)
        if self.ayar_in.value and str(self.ayar_in.value).strip():
            d["ayar"] = str(self.ayar_in.value).strip()
        d["subtitle"] = str(self.sub_in.value).strip() if self.sub_in.value is not None else d.get("subtitle","")
        PENDING_CUSTOM[interaction.user.id] = d

        try:
            if interaction.message:
                await interaction.message.edit(content=custom_text(interaction.user.id), view=CustomBuilderView(interaction.user.id))
        except Exception as e:
            log("custom extra edit error:", repr(e))

class CustomSetCountModal(discord.ui.Modal):
    def __init__(self, role: str):
        super().__init__(title=f"Set: {ROLE_LABELS.get(role, role)}")
        self.role = role
        self.count_in = discord.ui.TextInput(label="Kaç tane?", required=True, placeholder="0", max_length=3)
        self.add_item(self.count_in)

    async def on_submit(self, interaction: discord.Interaction):
        d = PENDING_CUSTOM.get(interaction.user.id)
        if not d:
            return await safe_send(interaction, "Custom state yok.", ephemeral=True)
        try:
            n = int(str(self.count_in.value).strip())
            if n < 0:
                n = 0
        except ValueError:
            n = 0
        d["counts"][self.role] = n
        PENDING_CUSTOM[interaction.user.id] = d

        try:
            if interaction.message:
                await interaction.message.edit(content=custom_text(interaction.user.id), view=CustomBuilderView(interaction.user.id))
        except Exception as e:
            log("custom set edit error:", repr(e))

class RolePickSelect(discord.ui.Select):
    def __init__(self, uid: int):
        d = PENDING_CUSTOM.get(uid, {})
        selected = d.get("selected_role", CUSTOM_ROLES_ORDER[0])
        opts = []
        for r in CUSTOM_ROLES_ORDER:
            opts.append(discord.SelectOption(label=ROLE_LABELS[r], value=r, emoji=ROLE_EMOJI[r], default=(r == selected)))
        super().__init__(placeholder="Rol seç", min_values=1, max_values=1, options=opts)

    async def callback(self, interaction: discord.Interaction):
        d = PENDING_CUSTOM.get(interaction.user.id)
        if not d:
            return await safe_send(interaction, "Custom state yok.", ephemeral=True)
        d["selected_role"] = self.values[0]
        PENDING_CUSTOM[interaction.user.id] = d
        await safe_defer(interaction, ephemeral=True)
        try:
            if interaction.message:
                await interaction.message.edit(content=custom_text(interaction.user.id), view=CustomBuilderView(interaction.user.id))
        except Exception as e:
            log("custom rolepick edit error:", repr(e))

class BtnPlus(discord.ui.Button):
    def __init__(self):
        super().__init__(label="+1", style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction):
        d = PENDING_CUSTOM.get(interaction.user.id)
        if not d:
            return await safe_send(interaction, "Custom state yok.", ephemeral=True)
        r = d.get("selected_role", CUSTOM_ROLES_ORDER[0])
        d["counts"][r] = int(d["counts"].get(r, 0)) + 1
        PENDING_CUSTOM[interaction.user.id] = d
        await safe_defer(interaction, ephemeral=True)
        try:
            if interaction.message:
                await interaction.message.edit(content=custom_text(interaction.user.id), view=CustomBuilderView(interaction.user.id))
        except Exception as e:
            log("custom + edit error:", repr(e))

class BtnMinus(discord.ui.Button):
    def __init__(self):
        super().__init__(label="-1", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        d = PENDING_CUSTOM.get(interaction.user.id)
        if not d:
            return await safe_send(interaction, "Custom state yok.", ephemeral=True)
        r = d.get("selected_role", CUSTOM_ROLES_ORDER[0])
        d["counts"][r] = max(0, int(d["counts"].get(r, 0)) - 1)
        PENDING_CUSTOM[interaction.user.id] = d
        await safe_defer(interaction, ephemeral=True)
        try:
            if interaction.message:
                await interaction.message.edit(content=custom_text(interaction.user.id), view=CustomBuilderView(interaction.user.id))
        except Exception as e:
            log("custom - edit error:", repr(e))

class BtnSet(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Set", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        d = PENDING_CUSTOM.get(interaction.user.id)
        if not d:
            return await safe_send(interaction, "Custom state yok.", ephemeral=True)
        r = d.get("selected_role", CUSTOM_ROLES_ORDER[0])
        try:
            await interaction.response.send_modal(CustomSetCountModal(r))
        except Exception as e:
            log("custom set modal error:", repr(e))
            await safe_send(interaction, "❌ Modal açılamadı. Tekrar dene.", ephemeral=True)

class BtnExtra(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Ayar / Altyazı", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.send_modal(CustomExtraModal())
        except Exception as e:
            log("custom extra modal error:", repr(e))
            await safe_send(interaction, "❌ Modal açılamadı. Tekrar dene.", ephemeral=True)

class BtnCreate(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Etkinlik Oluştur", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        d = PENDING_CUSTOM.get(interaction.user.id)
        if not d:
            return await safe_send(interaction, "Custom state yok.", ephemeral=True)
        total = sum(int(d["counts"].get(r, 0)) for r in CUSTOM_ROLES_ORDER)
        if total <= 0:
            return await safe_send(interaction, "En az 1 slot seç.", ephemeral=True)

        roles = [(r, int(d["counts"][r])) for r in CUSTOM_ROLES_ORDER if int(d["counts"][r]) > 0]
        roles.append(("fill", 999))
        tpl = EventTemplate("custom", d["title"], d.get("subtitle",""), d["thread_name"], roles)

        await safe_defer(interaction, ephemeral=True)
        try:
            await create_event_in_channel(
                interaction=interaction,
                template=tpl,
                time=d.get("time"),
                toplanma=d.get("toplanma"),
                binek=d.get("mount"),
                ayar=d.get("ayar"),
            )
            PENDING_CUSTOM.pop(interaction.user.id, None)
            await safe_send(interaction, "✅ Custom event oluşturuldu.", ephemeral=True)
        except Exception as e:
            await safe_send(interaction, f"❌ Hata: {e}", ephemeral=True)

class BtnCancel(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Cancel", style=discord.ButtonStyle.danger)

    async def callback(self, interaction: discord.Interaction):
        PENDING_CUSTOM.pop(interaction.user.id, None)
        await safe_defer(interaction, ephemeral=True)
        try:
            if interaction.message:
                await interaction.message.edit(content="İptal edildi.", view=None)
        except Exception as e:
            log("custom cancel edit error:", repr(e))

class CustomBuilderView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=600)
        self.owner_id = owner_id
        self.add_item(RolePickSelect(owner_id))
        self.add_item(BtnPlus())
        self.add_item(BtnMinus())
        self.add_item(BtnSet())
        self.add_item(BtnExtra())
        self.add_item(BtnCreate())
        self.add_item(BtnCancel())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.owner_id

# =========================================================
#                       /CONTENT MENU
# =========================================================
class ContentModal(discord.ui.Modal):
    def __init__(self, key: str):
        super().__init__(title="Content")
        self.key = key
        self.time = discord.ui.TextInput(label="Saat", required=False, placeholder="00:00", max_length=40)
        self.toplanma = discord.ui.TextInput(label="Toplanma Yeri", required=False, placeholder="Martlock", max_length=100)
        self.binek = discord.ui.TextInput(label="Binek", required=False, placeholder=DEFAULT_MOUNT, max_length=60)
        self.ayar = discord.ui.TextInput(label="Ayar", required=False, placeholder=DEFAULT_AYAR_FALLBACK, max_length=60)
        self.add_item(self.time); self.add_item(self.toplanma); self.add_item(self.binek); self.add_item(self.ayar)

    async def on_submit(self, interaction: discord.Interaction):
        await safe_defer(interaction, ephemeral=True)
        try:
            tpl = PRESETS[self.key]
            await create_event_in_channel(interaction, tpl, self.time.value, self.toplanma.value, self.binek.value, self.ayar.value)
            await safe_send(interaction, "✅ Event oluşturuldu.", ephemeral=True)
        except Exception as e:
            await safe_send(interaction, f"❌ Hata: {e}", ephemeral=True)


class CustomAllModal(discord.ui.Modal):
    """Custom All için özel modal - başlık alanı var."""
    def __init__(self):
        super().__init__(title="Custom All Content")
        self.baslik = discord.ui.TextInput(label="Başlık", required=True, placeholder="Örn: ZVZ, GANK, HO...", max_length=60)
        self.time = discord.ui.TextInput(label="Saat", required=False, placeholder="00:00", max_length=40)
        self.toplanma = discord.ui.TextInput(label="Toplanma Yeri", required=False, placeholder="Martlock", max_length=100)
        self.binek = discord.ui.TextInput(label="Binek", required=False, placeholder=DEFAULT_MOUNT, max_length=60)
        self.ayar = discord.ui.TextInput(label="Ayar", required=False, placeholder=DEFAULT_AYAR_FALLBACK, max_length=60)
        self.add_item(self.baslik)
        self.add_item(self.time)
        self.add_item(self.toplanma)
        self.add_item(self.binek)
        self.add_item(self.ayar)

    async def on_submit(self, interaction: discord.Interaction):
        await safe_defer(interaction, ephemeral=True)
        try:
            baslik = (self.baslik.value or "CUSTOM").strip().upper()
            # Özel template oluştur - kullanıcının başlığıyla
            tpl = EventTemplate(
                key="custom_all",
                title=f"🎮 {baslik}",
                subtitle="Herkes istediği role katılabilir!",
                thread_name=baslik,
                roles=[("tank", 999), ("def_tank", 999), ("dps", 999), ("pierce", 999), ("healer", 999)]
            )
            await create_event_in_channel(interaction, tpl, self.time.value, self.toplanma.value, self.binek.value, self.ayar.value)
            await safe_send(interaction, "✅ Event oluşturuldu.", ephemeral=True)
        except Exception as e:
            await safe_send(interaction, f"❌ Hata: {e}", ephemeral=True)

class ContentSelect(discord.ui.Select):
    def __init__(self):
        opts: List[discord.SelectOption] = [
            discord.SelectOption(label="Infinity (Avalon)", value="infinity", emoji="♾️"),
            discord.SelectOption(label="Avalon", value="avalon", emoji="🇦"),
            discord.SelectOption(label="Dungeon (Group)", value="dungeon", emoji="🇬"),
            discord.SelectOption(label="Kristal", value="kristal", emoji="🇰"),
            discord.SelectOption(label="Faction", value="faction", emoji="🇫"),
            discord.SelectOption(label="Track", value="track", emoji="🇹"),
            discord.SelectOption(label="Statik", value="statik", emoji="🇸"),
            discord.SelectOption(label="STATIC SPEED", value="static_speed", emoji="⚡"),
            discord.SelectOption(label="Custom All", value="custom_all", emoji="🎮"),
            discord.SelectOption(label="AVA SKIP", value="sheet_avaskip", emoji="🧩"),
            discord.SelectOption(label="10MAN", value="sheet_10man", emoji="🔟"),
            discord.SelectOption(label="Brawl Comp", value="sheet_brawlcomp", emoji="⚔️"),
        ]

        # dynamic sheets (25 option limit)
        try:
            dyn_items = sorted(
                DYNAMIC_SHEETS.items(),
                key=lambda kv: (kv[1].get("name", kv[0]).lower(), kv[0].lower())
            )
        except Exception:
            dyn_items = []

        max_opts = 25
        # keep 1 slot for "Custom"
        remaining = max(0, (max_opts - 1) - len(opts))

        for k, cfg in dyn_items[:remaining]:
            name = (cfg.get("name") or k).strip() or k
            emoji = (cfg.get("emoji") or "📄").strip() or "📄"
            opts.append(discord.SelectOption(label=name[:100], value=f"sheet_dyn:{k}", emoji=emoji))

        opts.append(discord.SelectOption(label="Custom", value="custom", emoji="🛠️"))

        super().__init__(placeholder="👇 Content seç", min_values=1, max_values=1, options=opts)

    async def callback(self, interaction: discord.Interaction):
        key = (self.values[0] or "").strip()

        if key == "sheet_avaskip":
            try:
                return await interaction.response.send_modal(SheetContentModal("avaskip"))
            except Exception as e:
                log("sheet avaskip modal error:", repr(e))
                return await safe_send(interaction, "❌ Açılmadı.", ephemeral=True)

        if key == "sheet_10man":
            try:
                return await interaction.response.send_modal(SheetContentModal("10man"))
            except Exception as e:
                log("sheet 10man modal error:", repr(e))
                return await safe_send(interaction, "❌ Açılmadı.", ephemeral=True)

        if key == "sheet_brawlcomp":
            try:
                return await interaction.response.send_modal(SheetContentModal("brawlcomp"))
            except Exception as e:
                log("sheet brawlcomp modal error:", repr(e))
                return await safe_send(interaction, "❌ Açılmadı.", ephemeral=True)

        if key.startswith("sheet_dyn:"):
            dyn_key = key.split(":", 1)[1].strip()
            try:
                return await interaction.response.send_modal(SheetContentModal(f"dyn:{dyn_key}"))
            except Exception as e:
                log("sheet dyn modal error:", repr(e))
                return await safe_send(interaction, "❌ Açılmadı.", ephemeral=True)

        # Custom All için özel modal
        if key == "custom_all":
            try:
                return await interaction.response.send_modal(CustomAllModal())
            except Exception as e:
                log("custom_all modal error:", repr(e))
                return await safe_send(interaction, "❌ Açılmadı.", ephemeral=True)

        try:
            await interaction.response.send_modal(ContentModal(key))
        except Exception as e:
            log("content modal error:", repr(e))
            await safe_send(interaction, "❌ Açılmadı.", ephemeral=True)
class ContentView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)
        self.add_item(ContentSelect())

# =========================================================
#                   ALBION KILLBOT HELPERS
# =========================================================

def _kb_load_state() -> Dict[str, Any]:
    """Load killbot state with backup support.

    Supports legacy format:
      {"last_event_id": 123}

    New format:
      {
        "guild_last_event_id": 123,
        "member_seen_kill_ids": [...],
        "member_seen_death_ids": [...],
        "last_saved_at": "ISO timestamp"
      }
    """
    def _parse_state(j: dict) -> Dict[str, Any]:
        guild_last = _kb_safe_int(j.get("guild_last_event_id"), _kb_safe_int(j.get("last_event_id"), 0))
        sk = j.get("member_seen_kill_ids") or j.get("seen_kill_ids") or []
        sd = j.get("member_seen_death_ids") or j.get("seen_death_ids") or []
        if not isinstance(sk, list):
            sk = []
        if not isinstance(sd, list):
            sd = []
        link_mode = (j.get("link_mode") or j.get("kb_link_mode") or "").strip().lower()
        if link_mode in ("murder", "murderledger", "ml"):
            link_mode = "murder"
        elif link_mode in ("albion", "official"):
            link_mode = "albion"
        else:
            link_mode = ""
        return {
            "guild_last_event_id": int(guild_last),
            "member_seen_kill_ids": [int(x) for x in sk if str(x).isdigit()],
            "member_seen_death_ids": [int(x) for x in sd if str(x).isdigit()],
            "link_mode": link_mode,
            "last_saved_at": j.get("last_saved_at", ""),
        }
    
    # Ana dosyayı dene
    try:
        with open(KILLBOT_STATE_FILE, "r", encoding="utf-8") as f:
            j = json.load(f)
        if isinstance(j, dict):
            result = _parse_state(j)
            # Geçerli bir state varsa döndür
            if result["guild_last_event_id"] > 0 or result["member_seen_kill_ids"] or result["member_seen_death_ids"]:
                log(f"[KB] State yüklendi: guild_eid={result['guild_last_event_id']}, kills={len(result['member_seen_kill_ids'])}, deaths={len(result['member_seen_death_ids'])}")
                return result
    except FileNotFoundError:
        pass
    except Exception as e:
        log(f"[KB] Ana state dosyası okunamadı: {e}")
    
    # Backup dosyasını dene
    try:
        with open(KILLBOT_STATE_BACKUP_FILE, "r", encoding="utf-8") as f:
            j = json.load(f)
        if isinstance(j, dict):
            result = _parse_state(j)
            if result["guild_last_event_id"] > 0 or result["member_seen_kill_ids"] or result["member_seen_death_ids"]:
                log(f"[KB] Backup state yüklendi: guild_eid={result['guild_last_event_id']}")
                return result
    except Exception:
        pass
    
    log("[KB] State dosyası yok veya boş - sıfırdan başlanacak")
    return {"guild_last_event_id": 0, "member_seen_kill_ids": [], "member_seen_death_ids": [], "link_mode": ""}

def _kb_save_state(state: Dict[str, Any]) -> None:
    """Save state with backup."""
    try:
        state["last_saved_at"] = datetime.now(UTC_TZ).isoformat()
        
        # Önce backup al (eski ana dosyayı)
        try:
            if os.path.exists(KILLBOT_STATE_FILE):
                import shutil
                shutil.copy2(KILLBOT_STATE_FILE, KILLBOT_STATE_BACKUP_FILE)
        except Exception:
            pass
        
        # Yeni state'i kaydet
        with open(KILLBOT_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        log(f"[KB] State kaydetme hatası: {e}")


def _kb_parse_event_time(ev: dict) -> Optional[datetime]:
    """Parse event timestamp and return datetime object."""
    ts = ev.get("TimeStamp") or ev.get("timestamp") or ""
    if not ts:
        return None
    try:
        # Format: "2024-12-26T16:10:00.000000Z" veya benzeri
        ts = str(ts).replace("Z", "+00:00")
        if "." in ts and "+" in ts:
            # Mikrosaniyeyi kısalt
            parts = ts.split("+")
            base = parts[0]
            tz = parts[1] if len(parts) > 1 else "00:00"
            if "." in base:
                date_part, micro = base.rsplit(".", 1)
                micro = micro[:6]  # Max 6 digit
                ts = f"{date_part}.{micro}+{tz}"
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _kb_is_event_too_old(ev: dict, max_hours: int = None) -> bool:
    """Check if event is older than max_hours. Returns True if too old."""
    if max_hours is None:
        max_hours = KILLBOT_MAX_EVENT_AGE_HOURS
    if max_hours <= 0:
        return False  # Disabled
    
    event_time = _kb_parse_event_time(ev)
    if not event_time:
        return False  # Can't determine, allow it
    
    now = datetime.now(UTC_TZ)
    age = now - event_time.replace(tzinfo=UTC_TZ)
    age_hours = age.total_seconds() / 3600
    
    return age_hours > max_hours


def _kb_format_event_age(ev: dict) -> str:
    """Return human-readable event age."""
    event_time = _kb_parse_event_time(ev)
    if not event_time:
        return "?"
    
    now = datetime.now(UTC_TZ)
    age = now - event_time.replace(tzinfo=UTC_TZ)
    
    if age.days > 0:
        return f"{age.days} gün önce"
    hours = int(age.total_seconds() / 3600)
    if hours > 0:
        return f"{hours} saat önce"
    minutes = int(age.total_seconds() / 60)
    return f"{minutes} dk önce"


def _kb_render_url(item_type: str, enchant: int = 0, quality: int = 0, size: int = 64) -> str:
    """Generate item render URL with proper quality handling for better icon availability."""
    it = (item_type or "").strip()
    if not it:
        return ""
    if "@" not in it and enchant and int(enchant) > 0:
        it = f"{it}@{int(enchant)}"
    # FIX: Use quality=1 minimum to ensure icons are available (quality=0 often fails)
    q = max(1, int(quality)) if quality is not None else 1
    s = max(32, min(256, int(size))) if size is not None else 64
    return f"https://render.albiononline.com/v1/item/{it}?quality={q}&size={s}"

def _kb_item_line(item: Optional[dict]) -> str:
    if not item or not isinstance(item, dict):
        return ""
    t = (item.get("Type") or "").strip()
    if not t:
        return ""
    count = int(item.get("Count") or 1)
    ench = int(item.get("EnchantmentLevel") or 0)
    qual = int(item.get("Quality") or 0)

    t_disp = t
    if "@" not in t_disp and ench > 0:
        t_disp = f"{t_disp}@{ench}"
    suffix = []
    if qual:
        suffix.append(f"Q{qual}")
    if count and count > 1:
        suffix.append(f"x{count}")

    return f"`{t_disp}`" + (f" ({', '.join(suffix)})" if suffix else "")

def _kb_safe_int(x, default=0):
    try:
        return int(x)
    except Exception:
        return default

def _kb_parse_ts(ts: str) -> Optional[datetime]:
    # gameinfo timestamp often like: 2025-12-25T00:37:13.069764600Z (nanoseconds)
    s = (ts or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s2 = s[:-1]
        else:
            s2 = s
        if "." in s2:
            base, frac = s2.split(".", 1)
            frac = re.sub(r"[^\d]", "", frac)
            frac = (frac + "000000")[:6]
            s2 = base + "." + frac
            dt = datetime.strptime(s2, "%Y-%m-%dT%H:%M:%S.%f")
        else:
            dt = datetime.strptime(s2, "%Y-%m-%dT%H:%M:%S")
        return dt.replace(tzinfo=UTC_TZ)
    except Exception:
        return None

def _kb_when_str(ts: str) -> str:
    dt = _kb_parse_ts(ts)
    if not dt:
        return ts or "?"
    dt_tr = dt.astimezone(TR_TZ)
    now_tr = datetime.now(TR_TZ)
    if dt_tr.date() == now_tr.date():
        return f"Bugün {dt_tr.strftime('%H:%M')}"
    return dt_tr.strftime("%Y-%m-%d %H:%M")

def _kb_get_equipment(d: dict) -> dict:
    eq = d.get("Equipment")
    return eq if isinstance(eq, dict) else {}

def _kb_pick_weapon_icon(eq: dict) -> str:
    mh = eq.get("MainHand") if isinstance(eq, dict) else None
    oh = eq.get("OffHand") if isinstance(eq, dict) else None
    for it in (mh, oh):
        if isinstance(it, dict) and (it.get("Type") or "").strip():
            return _kb_render_url(
                item_type=it.get("Type") or "",
                enchant=_kb_safe_int(it.get("EnchantmentLevel"), 0),
                quality=_kb_safe_int(it.get("Quality"), 0),
                size=KILLBOT_RENDER_SIZE,
            )
    return ""

def _kb_killboard_url(event_id: Any) -> str:
    """Return a Killboard URL for an event id. Returns '' if id is missing/invalid."""
    try:
        eid = int(str(event_id).strip())
    except Exception:
        return ""
    if eid <= 0:
        eid = 0

    # NOTE: Links are always sent to the official Albion Killboard.
    # Data source may differ, but URLs stay official to avoid confusion.
    return f"https://albiononline.com/en/killboard/kill/{eid}"


def _kb_battle_url(battle_id: Any) -> str:
    """Return a Killboard battle URL. Returns '' if id is missing/invalid."""
    try:
        bid = int(str(battle_id).strip())
    except Exception:
        return ""
    if bid <= 0:
        return ""
    return f"https://albiononline.com/en/killboard/battle/{bid}"

class KillbotLinks(discord.ui.View):
    def __init__(self, kill_url: str, battle_url: str = ""):
        super().__init__(timeout=None)
        self.kill_url = kill_url
        # Battle link is intentionally disabled (requested).
        # Keep the parameter to avoid breaking older calls.
        self.battle_url = ""

        if self.kill_url:
            self.add_item(discord.ui.Button(label="Killboard'ı Aç", url=self.kill_url))
        # never show Battle button

def _kb_find_guild_logo_path() -> Optional[str]:
    """Find guild logo file path for killbot embeds/images.

    Tries:
    - absolute path given in KILLBOT_GUILD_LOGO_FILE
    - same folder as bot.py
    - current working directory
    - /root, /home
    """
    fn = (KILLBOT_GUILD_LOGO_FILE or "").strip() or "guild.png"
    cand: List[str] = []
    try:
        if os.path.isabs(fn):
            cand.append(fn)
        else:
            cand.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), fn))
            cand.append(os.path.join(os.getcwd(), fn))
            cand.append(os.path.join("/root", fn))
            cand.append(os.path.join("/home", fn))
    except Exception:
        pass

    for p in cand:
        try:
            if p and os.path.isfile(p):
                return p
        except Exception:
            continue
    return None


# ===== Killbot helpers (missing definitions fix) =====
def _kb_item_icon_url(item_type: str, *, size: int = 64) -> str:
    """Small helper used by embeds to display an item icon as thumbnail."""
    it = (item_type or "").strip()
    if not it:
        return ""
    # Type may already include enchant like T6_XXX@2; quality is unknown here.
    return _kb_render_url(it, size=size)

# Slot order for equipment rendering (Victim/Killer Equipment dict keys from AO API)
_SLOT_ORDER: List[Tuple[str, str]] = [
    ("MainHand", "Ana Silah"),
    ("OffHand", "Yan El"),
    ("Head", "Kafa"),
    ("Armor", "Zırh"),
    ("Shoes", "Ayakkabı"),
    ("Bag", "Çanta"),
    ("Cape", "Pelerin"),
    ("Mount", "Binek"),
    ("Food", "Yiyecek"),
    ("Potion", "İksir"),
]

def _kb_build_embed(ev: dict, kind: str) -> discord.Embed:
    """Build a compact embed (no Location) showing only Fame + Time.

    Inventory/equipment visuals (when enabled) are shown via the generated image.
    """
    eid = (ev.get("EventId") or ev.get("id") or "?")
    ts = ev.get("TimeStamp") or ev.get("TimeStampISO") or ev.get("Time") or ""

    killer = ev.get("Killer") or {}
    victim = ev.get("Victim") or {}

    k_name = (killer.get("Name") or "Unknown").strip()
    v_name = (victim.get("Name") or "Unknown").strip()

    k_gname = (killer.get("GuildName") or "").strip()
    v_gname = (victim.get("GuildName") or "").strip()
    
    # Discord mention lookup
    killer_mention = ""
    victim_mention = ""
    if PLAYER_LINK_OK:
        try:
            killer_albion_id = (killer.get("Id") or "").strip()
            victim_albion_id = (victim.get("Id") or "").strip()
            
            if killer_albion_id:
                k_discord_id = get_discord_by_albion_id(killer_albion_id)
                if k_discord_id:
                    killer_mention = f" <@{k_discord_id}>"
            
            if victim_albion_id:
                v_discord_id = get_discord_by_albion_id(victim_albion_id)
                if v_discord_id:
                    victim_mention = f" <@{v_discord_id}>"
        except Exception:
            pass

    fame = _kb_safe_int(ev.get("TotalVictimKillFame"), 0)
    if fame <= 0:
        fame = _kb_safe_int(ev.get("TotalFame"), 0)

    if kind == "kill":
        title = f"✅ Öldürme: {v_name}"
    else:
        title = f"❌ Ölüm: {v_name}"

    left = f"**{k_name}**{killer_mention}" + (f" ({k_gname})" if k_gname else "")
    right = f"**{v_name}**{victim_mention}" + (f" ({v_gname})" if v_gname else "")
    desc = f"{left} ➜ {right}"

    e = discord.Embed(
        title=title,
        description=desc,
        url=_kb_killboard_url(str(eid)),
    )

    # Guild logo (thumbnail) - if guild.png exists, prefer it over weapon icon.
    _logo_path = _kb_find_guild_logo_path()
    if _logo_path:
        e.set_thumbnail(url="attachment://guild.png")

    # Fallback thumbnail: killer weapon icon (this gets overridden by guild.png if present)
    weapon_type = None
    try:
        weapon = killer.get("MainHand") or (killer.get("Equipment") or {}).get("MainHand")
        if isinstance(weapon, dict):
            weapon_type = weapon.get("Type")
        elif isinstance(weapon, str):
            weapon_type = weapon
    except Exception:
        weapon_type = None

    if (not _logo_path) and weapon_type:
        wurl = _kb_item_icon_url(weapon_type)
        if wurl:
            e.set_thumbnail(url=wurl)

    fame_str = f"{int(fame):,}".replace(",", ".") if fame else "0"
    e.add_field(name="🏆 Fame", value=fame_str, inline=True)
    e.add_field(name="🕒 Zaman", value=_kb_when_str(ts), inline=True)
    # Participant stats (best-effort)
    try:
        st = _kb_compute_stats(ev)
        p_total = int(st.get("participants_total", 0) or 0)
        party = int(st.get("party_size", 0) or 0)
        if p_total:
            e.add_field(
                name="👥 Fight",
                value=f"Katılan: {p_total}\nParty: {party or '-'}\nDMG: {int(st.get('dmg_count', 0) or 0)} • Heal: {int(st.get('heal_count', 0) or 0)}",
                inline=True,
            )
    except Exception:
        pass


    e.set_footer(text=f"Olay {eid}")
    return e

def _kb_slot_item(eq: dict, slot_key: str) -> Optional[dict]:
    if not isinstance(eq, dict):
        return None
    it = eq.get(slot_key)
    return it if isinstance(it, dict) else None

async def _kb_fetch_icon(session: aiohttp.ClientSession, url: str) -> Optional[bytes]:
    """Fetch an item render icon with small retry/backoff. Returns bytes or None."""
    if not url:
        return None
    headers = {"User-Agent": "CallidusKillbot/1.0"}
    retries = max(0, int(KILLBOT_ICON_RETRIES))
    for attempt in range(retries + 1):
        try:
            async with session.get(url, headers=headers) as r:
                if r.status == 200:
                    return await r.read()
                # transient errors: retry
                if r.status in (408, 425, 429, 500, 502, 503, 504):
                    raise aiohttp.ClientResponseError(
                        request_info=r.request_info,
                        history=r.history,
                        status=r.status,
                        message=f"HTTP {r.status}",
                        headers=r.headers,
                    )
                return None
        except Exception:
            if attempt >= retries:
                return None
            # exponential backoff (bounded)
            backoff = min(2.0, 0.4 * (2 ** attempt))
            try:
                await asyncio.sleep(backoff)
            except Exception:
                return None
    return None

def _kb_icon_disk_path(url: str) -> str:
    """Deterministic cache path for a render URL."""
    try:
        h = hashlib.sha1(url.encode('utf-8', errors='ignore')).hexdigest()
    except Exception:
        h = hashlib.sha1(str(url).encode('utf-8', errors='ignore')).hexdigest()
    d = KILLBOT_ICON_DISK_DIR or "killbot_icon_cache"
    return os.path.join(d, f"{h}.bin")

def _kb_try_load_icon_from_disk(url: str) -> Optional[bytes]:
    if not KILLBOT_ICON_DISK_CACHE:
        return None
    try:
        p = _kb_icon_disk_path(url)
        if not os.path.isfile(p):
            return None
        with open(p, 'rb') as f:
            b = f.read()
        return b if b else None
    except Exception:
        return None

def _kb_save_icon_to_disk(url: str, data: bytes) -> None:
    if not KILLBOT_ICON_DISK_CACHE:
        return
    if not data:
        return
    try:
        d = KILLBOT_ICON_DISK_DIR or "killbot_icon_cache"
        os.makedirs(d, exist_ok=True)
        p = _kb_icon_disk_path(url)
        # atomic-ish write
        tmp = p + ".tmp"
        with open(tmp, 'wb') as f:
            f.write(data)
        try:
            os.replace(tmp, p)
        except Exception:
            # fallback
            with open(p, 'wb') as f2:
                f2.write(data)
            try:
                os.remove(tmp)
            except Exception:
                pass
    except Exception:
        pass

async def _kb_prefetch_icons(bot: "CallidusBot", icon_urls) -> Dict[str, bytes]:
    """Prefetch icons with memory + optional disk cache and concurrency."""
    blobs: Dict[str, bytes] = {}
    if not icon_urls:
        return blobs
    if not getattr(bot, '_kb_http', None):
        return blobs

    urls = list(icon_urls)
    to_fetch: List[str] = []

    # warm from memory/disk
    for u in urls:
        if not u:
            continue
        b = bot._kb_icon_cache.get(u) if isinstance(getattr(bot, '_kb_icon_cache', None), dict) else None
        if b:
            blobs[u] = b
            continue
        b2 = _kb_try_load_icon_from_disk(u)
        if b2:
            blobs[u] = b2
            try:
                bot._kb_icon_cache[u] = b2
            except Exception:
                pass
            continue
        to_fetch.append(u)

    if not to_fetch:
        return blobs

    sem = asyncio.Semaphore(max(1, int(KILLBOT_ICON_CONCURRENCY)))

    async def fetch_one(u: str):
        async with sem:
            b3 = await _kb_fetch_icon(bot._kb_http, u)
        if b3:
            blobs[u] = b3
            try:
                bot._kb_icon_cache[u] = b3
            except Exception:
                pass
            _kb_save_icon_to_disk(u, b3)

    await asyncio.gather(*[fetch_one(u) for u in to_fetch], return_exceptions=True)

    # trim memory cache (simple FIFO)
    try:
        if isinstance(bot._kb_icon_cache, dict):
            while len(bot._kb_icon_cache) > int(KILLBOT_ICON_CACHE_MAX):
                bot._kb_icon_cache.pop(next(iter(bot._kb_icon_cache.keys())))
    except Exception:
        pass

    return blobs

def _kb_compute_stats(ev: dict) -> dict:
    """Compute participant stats for nicer embeds/images + a full report."""
    stats: Dict[str, Any] = {}
    killer = ev.get('Killer') if isinstance(ev.get('Killer'), dict) else {}
    victim = ev.get('Victim') if isinstance(ev.get('Victim'), dict) else {}
    killer_name = (killer.get('Name') or '').strip()
    parts = ev.get('Participants')

    participants: List[dict] = []
    if isinstance(parts, list):
        for p in parts:
            if not isinstance(p, dict):
                continue
            name = (p.get('Name') or '?').strip() or '?'
            dmg = _kb_safe_int(p.get('DamageDone') or 0, 0)
            heal = _kb_safe_int(p.get('HealDone') or p.get('HealingDone') or 0, 0)
            sup = _kb_safe_int(p.get('SupportHealingDone') or 0, 0)
            try:
                ip = float(p.get('AverageItemPower') or 0.0)
            except Exception:
                ip = 0.0
            participants.append({
                'name': name,
                'id': (p.get('Id') or '').strip(),
                'guild': (p.get('GuildName') or '').strip(),
                'alliance': (p.get('AllianceName') or '').strip(),
                'ip': ip,
                'dmg': dmg,
                'heal': heal,
                'support': sup,
            })

    stats['participants'] = participants
    stats['participants_total'] = len(participants)

    # party/group size (best-effort)
    party_size = 0
    gm = ev.get('GroupMembers')
    if isinstance(gm, list):
        party_size = len(gm)
    else:
        party_size = _kb_safe_int(ev.get('GroupMemberCount') or killer.get('GroupMemberCount') or 0, 0)
    stats['party_size'] = party_size

    dmg_list = [p for p in participants if (p.get('dmg') or 0) > 0]
    heal_list = [p for p in participants if ((p.get('heal') or 0) + (p.get('support') or 0)) > 0]
    stats['dmg_count'] = len(dmg_list)
    stats['heal_count'] = len(heal_list)

    assists = [p for p in participants if p.get('name') != killer_name and ((p.get('dmg') or 0) + (p.get('heal') or 0) + (p.get('support') or 0)) > 0]
    stats['assist_count'] = len(assists)

    total_dmg = sum(int(p.get('dmg') or 0) for p in participants)
    total_heal = sum(int(p.get('heal') or 0) + int(p.get('support') or 0) for p in participants)
    stats['dmg_total'] = total_dmg
    stats['heal_total'] = total_heal

    top_dmg = sorted(dmg_list, key=lambda x: int(x.get('dmg') or 0), reverse=True)
    top_heal = sorted(heal_list, key=lambda x: int(x.get('heal') or 0) + int(x.get('support') or 0), reverse=True)

    stats['top_damage'] = [(p.get('name') or '?', int(p.get('dmg') or 0)) for p in top_dmg[:max(1, int(KILLBOT_STATS_TOP_DMG))]]
    stats['top_heal'] = [(p.get('name') or '?', int(p.get('heal') or 0) + int(p.get('support') or 0)) for p in top_heal[:max(1, int(KILLBOT_STATS_TOP_HEAL))]]

    if top_dmg:
        best = top_dmg[0]
        stats['top_damage_name'] = best.get('name') or '?'
        stats['top_damage_val'] = int(best.get('dmg') or 0)
        stats['top_damage_frac'] = (float(stats['top_damage_val']) / float(total_dmg)) if total_dmg > 0 else 1.0
    else:
        # fallback: killer name
        stats['top_damage_name'] = killer_name or '?'
        stats['top_damage_val'] = _kb_safe_int(ev.get('TotalVictimKillFame') or 0, 0)
        stats['top_damage_frac'] = 0.65

    # small convenience fields
    stats['killer_name'] = killer_name or '?'
    stats['victim_name'] = (victim.get('Name') or '?').strip() or '?'

    return stats

def _kb_build_participants_report(ev: dict) -> str:
    stats = _kb_compute_stats(ev)
    parts = stats.get('participants') or []
    if not parts:
        return ""
    eid = _kb_safe_int(ev.get('EventId') or 0, 0)
    bid = _kb_safe_int(ev.get('BattleId') or 0, 0)
    loc = (ev.get('Location') or '?').strip() or '?'
    fame = _kb_safe_int(ev.get('TotalVictimKillFame') or 0, 0)
    when = _kb_when_str(ev.get('TimeStamp') or '')

    killer = ev.get('Killer') if isinstance(ev.get('Killer'), dict) else {}
    victim = ev.get('Victim') if isinstance(ev.get('Victim'), dict) else {}
    killer_name = (killer.get('Name') or '?').strip() or '?'
    victim_name = (victim.get('Name') or '?').strip() or '?'

    out_lines: List[str] = []
    out_lines.append(f"EventId: {eid}")
    if bid:
        out_lines.append(f"BattleId: {bid}")
    out_lines.append(f"Time: {when}")
    out_lines.append(f"Location: {loc}")
    out_lines.append(f"Fame: {fame}")
    out_lines.append(f"Killer: {killer_name}")
    out_lines.append(f"Victim: {victim_name}")
    out_lines.append(f"Participants: {stats.get('participants_total', 0)} | Party: {stats.get('party_size', 0)} | DMG: {stats.get('dmg_count', 0)} | Heal: {stats.get('heal_count', 0)}")
    out_lines.append("")

    def fmt_int(n: int) -> str:
        try:
            return f"{int(n):,}".replace(',', '.')
        except Exception:
            return str(n)

    # Damage list
    dmg_sorted = sorted([p for p in parts if int(p.get('dmg') or 0) > 0], key=lambda x: int(x.get('dmg') or 0), reverse=True)
    out_lines.append("=== Damage (desc) ===")
    if not dmg_sorted:
        out_lines.append("(no damage participants)")
    else:
        for p in dmg_sorted:
            g = p.get('guild') or ''
            ip = p.get('ip') or 0.0
            out_lines.append(f"- {p.get('name')}" + (f" [{g}]" if g else "") + f" | IP {ip:.3f} | DMG {fmt_int(p.get('dmg') or 0)}")
    out_lines.append("")

    # Heal list
    heal_sorted = sorted([p for p in parts if (int(p.get('heal') or 0) + int(p.get('support') or 0)) > 0], key=lambda x: int(x.get('heal') or 0) + int(x.get('support') or 0), reverse=True)
    out_lines.append("=== Healing (desc) ===")
    if not heal_sorted:
        out_lines.append("(no heal participants)")
    else:
        for p in heal_sorted:
            g = p.get('guild') or ''
            ip = p.get('ip') or 0.0
            hv = int(p.get('heal') or 0) + int(p.get('support') or 0)
            out_lines.append(f"- {p.get('name')}" + (f" [{g}]" if g else "") + f" | IP {ip:.3f} | HEAL {fmt_int(hv)}")

    # cap total lines
    cap = max(50, int(KILLBOT_PARTICIPANTS_MAX_LINES))
    if len(out_lines) > cap:
        out_lines = out_lines[:cap] + ["", f"(truncated: max lines = {cap})"]

    return "\n".join(out_lines).strip() + "\n"

def _kb_draw_text(draw: "ImageDraw.ImageDraw", xy, text: str, font=None):
    try:
        draw.text(xy, text, font=font)
    except Exception:
        # fallback
        draw.text(xy, text)


# ===== Killbot image: emoji/icon rendering =====
# PIL's default fonts on many Linux servers don't include color emoji glyphs;
# Discord-like "empty square" appears. We draw small icon images instead.
_KB_STAT_ICON_CACHE: Dict[Tuple[str, int], "Image.Image"] = {}

def _kb_get_stat_icon(name: str, size: int = 18) -> Optional["Image.Image"]:
    if not PIL_OK:
        return None
    key = (str(name or "").strip().lower(), int(size))
    if key in _KB_STAT_ICON_CACHE:
        return _KB_STAT_ICON_CACHE[key]

    nm, sz = key
    sz = max(12, min(32, sz))
    im = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    # colors chosen to feel "emoji-like" on Discord dark mode
    gold = (245, 200, 70, 255)
    white = (230, 232, 235, 255)
    gray = (160, 165, 170, 255)
    blue = (120, 170, 255, 255)

    try:
        if nm in ("trophy", "fame", "cup"):
            # simple trophy
            # cup
            d.rounded_rectangle([sz*0.22, sz*0.18, sz*0.78, sz*0.55], radius=int(sz*0.12), fill=gold)
            # handles
            d.arc([sz*0.10, sz*0.20, sz*0.36, sz*0.55], start=260, end=100, fill=gold, width=max(2, sz//10))
            d.arc([sz*0.64, sz*0.20, sz*0.90, sz*0.55], start=80, end=280, fill=gold, width=max(2, sz//10))
            # stem + base
            d.rectangle([sz*0.46, sz*0.55, sz*0.54, sz*0.72], fill=gold)
            d.rounded_rectangle([sz*0.30, sz*0.72, sz*0.70, sz*0.86], radius=int(sz*0.10), fill=gold)
        elif nm in ("clock", "time"):
            # clock face
            d.ellipse([sz*0.12, sz*0.12, sz*0.88, sz*0.88], outline=blue, width=max(2, sz//12))
            # hands
            cx, cy = sz*0.50, sz*0.50
            d.line([cx, cy, sz*0.50, sz*0.28], fill=white, width=max(2, sz//12))
            d.line([cx, cy, sz*0.70, sz*0.56], fill=white, width=max(2, sz//14))
            d.ellipse([sz*0.46, sz*0.46, sz*0.54, sz*0.54], fill=white)
        elif nm in ("people", "party", "group", "fight"):
            # two heads
            d.ellipse([sz*0.20, sz*0.18, sz*0.44, sz*0.42], fill=white)
            d.ellipse([sz*0.52, sz*0.20, sz*0.76, sz*0.44], fill=gray)
            # bodies
            d.rounded_rectangle([sz*0.14, sz*0.44, sz*0.50, sz*0.82], radius=int(sz*0.18), fill=white)
            d.rounded_rectangle([sz*0.46, sz*0.46, sz*0.82, sz*0.84], radius=int(sz*0.18), fill=gray)
        else:
            # fallback: simple dot
            d.ellipse([sz*0.25, sz*0.25, sz*0.75, sz*0.75], fill=white)
    except Exception:
        pass

    _KB_STAT_ICON_CACHE[key] = im
    return im

def _kb_text_width(draw: "ImageDraw.ImageDraw", text: str, font=None) -> int:
    try:
        if hasattr(draw, "textlength"):
            return int(draw.textlength(text, font=font))
        w, _h = draw.textsize(text, font=font) if font else draw.textsize(text)
        return int(w)
    except Exception:
        return max(0, len(text) * 7)

def _kb_draw_stat_item(base: "Image.Image", draw: "ImageDraw.ImageDraw", x: int, y: int, *, icon: str, label: str, value: str, font=None, gap: int = 16) -> int:
    ic = _kb_get_stat_icon(icon, size=18)
    if ic:
        try:
            base.alpha_composite(ic, (x, y + 1))
        except Exception:
            pass
        tx = x + ic.size[0] + 8
    else:
        tx = x

    txt = f"{label}: {value}"
    _kb_draw_text(draw, (tx, y), txt, font=font)
    return tx + _kb_text_width(draw, txt, font=font) + gap

def _kb_make_image_sync(payload: dict, icon_blobs: Dict[str, bytes]) -> Optional[bytes]:
    if not PIL_OK or not KILLBOT_IMAGE_ENABLED:
        return None

    kind = payload["kind"]
    ev = payload["event"]
    killer = payload["killer"]
    victim = payload["victim"]
    k_eq = payload["k_eq"]
    v_eq = payload["v_eq"]
    inv_items = payload["inv_items"]
    stats = payload["stats"]

    W = 900
    H = 1020 if inv_items else 720
    bg = (35, 37, 41, 255)  # discord dark
    card = (44, 47, 51, 255)

    im = Image.new("RGBA", (W, H), bg)
    draw = ImageDraw.Draw(im)

    # simple fonts
    try:
        font_big = ImageFont.truetype("DejaVuSans.ttf", 22)
        font_med = ImageFont.truetype("DejaVuSans.ttf", 16)
        font_small = ImageFont.truetype("DejaVuSans.ttf", 13)
    except Exception:
        font_big = None
        font_med = None
        font_small = None

    # Header card
    draw.rounded_rectangle([20, 20, W-20, 90], radius=14, fill=card)
    title = payload["title"]
    _kb_draw_text(draw, (34, 34), title, font=font_big)
    fame_str = f"{int(payload.get('fame') or 0):,}".replace(',', '.')
    p_total = _kb_safe_int(stats.get("participants_total"), 0) if isinstance(stats, dict) else 0
    party = _kb_safe_int(stats.get("party_size"), 0) if isinstance(stats, dict) else 0
    # Render header stats with drawn icons (no broken emoji squares)
    x0, y0 = 34, 62
    x0 = _kb_draw_stat_item(im, draw, x0, y0, icon="trophy", label="Fame", value=str(fame_str), font=font_med)
    x0 = _kb_draw_stat_item(im, draw, x0, y0, icon="clock", label="Zaman", value=str(payload['when']), font=font_med)
    if p_total:
        fight_val = f"{p_total}" + (f" (Party {party})" if party else "")
        _kb_draw_stat_item(im, draw, x0, y0, icon="people", label="Fight", value=fight_val, font=font_med)

    # Two player cards
    left_x = 20
    right_x = W//2 + 10
    top_y = 110
    box_w = W//2 - 30
    box_h = 290
    draw.rounded_rectangle([left_x, top_y, left_x + box_w, top_y + box_h], radius=14, fill=card)
    draw.rounded_rectangle([right_x, top_y, right_x + box_w, top_y + box_h], radius=14, fill=card)

    # Names
    _kb_draw_text(draw, (left_x+18, top_y+14), f"Öldüren: {killer.get('Name','?')}", font=font_med)
    _kb_draw_text(draw, (right_x+18, top_y+14), f"Ölen: {victim.get('Name','?')}", font=font_med)

    # IP
    kip = killer.get("AverageItemPower")
    vip = victim.get("AverageItemPower")
    if kip is not None:
        _kb_draw_text(draw, (left_x+18, top_y+40), f"IP: {kip}", font=font_small)
    if vip is not None:
        _kb_draw_text(draw, (right_x+18, top_y+40), f"IP: {vip}", font=font_small)

    # icon grid settings
    size = int(KILLBOT_RENDER_SIZE)
    pad = 10
    grid_top = top_y + 70
    grid_left_l = left_x + 18
    grid_left_r = right_x + 18

    def paste_slot(eq: dict, base_x: int, base_y: int):
        cols = 4
        for idx, (slot, _label) in enumerate(_SLOT_ORDER):
            r = idx // cols
            c = idx % cols
            x = base_x + c * (size + pad)
            y = base_y + r * (size + pad)
            # placeholder
            draw.rounded_rectangle([x, y, x+size, y+size], radius=10, outline=(90, 90, 90, 255), width=2)
            it = _kb_slot_item(eq, slot)
            if not it or not isinstance(it, dict):
                continue
            t = (it.get("Type") or "").strip()
            if not t:
                continue
            ench = _kb_safe_int(it.get("EnchantmentLevel"), 0)
            qual = _kb_safe_int(it.get("Quality"), 0)
            url = _kb_render_url(t, enchant=ench, quality=qual, size=size)
            blob = icon_blobs.get(url)
            # Fallbacks: try without quality, and try a safe size (64) if needed.
            if not blob and qual:
                url2 = _kb_render_url(t, enchant=ench, quality=0, size=size)
                blob = icon_blobs.get(url2)
            if not blob and int(size) != 64:
                url3 = _kb_render_url(t, enchant=ench, quality=qual, size=64)
                blob = icon_blobs.get(url3)
                if not blob and qual:
                    url4 = _kb_render_url(t, enchant=ench, quality=0, size=64)
                    blob = icon_blobs.get(url4)
            if not blob:
                continue
            try:
                icon = Image.open(io.BytesIO(blob)).convert("RGBA")
                if icon.size != (size, size):
                    icon = icon.resize((size, size))
                im.alpha_composite(icon, (x, y))
                # small enchant overlay
                try:
                    if ench and int(ench) > 0:
                        _kb_draw_text(draw, (x + 4, y + 2), f".{int(ench)}", font=font_small)
                except Exception:
                    pass
            except Exception:
                pass

    paste_slot(k_eq, grid_left_l, grid_top)
    paste_slot(v_eq, grid_left_r, grid_top)

    # Combat stats
    stats_top = top_y + box_h + 20
    panel_h = 260
    draw.rounded_rectangle([20, stats_top, W-20, stats_top+panel_h], radius=14, fill=card)
    _kb_draw_text(draw, (34, stats_top+14), "Savaş İstatistikleri", font=font_med)

    try:
        p_total2 = _kb_safe_int(stats.get("participants_total"), 0) if isinstance(stats, dict) else 0
        party2 = _kb_safe_int(stats.get("party_size"), 0) if isinstance(stats, dict) else 0
        dmg_count2 = _kb_safe_int(stats.get("dmg_count"), 0) if isinstance(stats, dict) else 0
        heal_count2 = _kb_safe_int(stats.get("heal_count"), 0) if isinstance(stats, dict) else 0
        dmg_total2 = _kb_safe_int(stats.get("dmg_total"), 0) if isinstance(stats, dict) else 0
        heal_total2 = _kb_safe_int(stats.get("heal_total"), 0) if isinstance(stats, dict) else 0
    except Exception:
        p_total2, party2, dmg_count2, heal_count2, dmg_total2, heal_total2 = 0, 0, 0, 0, 0, 0

    _kb_draw_text(draw, (34, stats_top+44), f"Katılan: {p_total2}   •   Party: {party2 or '-'}   •   DMG: {dmg_count2}   •   Heal: {heal_count2}", font=font_small)
    dmg_total_str2 = f"{dmg_total2:,}".replace(',', '.')
    heal_total_str2 = f"{heal_total2:,}".replace(',', '.')
    _kb_draw_text(draw, (34, stats_top+62), f"Toplam DMG: {dmg_total_str2}   •   Toplam Heal: {heal_total_str2}", font=font_small)

    # top damage bar (share of total dmg)
    top_damage = stats.get("top_damage_name", "") if isinstance(stats, dict) else ""
    top_damage_val = _kb_safe_int(stats.get("top_damage_val"), 0) if isinstance(stats, dict) else 0
    if top_damage:
        _kb_draw_text(draw, (34, stats_top+86), f"En Yüksek Hasar: {top_damage}  ({top_damage_val})", font=font_small)
        bar_x1, bar_y1 = 34, stats_top+108
        bar_x2, bar_y2 = W-34, stats_top+132
        draw.rounded_rectangle([bar_x1, bar_y1, bar_x2, bar_y2], radius=10, outline=(90,90,90,255), width=2)
        frac = float(stats.get("top_damage_frac", 0.0) if isinstance(stats, dict) else 0.0)
        fx2 = int(bar_x1 + (bar_x2 - bar_x1) * max(0.0, min(1.0, frac)))
        draw.rounded_rectangle([bar_x1, bar_y1, fx2, bar_y2], radius=10, fill=(180, 60, 60, 255))

    # top lists
    dmg_top = stats.get("top_damage", []) if isinstance(stats, dict) else []
    heal_top = stats.get("top_heal", []) if isinstance(stats, dict) else []
    list_y = stats_top + 146
    left_col_x = 34
    right_col_x = W//2 + 20
    _kb_draw_text(draw, (left_col_x, list_y), f"Hasar (Top {len(dmg_top)})", font=font_small)
    _kb_draw_text(draw, (right_col_x, list_y), f"Heal (Top {len(heal_top)})", font=font_small)

    def _short(n: str, maxlen: int = 18) -> str:
        s = (n or "?").strip() or "?"
        return s if len(s) <= maxlen else (s[:maxlen-1] + "…")

    row_y = list_y + 18
    for i2, pair in enumerate(dmg_top[:max(1, int(KILLBOT_STATS_TOP_DMG))]):
        try:
            nm, vv = pair
        except Exception:
            continue
        vv = _kb_safe_int(vv, 0)
        vv_str = f"{vv:,}".replace(',', '.')
        _kb_draw_text(draw, (left_col_x, row_y + i2*18), f"{i2+1}. {_short(str(nm))} ({vv_str})", font=font_small)

    for j2, pair in enumerate(heal_top[:max(1, int(KILLBOT_STATS_TOP_HEAL))]):
        try:
            nm, vv = pair
        except Exception:
            continue
        vv = _kb_safe_int(vv, 0)
        vv_str = f"{vv:,}".replace(',', '.')
        _kb_draw_text(draw, (right_col_x, row_y + j2*18), f"{j2+1}. {_short(str(nm))} ({vv_str})", font=font_small)

    # Inventory is sent as a separate image (see _kb_make_inventory_image).

    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def _kb_make_inventory_image_sync(v_eq: Dict[str, Any], inv_items: List[dict], icon_blobs: Dict[str, bytes], *, title: str) -> Optional[bytes]:
    """Render lost items as a separate image: victim equipment (incl. weapon) + inventory."""
    if not PIL_OK or not KILLBOT_IMAGE_ENABLED:
        return None

    if not isinstance(v_eq, dict):
        v_eq = {}
    inv_items = [it for it in inv_items if isinstance(it, dict)] if isinstance(inv_items, list) else []

    # Determine whether we have any equipment to show.
    eq_count = 0
    for slot, _ in _SLOT_ORDER:
        it = _kb_slot_item(v_eq, slot)
        if isinstance(it, dict) and (it.get("Type") or "").strip():
            eq_count += 1

    if eq_count == 0 and not inv_items:
        return None

    W = 900
    bg = (35, 37, 41, 255)
    card = (44, 47, 51, 255)

    cols = 10
    size2 = 64
    pad2 = 8

    # Inventory grid
    cap = 200  # hard cap to avoid huge images/timeouts
    items = inv_items[:cap]
    inv_rows = (len(items) + cols - 1) // cols if items else 0

    header_h = 90
    x0 = 34
    y = header_h + 22

    # Layout sizing
    if eq_count > 0:
        y += 18 + size2 + 26  # label + row + gap
    if items:
        y += 18 + (inv_rows * (size2 + pad2)) + 26  # label + grid + padding
    else:
        y += 40

    H = max(220, y + 20)

    im = Image.new("RGBA", (W, H), bg)
    draw = ImageDraw.Draw(im)

    try:
        font_big = ImageFont.truetype("DejaVuSans.ttf", 22)
        font_med = ImageFont.truetype("DejaVuSans.ttf", 16)
        font_small = ImageFont.truetype("DejaVuSans.ttf", 13)
    except Exception:
        font_big = None
        font_med = None
        font_small = None

    def paste_item_icon(it: dict, x: int, y: int, *, size_px: int = 64):
        if not isinstance(it, dict):
            return
        t = (it.get("Type") or "").strip()
        if not t:
            return
        ench = _kb_safe_int(it.get("EnchantmentLevel"), 0)
        qual = _kb_safe_int(it.get("Quality"), 0)

        # Primary URL
        url = _kb_render_url(t, enchant=ench, quality=qual, size=size_px)
        blob = icon_blobs.get(url)

        # Fallbacks (some items come back without quality or render behaves differently)
        if not blob and qual:
            url2 = _kb_render_url(t, enchant=ench, quality=0, size=size_px)
            blob = icon_blobs.get(url2)
        if not blob:
            return

        try:
            icon = Image.open(io.BytesIO(blob)).convert("RGBA")
            if icon.size != (size_px, size_px):
                icon = icon.resize((size_px, size_px))
            im.alpha_composite(icon, (x, y))

            # overlays: enchant + stack count
            try:
                if ench and int(ench) > 0:
                    _kb_draw_text(draw, (x + 4, y + 2), f".{int(ench)}", font=font_small)
                cnt = _kb_safe_int(it.get("Count") or it.get("Quantity") or 1, 1)
                if cnt and int(cnt) > 1:
                    txt = f"x{int(cnt)}"
                    try:
                        tw, th = draw.textsize(txt, font=font_small) if font_small else draw.textsize(txt)
                    except Exception:
                        tw, th = (20, 10)
                    tx = x + size_px - tw - 6
                    ty = y + size_px - th - 4
                    draw.rounded_rectangle([tx-3, ty-2, tx+tw+3, ty+th+2], radius=6, fill=(0,0,0,180))
                    _kb_draw_text(draw, (tx, ty), txt, font=font_small)
            except Exception:
                pass
        except Exception:
            pass

    # Header
    draw.rounded_rectangle([20, 20, W-20, header_h], radius=14, fill=card)
    _kb_draw_text(draw, (34, 34), title, font=font_big)

    inv_total = len(inv_items)
    if inv_total > cap:
        inv_hint = f"Envanter: {cap}/{inv_total}"
    else:
        inv_hint = f"Envanter: {inv_total}"

    _kb_draw_text(draw, (34, 62), f"Ekipman: {eq_count} • {inv_hint}", font=font_med)

    # Main card
    draw.rounded_rectangle([20, header_h + 10, W-20, H-20], radius=14, fill=card)

    cur_y = header_h + 22

    # Equipment section (includes weapons)
    if eq_count > 0:
        _kb_draw_text(draw, (34, cur_y), "🛡️ Ekipman", font=font_med)
        cur_y += 18
        row_y = cur_y
        for i, (slot, _label) in enumerate(_SLOT_ORDER):
            x = x0 + i * (size2 + pad2)
            y2 = row_y
            draw.rounded_rectangle([x, y2, x + size2, y2 + size2], radius=10, outline=(90, 90, 90, 255), width=2)
            it = _kb_slot_item(v_eq, slot)
            if isinstance(it, dict):
                paste_item_icon(it, x, y2, size_px=size2)
        cur_y = row_y + size2 + 26

    # Inventory section
    if items:
        _kb_draw_text(draw, (34, cur_y), "🎒 Envanter", font=font_med)
        cur_y += 18
        start_y = cur_y
        for i, it in enumerate(items):
            r = i // cols
            c = i % cols
            x = x0 + c * (size2 + pad2)
            y2 = start_y + r * (size2 + pad2)
            draw.rounded_rectangle([x, y2, x + size2, y2 + size2], radius=10, outline=(90, 90, 90, 255), width=2)
            paste_item_icon(it, x, y2, size_px=size2)
    else:
        _kb_draw_text(draw, (34, cur_y + 6), "Envanter boş.", font=font_med)

    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


async def _kb_make_image(bot: "CallidusBot", ev: dict, kind: str, *, include_inventory: bool = False) -> Optional[bytes]:
    if not (PIL_OK and KILLBOT_IMAGE_ENABLED):
        return None
    if not bot._kb_http:
        return None

    killer = ev.get("Killer") if isinstance(ev.get("Killer"), dict) else {}
    victim = ev.get("Victim") if isinstance(ev.get("Victim"), dict) else {}
    k_eq = _kb_get_equipment(killer)
    v_eq = _kb_get_equipment(victim)

    # victim inventory (kill + death)
    inv_items: List[dict] = []
    if include_inventory:
        inv = victim.get("Inventory")
        inv_items = [it for it in inv if isinstance(it, dict)] if isinstance(inv, list) else []

    # stats
    try:
        stats = _kb_compute_stats(ev)
    except Exception:
        stats = {"top_damage_name": "?", "top_damage_val": 0, "top_damage_frac": 0.65}

    # prefetch icons (with cache)
    icon_urls = set()

    def add_eq_icons(eq: dict, size: int):
        for slot, _ in _SLOT_ORDER:
            it = _kb_slot_item(eq, slot)
            if not it or not isinstance(it, dict):
                continue
            t = (it.get("Type") or "").strip()
            if not t:
                continue
            ench = _kb_safe_int(it.get("EnchantmentLevel"), 0)
            qual = _kb_safe_int(it.get("Quality"), 0)
            icon_urls.add(_kb_render_url(t, enchant=ench, quality=qual, size=size))
            # Fallbacks (render service can be picky about quality/size for some items)
            if qual:
                icon_urls.add(_kb_render_url(t, enchant=ench, quality=0, size=size))
            if int(size) != 64:
                icon_urls.add(_kb_render_url(t, enchant=ench, quality=qual, size=64))
                if qual:
                    icon_urls.add(_kb_render_url(t, enchant=ench, quality=0, size=64))

    add_eq_icons(k_eq, int(KILLBOT_RENDER_SIZE))
    add_eq_icons(v_eq, int(KILLBOT_RENDER_SIZE))

    if inv_items:
        for it in inv_items[:80]:
            if not isinstance(it, dict):
                continue
            t = (it.get("Type") or "").strip()
            if not t:
                continue
            ench = _kb_safe_int(it.get("EnchantmentLevel"), 0)
            qual = _kb_safe_int(it.get("Quality"), 0)
            icon_urls.add(_kb_render_url(t, enchant=ench, quality=qual, size=64))

    # fetch icons (concurrent; mem+disk cache)
    blobs = await _kb_prefetch_icons(bot, icon_urls)

    # event id (for labels / debug)
    eid = _kb_safe_int(ev.get("EventId") or ev.get("id") or 0, 0)

    payload = {
        "kind": kind,
        "event": ev,
        "killer": killer,
        "victim": victim,
        "k_eq": k_eq,
        "v_eq": v_eq,
        "inv_items": inv_items,
        "stats": stats,
        "title": f"{(killer.get('Name') or '?').strip()} adlı oyuncu {(victim.get('Name') or '?').strip()} adlı oyuncuyu öldürdü",
        "location": (ev.get("Location") or "?").strip() or "?",
        "fame": _kb_safe_int(ev.get("TotalVictimKillFame") or 0, 0),
        "when": _kb_when_str(ev.get("TimeStamp") or ""),
        "event_id": eid,
    }
    return await run_io(_kb_make_image_sync, payload, blobs)


async def _kb_make_inventory_image(bot: "CallidusBot", ev: dict, kind: str) -> Optional[bytes]:
    """Create a separate "lost items" image (equipment + inventory)."""
    if not (PIL_OK and KILLBOT_IMAGE_ENABLED):
        return None
    if not bot._kb_http:
        return None

    victim = ev.get("Victim") if isinstance(ev.get("Victim"), dict) else {}
    v_eq = _kb_get_equipment(victim)

    inv = victim.get("Inventory")
    inv_items = [it for it in inv if isinstance(it, dict)] if isinstance(inv, list) else []

    # check if there is anything to show
    has_eq = False
    try:
        for slot, _ in _SLOT_ORDER:
            it = _kb_slot_item(v_eq, slot)
            if isinstance(it, dict) and (it.get("Type") or "").strip():
                has_eq = True
                break
    except Exception:
        has_eq = False

    if not has_eq and not inv_items:
        return None

    # icon urls (equipment + inventory)
    icon_urls = set()

    # equipment icons (this is where the weapon lives)
    for slot, _ in _SLOT_ORDER:
        it = _kb_slot_item(v_eq, slot)
        if not isinstance(it, dict):
            continue
        t = (it.get("Type") or "").strip()
        if not t:
            continue
        ench = _kb_safe_int(it.get("EnchantmentLevel"), 0)
        qual = _kb_safe_int(it.get("Quality"), 0)
        icon_urls.add(_kb_render_url(t, enchant=ench, quality=qual, size=64))
        # fallback variant without quality (some payloads send 0/None)
        if qual:
            icon_urls.add(_kb_render_url(t, enchant=ench, quality=0, size=64))

    # inventory icons
    for it in inv_items[:200]:
        if not isinstance(it, dict):
            continue
        t = (it.get("Type") or "").strip()
        if not t:
            continue
        ench = _kb_safe_int(it.get("EnchantmentLevel"), 0)
        qual = _kb_safe_int(it.get("Quality"), 0)
        icon_urls.add(_kb_render_url(t, enchant=ench, quality=qual, size=64))
        if qual:
            icon_urls.add(_kb_render_url(t, enchant=ench, quality=0, size=64))

    blobs = await _kb_prefetch_icons(bot, icon_urls)

    vname = (victim.get("Name") or "?").strip() or "?"
    title = f"Kaybedilen Eşyalar • {vname}"
    return await run_io(_kb_make_inventory_image_sync, v_eq, inv_items, blobs, title=title)

# =========================================================
#                           BOT
# =========================================================
class CallidusBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.message_content = True  # Dev Portal'da da açılmalı
        intents.voice_states = True  # Müzik sistemi için gerekli
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

        # killbot runtime state
        _st = _kb_load_state()
        self._kb_last_event_id = int(_st.get("guild_last_event_id", 0) or 0)  # guild-mode kill stream cursor
        self._kb_seen_kill_ids = set(int(x) for x in (_st.get("member_seen_kill_ids") or []) if str(x).isdigit())
        self._kb_seen_death_ids = set(int(x) for x in (_st.get("member_seen_death_ids") or []) if str(x).isdigit())
        # killboard link mode (albion | murder)
        lm = (_st.get("link_mode") or "").strip().lower()
        if lm in ("murder", "murderledger", "ml"):
            lm = "murder"
        elif lm in ("albion", "official"):
            lm = "albion"
        else:
            lm = _KB_LINK_MODE
        self._kb_link_mode = _kb_set_link_mode(lm)
        self._kb_member_ids: List[str] = []
        self._kb_members_refreshed_at: Optional[datetime] = None
        self._kb_http: Optional[aiohttp.ClientSession] = None
        self._kb_task: Optional[asyncio.Task] = None
        self._kb_icon_cache: Dict[str, bytes] = {}
        self._kb_last_seen_at: Optional[datetime] = None
        self._kb_err: str = ""
        
        # Achievement system
        self._achievement_task: Optional[asyncio.Task] = None
        
        # Music system - her sunucu için ayrı queue
        self.music_queues: Dict[int, List[Dict[str, Any]]] = {}  # guild_id -> [songs]
        self.music_now_playing: Dict[int, Optional[Dict[str, Any]]] = {}  # guild_id -> current song
        self.music_loop: Dict[int, bool] = {}  # guild_id -> loop enabled
        self.music_volume: Dict[int, float] = {}  # guild_id -> volume (0.0-1.0)
        self.music_idle_tasks: Dict[int, asyncio.Task] = {}  # guild_id -> idle disconnect task
        
        # Content hatırlatma sistemi
        self.content_reminders: Dict[int, asyncio.Task] = {}  # message_id -> reminder task
        
        # Activity tracking
        self._activity_task: Optional[asyncio.Task] = None
        self._voice_join_times: Dict[int, datetime] = {}  # user_id -> voice join time

    async def setup_hook(self):
        load_localization_pairs(LOCALIZATION_PAIRS_TSV)
        try:
            self.tree.add_command(bbtest_cmd, guild=discord.Object(id=GUILD_ID))
        except Exception:
            pass
        await self.tree.sync(guild=discord.Object(id=GUILD_ID))
        log("✅ Commands synced for guild:", GUILD_ID)
        if not hasattr(self, "_bb_task"):
            self._bb_task = self.loop.create_task(_bb_worker(self))

        # Killbot session + task
        if self._kb_http is None:
            self._kb_http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        if self._kb_task is None:
            self._kb_task = asyncio.create_task(self._killbot_loop())
        
        # Activity inactivity check task
        if self._activity_task is None:
            self._activity_task = asyncio.create_task(self._activity_check_loop())
        
        # Achievement weekly report task - devre dışı
        # if ACHIEVEMENTS_OK and self._achievement_task is None:
        #     self._achievement_task = asyncio.create_task(weekly_report_task(self, GUILD_ID))

    async def on_ready(self):
        log(f"✅ Logged in as {self.user} (id={self.user.id})")
        if TRANSLATE_IDS:
            log("🈯 Translate channels:", TRANSLATE_IDS)
        else:
            log("🈯 Translate channel auto-detect: channel name contains 'çeviri/translate'")
        log(f"⚔️ Killbot: AO_GUILD_ID={AO_GUILD_ID} kill_ch={KILLBOARD_CHANNEL_ID} death_ch={DEATHBOARD_CHANNEL_ID} poll={KILLBOT_POLL_SECONDS}s img={'on' if (PIL_OK and KILLBOT_IMAGE_ENABLED) else 'off'}")
        log(f"🎉 Welcome: channel={WELCOME_CHANNEL_ID} guild_name={WELCOME_GUILD_NAME}")
        log(f"✅ Verify: channel={VERIFY_CHANNEL_ID} role={VERIFY_ROLE_ID}")
        log(f"🎫 Ticket: channel={TICKET_CATEGORY_ID} category={TICKET_CATEGORY_ID} staff={TICKET_STAFF_ROLE_ID}")
        log(f"📊 Activity: inactivity_days={ACTIVITY_INACTIVITY_DAYS}")

    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """Voice aktivitesini takip eder."""
        # Bot kendisini saymasın
        if member.bot:
            return
        
        # Ses kanalına katıldı
        if before.channel is None and after.channel is not None:
            self._voice_join_times[member.id] = datetime.now(UTC_TZ)
            log(f"[ACTIVITY] {member.name} voice'a katıldı")
        
        # Ses kanalından ayrıldı
        elif before.channel is not None and after.channel is None:
            if member.id in self._voice_join_times:
                join_time = self._voice_join_times.pop(member.id)
                duration = datetime.now(UTC_TZ) - join_time
                minutes = int(duration.total_seconds() / 60)
                if minutes > 0:
                    _update_activity(member.id, "voice", minutes=minutes)
                    log(f"[ACTIVITY] {member.name} voice'tan ayrıldı ({minutes} dk)")

    async def _activity_check_loop(self):
        """Her gün inaktif kullanıcıları kontrol eder ve DM atar."""
        await self.wait_until_ready()
        
        state = _load_activity_state()
        now = datetime.now(UTC_TZ)
        
        # İlk açılış tarihini kontrol et
        first_start = state.get("first_start")
        if first_start is None:
            # İlk kez çalışıyor, tarihi kaydet
            state["first_start"] = now.isoformat()
            _save_activity_state(state)
            log(f"[ACTIVITY] İlk başlatma kaydedildi, 5 gün sonra kontroller başlayacak...")
        
        while not self.is_closed():
            try:
                # İlk başlatmadan 5 gün geçti mi?
                state = _load_activity_state()
                first_start_str = state.get("first_start")
                if first_start_str:
                    first_start_dt = datetime.fromisoformat(first_start_str.replace("Z", "+00:00"))
                    days_since_start = (datetime.now(UTC_TZ) - first_start_dt).days
                    
                    if days_since_start < 5:
                        log(f"[ACTIVITY] Henüz {5 - days_since_start} gün bekleniyor...")
                    else:
                        await self._check_inactive_users()
            except Exception as e:
                log(f"[ACTIVITY] Check loop hatası: {repr(e)}")
            
            # Her 24 saatte bir kontrol et
            await asyncio.sleep(86400)  # 24 saat
    
    async def _check_inactive_users(self):
        """5+ gün inaktif kullanıcılara DM gönderir."""
        state = _load_activity_state()
        guild = self.get_guild(GUILD_ID)
        if not guild:
            return
        
        now = datetime.now(UTC_TZ)
        warned_users = state.get("warned_users", [])
        
        # Member rolü - sadece bu role sahip kişilere warning gönder
        MEMBER_ROLE_ID = 1419663333874729121
        member_role = guild.get_role(MEMBER_ROLE_ID)
        
        for member in guild.members:
            if member.bot:
                continue
            
            # Sadece Member rolüne sahip kişileri kontrol et (Looter vb. hariç)
            if member_role and member_role not in member.roles:
                continue
            
            user_id_str = str(member.id)
            user_data = state["users"].get(user_id_str)
            
            # Hiç aktivitesi yoksa ve yeni üye değilse
            if user_data is None:
                # Üye 5 günden eski mi?
                if member.joined_at:
                    days_since_join = (now - member.joined_at.replace(tzinfo=UTC_TZ)).days
                    if days_since_join >= ACTIVITY_INACTIVITY_DAYS:
                        if user_id_str not in warned_users:
                            await self._send_inactivity_warning(member)
                            warned_users.append(user_id_str)
                continue
            
            # Son aktiviteden bu yana kaç gün geçmiş?
            last_activity = user_data.get("last_activity")
            if last_activity:
                try:
                    last_dt = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
                    days_inactive = (now - last_dt).days
                    
                    if days_inactive >= ACTIVITY_INACTIVITY_DAYS:
                        if user_id_str not in warned_users:
                            await self._send_inactivity_warning(member)
                            warned_users.append(user_id_str)
                except Exception:
                    pass
        
        state["warned_users"] = warned_users
        _save_activity_state(state)
    
    async def _send_inactivity_warning(self, member: discord.Member):
        """İnaktif kullanıcıya DM gönderir."""
        try:
            message = f"""Selam {member.name} 👋

Son 5 gündür guild aktivitelerinde görünmüyorsun.

Eğer kısa süreli/bir süre offline isen sorun değil sadece haber vermen yeterli.

📌 **Bilgi:** 7 gün boyunca hiç aktif olmamak kick sebebidir.

Guild'de kalmak istiyorsan lütfen bu mesajı yanıtla:
• "Buradayım"
veya
• Ne kadar süre offline olacağını yaz ⏳

*CALLIDUS Bot*"""
            
            await member.send(message)
            log(f"[ACTIVITY] {member.name}'e inaktivite uyarısı gönderildi")
        except discord.Forbidden:
            log(f"[ACTIVITY] {member.name} DM kapalı")
        except Exception as e:
            log(f"[ACTIVITY] DM hatası: {repr(e)}")

    async def _create_welcome_image(self, member: discord.Member, member_count: int, for_dm: bool = False) -> Optional[io.BytesIO]:
        """PIL ile welcome görseli oluşturur."""
        if not PIL_OK:
            return None
        
        try:
            # Avatar'ı indir
            avatar_bytes = await member.display_avatar.replace(size=256).read()
            avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA").resize((150, 150))
            
            # Yuvarlak mask oluştur
            mask = Image.new("L", (150, 150), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, 150, 150), fill=255)
            
            # Yuvarlak avatar
            avatar_round = Image.new("RGBA", (150, 150), (0, 0, 0, 0))
            avatar_round.paste(avatar_img, (0, 0), mask)
            
            # Ana görsel (siyah arka plan)
            width, height = 500, 300
            img = Image.new("RGBA", (width, height), (43, 45, 49, 255))  # Discord koyu tema rengi
            draw = ImageDraw.Draw(img)
            
            # Beyaz yuvarlak çerçeve
            circle_x = (width - 160) // 2
            circle_y = 40
            draw.ellipse((circle_x - 5, circle_y - 5, circle_x + 160, circle_y + 160), outline=(255, 255, 255, 255), width=3)
            
            # Avatar'ı ortaya yapıştır
            img.paste(avatar_round, (circle_x, circle_y), avatar_round)
            
            # Font ayarla
            try:
                # Önce sistem fontlarını dene
                font_large = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
                font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 16)
            except:
                try:
                    font_large = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 24)
                    font_small = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", 16)
                except:
                    font_large = ImageFont.load_default()
                    font_small = ImageFont.load_default()
            
            # DM için farklı yazılar
            if for_dm:
                text1 = f"{WELCOME_GUILD_NAME}'a Hoşgeldin!"
                text2 = f"Bizim #{member_count}'inci memberimizsin!"
            else:
                text1 = f"{member.name} sunucuya katıldı!"
                text2 = f"Member #{member_count}"
            
            # Ana yazı
            bbox1 = draw.textbbox((0, 0), text1, font=font_large)
            text1_width = bbox1[2] - bbox1[0]
            draw.text(((width - text1_width) // 2, 220), text1, fill=(255, 255, 255, 255), font=font_large)
            
            # Member sayısı
            bbox2 = draw.textbbox((0, 0), text2, font=font_small)
            text2_width = bbox2[2] - bbox2[0]
            draw.text(((width - text2_width) // 2, 255), text2, fill=(180, 180, 180, 255), font=font_small)
            
            # BytesIO'ya kaydet
            buffer = io.BytesIO()
            img.save(buffer, format="PNG")
            buffer.seek(0)
            return buffer
            
        except Exception as e:
            log(f"[WELCOME] Görsel oluşturma hatası: {repr(e)}")
            return None

    async def _send_welcome_dm(self, member: discord.Member, member_count: int):
        """Yeni üyeye özelden hoş geldin mesajı gönderir."""
        try:
            # DM için görsel oluştur
            image_buffer = await self._create_welcome_image(member, member_count, for_dm=True)
            
            if image_buffer:
                file = discord.File(image_buffer, filename="welcome.png")
                embed = discord.Embed(color=0x2b2d31)
                embed.set_image(url="attachment://welcome.png")
                embed.set_footer(text=f"Şu sunucudan gönderildi: {WELCOME_GUILD_NAME}")
                
                await member.send(
                    content=f"**{WELCOME_GUILD_NAME}** 'a hoşgeldin!\nRecruit'e başvuru yaptıktan sonra en yakın zamanda sesliye bekleniyorsun.",
                    embed=embed,
                    file=file
                )
            else:
                # PIL yoksa basit mesaj
                await member.send(
                    f"**{WELCOME_GUILD_NAME}**'a hoşgeldin!\n"
                    f"Recruit'e başvuru yaptıktan sonra en yakın zamanda sesliye bekleniyorsun.\n\n"
                    f"Bizim #{member_count}'inci memberimizsin!"
                )
            
            log(f"[WELCOME-DM] {member.name}'e DM gönderildi")
        except discord.Forbidden:
            log(f"[WELCOME-DM] {member.name} DM kapalı")
        except Exception as e:
            log(f"[WELCOME-DM] Hata: {repr(e)}")

    async def on_member_join(self, member: discord.Member):
        """Yeni üye katıldığında hoş geldin mesajı gönderir."""
        try:
            channel = self.get_channel(WELCOME_CHANNEL_ID)
            if not channel:
                return
            
            # Kaçıncı üye olduğunu bul
            member_count = member.guild.member_count
            
            # PIL ile görsel oluştur
            image_buffer = await self._create_welcome_image(member, member_count, for_dm=False)
            
            if image_buffer:
                # Görsel ile gönder
                file = discord.File(image_buffer, filename="welcome.png")
                embed = discord.Embed(color=0x2b2d31)
                embed.set_image(url="attachment://welcome.png")
                
                await channel.send(
                    content=f"Selam {member.mention}, guilde **{WELCOME_GUILD_NAME}**'a hoşgeldin!",
                    embed=embed,
                    file=file
                )
            else:
                # PIL yoksa basit embed
                avatar_url = member.display_avatar.replace(size=256).url
                embed = discord.Embed(color=0x2b2d31)
                embed.set_image(url=avatar_url)
                embed.set_footer(text=f"{member.name} sunucuya katıldı! • Member #{member_count}")
                
                await channel.send(
                    content=f"Selam {member.mention}, guilde **{WELCOME_GUILD_NAME}**'a hoşgeldin!",
                    embed=embed
                )
            
            log(f"[WELCOME] {member.name} katıldı (#{member_count})")
            
            # Özelden de mesaj gönder
            await self._send_welcome_dm(member, member_count)
            
        except Exception as e:
            log(f"[WELCOME] Hata: {repr(e)}")

    async def on_member_remove(self, member: discord.Member):
        """Üye sunucudan ayrıldığında log kanalına bildirim gönderir."""
        try:
            channel = self.get_channel(LEAVE_LOG_CHANNEL_ID)
            if not channel:
                return
            
            # Üyenin sunucuya katılma tarihi
            joined_at = member.joined_at
            if joined_at:
                joined_str = joined_at.strftime("%d.%m.%Y %H:%M")
                # Ne kadar süre kaldığını hesapla
                now = datetime.now(UTC_TZ)
                delta = now - joined_at
                days = delta.days
                if days > 0:
                    duration = f"{days} gün"
                else:
                    hours = delta.seconds // 3600
                    duration = f"{hours} saat"
            else:
                joined_str = "Bilinmiyor"
                duration = "Bilinmiyor"
            
            # Rolleri listele
            roles = [r.mention for r in member.roles if r.name != "@everyone"]
            roles_str = ", ".join(roles) if roles else "Rol yok"
            
            embed = discord.Embed(
                title="Ayrıldı",
                color=0xe74c3c,
                timestamp=datetime.now(UTC_TZ)
            )
            embed.add_field(name="Kullanıcı", value=f"{member.name}#{member.discriminator}\n(`{member.id}`)", inline=True)
            embed.add_field(name="Katılma Tarihi", value=joined_str, inline=True)
            embed.add_field(name="Kalma Süresi", value=duration, inline=True)
            embed.add_field(name="Roller", value=roles_str[:1024], inline=False)
            embed.set_thumbnail(url=member.display_avatar.url if member.display_avatar else member.default_avatar.url)
            
            await channel.send(embed=embed)
            log(f"[LEAVE] {member.name} ayrıldı")
            
        except Exception as e:
            log(f"[LEAVE] Hata: {repr(e)}")

    async def close(self):
        try:
            if self._kb_task:
                self._kb_task.cancel()
        except Exception:
            pass
        try:
            if self._achievement_task:
                self._achievement_task.cancel()
        except Exception:
            pass
        try:
            if self._kb_http:
                await self._kb_http.close()
        except Exception:
            pass
        await super().close()

    async def _kb_get_json(self, url: str) -> Any:
        if not self._kb_http:
            self._kb_http = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
        async with self._kb_http.get(url, headers={"User-Agent": "CallidusKillbot/1.0"}) as r:
            if r.status != 200:
                raise RuntimeError(f"HTTP {r.status}")
            return await r.json()

    async def _kb_fetch_event_detail(self, event_id: int) -> Optional[dict]:
        try:
            url = f"{AO_API_BASE}/events/{int(event_id)}"
            j = await self._kb_get_json(url)
            return j if isinstance(j, dict) else None
        except Exception:
            return None

    def _kb_trim_seen(self) -> None:
        # Keep seen sets bounded (EventId is monotonic globally, so removing the smallest is OK)
        try:
            while len(self._kb_seen_kill_ids) > KILLBOT_MEMBER_SEEN_MAX:
                self._kb_seen_kill_ids.remove(min(self._kb_seen_kill_ids))
        except Exception:
            pass
        try:
            while len(self._kb_seen_death_ids) > KILLBOT_MEMBER_SEEN_MAX:
                self._kb_seen_death_ids.remove(min(self._kb_seen_death_ids))
        except Exception:
            pass

    def _kb_persist_state(self) -> None:
        self._kb_trim_seen()
        _kb_save_state({
            "guild_last_event_id": int(self._kb_last_event_id or 0),
            "member_seen_kill_ids": sorted(self._kb_seen_kill_ids)[-KILLBOT_MEMBER_SEEN_MAX:],
            "member_seen_death_ids": sorted(self._kb_seen_death_ids)[-KILLBOT_MEMBER_SEEN_MAX:],
            "link_mode": str(getattr(self, "_kb_link_mode", _KB_LINK_MODE) or _KB_LINK_MODE),
        })

    async def _kb_refresh_member_ids(self, *, force: bool = False) -> None:
        now = datetime.now(UTC_TZ)

        # Manuel liste verilirse (KILLBOT_MEMBER_IDS), API'ye gitmeden bunu kullan.
        manual = (KILLBOT_MEMBER_IDS or '').strip()
        if manual:
            parts = re.split(r"[\s,;]+", manual)
            ids2: List[str] = []
            seen = set()
            for x in parts:
                x = (x or '').strip()
                if x and x not in seen:
                    seen.add(x)
                    ids2.append(x)
            self._kb_member_ids = ids2
            self._kb_members_refreshed_at = now
            return
        if (not force) and self._kb_members_refreshed_at:
            if (now - self._kb_members_refreshed_at).total_seconds() < max(60, KILLBOT_MEMBER_REFRESH_SECONDS):
                return

        url = f"{AO_API_BASE}/guilds/{AO_GUILD_ID}/members"
        j = await self._kb_get_json(url)
        ids: List[str] = []
        if isinstance(j, list):
            for m in j:
                if not isinstance(m, dict):
                    continue
                pid = m.get("Id") or m.get("id") or m.get("PlayerId") or m.get("PlayerID") or m.get("PlayerId")
                if pid:
                    ids.append(str(pid).strip())
        # de-dup + stable order
        ids2: List[str] = []
        seen = set()
        for x in ids:
            if x and x not in seen:
                seen.add(x)
                ids2.append(x)
        self._kb_member_ids = ids2
        self._kb_members_refreshed_at = now

    async def _kb_fetch_player_events(self, player_id: str, which: str) -> List[dict]:
        # which: "kills" or "deaths"
        pid = (player_id or "").strip()
        if not pid:
            return []
        w = which.strip().lower()
        if w not in ("kills", "deaths"):
            return []
        url = f"{AO_API_BASE}/players/{pid}/{w}?limit={int(KILLBOT_MEMBER_EVENTS_LIMIT)}&offset=0"
        j = await self._kb_get_json(url)
        return j if isinstance(j, list) else []

    async def _kb_send_event(self, ch: discord.TextChannel, ev2: dict, kind: str) -> bool:
        if not isinstance(ev2, dict):
            return False

        try:
            eid = _kb_safe_int(ev2.get("EventId") or 0, 0)
            kill_url = _kb_killboard_url(eid)
            # Battle button is disabled; only keep Killboard link.
            view = KillbotLinks(kill_url=kill_url, battle_url="")

            emb = _kb_build_embed(ev2, kind)
            # Main image (equipment + stats) — inventory is sent as a separate image.
            img = await _kb_make_image(self, ev2, kind, include_inventory=False)
            inv_img = await _kb_make_inventory_image(self, ev2, kind)
            files: List[discord.File] = []
            try:
                logo_path = _kb_find_guild_logo_path()
                if logo_path and os.path.isfile(logo_path):
                    files.append(discord.File(logo_path, filename="guild.png"))
                    emb.set_thumbnail(url="attachment://guild.png")
                    emb.set_author(name="CALLIDUS", icon_url="attachment://guild.png")
            except Exception:
                pass

            if img:
                files.append(discord.File(fp=io.BytesIO(img), filename=f"{kind}_{eid}.png"))
                emb.set_image(url=f"attachment://{kind}_{eid}.png")

            # 1) Send the main kill/death card first.
            if files:
                await ch.send(embed=emb, files=files, view=view)
            else:
                await ch.send(embed=emb, view=view)

            # 2) Then send lost items as a separate image (so it shows cleanly after the main card).
            if inv_img:
                try:
                    await ch.send(
                        content="🎒 Kaybedilen eşyalar",
                        file=discord.File(fp=io.BytesIO(inv_img), filename=f"lost_{eid}.png"),
                    )
                except Exception:
                    # don't fail the whole event if follow-up send fails
                    pass
            
            # 3) Achievement processing
            if ACHIEVEMENTS_OK:
                try:
                    killer = ev2.get("Killer") if isinstance(ev2.get("Killer"), dict) else {}
                    victim = ev2.get("Victim") if isinstance(ev2.get("Victim"), dict) else {}
                    fame = int(ev2.get("TotalVictimKillFame") or 0)
                    
                    killer_id = (killer.get("Id") or "").strip()
                    victim_id = (victim.get("Id") or "").strip()
                    
                    # Check if solo kill (no other participants with damage)
                    parts = ev2.get("Participants") or []
                    is_solo = len([p for p in parts if int(p.get("DamageDone") or 0) > 0]) <= 1
                    
                    if kind == "kill":
                        discord_id, new_achievements = await process_kill_event(
                            self, killer_id, victim_id, fame, is_solo, eid
                        )
                        if discord_id and new_achievements:
                            for ach in new_achievements:
                                await send_achievement_notification(self, discord_id, ach, GUILD_ID)
                    else:  # death
                        discord_id, new_achievements = await process_death_event(
                            self, victim_id, killer_id, fame, eid
                        )
                        if discord_id and new_achievements:
                            for ach in new_achievements:
                                await send_achievement_notification(self, discord_id, ach, GUILD_ID)
                except Exception as e:
                    log("achievement processing error:", repr(e))
            
            return True
        except Exception as e:
            log(f"killboard send error:" if kind=="kill" else "deathboard send error:", repr(e))
            return False


    async def _killbot_loop(self):
        await self.wait_until_ready()

        bootstrap_guild_done = False
        bootstrap_members_done = False
        
        # İlk başlangıçta auto-sync yap (state yoksa veya boşsa)
        initial_sync_done = False

        while not self.is_closed():
            state_dirty = False
            sent_any = False
            skipped_old = 0  # Yaşı geçmiş event sayısı
            
            try:
                kill_ch = self.get_channel(KILLBOARD_CHANNEL_ID)
                death_ch = self.get_channel(DEATHBOARD_CHANNEL_ID)

                # Always keep member list fresh (deathboard always uses members)
                try:
                    await self._kb_refresh_member_ids()
                except Exception as e:
                    self._kb_err = f"members refresh: {repr(e)}"

                # ----------------------------
                # AUTO-SYNC: State boşsa otomatik senkronize et
                # ----------------------------
                if not initial_sync_done:
                    needs_sync = False
                    
                    # Guild mode için state kontrolü
                    if KILLBOT_KILL_MODE == "guild" and int(self._kb_last_event_id or 0) <= 0:
                        needs_sync = True
                    
                    # Members mode için seen set kontrolü  
                    if not self._kb_seen_death_ids and not self._kb_seen_kill_ids:
                        needs_sync = True
                    
                    if needs_sync:
                        log("[KB] State boş - otomatik senkronizasyon başlatılıyor...")
                        try:
                            await self._kb_auto_sync()
                            state_dirty = True
                            log("[KB] Otomatik senkronizasyon tamamlandı")
                        except Exception as e:
                            log(f"[KB] Otomatik senkronizasyon hatası: {e}")
                    
                    initial_sync_done = True
                    bootstrap_guild_done = True
                    bootstrap_members_done = True

                # ----------------------------
                # (A) Killboard - guild mode
                # ----------------------------
                if KILLBOT_KILL_MODE == "guild" and isinstance(kill_ch, discord.TextChannel):
                    url = f"{AO_API_BASE}/events?guildId={AO_GUILD_ID}&limit=51&offset=0"
                    events = await self._kb_get_json(url)
                    if not isinstance(events, list):
                        events = []

                    events_sorted: List[Tuple[int, dict]] = []
                    for ev in events:
                        if isinstance(ev, dict):
                            try:
                                eid = int(ev.get("EventId"))
                                events_sorted.append((eid, ev))
                            except Exception:
                                pass
                    events_sorted.sort(key=lambda x: x[0])

                    # State API'den ilerideyse düzelt
                    if events_sorted:
                        latest_eid = events_sorted[-1][0]
                        if int(self._kb_last_event_id or 0) > latest_eid:
                            log(f"[KB] State API'den ileride ({self._kb_last_event_id} > {latest_eid}), düzeltiliyor...")
                            self._kb_last_event_id = latest_eid
                            state_dirty = True

                    for eid, ev in events_sorted:
                        if eid <= int(self._kb_last_event_id or 0):
                            continue

                        # ⭐ ZAMAN FİLTRESİ - Çok eski eventleri atla
                        if _kb_is_event_too_old(ev, KILLBOT_MAX_EVENT_AGE_HOURS):
                            skipped_old += 1
                            self._kb_last_event_id = eid  # Cursor'u ilerlet ama atma
                            state_dirty = True
                            continue

                        detail = await self._kb_fetch_event_detail(eid)
                        ev2 = detail if detail else ev
                        
                        # Detaylı veri ile tekrar zaman kontrolü
                        if _kb_is_event_too_old(ev2, KILLBOT_MAX_EVENT_AGE_HOURS):
                            skipped_old += 1
                            self._kb_last_event_id = eid
                            state_dirty = True
                            continue

                        killer = ev2.get("Killer") if isinstance(ev2.get("Killer"), dict) else {}
                        k_gid = (killer.get("GuildId") or "").strip()

                        # Sadece guild killeri
                        if k_gid == AO_GUILD_ID:
                            ok = await self._kb_send_event(kill_ch, ev2, "kill")
                            if not ok:
                                break
                            sent_any = True

                        self._kb_last_event_id = eid
                        state_dirty = True

                # -------------------------------------------
                # (B) Members based - Deathboard (always)
                #     + Killboard (members mode only)
                # -------------------------------------------
                member_ids = list(self._kb_member_ids or [])

                # ---- Deathboard: players/<id>/deaths ----
                if isinstance(death_ch, discord.TextChannel) and member_ids:
                    sem = asyncio.Semaphore(max(1, int(KILLBOT_MEMBER_CONCURRENCY)))

                    async def fetch_deaths(pid: str):
                        async with sem:
                            try:
                                return await self._kb_fetch_player_events(pid, "deaths")
                            except Exception:
                                return []

                    deaths_lists = await asyncio.gather(*[fetch_deaths(pid) for pid in member_ids], return_exceptions=True)
                    deaths_events: List[Tuple[int, dict]] = []
                    for res in deaths_lists:
                        if isinstance(res, list):
                            for ev in res:
                                if isinstance(ev, dict) and ev.get("EventId") is not None:
                                    try:
                                        deaths_events.append((int(ev["EventId"]), ev))
                                    except Exception:
                                        pass
                    deaths_events.sort(key=lambda x: x[0])

                    for eid, ev in deaths_events:
                        if eid in self._kb_seen_death_ids:
                            continue
                        
                        # ⭐ ZAMAN FİLTRESİ
                        if _kb_is_event_too_old(ev, KILLBOT_MAX_EVENT_AGE_HOURS):
                            skipped_old += 1
                            self._kb_seen_death_ids.add(eid)  # Görüldü olarak işaretle
                            state_dirty = True
                            continue
                        
                        detail = await self._kb_fetch_event_detail(eid)
                        ev2 = detail if detail else ev
                        
                        # Detaylı veri ile tekrar kontrol
                        if _kb_is_event_too_old(ev2, KILLBOT_MAX_EVENT_AGE_HOURS):
                            skipped_old += 1
                            self._kb_seen_death_ids.add(eid)
                            state_dirty = True
                            continue
                        
                        ok = await self._kb_send_event(death_ch, ev2, "death")
                        if not ok:
                            break
                        self._kb_seen_death_ids.add(eid)
                        state_dirty = True
                        sent_any = True

                # ---- Killboard (members mode): players/<id>/kills ----
                if KILLBOT_KILL_MODE == "members" and isinstance(kill_ch, discord.TextChannel) and member_ids:
                    sem = asyncio.Semaphore(max(1, int(KILLBOT_MEMBER_CONCURRENCY)))

                    async def fetch_kills(pid: str):
                        async with sem:
                            try:
                                return await self._kb_fetch_player_events(pid, "kills")
                            except Exception:
                                return []

                    kills_lists = await asyncio.gather(*[fetch_kills(pid) for pid in member_ids], return_exceptions=True)
                    kill_events: List[Tuple[int, dict]] = []
                    for res in kills_lists:
                        if isinstance(res, list):
                            for ev in res:
                                if isinstance(ev, dict) and ev.get("EventId") is not None:
                                    try:
                                        kill_events.append((int(ev["EventId"]), ev))
                                    except Exception:
                                        pass
                    kill_events.sort(key=lambda x: x[0])

                    for eid, ev in kill_events:
                        if eid in self._kb_seen_kill_ids:
                            continue
                        
                        # ⭐ ZAMAN FİLTRESİ
                        if _kb_is_event_too_old(ev, KILLBOT_MAX_EVENT_AGE_HOURS):
                            skipped_old += 1
                            self._kb_seen_kill_ids.add(eid)
                            state_dirty = True
                            continue
                        
                        detail = await self._kb_fetch_event_detail(eid)
                        ev2 = detail if detail else ev
                        
                        if _kb_is_event_too_old(ev2, KILLBOT_MAX_EVENT_AGE_HOURS):
                            skipped_old += 1
                            self._kb_seen_kill_ids.add(eid)
                            state_dirty = True
                            continue
                        
                        ok = await self._kb_send_event(kill_ch, ev2, "kill")
                        if not ok:
                            break
                        self._kb_seen_kill_ids.add(eid)
                        state_dirty = True
                        sent_any = True

                # Persist state
                if state_dirty:
                    self._kb_persist_state()

                if sent_any:
                    self._kb_last_seen_at = datetime.now(TR_TZ)
                    self._kb_err = ""
                
                # Log skipped old events (sadece ilk sefer veya çok fazlaysa)
                if skipped_old > 0:
                    log(f"[KB] {skipped_old} eski event atlandı (>{KILLBOT_MAX_EVENT_AGE_HOURS} saat)")

            except Exception as e:
                self._kb_err = repr(e)
                log("killbot loop error:", self._kb_err)

            await asyncio.sleep(KILLBOT_POLL_SECONDS)


    async def _kb_auto_sync(self) -> None:
        """Otomatik senkronizasyon - API'deki mevcut eventleri 'görülmüş' olarak işaretle."""
        log("[KB] Auto-sync başlıyor...")
        
        # Guild mode için en son EventId'yi al
        if KILLBOT_KILL_MODE == "guild":
            url = f"{AO_API_BASE}/events?guildId={AO_GUILD_ID}&limit=51&offset=0"
            events = await self._kb_get_json(url)
            if isinstance(events, list):
                for ev in events:
                    if isinstance(ev, dict):
                        try:
                            eid = int(ev.get("EventId") or 0)
                            if eid > int(self._kb_last_event_id or 0):
                                self._kb_last_event_id = eid
                        except:
                            pass
            log(f"[KB] Guild last_event_id: {self._kb_last_event_id}")
        
        # Members için seen setlerini doldur
        member_ids = list(self._kb_member_ids or [])
        if member_ids:
            sem = asyncio.Semaphore(max(1, int(KILLBOT_MEMBER_CONCURRENCY)))
            
            async def fetch_events(pid: str, which: str):
                async with sem:
                    try:
                        return await self._kb_fetch_player_events(pid, which)
                    except:
                        return []
            
            # Deaths
            death_results = await asyncio.gather(*[fetch_events(pid, "deaths") for pid in member_ids], return_exceptions=True)
            for res in death_results:
                if isinstance(res, list):
                    for ev in res:
                        if isinstance(ev, dict):
                            try:
                                self._kb_seen_death_ids.add(int(ev.get("EventId")))
                            except:
                                pass
            
            # Kills (members mode için)
            if KILLBOT_KILL_MODE == "members":
                kill_results = await asyncio.gather(*[fetch_events(pid, "kills") for pid in member_ids], return_exceptions=True)
                for res in kill_results:
                    if isinstance(res, list):
                        for ev in res:
                            if isinstance(ev, dict):
                                try:
                                    self._kb_seen_kill_ids.add(int(ev.get("EventId")))
                                except:
                                    pass
            
            log(f"[KB] Seen deaths: {len(self._kb_seen_death_ids)}, Seen kills: {len(self._kb_seen_kill_ids)}")


    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # ===== Translation channel auto-reply =====
        if is_translation_channel(message.channel):
            text = (message.content or "").strip()
            if not text:
                return
            if len(text) > 600:
                return

            if not LOC_LOADED:
                try:
                    await message.reply("❌ Çeviri verisi yüklenmedi. pairs.tsv var mı?", mention_author=False)
                except Exception:
                    pass
                return

            hit = lookup_en_tr(text)
            if not hit:
                try:
                    await message.reply("❌ Bulamadım.", mention_author=False)
                except Exception:
                    pass
                return

            en, tr, how = hit
            if how == "exact-tr":
                out = f"🇬🇧 **{en}**"
            else:
                out = f"🇹🇷 **{tr}**"

            try:
                await message.reply(out, mention_author=False)
            except Exception:
                pass
            return

        # sadece thread içi seçimler:
        if not isinstance(message.channel, discord.Thread):
            return

        # ===== Sheet thread ise (AVA SKIP / 10MAN) =====
        main_id = SHEET_THREAD_TO_MAIN.get(message.channel.id)
        if main_id and main_id in SHEET_EVENTS:
            st = SHEET_EVENTS[main_id]
            text = (message.content or "").strip()
            if not text:
                return

            if text.lower() in ("leave", "çık", "cik", "exit"):
                ok, msg = await sheet_leave_user(self, st, message.author.id)
                try:
                    await message.reply("✅ Çıkıldı." if ok else f"❌ {msg}", mention_author=False)
                except Exception:
                    pass
                return

            # sayı ile seçme
            if re.fullmatch(r"\d{1,2}", text):
                n = int(text)
                try:
                    headers, rows = await load_sheet_rows(st.sheet_tab, force=True)
                    entries = build_role_entries(st.sheet_tab, st.slots, headers, rows)
                    total_pages = max(1, (len(entries) + SHEET_PAGE_SIZE - 1) // SHEET_PAGE_SIZE)
                    st.page = max(0, min(st.page, total_pages - 1))
                    start = st.page * SHEET_PAGE_SIZE
                    end = start + SHEET_PAGE_SIZE
                    page_entries = entries[start:end]
                    if 1 <= n <= len(page_entries):
                        chosen = page_entries[n-1].variant_id
                        await self._sheet_assign_from_message(message, st, chosen)
                        return
                except Exception as e:
                    log("sheet number select error:", repr(e))
                return

            # isim ile seçme (role/varyant label)
            try:
                headers, rows = await load_sheet_rows(st.sheet_tab, force=True)
                entries = build_role_entries(st.sheet_tab, st.slots, headers, rows)
                want = _norm(text)
                match = None
                for ent in entries:
                    if want == ent.variant_id or want == ent.role_key or want in _norm(ent.role_name) or want in _norm(ent.label):
                        match = ent.variant_id
                        break
                if match:
                    await self._sheet_assign_from_message(message, st, match)
                    return
            except Exception as e:
                log("sheet text select error:", repr(e))
            return

        # ===== Normal event thread -> class yazma =====
        st2 = None
        for s in EVENTS.values():
            if s.thread_id == message.channel.id:
                st2 = s
                break
        if not st2:
            return

        role = parse_role_key(message.content)
        if not role:
            return

        ok, reason = try_add_user(st2, message.author.id, role)
        if not ok:
            if reason in ("Slot dolu.", "Event dolu."):
                try:
                    await message.reply(reason, mention_author=False)
                except Exception:
                    pass
            return

        ch = self.get_channel(st2.channel_id)
        if isinstance(ch, discord.TextChannel):
            try:
                main_msg = await ch.fetch_message(st2.message_id)
                await main_msg.edit(embed=build_embed(st2, message.guild), view=EventView(st2.template))
            except Exception as e:
                log("thread->main edit error:", repr(e))

    async def _sheet_assign_from_message(self, message: discord.Message, st: SheetEventState, chosen_variant_id: str):
        chosen_variant_id = (chosen_variant_id or "").strip()
        if "|" not in chosen_variant_id:
            return
        chosen_role_key, chosen_sig8 = chosen_variant_id.split("|", 1)
        chosen_role_key = chosen_role_key.strip()
        chosen_sig8 = chosen_sig8.strip()

        try:
            headers, rows = await load_sheet_rows(st.sheet_tab, force=True)
            role_rows = _find_rows_for_variant(headers, rows, chosen_role_key, chosen_sig8)
            if not role_rows:
                return
        except Exception:
            return

        old_slot = st.user_slot.get(message.author.id)
        if old_slot and old_slot in st.slots:
            old_role_name, old_uid = st.slots[old_slot]
            if old_uid == message.author.id:
                st.slots[old_slot] = (old_role_name, None)

        chosen_row = None
        chosen_slot_key = None
        for rr in role_rows:
            sk = str(rr.row_idx)
            role_name, uid = st.slots.get(sk, (rr.role, None))
            if uid is None:
                chosen_row = rr
                chosen_slot_key = sk
                break

        if not chosen_row or not chosen_slot_key:
            try:
                row_idxs = [rr.row_idx for rr in role_rows]
                filled, total = _count_rows_in_state(st.slots, row_idxs)
                await message.reply(f"❌ Slot dolu. ({filled}/{total})", mention_author=False)
            except Exception:
                pass
            return

        try:
            headers2, _rows2 = await load_sheet_rows(st.sheet_tab, force=True)
            await clear_user_from_sheet(st.sheet_tab, headers2, message.author.id)
            await set_role_nick(st.sheet_tab, headers2, chosen_row, sheet_user_string(message.author))
        except Exception as e:
            try:
                await message.reply(f"❌ Sheet yazma hatası: {e}", mention_author=False)
            except Exception:
                pass
            return

        st.slots[chosen_slot_key] = (chosen_row.role, message.author.id)
        st.user_slot[message.author.id] = chosen_slot_key

        await _edit_sheet_messages(self, st)

        main_embed, swap_embed = build_set_embeds(chosen_row.role, chosen_row, headers, title_prefix=st.title)
        dm_text = (
            f"✅ **{st.title}** rolün: **{chosen_row.role}**\n"
            f"⏰ **Zaman:** **{st.time_tr} / {st.time_utc} UTC**\n"
            f"📍 **Toplanma:** **{st.toplanma}**\n"
            f"⚠️ **Geç kalma!**"
        )
        try:
            await message.author.send(content=dm_text, embed=main_embed)
            if swap_embed is not None:
                await message.author.send(embed=swap_embed)
            try:
                await message.reply("✅ Alındı. Set DM’den gönderildi.", mention_author=False)
            except Exception:
                pass
        except Exception:
            try:
                await message.reply("✅ DM kapalı. Seti burada gösteriyorum:", mention_author=False)
                await message.reply(content=dm_text, embed=main_embed, mention_author=False)
                if swap_embed is not None:
                    await message.reply(embed=swap_embed, mention_author=False)
            except Exception:
                pass

bot = CallidusBot()

# =========================================================
#                        EVENT VIEW
# =========================================================
class RoleSelect(discord.ui.Select):
    def __init__(self, tpl: EventTemplate):
        opts: List[discord.SelectOption] = []
        for role, _count in tpl.roles:
            opts.append(discord.SelectOption(label=ROLE_LABELS.get(role, role), value=role, emoji=ROLE_EMOJI.get(role)))
        super().__init__(placeholder="👇 Rol seç", min_values=1, max_values=1, options=opts)

    async def callback(self, interaction: discord.Interaction):
        await safe_defer(interaction, ephemeral=True)
        state = EVENTS.get(interaction.message.id) if interaction.message else None
        if not state:
            return await safe_send(interaction, "Event state bulunamadı.", ephemeral=True)

        ok, reason = try_add_user(state, interaction.user.id, self.values[0])
        if not ok:
            return await safe_send(interaction, reason, ephemeral=True)

        try:
            if interaction.message:
                await interaction.message.edit(embed=build_embed(state, interaction.guild), view=EventView(state.template))
        except Exception as e:
            log("event edit error:", repr(e))

class EventView(discord.ui.View):
    def __init__(self, tpl: EventTemplate):
        super().__init__(timeout=None)
        self.add_item(RoleSelect(tpl))

    @discord.ui.button(label="Çık", style=discord.ButtonStyle.danger, emoji="❌")
    async def leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        await safe_defer(interaction, ephemeral=True)
        state = EVENTS.get(interaction.message.id) if interaction.message else None
        if not state:
            return await safe_send(interaction, "Event state bulunamadı.", ephemeral=True)

        remove_user(state, interaction.user.id)
        try:
            if interaction.message:
                await interaction.message.edit(embed=build_embed(state, interaction.guild), view=EventView(state.template))
        except Exception as e:
            log("leave edit error:", repr(e))

# =========================================================
#                      EVENT CREATE
# =========================================================
# =========================================================
#              CONTENT HATIRLATMA SİSTEMİ
# =========================================================

CONTENT_REMINDER_MINUTES = 10  # Content'e kaç dakika kala hatırlatma yapılsın

async def _send_content_reminder_dm(bot_client: "CallidusBot", message_id: int, content_name: str, time_str: str):
    """Content'e katılan kişilere DM gönderir."""
    try:
        # Normal event mi sheet event mi kontrol et
        participant_ids: List[int] = []
        
        if message_id in EVENTS:
            state = EVENTS[message_id]
            participant_ids = list(state.user_role.keys())
        elif message_id in SHEET_EVENTS:
            st = SHEET_EVENTS[message_id]
            participant_ids = list(st.user_slot.keys())
        
        if not participant_ids:
            log(f"[REMINDER] Katılımcı yok, DM gönderilmedi: {content_name}")
            return
        
        sent_count = 0
        failed_count = 0
        
        for user_id in participant_ids:
            try:
                user = bot_client.get_user(user_id)
                if not user:
                    user = await bot_client.fetch_user(user_id)
                
                if user:
                    embed = discord.Embed(
                        title="⏰ Content Hatırlatma!",
                        description=f"**{content_name}** content'ine az kaldı! (**{time_str}**)\n\n"
                                    f"✅ Set hazır, varsa swap hazır olsun.\n"
                                    f"❌ Hazır olmayan gelmesin.",
                        color=0xFF9900
                    )
                    embed.set_footer(text="10 dakika kaldı • İyi oyunlar!")
                    
                    await user.send(embed=embed)
                    sent_count += 1
            except discord.Forbidden:
                failed_count += 1  # DM kapalı
            except Exception:
                failed_count += 1
        
        log(f"[REMINDER] DM gönderildi: {content_name} @ {time_str} ({sent_count} başarılı, {failed_count} başarısız)")
        
    except Exception as e:
        log(f"[REMINDER] DM hatası: {repr(e)}")

async def _schedule_content_reminder(bot_client: "CallidusBot", channel: discord.TextChannel, message_id: int, content_name: str, time_str: str, dt_tr: datetime):
    """Content için 10 dk öncesine hatırlatma zamanlar."""
    try:
        reminder_time = dt_tr - timedelta(minutes=CONTENT_REMINDER_MINUTES)
        now = datetime.now(TR_TZ)
        
        wait_seconds = (reminder_time - now).total_seconds()
        
        if wait_seconds <= 0:
            log(f"[REMINDER] Hatırlatma zamanı geçmiş, atlanıyor: {content_name}")
            return
        
        log(f"[REMINDER] Hatırlatma zamanlandı: {content_name} @ {time_str} ({int(wait_seconds)}sn sonra)")
        
        await asyncio.sleep(wait_seconds)
        
        # Hatırlatma zamanı geldi - katılımcılara DM at
        await _send_content_reminder_dm(bot_client, message_id, content_name, time_str)
        
        # Task'ı temizle
        if message_id in bot_client.content_reminders:
            del bot_client.content_reminders[message_id]
            
    except asyncio.CancelledError:
        log(f"[REMINDER] Hatırlatma iptal edildi: {content_name}")
    except Exception as e:
        log(f"[REMINDER] Hatırlatma hatası: {repr(e)}")


async def create_event_in_channel(
    interaction: discord.Interaction,
    template: EventTemplate,
    time: Optional[str],
    toplanma: Optional[str],
    binek: Optional[str],
    ayar: Optional[str],
):
    guild = interaction.guild
    if not guild:
        raise RuntimeError("Guild bulunamadı.")
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        raise RuntimeError("Bu komut sadece text channel içinde çalışır.")

    t_tr, t_utc = fmt_time(time)
    toplanma_val = toplanma.strip() if toplanma and str(toplanma).strip() else "BELİRTİLMEMİŞ"
    mount_val = binek.strip() if binek and str(binek).strip() else DEFAULT_MOUNT
    ayar_val = ayar.strip() if ayar and str(ayar).strip() else DEFAULT_AYAR_FALLBACK

    roster_init = {role: [] for role, _ in template.roles}
    state = EventState(
        template=template,
        channel_id=channel.id,
        message_id=0,
        thread_id=0,
        owner_id=interaction.user.id,
        roster=roster_init,
        user_role={},
        toplanma=toplanma_val,
        time_tr=t_tr,
        time_utc=t_utc,
        mount=mount_val,
        ayar=ayar_val,
    )

    ping_text = f"<@&{PING_ROLE_ID}>" if PING_ROLE_ID else ""
    msg = await channel.send(
        content=ping_text,
        embed=build_embed(state, guild),
        view=EventView(template),
        allowed_mentions=discord.AllowedMentions(roles=True, everyone=False, users=False),
    )

    state.message_id = msg.id
    EVENTS[msg.id] = state

    thread = await msg.create_thread(name=template.thread_name)
    try:
        await thread.send("Gelecek olan classını yazsın.")
    except Exception:
        pass
    state.thread_id = thread.id
    
    # Content hatırlatması zamanla (10 dk önce)
    try:
        if time and re.fullmatch(r"\d{1,2}:\d{2}", _normalize_time_input(str(time).strip())):
            hh, mm = map(int, _normalize_time_input(str(time).strip()).split(":"))
            now_tr = datetime.now(TR_TZ)
            dt_tr = now_tr.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if dt_tr < now_tr - timedelta(minutes=1):
                dt_tr += timedelta(days=1)
            
            # Hatırlatma task'ı oluştur
            reminder_task = asyncio.create_task(
                _schedule_content_reminder(bot, channel, msg.id, template.thread_name, t_tr, dt_tr)
            )
            bot.content_reminders[msg.id] = reminder_task
    except Exception as e:
        log(f"[REMINDER] Hatırlatma zamanlanamadı: {repr(e)}")

async def create_sheet_event(
    interaction: discord.Interaction,
    *,
    sheet_tab: str,
    title: str,
    thread_name: str,
    time: Optional[str],
    toplanma: Optional[str],
    binek: Optional[str],
    ayar: Optional[str],
):
    guild = interaction.guild
    if not guild:
        raise RuntimeError("Guild bulunamadı.")
    channel = interaction.channel
    if not isinstance(channel, discord.TextChannel):
        raise RuntimeError("Bu komut sadece text channel içinde çalışır.")

    sheet_id = _resolve_sheet_id_for_tab(sheet_tab)
    if not GOOGLE_CREDS_JSON or not sheet_id:
        raise RuntimeError("GOOGLE_CREDS_JSON veya Sheet ID ayarlı değil. (AVASKIP_SHEET_ID / BRAWLCOMP_SHEET_ID)")

    headers, rows = await load_sheet_rows(sheet_tab, force=True)
    if not rows:
        raise RuntimeError(f"Sheet ({sheet_tab})'te rol bulunamadı.")

    await clear_all_nicks_from_sheet(sheet_tab, headers, last_row=(len(rows) + 1))

    t_tr, t_utc = fmt_time(time)
    toplanma_val = toplanma.strip() if toplanma and str(toplanma).strip() else "BELİRTİLMEMİŞ"
    mount_val = binek.strip() if binek and str(binek).strip() else DEFAULT_MOUNT
    ayar_val = ayar.strip() if ayar and str(ayar).strip() else DEFAULT_AYAR_FALLBACK

    slots = {str(r.row_idx): (r.role, None) for r in rows}

    st = SheetEventState(
        sheet_tab=sheet_tab,
        title=title,
        channel_id=channel.id,
        message_id=0,
        thread_id=0,
        thread_msg_id=0,
        owner_id=interaction.user.id,
        toplanma=toplanma_val,
        time_tr=t_tr,
        time_utc=t_utc,
        mount=mount_val,
        ayar=ayar_val,
        slots=slots,
        user_slot={},
        page=0,
    )

    ping_text = f"<@&{PING_ROLE_ID}>" if PING_ROLE_ID else ""
    main_embed = await build_sheet_main_embed_async(st, guild)
    main_msg = await channel.send(
        content=ping_text,
        embed=main_embed,
        view=SheetMainView(st),
        allowed_mentions=discord.AllowedMentions(roles=True, everyone=False, users=False),
    )

    st.message_id = main_msg.id
    SHEET_EVENTS[main_msg.id] = st

    th = await main_msg.create_thread(name=thread_name)
    st.thread_id = th.id
    SHEET_THREAD_TO_MAIN[th.id] = main_msg.id

    emb, page_entries, total_pages = await build_sheet_thread_embed(st)
    tmsg = await th.send(
        embed=emb,
        view=SheetThreadView(st, page_entries, total_pages),
        allowed_mentions=discord.AllowedMentions(everyone=False, users=False, roles=False),
    )
    st.thread_msg_id = tmsg.id
    
    # Content hatırlatması zamanla (10 dk önce)
    try:
        if time and re.fullmatch(r"\d{1,2}:\d{2}", _normalize_time_input(str(time).strip())):
            hh, mm = map(int, _normalize_time_input(str(time).strip()).split(":"))
            now_tr = datetime.now(TR_TZ)
            dt_tr = now_tr.replace(hour=hh, minute=mm, second=0, microsecond=0)
            if dt_tr < now_tr - timedelta(minutes=1):
                dt_tr += timedelta(days=1)
            
            # Hatırlatma task'ı oluştur
            reminder_task = asyncio.create_task(
                _schedule_content_reminder(bot, channel, main_msg.id, thread_name, t_tr, dt_tr)
            )
            bot.content_reminders[main_msg.id] = reminder_task
    except Exception as e:
        log(f"[REMINDER] Hatırlatma zamanlanamadı: {repr(e)}")

# =========================================================
#                        COMMANDS
# =========================================================

# ---- Mesaj / Foto (Embed + Attachment sender) ----
def _is_staff_member(interaction: discord.Interaction) -> bool:
    """Restrict /mesaj and /foto to staff-level perms (admin / manage_guild / manage_channels / manage_messages)."""
    try:
        if not interaction.guild:
            return False
        m = interaction.guild.get_member(interaction.user.id)
        if not m:
            return False
        p = m.guild_permissions
        return bool(p.administrator or p.manage_guild or p.manage_channels or p.manage_messages)
    except Exception:
        return False

# Color presets (user-friendly)
_COLOR_PRESETS: Dict[str, discord.Color] = {
    "purple": discord.Color.purple(),
    "blurple": discord.Color.blurple(),
    "blue": discord.Color.blue(),
    "green": discord.Color.green(),
    "yellow": discord.Color.gold(),
    "orange": discord.Color.orange(),
    "red": discord.Color.red(),
    "gray": discord.Color.dark_grey(),
    "white": discord.Color.from_rgb(240, 240, 240),
    "black": discord.Color.from_rgb(20, 20, 20),
}

_HEX_COLOR_RE = re.compile(r"^(#|0x)?([0-9a-fA-F]{6})$")

def _resolve_embed_color(name_or_hex: str) -> discord.Color:
    """Accepts preset names (purple/green/...) or hex (#ff3355)."""
    s = (name_or_hex or "").strip().lower()
    if not s:
        return discord.Color.blurple()
    if s in _COLOR_PRESETS:
        return _COLOR_PRESETS[s]
    m = _HEX_COLOR_RE.match(s)
    if m:
        return discord.Color(int(m.group(2), 16))
    # fallback
    return discord.Color.blurple()

def _chunk_text(s: str, limit: int) -> List[str]:
    s = s or ""
    if len(s) <= limit:
        return [s]
    parts: List[str] = []
    cur = ""
    for line in s.splitlines(True):
        if len(cur) + len(line) > limit:
            if cur:
                parts.append(cur)
                cur = ""
            while len(line) > limit:
                parts.append(line[:limit])
                line = line[limit:]
        cur += line
    if cur:
        parts.append(cur)
    return parts

def _parse_faq_blocks(body: str) -> List[Tuple[str, str]]:
    """
    FAQ formatı:
      ? Soru
      cevap satırları...
      (boş satır)
      ? Soru2
      cevap...
    Ayrıca "Q:" ile başlayanları da kabul eder.
    """
    lines = (body or "").splitlines()
    out: List[Tuple[str, str]] = []
    q: Optional[str] = None
    buf: List[str] = []
    for raw in lines:
        line = raw.rstrip()
        is_q = line.startswith("?") or line.lower().startswith("q:")
        if is_q:
            if q is not None:
                out.append((q.strip(), "\n".join(buf).strip()))
            q = line[1:].strip() if line.startswith("?") else line.split(":", 1)[1].strip()
            buf = []
            continue
        if q is None:
            continue
        buf.append(raw)
    if q is not None:
        out.append((q.strip(), "\n".join(buf).strip()))
    return [(qq, aa) for (qq, aa) in out if qq]

def _build_faq_embeds(title: str, body: str, color: discord.Color) -> List[discord.Embed]:
    qa = _parse_faq_blocks(body)
    if not qa:
        # fallback plain
        return [discord.Embed(title=title or None, description=chunk, color=color) for chunk in _chunk_text(body, 4000)]

    embeds: List[discord.Embed] = []
    cur = discord.Embed(title=title or None, color=color)
    field_count = 0

    for (q, a) in qa:
        a = (a or "").strip() or "—"
        a_chunks = _chunk_text(a, 1000)  # 1024 limit safety
        for j, ach in enumerate(a_chunks):
            name = f"❓ {q}" if j == 0 else f"↳ {q} (devam)"
            if len(name) > 256:
                name = name[:253] + "..."
            if field_count >= 25:
                embeds.append(cur)
                cur = discord.Embed(title=None, color=color)
                field_count = 0
            cur.add_field(name=name, value=ach, inline=False)
            field_count += 1

    embeds.append(cur)
    return embeds

class MessageSendModal(discord.ui.Modal):
    def __init__(self, *, target: discord.abc.Messageable, style: str, color_name: str):
        super().__init__(title="Mesaj Gönder")
        self._target = target
        self._style = (style or "plain").strip().lower()
        self._color_name = (color_name or "").strip()

        self.title_in = discord.ui.TextInput(
            label="Başlık (opsiyonel)",
            required=False,
            max_length=180,
            placeholder="Örn: 🏰 Guild Olarak Hedeflerimiz"
        )
        self.body_in = discord.ui.TextInput(
            label="Mesaj (zorunlu)",
            required=True,
            style=discord.TextStyle.paragraph,
            max_length=4000,
            placeholder="Plain: direkt yaz\n\nFAQ: her soruyu '? Soru' ile başlat, altına cevapları yaz."
        )
        self.add_item(self.title_in)
        self.add_item(self.body_in)

    async def on_submit(self, interaction: discord.Interaction):
        await safe_defer(interaction, ephemeral=True)

        if not _is_staff_member(interaction):
            return await safe_send(interaction, "❌ Bu komut sadece yetkililer için.", ephemeral=True)

        title = (self.title_in.value or "").strip()
        body = (self.body_in.value or "").strip()
        if not body:
            return await safe_send(interaction, "❌ Mesaj boş olamaz.", ephemeral=True)

        color = _resolve_embed_color(self._color_name)

        try:
            if self._style == "faq":
                embeds = _build_faq_embeds(title, body, color)
            else:
                embeds = [discord.Embed(title=title or None, description=chunk, color=color) for chunk in _chunk_text(body, 4000)]

            for e in embeds:
                await self._target.send(
                    embed=e,
                    allowed_mentions=discord.AllowedMentions(everyone=False, users=False, roles=False),
                )
            return await safe_send(interaction, "✅ Mesaj gönderildi.", ephemeral=True)
        except Exception as e:
            return await safe_send(interaction, f"❌ Gönderilemedi: {e}", ephemeral=True)

@bot.tree.command(name="mesaj", description="Mesaj gönderir.", guild=discord.Object(id=GUILD_ID))
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    channel="Hangi kanala gitsin? (Boş: bulunduğun kanal)",
    format="Plain veya FAQ formatı",
    renk="Renk seçimi (purple/green/yellow/...)"
)
@app_commands.choices(
    format=[
        app_commands.Choice(name="Plain", value="plain"),
        app_commands.Choice(name="FAQ", value="faq"),
    ],
    renk=[
        app_commands.Choice(name="Purple", value="purple"),
        app_commands.Choice(name="Green", value="green"),
        app_commands.Choice(name="Yellow", value="yellow"),
        app_commands.Choice(name="Red", value="red"),
        app_commands.Choice(name="Blue", value="blue"),
        app_commands.Choice(name="Orange", value="orange"),
        app_commands.Choice(name="Gray", value="gray"),
        app_commands.Choice(name="Blurple", value="blurple"),
    ],
)
async def mesaj_cmd(
    interaction: discord.Interaction,
    channel: Optional[discord.TextChannel] = None,
    format: str = "plain",
    renk: str = "purple",
):
    if not _is_staff_member(interaction):
        return await safe_send(interaction, "❌ Bu komut sadece yetkililer için.", ephemeral=True)

    target = channel or interaction.channel
    if not target or not hasattr(target, "send"):
        return await safe_send(interaction, "❌ Bu kanala mesaj gönderemiyorum.", ephemeral=True)

    try:
        await interaction.response.send_modal(MessageSendModal(target=target, style=format, color_name=renk))
    except Exception as e:
        log("mesaj modal error:", repr(e))
        return await safe_send(interaction, "❌ Modal açılamadı. Tekrar dene.", ephemeral=True)

async def _find_attachment_by_filename(source: discord.TextChannel, filename: str, limit: int = 500) -> Optional[discord.Attachment]:
    fn = (filename or "").strip().lower()
    if not fn:
        return None
    try:
        async for msg in source.history(limit=limit, oldest_first=False):
            for a in msg.attachments:
                if (a.filename or "").strip().lower() == fn:
                    return a
    except Exception:
        return None
    return None

@bot.tree.command(name="foto", description="Fotoğraf gönderir.", guild=discord.Object(id=GUILD_ID))
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    dosya="PNG/JPG dosya adı. Örn: banner.png",
    channel="Hangi kanala gitsin? (Boş: bulunduğun kanal)",
    kaynak="Dosyayı hangi kanalda arayalım? (Boş: MEDIA_CHANNEL_ID varsa o, yoksa bulunduğun kanal)"
)
async def foto_cmd(
    interaction: discord.Interaction,
    dosya: str,
    channel: Optional[discord.TextChannel] = None,
    kaynak: Optional[discord.TextChannel] = None,
):
    await safe_defer(interaction, ephemeral=True)

    if not _is_staff_member(interaction):
        return await safe_send(interaction, "❌ Bu komut sadece yetkililer için.", ephemeral=True)

    target = channel or interaction.channel
    if not target or not hasattr(target, "send"):
        return await safe_send(interaction, "❌ Bu kanala fotoğraf gönderemiyorum.", ephemeral=True)

    # source channel resolve
    source = kaynak
    if source is None:
        try:
            media_id = int(os.getenv("MEDIA_CHANNEL_ID", "0") or "0")
        except Exception:
            media_id = 0
        if media_id and interaction.guild:
            ch = interaction.guild.get_channel(media_id)
            if isinstance(ch, discord.TextChannel):
                source = ch
    if source is None:
        # fallback to current channel
        if isinstance(interaction.channel, discord.TextChannel):
            source = interaction.channel

    if source is None:
        return await safe_send(interaction, "❌ Kaynak kanal bulunamadı.", ephemeral=True)

    att = await _find_attachment_by_filename(source, dosya, limit=600)
    if not att:
        return await safe_send(interaction, f"❌ Bulunamadı: `{dosya}` (Kaynak: #{getattr(source, 'name', 'kanal')})", ephemeral=True)

    try:
        f = await att.to_file()
        await target.send(file=f, allowed_mentions=discord.AllowedMentions(everyone=False, users=False, roles=False))
        return await safe_send(interaction, "✅ Fotoğraf gönderildi.", ephemeral=True)
    except Exception as e:
        return await safe_send(interaction, f"❌ Gönderilemedi: {e}", ephemeral=True)

@bot.tree.command(name="content", description="Content seçip event oluşturur.", guild=discord.Object(id=GUILD_ID))
async def content_cmd(interaction: discord.Interaction):
    try:
        await interaction.response.send_message("👇", ephemeral=True, view=ContentView())
    except Exception as e:
        log("/content response error:", repr(e))
        try:
            await interaction.followup.send("👇", ephemeral=True, view=ContentView())
        except Exception as e2:
            log("/content followup error:", repr(e2))

@bot.tree.command(name="contentoylama", description="Content oylaması başlatır.", guild=discord.Object(id=GUILD_ID))
async def contentoylama_cmd(interaction: discord.Interaction):
    try:
        await interaction.response.send_modal(ContentOylamaModal())
    except Exception as e:
        log("contentoylama modal error:", repr(e))
        await safe_send(interaction, "❌ Modal açılamadı. Tekrar dene.", ephemeral=True)



@bot.tree.command(name="sheetekle", description="Sheet'i /content'e ekler.", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(
    isim="Menüde gözükecek ad",
    link="Google Sheet linki veya ID",
    tab="Tab adı",
    emoji="Emoji (opsiyonel)"
)
async def sheetekle_cmd(
    interaction: discord.Interaction,
    isim: str,
    link: str,
    tab: str,
    emoji: Optional[str] = None,
):
    if not _is_staff_member(interaction):
        return await safe_send(interaction, "❌ Yetki yok.", ephemeral=True)

    await safe_defer(interaction, ephemeral=True)

    sheet_id = _extract_sheet_id(link)
    tab = (tab or "").strip()
    isim = (isim or "").strip()
    emoji = (emoji or "").strip() if emoji else "📄"

    if not isim or not sheet_id or not tab:
        return await safe_send(interaction, "❌ Eksik.", ephemeral=True)

    base = _slug_key(isim)
    key = base
    i = 2
    while key in DYNAMIC_SHEETS:
        key = f"{base}_{i}"
        i += 1

    DYNAMIC_SHEETS[key] = {"name": isim, "sheet_id": sheet_id, "tab": tab, "emoji": emoji}
    _save_dynamic_sheets()

    return await safe_send(interaction, f"✅ Eklendi: **{isim}** (`{key}`)", ephemeral=True)


@bot.tree.command(name="sheetkaldir", description="Content'ten sheet kaldırır.", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(anahtar="Key veya isim")
async def sheetkaldir_cmd(interaction: discord.Interaction, anahtar: str):
    if not _is_staff_member(interaction):
        return await safe_send(interaction, "❌ Yetki yok.", ephemeral=True)

    await safe_defer(interaction, ephemeral=True)

    q = (anahtar or "").strip()
    if not q:
        return await safe_send(interaction, "❌ Eksik.", ephemeral=True)

    if q in DYNAMIC_SHEETS:
        name = DYNAMIC_SHEETS[q].get("name", q)
        del DYNAMIC_SHEETS[q]
        _save_dynamic_sheets()
        return await safe_send(interaction, f"✅ Kaldırıldı: **{name}**", ephemeral=True)

    # name match
    hits = [k for k, v in DYNAMIC_SHEETS.items() if (v.get("name", "") or "").strip().lower() == q.lower()]
    if len(hits) == 1:
        k = hits[0]
        name = DYNAMIC_SHEETS[k].get("name", k)
        del DYNAMIC_SHEETS[k]
        _save_dynamic_sheets()
        return await safe_send(interaction, f"✅ Kaldırıldı: **{name}**", ephemeral=True)

    if len(hits) > 1:
        short = ", ".join([f"`{k}`" for k in hits[:10]])
        return await safe_send(interaction, f"❌ Birden fazla: {short}", ephemeral=True)

    return await safe_send(interaction, "❌ Bulunamadı.", ephemeral=True)


@bot.tree.command(name="sheetliste", description="Ekli sheet içeriklerini listeler.", guild=discord.Object(id=GUILD_ID))
async def sheetliste_cmd(interaction: discord.Interaction):
    if not _is_staff_member(interaction):
        return await safe_send(interaction, "❌ Yetki yok.", ephemeral=True)

    if not DYNAMIC_SHEETS:
        return await safe_send(interaction, "Boş.", ephemeral=True)

    lines = []
    for k, v in sorted(DYNAMIC_SHEETS.items(), key=lambda kv: (kv[1].get("name", kv[0]).lower(), kv[0].lower())):
        lines.append(f"• `{k}` → {v.get('name', k)}  ({v.get('tab','')})")
    msg = "\n".join(lines)
    if len(msg) > 1800:
        msg = msg[:1800] + "\n…"
    return await safe_send(interaction, msg, ephemeral=True)

def register_command(name: str, description: str, preset_key: str):
    @bot.tree.command(name=name, description=description, guild=discord.Object(id=GUILD_ID))
    async def _cmd(interaction: discord.Interaction):
        try:
            await interaction.response.send_modal(ContentModal(preset_key))
        except Exception:
            await safe_send(interaction, "❌ Modal açılamadı.", ephemeral=True)
    return _cmd

# Content komutları kaldırıldı - sadece /content üzerinden erişilebilir

# ---- Killbot commands ----
@bot.tree.command(name="killboardstatus", description="Killboard durumunu gösterir.", guild=discord.Object(id=GUILD_ID))
async def killboardstatus_cmd(interaction: discord.Interaction):
    await safe_defer(interaction, ephemeral=True)
    st: List[str] = []
    st.append(f"AO_GUILD_ID: `{AO_GUILD_ID}`")
    st.append(f"Kill mode (Killboard): `{KILLBOT_KILL_MODE}`")
    st.append(f"Link mode: `{getattr(bot, '_kb_link_mode', _KB_LINK_MODE)}`")
    st.append(f"MurderLedger: `{MURDERLEDGER_BASE_URL}`")
    st.append(f"Killboard Channel: `{KILLBOARD_CHANNEL_ID}`")
    st.append(f"Deathboard Channel: `{DEATHBOARD_CHANNEL_ID}`")
    st.append(f"API Base: `{AO_API_BASE}`")
    st.append(f"Poll: `{KILLBOT_POLL_SECONDS}s`")
    st.append(f"Image: `{'on' if (PIL_OK and KILLBOT_IMAGE_ENABLED) else 'off'}` (PIL={'ok' if PIL_OK else 'missing'})")

    logo_path = _kb_find_guild_logo_path()
    st.append(f"Guild logo: `{'found' if logo_path else 'not found'}` ({(logo_path or KILLBOT_GUILD_LOGO_FILE)})")

    mem_ids = getattr(bot, "_kb_member_ids", []) or []
    refreshed = getattr(bot, "_kb_members_refreshed_at", None)
    if refreshed:
        try:
            st.append(f"Members cached: `{len(mem_ids)}` (refreshed: `{refreshed.strftime('%Y-%m-%d %H:%M:%S')} UTC`)")
        except Exception:
            st.append(f"Members cached: `{len(mem_ids)}`")
    else:
        st.append(f"Members cached: `{len(mem_ids)}`")

    seen_k = getattr(bot, "_kb_seen_kill_ids", set()) or set()
    seen_d = getattr(bot, "_kb_seen_death_ids", set()) or set()
    st.append(f"Seen (members) -> kills: `{len(seen_k)}` | deaths: `{len(seen_d)}`")

    st.append(f"Guild cursor (last EventId): `{getattr(bot, '_kb_last_event_id', 0)}`")

    # API'den son EventId'yi kontrol et (hızlı teşhis)
    try:
        url = f"{AO_API_BASE}/events?guildId={AO_GUILD_ID}&limit=5&offset=0"
        evs = await bot._kb_get_json(url)
        latest = 0
        if isinstance(evs, list):
            for ev in evs:
                if isinstance(ev, dict) and ev.get("EventId") is not None:
                    try:
                        latest = max(latest, int(ev["EventId"]))
                    except Exception:
                        pass
        if latest:
            st.append(f"API Latest (guild feed) EventId: `{latest}`")
            cur = int(getattr(bot, "_kb_last_event_id", 0) or 0)
            if cur > latest:
                st.append("⚠️ Uyarı: State API'den ileride (killbot_state.json bozulmuş olabilir).")
    except Exception:
        pass

    last_seen = getattr(bot, "_kb_last_seen_at", None)
    if last_seen:
        st.append(f"Last seen: `{last_seen.strftime('%Y-%m-%d %H:%M:%S')}`")
    err = getattr(bot, "_kb_err", "")
    if err:
        st.append(f"Last error: `{err}`")

    await safe_send(interaction, "\n".join(st), ephemeral=True)



@bot.tree.command(name="aktif", description="Threadi aktif eder.", guild=discord.Object(id=GUILD_ID))
async def aktif_cmd(interaction: discord.Interaction):
    await safe_defer(interaction, ephemeral=True)
    if not interaction.guild:
        return await safe_send(interaction, "❌ Guild bulunamadı.", ephemeral=True)

    # Yetki: en az manage_channels / manage_guild / admin
    try:
        perms = interaction.user.guild_permissions  # type: ignore
        if not (perms.administrator or perms.manage_guild or perms.manage_channels):
            return await safe_send(interaction, "❌ Bu komut için yetkin yok. (manage_channels gerekir)", ephemeral=True)
    except Exception:
        return await safe_send(interaction, "❌ Yetki kontrolü yapılamadı.", ephemeral=True)

    if not isinstance(interaction.channel, discord.Thread):
        return await safe_send(interaction, "❌ Bu komut sadece ilgili **thread** içinde çalışır.", ephemeral=True)

    th: discord.Thread = interaction.channel
    parent = th.parent
    if not isinstance(parent, discord.TextChannel):
        return await safe_send(interaction, "❌ Thread parent channel bulunamadı.", ephemeral=True)

    bot_user_id = interaction.client.user.id if interaction.client.user else 0

    main_id = await _sheet_find_parent_main_message_id(parent, th)
    if not main_id:
        main_id = await _sheet_find_thread_main_message_id(th)
    if not main_id:
        return await safe_send(interaction, "❌ Thread içindeki ana mesaj ID bulunamadı.", ephemeral=True)

    try:
        main_msg = await parent.fetch_message(main_id)
    except Exception:
        # bazı durumlarda aynı mesaj thread içinde de fetch edilebilir
        try:
            main_msg = await th.fetch_message(main_id)
        except Exception as e:
            return await safe_send(interaction, f"❌ Ana mesaj fetch edilemedi: {e}", ephemeral=True)

    panel_id = await _sheet_find_thread_panel_message_id(th, bot_user_id)
    if not panel_id:
        return await safe_send(interaction, "❌ Thread panel mesajı bulunamadı. (Rol Seçimi embed'i)", ephemeral=True)

    # State'i yeniden kur
    try:
        st = await _rebuild_sheet_state_from_discord(
            interaction.client,
            main_msg=main_msg,
            th=th,
            thread_msg_id=panel_id,
            owner_id=interaction.user.id,
        )
    except Exception as e:
        log("aktif rebuild error:", repr(e))
        return await safe_send(interaction, f"❌ Yeniden kurma hatası: {e}", ephemeral=True)

    # Eski state varsa temizle
    try:
        SHEET_EVENTS.pop(st.message_id, None)
    except Exception:
        pass
    try:
        # aynı thread'e bağlı eski mapping varsa
        SHEET_THREAD_TO_MAIN[st.thread_id] = st.message_id
    except Exception:
        pass

    SHEET_EVENTS[st.message_id] = st
    SHEET_THREAD_TO_MAIN[st.thread_id] = st.message_id

    # Mesajları yeniden view ile bağla
    await _edit_sheet_messages(interaction.client, st)

    return await safe_send(interaction, f"✅ Aktif edildi. Tab: `{_display_tab(st.sheet_tab)}`", ephemeral=True)

@bot.tree.command(name="kbmurder", description="Killboard linklerini MurderLedger'a geçirir.", guild=discord.Object(id=GUILD_ID))
async def kbmurder_cmd(interaction: discord.Interaction):
    await safe_defer(interaction, ephemeral=True)
    mode = _kb_set_link_mode("murder")
    try:
        bot._kb_link_mode = mode  # type: ignore
        bot._kb_persist_state()   # type: ignore
    except Exception:
        pass
    return await safe_send(interaction, f"✅ Killboard link modu: `{mode}`", ephemeral=True)

@bot.tree.command(name="kbalbion", description="Killboard linklerini Albion'a geçirir.", guild=discord.Object(id=GUILD_ID))
async def kbalbion_cmd(interaction: discord.Interaction):
    await safe_defer(interaction, ephemeral=True)
    mode = _kb_set_link_mode("albion")
    try:
        bot._kb_link_mode = mode  # type: ignore
        bot._kb_persist_state()   # type: ignore
    except Exception:
        pass
    return await safe_send(interaction, f"✅ Killboard link modu: `{mode}`", ephemeral=True)

@bot.tree.command(name="killboardtest", description="Killboard/Deathboard kanallarına test mesajı basar.", guild=discord.Object(id=GUILD_ID))
async def killboardtest_cmd(interaction: discord.Interaction):
    """
    Not: Slash command'larda 3 saniye içinde ACK şart. Bot yoğunken defer/response geç kalabiliyor.
    Bu yüzden burada önce hızlı ACK yapıp asıl işi background task'e alıyoruz.
    """
    acked = False

    # HIZLI ACK: önce ephemeralle "başladı" mesajını bas.
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message("⏳ Test başlıyor… Killboard & Deathboard kanallarına 2 test mesajı basacağım.", ephemeral=True)
        else:
            await interaction.followup.send("⏳ Test başlıyor… Killboard & Deathboard kanallarına 2 test mesajı basacağım.", ephemeral=True)
        acked = True
    except Exception:
        acked = False

    # ACK başarısızsa (interaction expired) yine de kullanıcıya normal mesajla haber ver.
    if not acked:
        try:
            ch0 = interaction.channel
            if isinstance(ch0, (discord.TextChannel, discord.Thread)):
                await ch0.send(f"{interaction.user.mention} ⏳ `/killboardtest` başladı ama Discord etkileşimi zaman aşımına uğramış olabilir. Kanallara test mesajı basıyorum…")
        except Exception:
            pass

    async def _run_test():
        kill_ch = bot.get_channel(KILLBOARD_CHANNEL_ID)
        death_ch = bot.get_channel(DEATHBOARD_CHANNEL_ID)

        ok = True
        logo_path = _kb_find_guild_logo_path()

        # ---- Kill test ----
        try:
            if isinstance(kill_ch, discord.TextChannel):
                dummy = {
                    "EventId": 0,
                    "Location": "Test",
                    "TimeStamp": datetime.now(UTC_TZ).strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
                    "TotalVictimKillFame": 123456,
                    "BattleId": 0,
                    "Killer": {
                        "Name": "Tester",
                        "GuildId": AO_GUILD_ID,
                        "GuildName": "CALLIDUS",
                        "AverageItemPower": 1200,
                        "Equipment": {
                            "MainHand": {"Type": "T6_2H_AXE", "EnchantmentLevel": 1, "Quality": 3},
                            "Head": {"Type": "T6_HEAD_LEATHER_SET1", "EnchantmentLevel": 0, "Quality": 1},
                        },
                    },
                    "Victim": {
                        "Name": "Dummy",
                        "GuildId": "X",
                        "GuildName": "ENEMY",
                        "AverageItemPower": 1100,
                        "Equipment": {"Armor": {"Type": "T6_ARMOR_LEATHER_SET1", "EnchantmentLevel": 0, "Quality": 1}},
                        "Inventory": [],
                    },
                    # destekleyici alanlar (opsiyonel)
                    "Participants": [],
                    "GroupMembers": [],
                }
                emb = _kb_build_embed(dummy, "kill")
                img = await _kb_make_image(bot, dummy, "kill", include_inventory=False)
                view = KillbotLinks(kill_url=_kb_killboard_url(0))
                files: List[discord.File] = []

                if logo_path and os.path.isfile(logo_path):
                    files.append(discord.File(logo_path, filename="guild.png"))
                    emb.set_thumbnail(url="attachment://guild.png")
                    emb.set_author(name="CALLIDUS", icon_url="attachment://guild.png")

                if img:
                    files.append(discord.File(fp=io.BytesIO(img), filename="kill_test.png"))
                    emb.set_image(url="attachment://kill_test.png")

                if files:
                    await kill_ch.send(embed=emb, files=files, view=view)
                else:
                    await kill_ch.send(embed=emb, view=view)
            else:
                ok = False
        except Exception as e:
            ok = False
            log("killbottest kill send error:", repr(e))

        # ---- Death test ----
        try:
            if isinstance(death_ch, discord.TextChannel):
                dummy2 = {
                    "EventId": 0,
                    "Location": "Test",
                    "TimeStamp": datetime.now(UTC_TZ).strftime("%Y-%m-%dT%H:%M:%S.000000Z"),
                    "TotalVictimKillFame": 234567,
                    "BattleId": 0,
                    "Killer": {"Name": "Tester", "GuildId": "X", "GuildName": "ENEMY", "AverageItemPower": 1200, "Equipment": {}},
                    "Victim": {
                        "Name": "Dummy",
                        "GuildId": AO_GUILD_ID,
                        "GuildName": "CALLIDUS",
                        "AverageItemPower": 1150,
                        "Equipment": {
                            "MainHand": {"Type": "T6_2H_BOW", "EnchantmentLevel": 0, "Quality": 1},
                            "Armor": {"Type": "T6_ARMOR_CLOTH_SET1", "EnchantmentLevel": 0, "Quality": 1},
                        },
                        "Inventory": [
                            {"Type": "T4_BAG", "Count": 1, "Quality": 1, "EnchantmentLevel": 0},
                            {"Type": "T5_POTION_HEAL", "Count": 3, "Quality": 1, "EnchantmentLevel": 0},
                        ],
                    },
                    "Participants": [],
                    "GroupMembers": [],
                }
                emb2 = _kb_build_embed(dummy2, "death")
                img2 = await _kb_make_image(bot, dummy2, "death", include_inventory=False)
                view2 = KillbotLinks(kill_url=_kb_killboard_url(0))
                files2: List[discord.File] = []

                if logo_path and os.path.isfile(logo_path):
                    files2.append(discord.File(logo_path, filename="guild.png"))
                    emb2.set_thumbnail(url="attachment://guild.png")
                    emb2.set_author(name="CALLIDUS", icon_url="attachment://guild.png")

                if img2:
                    files2.append(discord.File(fp=io.BytesIO(img2), filename="death_test.png"))
                    emb2.set_image(url="attachment://death_test.png")

                if files2:
                    await death_ch.send(embed=emb2, files=files2, view=view2)
                else:
                    await death_ch.send(embed=emb2, view=view2)
            else:
                ok = False
        except Exception as e:
            ok = False
            log("killbottest death send error:", repr(e))

        final_msg = "✅ Test mesajı basıldı. Kanalları kontrol et." if ok else "❌ Testte sorun var. Bot loguna bak."

        # Kullanıcıya geri bildirim
        if acked:
            try:
                # İlk ephemerali editlemek daha temiz
                await interaction.edit_original_response(content=final_msg)
            except Exception:
                try:
                    await interaction.followup.send(final_msg, ephemeral=True)
                except Exception:
                    pass
        else:
            try:
                ch0 = interaction.channel
                if isinstance(ch0, (discord.TextChannel, discord.Thread)):
                    await ch0.send(f"{interaction.user.mention} {final_msg}")
            except Exception:
                pass

    # Background task
    try:
        asyncio.create_task(_run_test())
    except Exception:
        # create_task fail olmaz normalde ama "olur da" diye:
        await safe_send(interaction, "❌ Test task oluşturulamadı. Bot loguna bak.", ephemeral=True)


# =========================================================
#            KILLBOARD YÖNETİM KOMUTLARI (İYİLEŞTİRİLMİŞ)
# =========================================================

@bot.tree.command(name="killboard-ayar", description="Killboard ayarlarını gösterir ve düzenler.", guild=discord.Object(id=GUILD_ID))
@app_commands.default_permissions(administrator=True)
@app_commands.describe(
    killboard_kanal="Killboard kanalı",
    deathboard_kanal="Deathboard kanalı",
    killboard_aktif="Killboard açık/kapalı",
    deathboard_aktif="Deathboard açık/kapalı",
    max_event_saat="Max event yaşı (saat)"
)
@app_commands.choices(
    killboard_aktif=[
        app_commands.Choice(name="Açık", value="on"),
        app_commands.Choice(name="Kapalı", value="off"),
        app_commands.Choice(name="Değiştirme", value="keep"),
    ],
    deathboard_aktif=[
        app_commands.Choice(name="Açık", value="on"),
        app_commands.Choice(name="Kapalı", value="off"),
        app_commands.Choice(name="Değiştirme", value="keep"),
    ]
)
async def killboard_ayar_cmd(
    interaction: discord.Interaction, 
    killboard_kanal: Optional[discord.TextChannel] = None,
    deathboard_kanal: Optional[discord.TextChannel] = None,
    killboard_aktif: str = "keep",
    deathboard_aktif: str = "keep",
    max_event_saat: Optional[int] = None
):
    await safe_defer(interaction, ephemeral=True)
    
    global KILLBOARD_CHANNEL_ID, DEATHBOARD_CHANNEL_ID, KILLBOT_MAX_EVENT_AGE_HOURS
    
    changes = []
    
    if killboard_kanal:
        KILLBOARD_CHANNEL_ID = killboard_kanal.id
        changes.append(f"🎯 Killboard: {killboard_kanal.mention}")
    
    if deathboard_kanal:
        DEATHBOARD_CHANNEL_ID = deathboard_kanal.id
        changes.append(f"💀 Deathboard: {deathboard_kanal.mention}")
    
    if max_event_saat is not None and max_event_saat > 0:
        KILLBOT_MAX_EVENT_AGE_HOURS = max_event_saat
        changes.append(f"⏰ Max yaş: `{max_event_saat}` saat")
    
    if killboard_aktif == "off":
        KILLBOARD_CHANNEL_ID = 0
        changes.append("🎯 Killboard: **Kapalı**")
    
    if deathboard_aktif == "off":
        DEATHBOARD_CHANNEL_ID = 0
        changes.append("💀 Deathboard: **Kapalı**")
    
    if changes:
        result = "**Güncellendi:**\n" + "\n".join(changes)
    else:
        result = f"""**Killboard Ayarları:**
🎯 Killboard: {f'<#{KILLBOARD_CHANNEL_ID}>' if KILLBOARD_CHANNEL_ID else 'Kapalı'}
💀 Deathboard: {f'<#{DEATHBOARD_CHANNEL_ID}>' if DEATHBOARD_CHANNEL_ID else 'Kapalı'}
⏰ Max yaş: `{KILLBOT_MAX_EVENT_AGE_HOURS}` saat
⚙️ Mode: `{KILLBOT_KILL_MODE}`"""
    
    await safe_send(interaction, result, ephemeral=True)


@bot.tree.command(name="killboard-sync", description="Mevcut eventleri senkronize eder.", guild=discord.Object(id=GUILD_ID))
@app_commands.default_permissions(administrator=True)
async def killboard_sync_cmd(interaction: discord.Interaction):
    await safe_defer(interaction, ephemeral=True)
    
    try:
        await bot._kb_auto_sync()
        bot._kb_persist_state()
        
        guild_eid = getattr(bot, "_kb_last_event_id", 0)
        death_count = len(getattr(bot, "_kb_seen_death_ids", set()))
        kill_count = len(getattr(bot, "_kb_seen_kill_ids", set()))
        
        await safe_send(interaction, f"✅ Senkronize edildi.\n• EventId: `{guild_eid}`\n• Deaths: `{death_count}`\n• Kills: `{kill_count}`", ephemeral=True)
        log(f"[KB-SYNC] {interaction.user.name} tarafından senkronize edildi")
        
    except Exception as e:
        await safe_send(interaction, f"❌ Hata: {e}", ephemeral=True)


@bot.tree.command(name="killboard-reset", description="Killboard state'ini sıfırlar.", guild=discord.Object(id=GUILD_ID))
@app_commands.default_permissions(administrator=True)
@app_commands.describe(onay="Sıfırlamak için 'EVET' yaz")
async def killboard_reset_cmd(interaction: discord.Interaction, onay: str):
    await safe_defer(interaction, ephemeral=True)
    
    if onay.upper() != "EVET":
        return await safe_send(interaction, "⚠️ Sıfırlamak için `onay` parametresine `EVET` yaz.", ephemeral=True)
    
    try:
        bot._kb_last_event_id = 0
        bot._kb_seen_kill_ids = set()
        bot._kb_seen_death_ids = set()
        
        _kb_save_state({
            "guild_last_event_id": 0,
            "member_seen_kill_ids": [],
            "member_seen_death_ids": [],
            "link_mode": getattr(bot, "_kb_link_mode", _KB_LINK_MODE) or _KB_LINK_MODE,
        })
        
        await safe_send(interaction, "✅ Killboard state sıfırlandı.", ephemeral=True)
        log(f"[KB-RESET] {interaction.user.name} tarafından state sıfırlandı")
        
    except Exception as e:
        await safe_send(interaction, f"❌ Hata: {e}", ephemeral=True)


@bot.tree.command(name="killboard-debug", description="Killboard debug bilgisi.", guild=discord.Object(id=GUILD_ID))
@app_commands.default_permissions(administrator=True)
async def killboard_debug_cmd(interaction: discord.Interaction):
    await safe_defer(interaction, ephemeral=True)
    
    try:
        mem_guild_eid = getattr(bot, "_kb_last_event_id", 0)
        mem_seen_kills = len(getattr(bot, "_kb_seen_kill_ids", set()))
        mem_seen_deaths = len(getattr(bot, "_kb_seen_death_ids", set()))
        mem_members = len(getattr(bot, "_kb_member_ids", []))
        
        # API kontrolü
        api_latest = 0
        sample_events = []
        
        try:
            url = f"{AO_API_BASE}/events?guildId={AO_GUILD_ID}&limit=5&offset=0"
            events = await bot._kb_get_json(url)
            if isinstance(events, list):
                for ev in events:
                    try:
                        eid = int(ev.get("EventId") or 0)
                        if eid > api_latest:
                            api_latest = eid
                        age_str = _kb_format_event_age(ev)
                        is_old = _kb_is_event_too_old(ev, KILLBOT_MAX_EVENT_AGE_HOURS)
                        sample_events.append(f"• `{eid}`: {age_str} {'⛔' if is_old else '✅'}")
                    except:
                        pass
        except:
            pass
        
        result = f"""**Killboard Debug**

**State:**
• EventId: `{mem_guild_eid}`
• Kills: `{mem_seen_kills}` | Deaths: `{mem_seen_deaths}`
• Members: `{mem_members}`

**API:** (son 5 event)
{chr(10).join(sample_events[:5]) if sample_events else 'Veri yok'}

**Filtre:** `{KILLBOT_MAX_EVENT_AGE_HOURS}` saatten eski = ⛔ atlanır"""
        
        await safe_send(interaction, result, ephemeral=True)
        
    except Exception as e:
        await safe_send(interaction, f"❌ Hata: {e}", ephemeral=True)


# =========================================================
#                 ACHIEVEMENT COMMANDS
# =========================================================

async def _search_albion_player(bot_client, name: str):
    """Search Albion API for player. Returns (player_id, player_name) or None."""
    try:
        url = f"{AO_API_BASE}/search?q={name}"
        data = await bot_client._kb_get_json(url)
        if isinstance(data, dict):
            players = data.get("players") or []
            if players and isinstance(players, list):
                for p in players:
                    if isinstance(p, dict):
                        pid = p.get("Id") or p.get("id") or ""
                        pname = p.get("Name") or p.get("name") or ""
                        if pid and pname:
                            if pname.lower() == name.lower():
                                return (str(pid).strip(), str(pname).strip())
                if players:
                    p = players[0]
                    pid = p.get("Id") or p.get("id") or ""
                    pname = p.get("Name") or p.get("name") or ""
                    if pid and pname:
                        return (str(pid).strip(), str(pname).strip())
    except Exception as e:
        log("albion search error:", repr(e))
    return None

# =========================================================
#              PLAYER LINK COMMANDS (Bağlama Sistemi)
# =========================================================
if PLAYER_LINK_OK:
    MEMBER_ROLE_ID = 1419663333874729121  # Member rolü
    
    @bot.tree.command(name="bagla", description="Discord-Albion bağlantısı kurar (Yetkili).", guild=discord.Object(id=GUILD_ID))
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(albion_nick="Albion oyuncu adı", kisi="Bağlanacak Discord kullanıcısı (boş = kendin)")
    async def bagla_cmd(interaction: discord.Interaction, albion_nick: str, kisi: Optional[discord.Member] = None):
        await safe_defer(interaction, ephemeral=True)
        target = kisi or interaction.user
        albion_nick = (albion_nick or "").strip()
        if not albion_nick:
            return await safe_send(interaction, "❌ Albion nick boş olamaz.", ephemeral=True)
        result = await _search_albion_player(bot, albion_nick)
        if not result:
            return await safe_send(interaction, f"❌ Albion'da `{albion_nick}` bulunamadı.", ephemeral=True)
        player_id, player_name = result
        try:
            link_player(discord_id=target.id, albion_name=player_name, albion_id=player_id, linked_by=interaction.user.id)
            # Member rolü ver
            role_msg = ""
            try:
                member_role = interaction.guild.get_role(MEMBER_ROLE_ID)
                if member_role and isinstance(target, discord.Member):
                    await target.add_roles(member_role, reason="Albion hesabı bağlandı")
                    role_msg = f"\n🎭 **Member** rolü verildi."
            except Exception as e:
                role_msg = f"\n⚠️ Rol verilemedi: {e}"
            return await safe_send(interaction, f"✅ {target.mention} artık **{player_name}** ile bağlı.\n🆔 Albion ID: `{player_id}`{role_msg}", ephemeral=True)
        except Exception as e:
            return await safe_send(interaction, f"❌ Bağlama hatası: {e}", ephemeral=True)

    @bot.tree.command(name="baglantim", description="Bağlı Albion hesabını gösterir.", guild=discord.Object(id=GUILD_ID))
    @app_commands.describe(kisi="Kontrol edilecek kişi (boş = kendin)")
    async def baglantim_cmd(interaction: discord.Interaction, kisi: Optional[discord.Member] = None):
        await safe_defer(interaction, ephemeral=True)
        target = kisi or interaction.user
        link = get_link_by_discord(target.id)
        if not link:
            msg = "❌ Henüz bir Albion hesabına bağlı değilsin." if target.id == interaction.user.id else f"❌ {target.mention} henüz bağlı değil."
            return await safe_send(interaction, msg, ephemeral=True)
        embed = discord.Embed(title="🔗 Hesap Bağlantısı", color=discord.Color.green())
        embed.add_field(name="Discord", value=target.mention, inline=True)
        embed.add_field(name="Albion", value=f"**{link.albion_name}**", inline=True)
        embed.add_field(name="Albion ID", value=f"`{link.albion_id}`", inline=False)
        return await safe_send(interaction, "", embed=embed, ephemeral=True)

    @bot.tree.command(name="baglantikal", description="Albion bağlantısını kaldırır (Yetkili).", guild=discord.Object(id=GUILD_ID))
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(kisi="Bağlantısı kaldırılacak kişi")
    async def baglantikal_cmd(interaction: discord.Interaction, kisi: discord.Member):
        await safe_defer(interaction, ephemeral=True)
        link = get_link_by_discord(kisi.id)
        if not link:
            return await safe_send(interaction, f"❌ {kisi.mention} zaten bağlı değil.", ephemeral=True)
        old_name = link.albion_name
        unlink_player(kisi.id)
        # Member rolünü kaldır
        role_msg = ""
        try:
            member_role = interaction.guild.get_role(MEMBER_ROLE_ID)
            if member_role and isinstance(kisi, discord.Member) and member_role in kisi.roles:
                await kisi.remove_roles(member_role, reason="Albion hesabı bağlantısı kaldırıldı")
                role_msg = f"\n🎭 **Member** rolü kaldırıldı."
        except Exception as e:
            role_msg = f"\n⚠️ Rol kaldırılamadı: {e}"
        return await safe_send(interaction, f"✅ {kisi.mention} artık **{old_name}** ile bağlı değil.{role_msg}", ephemeral=True)

    @bot.tree.command(name="basarimlarim", description="Başarımlarını gösterir (DM).", guild=discord.Object(id=GUILD_ID))
    async def basarimlarim_cmd(interaction: discord.Interaction):
        await safe_defer(interaction, ephemeral=True)
        embed = build_achievements_embed(interaction.user.id, interaction.user)
        try:
            await interaction.user.send(embed=embed)
            return await safe_send(interaction, "✅ Başarımların DM olarak gönderildi.", ephemeral=True)
        except Exception:
            return await safe_send(interaction, "", embed=embed, ephemeral=True)

    @bot.tree.command(name="basarimlar", description="Bir kişinin başarımlarını gösterir.", guild=discord.Object(id=GUILD_ID))
    @app_commands.describe(kisi="Başarımları gösterilecek kişi")
    async def basarimlar_cmd(interaction: discord.Interaction, kisi: discord.Member):
        await safe_defer(interaction, ephemeral=False)
        embed = build_achievements_embed(kisi.id, kisi)
        return await safe_send(interaction, "", embed=embed, ephemeral=False)

    @bot.tree.command(name="istatistik", description="İstatistikleri gösterir.", guild=discord.Object(id=GUILD_ID))
    @app_commands.describe(kisi="İstatistikleri gösterilecek kişi (boş = kendin)")
    async def istatistik_cmd(interaction: discord.Interaction, kisi: Optional[discord.Member] = None):
        await safe_defer(interaction, ephemeral=True)
        target = kisi or interaction.user
        embed = build_stats_embed(target.id, target)
        return await safe_send(interaction, "", embed=embed, ephemeral=True)

    @bot.tree.command(name="leaderboard", description="Başarım sıralamasını gösterir.", guild=discord.Object(id=GUILD_ID))
    async def leaderboard_cmd(interaction: discord.Interaction):
        await safe_defer(interaction, ephemeral=False)
        embed = build_leaderboard_embed(bot)
        return await safe_send(interaction, "", embed=embed, ephemeral=False)



# Slash: /bbtest <n>
@bot.tree.command(name="bbtest", description="Son savaşlardan seçip battleboard kanalına atar.", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(n="1=son battle, 2=sondan bir önceki, 3=sondan iki önceki ...")
async def bbtest_cmd(interaction: discord.Interaction, n: int = 1):
    await interaction.response.defer(ephemeral=True)
    try:
        # n is 1-based: 1=latest, 2=previous, ...
        battle_id = await _bb_pick_battle_id(n)
        if not battle_id:
            await interaction.followup.send("❌ Battle bulunamadı.", ephemeral=True)
            return
        ok = await _bb_post_battleboard(interaction.client, battle_id)
        if ok:
            await interaction.followup.send(f"✅ Battleboard gönderildi. (battleId={battle_id})", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ Bu battle CALLIDUS için yeterince büyük değil (min {MIN_CALLIDUS_PLAYERS} oyuncu).", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Hata: {repr(e)}", ephemeral=True)

# =========================
# Battleboard helpers (py3.8 safe)
# =========================
def _bb_load_state() -> Dict[str, Any]:
    try:
        with open(BATTLEBOARD_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _bb_save_state(state: Dict[str, Any]) -> None:
    try:
        with open(BATTLEBOARD_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _bb_fmt_k(n: int) -> str:
    try:
        n = int(n)
    except Exception:
        return str(n)
    if n >= 1_000_000_000:
        s = f"{n/1_000_000_000:.1f}b"
    elif n >= 1_000_000:
        s = f"{n/1_000_000:.1f}m"
    elif n >= 1_000:
        s = f"{n/1_000:.0f}k"
    else:
        s = str(n)
    return s.replace(".0", "")

def _albionbb_battle_link(battle_id: int) -> str:
    return f"{ALBIONBB_BASE}/battles/{int(battle_id)}"

async def _ao_get_json(session: aiohttp.ClientSession, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Any]:
    try:
        async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            return await resp.json()
    except Exception:
        return None

async def _ao_fetch_recent_guild_battles(session: aiohttp.ClientSession, limit: int = 25) -> List[Dict[str, Any]]:
    # Uses official AO API list endpoint (stable).
    params = {
        "range": "day",
        "sort": "recent",
        "offset": 0,
        "limit": limit,
        "guildId": AO_GUILD_ID,
    }
    data = await _ao_get_json(session, f"{AO_API_BASE}/battles", params=params)
    return data if isinstance(data, list) else []

async def _ao_fetch_battle_detail(session: aiohttp.ClientSession, battle_id: int) -> Optional[Dict[str, Any]]:
    return await _ao_get_json(session, f"{AO_API_BASE}/battles/{int(battle_id)}")

def _bb_rows_from_ao_detail(detail: Dict[str, Any]) -> List[Dict[str, Any]]:
    guilds = detail.get("guilds") or {}
    players = detail.get("players") or {}

    counts: Dict[str, int] = {}
    for p in players.values():
        gid = (p.get("guildId") or "").strip()
        if gid:
            counts[gid] = counts.get(gid, 0) + 1

    rows: List[Dict[str, Any]] = []
    for gid, g in guilds.items():
        rows.append({
            "id": gid,
            "name": g.get("name") or "Unknown",
            "alliance": g.get("alliance") or "",
            "players": int(counts.get(gid, 0)),
            "kills": int(g.get("kills") or 0),
            "deaths": int(g.get("deaths") or 0),
            "fame": int(g.get("killFame") or 0),
        })
    rows.sort(key=lambda r: (r["fame"], r["kills"]), reverse=True)
    return rows

def _bb_make_table(rows: List[Dict[str, Any]], top_n: int = 10) -> str:
    # AlbionBB-like columns: Guild | Alliance | Players | Kills | Deaths | Fame
    rows = rows[:top_n]
    gw = min(20, max(5, max((len(r["name"]) for r in rows), default=5)))
    aw = min(10, max(7, max((len((r.get("alliance") or "")) for r in rows), default=7)))
    header = f'{"Guild":<{gw}}  {"Alliance":<{aw}}  {"Players":>7}  {"Kills":>5}  {"Deaths":>6}  {"Fame":>6}'
    lines = [header]
    for r in rows:
        g = r["name"]
        if len(g) > gw:
            g = g[:gw-1] + "…"
        a = (r.get("alliance") or "")
        if len(a) > aw:
            a = a[:aw-1] + "…"
        lines.append(f'{g:<{gw}}  {a:<{aw}}  {r["players"]:>7}  {r["kills"]:>5}  {r["deaths"]:>6}  {_bb_fmt_k(r["fame"]):>6}')
    return "```" + "\n".join(lines) + "```"

async def _bb_post_battle(interaction_or_client: Any, battle_detail: Dict[str, Any]) -> None:
    # interaction_or_client: discord.Interaction or discord.Client
    client = getattr(interaction_or_client, "client", interaction_or_client)
    ch = client.get_channel(BATTLEBOARD_CHANNEL_ID)
    if ch is None:
        return

    battle_id = int(battle_detail.get("id") or 0)
    rows = _bb_rows_from_ao_detail(battle_detail)

    embed = discord.Embed(
        title=f"Battle #{battle_id}",
        description=_bb_make_table(rows, top_n=10),
    )
    embed.add_field(
        name="Toplam",
        value=f'Fame: **{_bb_fmt_k(int(battle_detail.get("totalFame") or 0))}** | Öldürme: **{int(battle_detail.get("totalKills") or 0)}**',
        inline=False,
    )
    embed.add_field(name="AlbionBB", value=_albionbb_battle_link(battle_id), inline=False)

    await ch.send(embed=embed)

async def _battleboard_worker(bot: discord.Client) -> None:
    await bot.wait_until_ready()
    state = _bb_load_state()
    last_posted = int(state.get("last_posted_battle_id") or 0)

    headers = {"User-Agent": "CALLIDUS-DiscordBot/1.0"}
    async with aiohttp.ClientSession(headers=headers) as session:
        while not bot.is_closed():
            try:
                battles = await _ao_fetch_recent_guild_battles(session, limit=30)
                # process oldest -> newest for stable posting
                for b in reversed(battles):
                    bid = int(b.get("id") or b.get("Id") or 0)
                    if bid <= 0 or bid <= last_posted:
                        continue

                    detail = await _ao_fetch_battle_detail(session, bid)
                    if not detail:
                        continue

                    # Filters
                    total_fame = int(detail.get("totalFame") or 0)
                    if total_fame < BATTLEBOARD_MIN_TOTAL_FAME:
                        continue

                    # guild players count
                    my_players = 0
                    for p in (detail.get("players") or {}).values():
                        if (p.get("guildId") or "") == AO_GUILD_ID:
                            my_players += 1
                    if my_players < BATTLEBOARD_MIN_GUILD_PLAYERS:
                        continue

                    await _bb_post_battle(bot, detail)

                    last_posted = bid
                    state["last_posted_battle_id"] = last_posted
                    _bb_save_state(state)

            except Exception as e:
                print(f"[BOT] [BB] worker error: {repr(e)}")

            await asyncio.sleep(BATTLEBOARD_POLL_SECONDS)

    if n < 1:
        n = 1

    headers = {"User-Agent": "CALLIDUS-DiscordBot/1.0"}
    async with aiohttp.ClientSession(headers=headers) as session:
        battles = await _ao_fetch_recent_guild_battles(session, limit=max(10, n + 5))
        if not battles or n > len(battles):
            await interaction.followup.send("❌ Bu aralıkta battle yok.", ephemeral=True)
            return

        bid = int(battles[n-1].get("id") or 0)
        detail = await _ao_fetch_battle_detail(session, bid)
        if not detail:
            await interaction.followup.send(f"❌ Bu battle CALLIDUS için yeterince büyük değil (min {MIN_CALLIDUS_PLAYERS} oyuncu).", ephemeral=True)
            return

        await _bb_post_battle(interaction, detail)

    await interaction.followup.send(f"✅ Battleboard gönderildi. (battleId={bid})", ephemeral=True)


# =========================================================
#                    MUSIC SYSTEM COMMANDS
# =========================================================

# Varsayılan ses seviyesi (%25)
MUSIC_DEFAULT_VOLUME = 0.25

# YT-DLP ve FFmpeg ayarları
# Cookie dosyası varsa kullan (YouTube bot koruması için)
import os as _os
_COOKIE_FILE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'cookies.txt')
_COOKIE_EXISTS = _os.path.exists(_COOKIE_FILE)
if _COOKIE_EXISTS:
    print(f"[MUSIC] Cookie dosyası bulundu: {_COOKIE_FILE}")
else:
    print(f"[MUSIC] Cookie dosyası bulunamadı: {_COOKIE_FILE} - YouTube bot korumasına takılabilir!")

YTDL_OPTIONS = {
    'format': 'bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,  # Tek şarkı için
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch',
    'source_address': '0.0.0.0',
    'prefer_ffmpeg': True,
    'keepvideo': False,
    'cookiefile': _COOKIE_FILE if _COOKIE_EXISTS else None,
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    },
}

# Playlist için ayrı ayarlar
YTDL_PLAYLIST_OPTIONS = {
    'format': 'bestaudio/best',
    'extractaudio': True,
    'audioformat': 'mp3',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,  # Playlist'leri işle
    'nocheckcertificate': True,
    'ignoreerrors': True,  # Hatalı şarkıları atla
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'source_address': '0.0.0.0',
    'extract_flat': True,  # Hızlı playlist tarama
    'playlistend': 100,  # Max 100 şarkı
    'cookiefile': _COOKIE_FILE if _COOKIE_EXISTS else None,
    'http_headers': {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
    },
}

FFMPEG_OPTIONS = {
    'before_options': '-nostdin -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -ss 0',
    'options': '-vn',
}

# Müzik boşta kalma ayarları
MUSIC_IDLE_TIMEOUT = 600  # 10 dakika (saniye)
MUSIC_IDLE_CHANNEL_ID = 1431235375422115942  # Ayrılma mesajı gönderilecek kanal

def _music_log(msg: str) -> None:
    try:
        print("[MUSIC]", msg)
    except Exception:
        pass

async def _music_search(query: str) -> Optional[Dict[str, Any]]:
    """YouTube, Dailymotion ve diğer desteklenen sitelerden şarkı arar."""
    if not YTDLP_OK:
        return None
    
    _music_log(f"Müzik arama başladı: {query[:80]}...")
    
    # URL mi kontrol et (YouTube, Dailymotion, SoundCloud vs.)
    is_url = query.startswith(('http://', 'https://'))
    
    try:
        loop = asyncio.get_event_loop()
        
        def _extract():
            # URL için default_search kullanma
            opts = YTDL_OPTIONS.copy()
            if is_url:
                opts.pop('default_search', None)  # URL için arama yapma
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                if is_url:
                    # Direkt URL - yt-dlp otomatik tanır (YouTube, Dailymotion, SoundCloud vs.)
                    _music_log(f"URL olarak işleniyor: {query}")
                    info = ydl.extract_info(query, download=False)
                else:
                    # Arama - YouTube'da ara
                    info = ydl.extract_info(f"ytsearch:{query}", download=False)
                    if info and 'entries' in info and info['entries']:
                        info = info['entries'][0]
                return info
        
        info = await loop.run_in_executor(None, _extract)
        
        if info:
            _music_log(f"Info keys: {list(info.keys())[:10]}")
            _music_log(f"Extractor: {info.get('extractor', 'bilinmiyor')}")
            _music_log(f"info['url'] var mı: {bool(info.get('url'))}")
            _music_log(f"formats sayısı: {len(info.get('formats', []))}")
            
            # Stream URL'sini bul
            stream_url = info.get('url')  # Önce direkt URL'yi dene
            
            # Eğer yoksa formats içinden al
            if not stream_url:
                formats = info.get('formats', [])
                # Audio formatlarını filtrele ve en iyisini al
                audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']
                if audio_formats:
                    # En yüksek bitrate'i al
                    audio_formats.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)
                    stream_url = audio_formats[0].get('url')
                    _music_log(f"Audio format seçildi: {audio_formats[0].get('format_id')}")
                elif formats:
                    # Audio-only yoksa herhangi birini al (video+audio)
                    for f in reversed(formats):
                        if f.get('url'):
                            stream_url = f.get('url')
                            _music_log(f"Fallback format seçildi: {f.get('format_id')}")
                            break
            
            source = info.get('extractor', 'Bilinmiyor')
            _music_log(f"Bulundu [{source}]: {info.get('title')} | URL var: {bool(stream_url)}")
            
            if not stream_url:
                _music_log("UYARI: Stream URL bulunamadı!")
                return None
            
            return {
                'title': info.get('title', 'Bilinmeyen'),
                'url': stream_url,
                'webpage_url': info.get('webpage_url', query if is_url else ''),
                'duration': info.get('duration', 0),
                'thumbnail': info.get('thumbnail', ''),
                'uploader': info.get('uploader', 'Bilinmeyen'),
                'source': source,  # YouTube, Dailymotion, SoundCloud vs.
            }
        else:
            _music_log("Info None döndü")
    except Exception as e:
        _music_log(f"Arama hatası: {repr(e)}")
    return None

# Eski fonksiyon adı için alias (geriye uyumluluk)
_music_search_youtube = _music_search

def _format_duration(seconds: int) -> str:
    """Saniyeyi mm:ss formatına çevirir."""
    if not seconds:
        return "0:00"
    mins, secs = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    if hours:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"

async def _music_extract_playlist(url: str, max_songs: int = 50) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """Playlist'ten şarkıları çıkarır. Returns (playlist_title, songs_list)"""
    if not YTDLP_OK:
        _music_log("yt-dlp yüklü değil!")
        return None, []
    
    try:
        # YouTube Music URL'sini normal YouTube'a çevir
        original_url = url
        if 'music.youtube.com' in url:
            url = url.replace('music.youtube.com', 'www.youtube.com')
            _music_log(f"URL dönüştürüldü: {original_url} -> {url}")
        
        _music_log(f"Playlist çıkarılıyor: {url}")
        
        loop = asyncio.get_event_loop()
        
        opts = {
            'extract_flat': True,
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': True,
            'nocheckcertificate': True,
        }
        
        def _extract():
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    return ydl.extract_info(url, download=False)
            except Exception as e:
                _music_log(f"yt-dlp extract hatası: {repr(e)}")
                return None
        
        # Timeout ile çalıştır
        try:
            info = await asyncio.wait_for(
                loop.run_in_executor(None, _extract),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            _music_log("Playlist extraction timeout!")
            return None, []
        
        if not info:
            _music_log("Playlist info None döndü")
            return None, []
        
        playlist_title = info.get('title') or info.get('playlist_title') or 'Playlist'
        songs = []
        
        # Playlist mi yoksa tek şarkı mı?
        entries = info.get('entries')
        if not entries:
            _music_log("Entries boş, tek şarkı olabilir")
            video_id = info.get('id')
            if video_id:
                songs.append({
                    'title': info.get('title', 'Bilinmeyen'),
                    'url': None,
                    'webpage_url': f"https://www.youtube.com/watch?v={video_id}",
                    'duration': info.get('duration', 0) or 0,
                    'thumbnail': info.get('thumbnail', ''),
                    'uploader': info.get('uploader', 'Bilinmeyen'),
                })
            return playlist_title, songs
        
        # Playlist
        _music_log(f"Entries sayısı: {len(list(entries)) if entries else 0}")
        
        for entry in entries:
            if entry is None:
                continue
            if len(songs) >= max_songs:
                break
                
            video_id = entry.get('id') or entry.get('url')
            if not video_id:
                continue
            
            # video_id bazen tam URL olabiliyor
            if str(video_id).startswith('http'):
                webpage_url = video_id
            else:
                webpage_url = f"https://www.youtube.com/watch?v={video_id}"
            
            songs.append({
                'title': entry.get('title', 'Bilinmeyen'),
                'url': None,
                'webpage_url': webpage_url,
                'duration': entry.get('duration', 0) or 0,
                'thumbnail': entry.get('thumbnail', ''),
                'uploader': entry.get('uploader') or entry.get('channel', 'Bilinmeyen'),
            })
        
        _music_log(f"Playlist yüklendi: {playlist_title} ({len(songs)} şarkı)")
        return playlist_title, songs
        
    except Exception as e:
        _music_log(f"Playlist çıkarma hatası: {repr(e)}")
        return None, []

async def _music_idle_disconnect(bot: "CallidusBot", guild_id: int):
    """10 dakika bekleyip ses kanalından ayrılır ve mesaj atar."""
    try:
        await asyncio.sleep(MUSIC_IDLE_TIMEOUT)
        
        guild = bot.get_guild(guild_id)
        if not guild:
            return
        
        vc = guild.voice_client
        if not vc:
            return
        
        # Hâlâ boşta mı kontrol et
        if vc.is_playing() or vc.is_paused():
            return
        
        _music_log(f"10 dk boşta kaldı, ayrılıyor (guild={guild_id})")
        
        # Ayrıl
        await vc.disconnect()
        
        # Queue'yu temizle
        bot.music_queues[guild_id] = []
        bot.music_now_playing[guild_id] = None
        
        # Mesaj gönder
        channel = bot.get_channel(MUSIC_IDLE_CHANNEL_ID)
        if channel:
            try:
                await channel.send("🎵 Bir süredir şarkı çalmadığım için ses kanalından ayrıldım. Tekrar çalmak için `/cal` veya `/playlist` kullanabilirsin!")
            except Exception as e:
                _music_log(f"Idle mesaj gönderilemedi: {repr(e)}")
        
    except asyncio.CancelledError:
        _music_log(f"Idle timer iptal edildi (guild={guild_id})")
    except Exception as e:
        _music_log(f"Idle disconnect hatası: {repr(e)}")
    finally:
        # Task'ı temizle
        if guild_id in bot.music_idle_tasks:
            del bot.music_idle_tasks[guild_id]

def _music_start_idle_timer(bot: "CallidusBot", guild_id: int):
    """Boşta kalma timer'ını başlatır."""
    # Önceki timer varsa iptal et
    _music_cancel_idle_timer(bot, guild_id)
    
    # Yeni timer başlat
    task = asyncio.create_task(_music_idle_disconnect(bot, guild_id))
    bot.music_idle_tasks[guild_id] = task
    _music_log(f"Idle timer başlatıldı (guild={guild_id}, {MUSIC_IDLE_TIMEOUT}sn)")

def _music_cancel_idle_timer(bot: "CallidusBot", guild_id: int):
    """Boşta kalma timer'ını iptal eder."""
    if guild_id in bot.music_idle_tasks:
        bot.music_idle_tasks[guild_id].cancel()
        del bot.music_idle_tasks[guild_id]
        _music_log(f"Idle timer iptal edildi (guild={guild_id})")

async def _music_play_next(bot: "CallidusBot", guild_id: int):
    """Sıradaki şarkıyı çalar."""
    queue = bot.music_queues.get(guild_id, [])
    
    # Loop açıksa ve şu an çalan varsa, tekrar sıraya ekle
    if bot.music_loop.get(guild_id, False) and bot.music_now_playing.get(guild_id):
        queue.append(bot.music_now_playing[guild_id])
        bot.music_queues[guild_id] = queue
    
    if not queue:
        bot.music_now_playing[guild_id] = None
        # Queue boş, idle timer başlat
        _music_start_idle_timer(bot, guild_id)
        return
    
    # Şarkı çalacak, idle timer'ı iptal et
    _music_cancel_idle_timer(bot, guild_id)
    
    song = queue.pop(0)
    bot.music_queues[guild_id] = queue
    bot.music_now_playing[guild_id] = song
    
    guild = bot.get_guild(guild_id)
    if not guild or not guild.voice_client:
        return
    
    vc = guild.voice_client
    
    try:
        # Yeni URL al (süre dolmuş olabilir)
        search_query = song.get('webpage_url') or song.get('title')
        _music_log(f"Şarkı yükleniyor: {song.get('title')} | Query: {search_query}")
        
        fresh_info = await _music_search_youtube(search_query)
        
        if not fresh_info:
            _music_log(f"Şarkı bulunamadı, atlıyorum: {song.get('title')}")
            await _music_play_next(bot, guild_id)
            return
            
        if not fresh_info.get('url'):
            _music_log(f"URL bulunamadı, atlıyorum: {song.get('title')}")
            await _music_play_next(bot, guild_id)
            return
        
        _music_log(f"Çalınıyor: {fresh_info.get('title')} | URL uzunluğu: {len(fresh_info.get('url', ''))} | URL başı: {fresh_info.get('url', '')[:50]}...")
        
        source = discord.FFmpegPCMAudio(fresh_info['url'], **FFMPEG_OPTIONS)
        # Ses seviyesi kontrolü için PCMVolumeTransformer
        volume = bot.music_volume.get(guild_id, MUSIC_DEFAULT_VOLUME)
        source = discord.PCMVolumeTransformer(source, volume=volume)
        
        def after_playing(error):
            if error:
                _music_log(f"Oynatma hatası: {repr(error)}")
            # Sonraki şarkıya geç
            asyncio.run_coroutine_threadsafe(_music_play_next(bot, guild_id), bot.loop)
        
        vc.play(source, after=after_playing)
        _music_log(f"Çalıyor: {song.get('title')} (guild={guild_id}, volume={int(volume*100)}%)")
    except Exception as e:
        _music_log(f"Çalma hatası: {repr(e)}")
        # Hata olursa sonrakine geç
        await _music_play_next(bot, guild_id)

if YTDLP_OK:
    @bot.tree.command(name="katil", description="Ses kanalına katılır.", guild=discord.Object(id=GUILD_ID))
    async def music_join_cmd(interaction: discord.Interaction):
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.response.send_message("❌ Önce bir ses kanalına katılmalısın!", ephemeral=True)
        
        channel = interaction.user.voice.channel
        
        if interaction.guild.voice_client:
            if interaction.guild.voice_client.channel.id == channel.id:
                return await interaction.response.send_message("✅ Zaten bu kanaldayım!", ephemeral=True)
            await interaction.guild.voice_client.move_to(channel)
        else:
            try:
                await channel.connect()
            except TimeoutError:
                return await interaction.response.send_message("❌ Ses kanalına bağlanırken zaman aşımı oldu. Tekrar dene.", ephemeral=True)
            except Exception as e:
                return await interaction.response.send_message(f"❌ Ses kanalına bağlanamadım: {repr(e)}", ephemeral=True)
        
        await interaction.response.send_message(f"🎵 **{channel.name}** kanalına katıldım!")

    @bot.tree.command(name="ayril", description="Ses kanalından ayrılır.", guild=discord.Object(id=GUILD_ID))
    async def music_leave_cmd(interaction: discord.Interaction):
        if not interaction.guild.voice_client:
            return await interaction.response.send_message("❌ Herhangi bir ses kanalında değilim!", ephemeral=True)
        
        guild_id = interaction.guild.id
        
        # Idle timer'ı iptal et (manuel ayrılma)
        _music_cancel_idle_timer(bot, guild_id)
        
        bot.music_queues[guild_id] = []
        bot.music_now_playing[guild_id] = None
        
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("👋 Ses kanalından ayrıldım!")

    @bot.tree.command(name="cal", description="YouTube, Dailymotion, SoundCloud vb. sitelerden müzik çalar.", guild=discord.Object(id=GUILD_ID))
    @app_commands.describe(sorgu="Şarkı linki (YouTube, Dailymotion, SoundCloud vb.) veya şarkı adı")
    async def music_play_cmd(interaction: discord.Interaction, sorgu: str):
        await interaction.response.defer()
        
        # Ses kanalı kontrolü
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.followup.send("❌ Önce bir ses kanalına katılmalısın!")
        
        channel = interaction.user.voice.channel
        guild_id = interaction.guild.id
        
        # Kanala katıl
        if not interaction.guild.voice_client:
            try:
                await channel.connect()
            except TimeoutError:
                return await interaction.followup.send("❌ Ses kanalına bağlanırken zaman aşımı oldu. Tekrar dene.")
            except Exception as e:
                return await interaction.followup.send(f"❌ Ses kanalına bağlanamadım: {repr(e)}")
        elif interaction.guild.voice_client.channel.id != channel.id:
            await interaction.guild.voice_client.move_to(channel)
        
        # Varsayılan ses seviyesi ayarla (eğer daha önce ayarlanmadıysa)
        if guild_id not in bot.music_volume:
            bot.music_volume[guild_id] = MUSIC_DEFAULT_VOLUME
        
        # Şarkıyı ara
        song = await _music_search(sorgu)
        if not song:
            return await interaction.followup.send("❌ Şarkı bulunamadı!")
        
        song['requested_by'] = interaction.user.display_name
        
        # Queue'ya ekle
        if guild_id not in bot.music_queues:
            bot.music_queues[guild_id] = []
        
        vc = interaction.guild.voice_client
        current_volume = int(bot.music_volume.get(guild_id, MUSIC_DEFAULT_VOLUME) * 100)
        
        # Eğer şu an bir şey çalmıyorsa direkt başlat
        if not vc.is_playing() and not vc.is_paused():
            bot.music_queues[guild_id].append(song)
            await _music_play_next(bot, guild_id)
            
            embed = discord.Embed(
                title="🎵 Şimdi Çalıyor",
                description=f"**[{song['title']}]({song.get('webpage_url', '')})**",
                color=0x00ff00
            )
            embed.add_field(name="Süre", value=_format_duration(song.get('duration', 0)), inline=True)
            embed.add_field(name="İsteyen", value=song['requested_by'], inline=True)
            embed.add_field(name="🔊 Ses", value=f"%{current_volume}", inline=True)
            if song.get('thumbnail'):
                embed.set_thumbnail(url=song['thumbnail'])
            
            await interaction.followup.send(embed=embed)
        else:
            # Sıraya ekle
            bot.music_queues[guild_id].append(song)
            position = len(bot.music_queues[guild_id])
            
            embed = discord.Embed(
                title="📋 Sıraya Eklendi",
                description=f"**[{song['title']}]({song.get('webpage_url', '')})**",
                color=0x3498db
            )
            embed.add_field(name="Sıra", value=f"#{position}", inline=True)
            embed.add_field(name="Süre", value=_format_duration(song.get('duration', 0)), inline=True)
            if song.get('thumbnail'):
                embed.set_thumbnail(url=song['thumbnail'])
            
            await interaction.followup.send(embed=embed)

    @bot.tree.command(name="playlist", description="YouTube/YouTube Music playlist çalar.", guild=discord.Object(id=GUILD_ID))
    @app_commands.describe(url="YouTube veya YouTube Music playlist linki", karistir="Playlist'i karıştır (varsayılan: Hayır)")
    @app_commands.choices(karistir=[
        app_commands.Choice(name="Evet", value="yes"),
        app_commands.Choice(name="Hayır", value="no"),
    ])
    async def music_playlist_cmd(interaction: discord.Interaction, url: str, karistir: str = "no"):
        _music_log(f"Playlist komutu başladı: {url}")
        await interaction.response.defer()
        _music_log("Defer yapıldı")
        
        # URL kontrolü
        if not url.startswith(('http://', 'https://')):
            return await interaction.followup.send("❌ Geçerli bir playlist URL'si gir!\nÖrnek: `https://music.youtube.com/playlist?list=...` veya `https://www.youtube.com/playlist?list=...`")
        
        # Playlist URL'si mi kontrol et
        if 'list=' not in url:
            return await interaction.followup.send("❌ Bu bir playlist linki değil!\nPlaylist linki `list=` içermelidir.\nTek şarkı için `/cal` komutunu kullan.")
        
        # Ses kanalı kontrolü
        if not interaction.user.voice or not interaction.user.voice.channel:
            return await interaction.followup.send("❌ Önce bir ses kanalına katılmalısın!")
        
        channel = interaction.user.voice.channel
        guild_id = interaction.guild.id
        
        # Kanala katıl
        _music_log("Ses kanalına katılıyor...")
        if not interaction.guild.voice_client:
            try:
                await channel.connect()
            except TimeoutError:
                return await interaction.followup.send("❌ Ses kanalına bağlanırken zaman aşımı oldu. Tekrar dene.")
            except Exception as e:
                return await interaction.followup.send(f"❌ Ses kanalına bağlanamadım: {repr(e)}")
        elif interaction.guild.voice_client.channel.id != channel.id:
            await interaction.guild.voice_client.move_to(channel)
        _music_log("Ses kanalına katıldı")
        
        # Varsayılan ses seviyesi ayarla
        if guild_id not in bot.music_volume:
            bot.music_volume[guild_id] = MUSIC_DEFAULT_VOLUME
        
        # Playlist bilgisi yükleniyor mesajı
        _music_log("Loading embed gönderiliyor...")
        loading_embed = discord.Embed(
            title="⏳ Playlist Yükleniyor...",
            description="Şarkılar taranıyor, lütfen bekle...",
            color=0xffaa00
        )
        await interaction.followup.send(embed=loading_embed)
        _music_log("Loading embed gönderildi, playlist çıkarılıyor...")
        
        # Playlist'i çıkar (timeout ile)
        try:
            playlist_title, songs = await asyncio.wait_for(
                _music_extract_playlist(url, max_songs=100),
                timeout=60.0  # 60 saniye timeout
            )
            _music_log(f"Playlist çıkarıldı: {len(songs)} şarkı")
        except asyncio.TimeoutError:
            _music_log("Playlist timeout!")
            return await interaction.edit_original_response(embed=discord.Embed(
                title="❌ Zaman Aşımı",
                description="Playlist yüklenirken zaman aşımı oluştu. Daha küçük bir playlist dene.",
                color=0xff0000
            ))
        except Exception as e:
            _music_log(f"Playlist hatası: {repr(e)}")
            return await interaction.edit_original_response(embed=discord.Embed(
                title="❌ Hata",
                description=f"Playlist yüklenirken hata oluştu.\n```{str(e)[:100]}```",
                color=0xff0000
            ))
        
        if not songs:
            return await interaction.edit_original_response(embed=discord.Embed(
                title="❌ Playlist Bulunamadı",
                description="Playlist boş veya erişilemiyor.\n\n**Kontrol et:**\n• URL doğru mu?\n• Playlist public mi?\n• `list=` parametresi var mı?",
                color=0xff0000
            ))
        
        # Karıştır
        if karistir == "yes":
            import random
            random.shuffle(songs)
        
        # Şarkılara requested_by ekle
        for song in songs:
            song['requested_by'] = interaction.user.display_name
        
        # Queue'ya ekle
        if guild_id not in bot.music_queues:
            bot.music_queues[guild_id] = []
        
        vc = interaction.guild.voice_client
        was_playing = vc.is_playing() or vc.is_paused()
        
        # Tüm şarkıları sıraya ekle
        bot.music_queues[guild_id].extend(songs)
        
        # Toplam süre hesapla
        total_duration = sum(s.get('duration', 0) for s in songs)
        
        # Eğer şu an bir şey çalmıyorsa başlat
        if not was_playing:
            await _music_play_next(bot, guild_id)
        
        # Sonuç embed'i
        embed = discord.Embed(
            title="📋 Playlist Sıraya Eklendi" if was_playing else "🎵 Playlist Başlatıldı",
            description=f"**{playlist_title}**",
            color=0x00ff00
        )
        embed.add_field(name="Şarkı Sayısı", value=str(len(songs)), inline=True)
        embed.add_field(name="Toplam Süre", value=_format_duration(total_duration), inline=True)
        embed.add_field(name="Karıştırma", value="✅ Açık" if karistir == "yes" else "❌ Kapalı", inline=True)
        embed.add_field(name="İsteyen", value=interaction.user.display_name, inline=True)
        
        if songs and songs[0].get('thumbnail'):
            embed.set_thumbnail(url=songs[0]['thumbnail'])
        
        # İlk 5 şarkıyı göster
        preview = "\n".join([f"`{i+1}.` {s['title'][:40]}{'...' if len(s['title']) > 40 else ''}" for i, s in enumerate(songs[:5])])
        if len(songs) > 5:
            preview += f"\n*... ve {len(songs) - 5} şarkı daha*"
        embed.add_field(name="Şarkılar", value=preview, inline=False)
        
        await interaction.edit_original_response(embed=embed)

    @bot.tree.command(name="duraklat", description="Müziği duraklatır.", guild=discord.Object(id=GUILD_ID))
    async def music_pause_cmd(interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or not vc.is_playing():
            return await interaction.response.send_message("❌ Şu an çalan bir şey yok!", ephemeral=True)
        
        vc.pause()
        await interaction.response.send_message("⏸️ Müzik duraklatıldı.")

    @bot.tree.command(name="devam", description="Duraklatılmış müziği devam ettirir.", guild=discord.Object(id=GUILD_ID))
    async def music_resume_cmd(interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or not vc.is_paused():
            return await interaction.response.send_message("❌ Duraklatılmış bir şey yok!", ephemeral=True)
        
        vc.resume()
        await interaction.response.send_message("▶️ Müzik devam ediyor.")

    @bot.tree.command(name="durdur", description="Müziği durdurur ve sırayı temizler.", guild=discord.Object(id=GUILD_ID))
    async def music_stop_cmd(interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc:
            return await interaction.response.send_message("❌ Ses kanalında değilim!", ephemeral=True)
        
        guild_id = interaction.guild.id
        bot.music_queues[guild_id] = []
        bot.music_now_playing[guild_id] = None
        
        if vc.is_playing() or vc.is_paused():
            vc.stop()
        
        # Sıra temizlendi, idle timer başlat
        _music_start_idle_timer(bot, guild_id)
        
        await interaction.response.send_message("⏹️ Müzik durduruldu ve sıra temizlendi.")

    @bot.tree.command(name="atla", description="Şu anki şarkıyı atlar.", guild=discord.Object(id=GUILD_ID))
    async def music_skip_cmd(interaction: discord.Interaction):
        vc = interaction.guild.voice_client
        if not vc or not (vc.is_playing() or vc.is_paused()):
            return await interaction.response.send_message("❌ Atlanacak şarkı yok!", ephemeral=True)
        
        vc.stop()  # Bu otomatik olarak sonraki şarkıyı başlatacak (after callback)
        await interaction.response.send_message("⏭️ Şarkı atlandı.")

    @bot.tree.command(name="sira", description="Şarkı sırasını gösterir.", guild=discord.Object(id=GUILD_ID))
    async def music_queue_cmd(interaction: discord.Interaction):
        guild_id = interaction.guild.id
        queue = bot.music_queues.get(guild_id, [])
        now_playing = bot.music_now_playing.get(guild_id)
        
        if not now_playing and not queue:
            return await interaction.response.send_message("📋 Sıra boş!", ephemeral=True)
        
        embed = discord.Embed(title="🎵 Müzik Sırası", color=0x9b59b6)
        
        if now_playing:
            embed.add_field(
                name="▶️ Şimdi Çalıyor",
                value=f"**{now_playing['title']}** [{_format_duration(now_playing.get('duration', 0))}]",
                inline=False
            )
        
        if queue:
            queue_text = ""
            for i, song in enumerate(queue[:10], 1):
                queue_text += f"`{i}.` **{song['title']}** [{_format_duration(song.get('duration', 0))}]\n"
            
            if len(queue) > 10:
                queue_text += f"\n... ve {len(queue) - 10} şarkı daha"
            
            embed.add_field(name="📋 Sıradakiler", value=queue_text, inline=False)
        
        current_volume = int(bot.music_volume.get(guild_id, MUSIC_DEFAULT_VOLUME) * 100)
        loop_status = "🔁 Döngü: Açık" if bot.music_loop.get(guild_id, False) else "➡️ Döngü: Kapalı"
        embed.set_footer(text=f"{loop_status} | 🔊 Ses: %{current_volume}")
        
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="calan", description="Şu an çalan şarkıyı gösterir.", guild=discord.Object(id=GUILD_ID))
    async def music_nowplaying_cmd(interaction: discord.Interaction):
        guild_id = interaction.guild.id
        now_playing = bot.music_now_playing.get(guild_id)
        
        if not now_playing:
            return await interaction.response.send_message("❌ Şu an çalan bir şey yok!", ephemeral=True)
        
        current_volume = int(bot.music_volume.get(guild_id, MUSIC_DEFAULT_VOLUME) * 100)
        
        embed = discord.Embed(
            title="🎵 Şimdi Çalıyor",
            description=f"**[{now_playing['title']}]({now_playing.get('webpage_url', '')})**",
            color=0x1db954
        )
        embed.add_field(name="Süre", value=_format_duration(now_playing.get('duration', 0)), inline=True)
        embed.add_field(name="Kanal", value=now_playing.get('uploader', 'Bilinmeyen'), inline=True)
        embed.add_field(name="🔊 Ses", value=f"%{current_volume}", inline=True)
        if now_playing.get('requested_by'):
            embed.add_field(name="İsteyen", value=now_playing['requested_by'], inline=True)
        if now_playing.get('thumbnail'):
            embed.set_thumbnail(url=now_playing['thumbnail'])
        
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="dongu", description="Sıra döngüsünü açar/kapatır.", guild=discord.Object(id=GUILD_ID))
    async def music_loop_cmd(interaction: discord.Interaction):
        guild_id = interaction.guild.id
        current = bot.music_loop.get(guild_id, False)
        bot.music_loop[guild_id] = not current
        
        if bot.music_loop[guild_id]:
            await interaction.response.send_message("🔁 Döngü açıldı! Şarkılar tekrar edecek.")
        else:
            await interaction.response.send_message("➡️ Döngü kapatıldı.")

    @bot.tree.command(name="temizle", description="Sıradaki şarkıları temizler.", guild=discord.Object(id=GUILD_ID))
    async def music_clear_cmd(interaction: discord.Interaction):
        guild_id = interaction.guild.id
        count = len(bot.music_queues.get(guild_id, []))
        bot.music_queues[guild_id] = []
        await interaction.response.send_message(f"🗑️ Sıra temizlendi! ({count} şarkı silindi)")

    @bot.tree.command(name="ses", description="Ses seviyesini ayarlar (0-100).", guild=discord.Object(id=GUILD_ID))
    @app_commands.describe(seviye="Ses seviyesi (0-100). Boş bırakırsan mevcut seviyeyi gösterir.")
    async def music_volume_cmd(interaction: discord.Interaction, seviye: Optional[int] = None):
        guild_id = interaction.guild.id
        vc = interaction.guild.voice_client
        
        # Mevcut ses seviyesini göster
        if seviye is None:
            current = int(bot.music_volume.get(guild_id, MUSIC_DEFAULT_VOLUME) * 100)
            return await interaction.response.send_message(f"🔊 Mevcut ses seviyesi: **%{current}**")
        
        # Geçersiz değer kontrolü
        if seviye < 0 or seviye > 100:
            return await interaction.response.send_message("❌ Ses seviyesi 0-100 arasında olmalı!", ephemeral=True)
        
        # Ses seviyesini kaydet
        volume = seviye / 100.0
        bot.music_volume[guild_id] = volume
        
        # Eğer şu an çalıyorsa ses seviyesini güncelle
        if vc and vc.source and hasattr(vc.source, 'volume'):
            vc.source.volume = volume
        
        await interaction.response.send_message(f"🔊 Ses seviyesi: **%{seviye}**")

    _music_log("✅ Müzik komutları yüklendi.")
else:
    _music_log("⚠️ yt-dlp yüklü değil, müzik komutları devre dışı.")


# =========================================================
#                    KOMUTLAR LİSTESİ
# =========================================================

# =========================================================
#              CONTENT DÜZENLEME SİSTEMİ (Sağ Tık)
# =========================================================

class ContentEditSelect(discord.ui.Select):
    def __init__(self, message_id: int):
        self.target_message_id = message_id
        options = [
            discord.SelectOption(label="Rol Ekle", value="add_role", emoji="➕", description="Yeni rol tipi ekle"),
            discord.SelectOption(label="Rol Kaldır", value="remove_role", emoji="➖", description="Rol tipini kaldır"),
            discord.SelectOption(label="Slot Değiştir", value="change_slot", emoji="🔢", description="Rol slot sayısını değiştir"),
            discord.SelectOption(label="Kişi Ekle", value="add_person", emoji="👤", description="Role kişi ekle"),
            discord.SelectOption(label="Kişi Çıkar", value="remove_person", emoji="🚫", description="Kişiyi kadrodan çıkar"),
            discord.SelectOption(label="Bilgileri Düzenle", value="edit_info", emoji="⏰", description="Saat, toplanma, binek, ayar"),
        ]
        super().__init__(placeholder="İşlem seç...", options=options)
    
    async def callback(self, interaction: discord.Interaction):
        action = self.values[0]
        msg_id = self.target_message_id
        
        if msg_id not in EVENTS:
            return await interaction.response.send_message("❌ Bu content artık mevcut değil.", ephemeral=True)
        
        state = EVENTS[msg_id]
        
        if action == "add_role":
            await interaction.response.send_modal(ContentEditRoleAddModal(msg_id))
        
        elif action == "remove_role":
            if not state.template.roles:
                return await interaction.response.send_message("❌ Kaldırılacak rol yok.", ephemeral=True)
            await interaction.response.send_message(
                "Kaldırılacak rolü seç:",
                view=ContentEditRoleRemoveView(msg_id, state),
                ephemeral=True
            )
        
        elif action == "change_slot":
            if not state.template.roles:
                return await interaction.response.send_message("❌ Değiştirilecek rol yok.", ephemeral=True)
            await interaction.response.send_message(
                "Slot sayısını değiştireceğin rolü seç:",
                view=ContentEditSlotSelectView(msg_id, state),
                ephemeral=True
            )
        
        elif action == "add_person":
            if not state.template.roles:
                return await interaction.response.send_message("❌ Önce rol ekle.", ephemeral=True)
            await interaction.response.send_message(
                "Kişiyi ekleyeceğin rolü seç:",
                view=ContentEditPersonAddSelectView(msg_id, state),
                ephemeral=True
            )
        
        elif action == "remove_person":
            all_users = list(state.user_role.keys())
            if not all_users:
                return await interaction.response.send_message("❌ Çıkarılacak kişi yok.", ephemeral=True)
            await interaction.response.send_message(
                "Çıkarılacak kişiyi seç:",
                view=ContentEditPersonRemoveView(msg_id, state, interaction.guild),
                ephemeral=True
            )
        
        elif action == "edit_info":
            await interaction.response.send_modal(ContentEditInfoModal(msg_id, state))


class ContentEditView(discord.ui.View):
    def __init__(self, message_id: int):
        super().__init__(timeout=120)
        self.add_item(ContentEditSelect(message_id))


# --- Rol Ekle Modal ---
class ContentEditRoleAddModal(discord.ui.Modal):
    def __init__(self, message_id: int):
        super().__init__(title="Rol Ekle")
        self.message_id = message_id
        self.role_name = discord.ui.TextInput(label="Rol Adı", placeholder="Örn: Scout, Battlemount", max_length=50)
        self.slot_count = discord.ui.TextInput(label="Slot Sayısı", placeholder="Örn: 3", max_length=3)
        self.add_item(self.role_name)
        self.add_item(self.slot_count)
    
    async def on_submit(self, interaction: discord.Interaction):
        if self.message_id not in EVENTS:
            return await interaction.response.send_message("❌ Content bulunamadı.", ephemeral=True)
        
        state = EVENTS[self.message_id]
        role_name = self.role_name.value.strip().lower().replace(" ", "_")
        
        try:
            slot_count = int(self.slot_count.value.strip())
            if slot_count < 1:
                raise ValueError()
        except:
            return await interaction.response.send_message("❌ Geçersiz slot sayısı.", ephemeral=True)
        
        # Rol zaten var mı?
        existing_roles = [r for r, _ in state.template.roles]
        if role_name in existing_roles:
            return await interaction.response.send_message(f"❌ `{role_name}` rolü zaten var.", ephemeral=True)
        
        # Yeni rol ekle
        new_roles = list(state.template.roles) + [(role_name, slot_count)]
        state.template = EventTemplate(
            key=state.template.key,
            title=state.template.title,
            subtitle=state.template.subtitle,
            thread_name=state.template.thread_name,
            roles=new_roles
        )
        state.roster[role_name] = []
        
        # Mesajı güncelle
        await _update_event_message(interaction, state)
        await interaction.response.send_message(f"✅ `{role_name}` rolü eklendi ({slot_count} slot).", ephemeral=True)


# --- Rol Kaldır View ---
class ContentEditRoleRemoveSelect(discord.ui.Select):
    def __init__(self, message_id: int, state: EventState):
        self.message_id = message_id
        options = []
        for role, cap in state.template.roles:
            label = ROLE_LABELS.get(role, role.replace("_", " ").title())
            options.append(discord.SelectOption(label=f"{label} ({cap} slot)", value=role))
        super().__init__(placeholder="Kaldırılacak rol...", options=options[:25])
    
    async def callback(self, interaction: discord.Interaction):
        if self.message_id not in EVENTS:
            return await interaction.response.send_message("❌ Content bulunamadı.", ephemeral=True)
        
        state = EVENTS[self.message_id]
        role_to_remove = self.values[0]
        
        # Roldeki kişileri çıkar
        if role_to_remove in state.roster:
            for uid in state.roster[role_to_remove]:
                if uid in state.user_role:
                    del state.user_role[uid]
            del state.roster[role_to_remove]
        
        # Template'den rolü çıkar
        new_roles = [(r, c) for r, c in state.template.roles if r != role_to_remove]
        state.template = EventTemplate(
            key=state.template.key,
            title=state.template.title,
            subtitle=state.template.subtitle,
            thread_name=state.template.thread_name,
            roles=new_roles
        )
        
        await _update_event_message(interaction, state)
        await interaction.response.send_message(f"✅ `{role_to_remove}` rolü kaldırıldı.", ephemeral=True)


class ContentEditRoleRemoveView(discord.ui.View):
    def __init__(self, message_id: int, state: EventState):
        super().__init__(timeout=60)
        self.add_item(ContentEditRoleRemoveSelect(message_id, state))


# --- Slot Değiştir View ---
class ContentEditSlotSelect(discord.ui.Select):
    def __init__(self, message_id: int, state: EventState):
        self.message_id = message_id
        options = []
        for role, cap in state.template.roles:
            label = ROLE_LABELS.get(role, role.replace("_", " ").title())
            options.append(discord.SelectOption(label=f"{label} ({cap} slot)", value=role))
        super().__init__(placeholder="Rol seç...", options=options[:25])
    
    async def callback(self, interaction: discord.Interaction):
        selected_role = self.values[0]
        await interaction.response.send_modal(ContentEditSlotModal(self.message_id, selected_role))


class ContentEditSlotSelectView(discord.ui.View):
    def __init__(self, message_id: int, state: EventState):
        super().__init__(timeout=60)
        self.add_item(ContentEditSlotSelect(message_id, state))


class ContentEditSlotModal(discord.ui.Modal):
    def __init__(self, message_id: int, role: str):
        super().__init__(title=f"Slot Değiştir: {role}")
        self.message_id = message_id
        self.role = role
        self.new_slot = discord.ui.TextInput(label="Yeni Slot Sayısı", placeholder="Örn: 5", max_length=3)
        self.add_item(self.new_slot)
    
    async def on_submit(self, interaction: discord.Interaction):
        if self.message_id not in EVENTS:
            return await interaction.response.send_message("❌ Content bulunamadı.", ephemeral=True)
        
        try:
            new_count = int(self.new_slot.value.strip())
            if new_count < 1:
                raise ValueError()
        except:
            return await interaction.response.send_message("❌ Geçersiz slot sayısı.", ephemeral=True)
        
        state = EVENTS[self.message_id]
        new_roles = []
        for r, c in state.template.roles:
            if r == self.role:
                new_roles.append((r, new_count))
            else:
                new_roles.append((r, c))
        
        state.template = EventTemplate(
            key=state.template.key,
            title=state.template.title,
            subtitle=state.template.subtitle,
            thread_name=state.template.thread_name,
            roles=new_roles
        )
        
        await _update_event_message(interaction, state)
        await interaction.response.send_message(f"✅ `{self.role}` slotu {new_count} olarak güncellendi.", ephemeral=True)


# --- Kişi Ekle View ---
class ContentEditPersonAddSelect(discord.ui.Select):
    def __init__(self, message_id: int, state: EventState):
        self.message_id = message_id
        options = []
        for role, cap in state.template.roles:
            label = ROLE_LABELS.get(role, role.replace("_", " ").title())
            current = len(state.roster.get(role, []))
            options.append(discord.SelectOption(label=f"{label} ({current}/{cap})", value=role))
        super().__init__(placeholder="Rol seç...", options=options[:25])
    
    async def callback(self, interaction: discord.Interaction):
        selected_role = self.values[0]
        await interaction.response.send_modal(ContentEditPersonAddModal(self.message_id, selected_role))


class ContentEditPersonAddSelectView(discord.ui.View):
    def __init__(self, message_id: int, state: EventState):
        super().__init__(timeout=60)
        self.add_item(ContentEditPersonAddSelect(message_id, state))


class ContentEditPersonAddModal(discord.ui.Modal):
    def __init__(self, message_id: int, role: str):
        super().__init__(title=f"Kişi Ekle: {role}")
        self.message_id = message_id
        self.role = role
        self.user_input = discord.ui.TextInput(label="Kullanıcı ID veya @mention", placeholder="Örn: 123456789 veya kullanıcı adı", max_length=100)
        self.add_item(self.user_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        if self.message_id not in EVENTS:
            return await interaction.response.send_message("❌ Content bulunamadı.", ephemeral=True)
        
        state = EVENTS[self.message_id]
        user_input = self.user_input.value.strip()
        
        # ID çıkar
        user_id = None
        # Mention formatı: <@123456789> veya <@!123456789>
        match = re.search(r'<@!?(\d+)>', user_input)
        if match:
            user_id = int(match.group(1))
        elif user_input.isdigit():
            user_id = int(user_input)
        else:
            # İsimle ara
            if interaction.guild:
                member = discord.utils.find(lambda m: m.name.lower() == user_input.lower() or (m.nick and m.nick.lower() == user_input.lower()), interaction.guild.members)
                if member:
                    user_id = member.id
        
        if not user_id:
            return await interaction.response.send_message("❌ Kullanıcı bulunamadı.", ephemeral=True)
        
        # Zaten kayıtlı mı?
        if user_id in state.user_role:
            return await interaction.response.send_message(f"❌ Bu kişi zaten `{state.user_role[user_id]}` rolünde.", ephemeral=True)
        
        # Slot dolu mu?
        cap = role_capacity(state.template, self.role)
        current = len(state.roster.get(self.role, []))
        if current >= cap:
            return await interaction.response.send_message(f"❌ `{self.role}` rolü dolu ({current}/{cap}).", ephemeral=True)
        
        # Ekle
        if self.role not in state.roster:
            state.roster[self.role] = []
        state.roster[self.role].append(user_id)
        state.user_role[user_id] = self.role
        
        await _update_event_message(interaction, state)
        await interaction.response.send_message(f"✅ <@{user_id}> `{self.role}` rolüne eklendi.", ephemeral=True)


# --- Kişi Çıkar View ---
class ContentEditPersonRemoveSelect(discord.ui.Select):
    def __init__(self, message_id: int, state: EventState, guild: discord.Guild):
        self.message_id = message_id
        options = []
        for uid, role in state.user_role.items():
            member = guild.get_member(uid)
            name = member.display_name if member else f"ID: {uid}"
            role_label = ROLE_LABELS.get(role, role)
            options.append(discord.SelectOption(label=f"{name} ({role_label})", value=str(uid)))
        super().__init__(placeholder="Çıkarılacak kişi...", options=options[:25])
    
    async def callback(self, interaction: discord.Interaction):
        if self.message_id not in EVENTS:
            return await interaction.response.send_message("❌ Content bulunamadı.", ephemeral=True)
        
        state = EVENTS[self.message_id]
        user_id = int(self.values[0])
        
        if user_id in state.user_role:
            role = state.user_role[user_id]
            if role in state.roster and user_id in state.roster[role]:
                state.roster[role].remove(user_id)
            del state.user_role[user_id]
        
        await _update_event_message(interaction, state)
        await interaction.response.send_message(f"✅ <@{user_id}> çıkarıldı.", ephemeral=True)


class ContentEditPersonRemoveView(discord.ui.View):
    def __init__(self, message_id: int, state: EventState, guild: discord.Guild):
        super().__init__(timeout=60)
        self.add_item(ContentEditPersonRemoveSelect(message_id, state, guild))


# --- Bilgi Düzenle Modal ---
class ContentEditInfoModal(discord.ui.Modal):
    def __init__(self, message_id: int, state: EventState):
        super().__init__(title="Bilgileri Düzenle")
        self.message_id = message_id
        self.time_input = discord.ui.TextInput(label="Saat", default=state.time_tr, required=False, max_length=20)
        self.toplanma_input = discord.ui.TextInput(label="Toplanma Yeri", default=state.toplanma, required=False, max_length=100)
        self.binek_input = discord.ui.TextInput(label="Binek", default=state.mount, required=False, max_length=60)
        self.ayar_input = discord.ui.TextInput(label="Ayar", default=state.ayar, required=False, max_length=60)
        self.add_item(self.time_input)
        self.add_item(self.toplanma_input)
        self.add_item(self.binek_input)
        self.add_item(self.ayar_input)
    
    async def on_submit(self, interaction: discord.Interaction):
        if self.message_id not in EVENTS:
            return await interaction.response.send_message("❌ Content bulunamadı.", ephemeral=True)
        
        state = EVENTS[self.message_id]
        
        # Saat güncelle
        if self.time_input.value.strip():
            t_tr, t_utc = fmt_time(self.time_input.value.strip())
            state.time_tr = t_tr
            state.time_utc = t_utc
        
        if self.toplanma_input.value.strip():
            state.toplanma = self.toplanma_input.value.strip()
        if self.binek_input.value.strip():
            state.mount = self.binek_input.value.strip()
        if self.ayar_input.value.strip():
            state.ayar = self.ayar_input.value.strip()
        
        await _update_event_message(interaction, state)
        await interaction.response.send_message("✅ Bilgiler güncellendi.", ephemeral=True)


# --- Mesaj Güncelleme Yardımcı Fonksiyon ---
async def _update_event_message(interaction: discord.Interaction, state: EventState):
    """Event mesajını günceller."""
    try:
        channel = interaction.guild.get_channel(state.channel_id)
        if channel:
            msg = await channel.fetch_message(state.message_id)
            if msg:
                await msg.edit(embed=build_embed(state, interaction.guild), view=EventView(state.template))
    except Exception as e:
        log(f"[EDIT] Mesaj güncellenemedi: {repr(e)}")


# --- Context Menu (Sağ Tık) ---
@bot.tree.context_menu(name="Content Düzenle", guild=discord.Object(id=GUILD_ID))
async def content_edit_context(interaction: discord.Interaction, message: discord.Message):
    # Admin kontrolü
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Bu işlem sadece adminler için.", ephemeral=True)
    
    # Bu mesaj bir event mi?
    if message.id not in EVENTS:
        return await interaction.response.send_message("❌ Bu mesaj bir content değil.", ephemeral=True)
    
    await interaction.response.send_message(
        "**Content Düzenleme**\nBir işlem seç:",
        view=ContentEditView(message.id),
        ephemeral=True
    )


@bot.tree.context_menu(name="Oy Verenler", guild=discord.Object(id=GUILD_ID))
async def poll_voters_context(interaction: discord.Interaction, message: discord.Message):
    """Oylama mesajında kim oy verdi gösterir - sadece adminler için."""
    # Admin kontrolü
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Bu işlem sadece adminler için.", ephemeral=True)
    
    # Bu mesaj bir oylama mı?
    if message.id not in ACTIVE_POLLS:
        return await interaction.response.send_message("❌ Bu mesaj bir oylama değil veya artık aktif değil.", ephemeral=True)
    
    view = ACTIVE_POLLS[message.id]
    
    if not view.user_choice:
        return await interaction.response.send_message("📭 Henüz kimse oy kullanmadı.", ephemeral=True)
    
    # Seçeneklere göre grupla
    votes_by_choice: Dict[str, List[int]] = {}
    for uid, choice in view.user_choice.items():
        if choice not in votes_by_choice:
            votes_by_choice[choice] = []
        votes_by_choice[choice].append(uid)
    
    # Embed oluştur
    embed = discord.Embed(
        title="👥 Oy Kullananlar",
        description=f"**{view.question}** oylaması",
        color=0x5865F2
    )
    
    for key, label, emoji in CONTENT_POLL_CHOICES:
        if key in votes_by_choice:
            voters = votes_by_choice[key]
            voter_mentions = [f"<@{uid}>" for uid in voters[:15]]
            if len(voters) > 15:
                voter_mentions.append(f"*... ve {len(voters) - 15} kişi daha*")
            embed.add_field(
                name=f"{emoji} {label} ({len(voters)} oy)",
                value="\n".join(voter_mentions) or "Yok",
                inline=True
            )
    
    # Oy kullanmayanları da göster (opsiyonel bilgi)
    total_votes = len(view.user_choice)
    status = "🟢 Aktif" if not view.ended else "🔴 Sona Erdi"
    embed.set_footer(text=f"{status} • Toplam {total_votes} kişi oy kullandı")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="komutlar", description="Tüm bot komutlarını listeler.", guild=discord.Object(id=GUILD_ID))
async def komutlar_cmd(interaction: discord.Interaction):
    embed = discord.Embed(title="📜 Bot Komutları", color=0x5865F2)
    
    # Content komutları
    content_cmds = """
`/content` - Content seçip event oluşturur
`/contentoylama` - Content oylaması başlatır
"""
    embed.add_field(name="📅 Content", value=content_cmds, inline=False)
    
    # Sheet komutları
    sheet_cmds = """
`/sheetekle` - Sheet'i /content'e ekler
`/sheetkaldir` - Sheet kaldırır
`/sheetliste` - Ekli sheetleri listeler
"""
    embed.add_field(name="📋 Sheet", value=sheet_cmds, inline=False)
    
    # Müzik komutları
    music_cmds = """
`/cal <şarkı>` - YouTube'dan müzik çalar
`/playlist <url>` - YouTube/YT Music playlist çalar
`/atla` - Şarkıyı geçer
`/duraklat` - Duraklatır
`/devam` - Devam ettirir
`/durdur` - Durdurur ve sırayı temizler
`/sira` - Şarkı sırasını gösterir
`/calan` - Çalan şarkıyı gösterir
`/ses <0-100>` - Ses seviyesi ayarlar
`/dongu` - Döngü aç/kapa
`/temizle` - Sırayı temizler
`/katil` - Ses kanalına katılır
`/ayril` - Ses kanalından ayrılır
"""
    embed.add_field(name="🎵 Müzik", value=music_cmds, inline=False)
    
    # Killboard komutları
    kb_cmds = """
`/killboardstatus` - Killboard durumu
`/killboardtest` - Test mesajı
`/kbmurder` - Link modunu MurderLedger yapar
`/kbalbion` - Link modunu Albion yapar
`/bbtest` - Battleboard test
"""
    embed.add_field(name="⚔️ Killboard", value=kb_cmds, inline=False)
    
    # Bağlama komutları
    link_cmds = """
`/bagla` - Discord-Albion bağlantısı kurar (Admin)
`/baglantim` - Bağlı hesabı gösterir
`/baglantikal` - Bağlantıyı kaldırır (Admin)
"""
    embed.add_field(name="🔗 Hesap Bağlama", value=link_cmds, inline=False)
    
    # Diğer komutlar
    other_cmds = """
`/mesaj` - Mesaj gönderir (Admin)
`/foto` - Fotoğraf gönderir (Admin)
`/aktif` - Thread'i aktif eder
`/komutlar` - Bu listeyi gösterir
`/dogrulama-kur` - Doğrulama mesajını kurar (Admin)
`/ticket-kur` - Ticket mesajını kurar (Admin)
`Sağ tık → Content Düzenle` - Content düzenleme (Admin)
`Sağ tık → Oy Verenler` - Oylamada kim oy verdi (Admin)
"""
    embed.add_field(name="🔧 Diğer", value=other_cmds, inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


# =========================================================
#                DOĞRULAMA SİSTEMİ
# =========================================================
class VerifyButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="Başvuru Yap", style=discord.ButtonStyle.danger, emoji="📋", custom_id="verify_button")
    async def verify_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            role = interaction.guild.get_role(VERIFY_ROLE_ID)
            if role is None:
                return await interaction.response.send_message("❌ Rol bulunamadı.", ephemeral=True)
            
            if role in interaction.user.roles:
                return await interaction.response.send_message("✅ Zaten doğrulanmışsın!", ephemeral=True)
            
            await interaction.user.add_roles(role, reason="Doğrulama butonu")
            await interaction.response.send_message(
                f"✅ Doğrulama tamamlandı! Artık **recruit** kanallarını görebilirsin.",
                ephemeral=True
            )
            log(f"[VERIFY] {interaction.user.name} doğrulandı")
        except discord.Forbidden:
            await interaction.response.send_message("❌ Bot bu rolü veremedi. Yetki hatası.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Hata: {repr(e)}", ephemeral=True)


@bot.tree.command(name="dogrulama-kur", description="Doğrulama mesajını kanala gönderir.", guild=discord.Object(id=GUILD_ID))
@app_commands.default_permissions(administrator=True)
async def dogrulama_kur_cmd(interaction: discord.Interaction):
    channel = bot.get_channel(VERIFY_CHANNEL_ID)
    if not channel:
        return await interaction.response.send_message("❌ Doğrulama kanalı bulunamadı.", ephemeral=True)
    
    embed = discord.Embed(
        title="📋 Doğrulama",
        description=(
            "Sunucuya hoş geldin.\n\n"
            "Devam etmeden önce kuralları okuduğunu ve anladığını onaylaman gerekiyor.\n"
            "Aşağıdaki butona tıklayarak doğrulamayı tamamla.\n\n"
            "**Doğrulama yapıldığında:**\n"
            "• Kuralları kabul etmiş sayılırsın,\n"
            "• Recruit (başvuru) kanalı görünür hale gelir.\n\n"
            "*Aramıza katılmak istiyorsan doğrulamayı tamamla ve başvuru adımlarını takip et.*"
        ),
        color=0x2b2d31
    )
    
    await channel.send(embed=embed, view=VerifyButton())
    await interaction.response.send_message(f"✅ Doğrulama mesajı {channel.mention} kanalına gönderildi!", ephemeral=True)
    log(f"[VERIFY] Doğrulama mesajı kuruldu - {interaction.user.name}")


# =========================================================
#                   TICKET SİSTEMİ
# =========================================================
class TicketOpenButton(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="Destek Aç", style=discord.ButtonStyle.primary, emoji="🎫", custom_id="ticket_open_button")
    async def open_ticket_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Ticket sayacını yükle ve artır
            state = _load_ticket_state()
            state["counter"] = state.get("counter", 0) + 1
            ticket_num = state["counter"]
            _save_ticket_state(state)
            
            # Kategoriyi bul
            category = interaction.guild.get_channel(TICKET_CATEGORY_ID)
            if not category:
                return await interaction.response.send_message("❌ Ticket kategorisi bulunamadı.", ephemeral=True)
            
            # Yetkili rolünü bul
            staff_role = interaction.guild.get_role(TICKET_STAFF_ROLE_ID)
            
            # Kanal izinleri
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    attach_files=True,
                    embed_links=True,
                    read_message_history=True
                ),
                interaction.guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    manage_channels=True,
                    manage_messages=True
                )
            }
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    attach_files=True,
                    embed_links=True,
                    read_message_history=True,
                    manage_messages=True
                )
            
            # Kanalı oluştur
            channel_name = f"ticket-{ticket_num}"
            ticket_channel = await interaction.guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                reason=f"Ticket #{ticket_num} - {interaction.user.name}"
            )
            
            # Hoş geldin embed'i
            embed = discord.Embed(
                title="🎫 Ticket Açıldı",
                description=(
                    f"Merhaba {interaction.user.mention}, savaşçı!\n\n"
                    "Buraya bırakacağın her bilgi çözümü hızlandırır.\n"
                    "Sorunun, isteğin veya yaşadığın durumu anlaşılır biçimde yazabilirsin.\n"
                    "Gerekirse ekran görüntüsü ya da kanıt ekleyebilirsin."
                ),
                color=0x5865F2
            )
            embed.set_footer(text=f"Ticket #{ticket_num} • {interaction.user.name}")
            embed.timestamp = datetime.now(UTC_TZ)
            
            msg = await ticket_channel.send(
                content=f"{interaction.user.mention}" + (f" {staff_role.mention}" if staff_role else ""),
                embed=embed,
                view=TicketControlView()
            )
            await msg.pin(reason="Ticket bilgisi")
            
            await interaction.response.send_message(
                f"✅ Ticket oluşturuldu! {ticket_channel.mention}",
                ephemeral=True
            )
            log(f"[TICKET] #{ticket_num} açıldı - {interaction.user.name}")
            
        except discord.Forbidden:
            await interaction.response.send_message("❌ Bot kanal oluşturamadı. Yetki hatası.", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Hata: {repr(e)}", ephemeral=True)


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success, emoji="✋", custom_id="ticket_claim")
    async def claim_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Sadece yetkililer claim edebilir
        staff_role = interaction.guild.get_role(TICKET_STAFF_ROLE_ID)
        if staff_role and staff_role not in interaction.user.roles:
            return await interaction.response.send_message("❌ Bu işlem sadece yetkililer için.", ephemeral=True)
        
        await interaction.response.send_message(
            f"✅ Bu ticket **{interaction.user.mention}** tarafından üstlenildi.",
            allowed_mentions=discord.AllowedMentions(users=True)
        )
        log(f"[TICKET] {interaction.channel.name} claimed by {interaction.user.name}")
    
    @discord.ui.button(label="Kapat", style=discord.ButtonStyle.secondary, emoji="🔒", custom_id="ticket_close")
    async def close_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(
            "🔒 Ticket kapatılıyor... Bu kanal 5 saniye içinde arşivlenecek.",
        )
        
        # Kanalı arşivle (izinleri kapat)
        try:
            overwrites = interaction.channel.overwrites
            for target in list(overwrites.keys()):
                if isinstance(target, discord.Member) and target != interaction.guild.me:
                    overwrites[target] = discord.PermissionOverwrite(view_channel=True, send_messages=False)
            await interaction.channel.edit(overwrites=overwrites, name=f"kapalı-{interaction.channel.name}")
            log(f"[TICKET] {interaction.channel.name} kapatıldı - {interaction.user.name}")
        except Exception as e:
            await interaction.channel.send(f"❌ Kapatma hatası: {repr(e)}")
    
    @discord.ui.button(label="Yeniden Aç", style=discord.ButtonStyle.success, emoji="🔓", custom_id="ticket_reopen")
    async def reopen_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Sadece yetkililer reopen edebilir
        staff_role = interaction.guild.get_role(TICKET_STAFF_ROLE_ID)
        if staff_role and staff_role not in interaction.user.roles:
            return await interaction.response.send_message("❌ Bu işlem sadece yetkililer için.", ephemeral=True)
        
        try:
            # İzinleri geri aç
            new_name = interaction.channel.name.replace("kapalı-", "")
            await interaction.channel.edit(name=new_name)
            await interaction.response.send_message("🔓 Ticket yeniden açıldı!")
            log(f"[TICKET] {new_name} yeniden açıldı - {interaction.user.name}")
        except Exception as e:
            await interaction.response.send_message(f"❌ Hata: {repr(e)}", ephemeral=True)
    
    @discord.ui.button(label="Sil", style=discord.ButtonStyle.danger, emoji="🗑️", custom_id="ticket_delete")
    async def delete_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Sadece yetkililer silebilir
        staff_role = interaction.guild.get_role(TICKET_STAFF_ROLE_ID)
        if staff_role and staff_role not in interaction.user.roles:
            return await interaction.response.send_message("❌ Bu işlem sadece yetkililer için.", ephemeral=True)
        
        await interaction.response.send_message("🗑️ Ticket 5 saniye içinde silinecek...")
        log(f"[TICKET] {interaction.channel.name} siliniyor - {interaction.user.name}")
        await asyncio.sleep(5)
        
        try:
            await interaction.channel.delete(reason=f"Ticket silindi - {interaction.user.name}")
        except Exception as e:
            log(f"[TICKET] Silme hatası: {repr(e)}")


@bot.tree.command(name="ticket-kur", description="Ticket mesajını kanala gönderir.", guild=discord.Object(id=GUILD_ID))
@app_commands.default_permissions(administrator=True)
async def ticket_kur_cmd(interaction: discord.Interaction):
    channel = bot.get_channel(TICKET_CHANNEL_ID)
    if not channel:
        return await interaction.response.send_message("❌ Ticket kanalı bulunamadı.", ephemeral=True)
    
    embed = discord.Embed(
        title="🎫 Destek Merkezi",
        description=(
            "Avalon'un salonlarına hoş geldin, savaşçı.\n\n"
            "Buraya yalnızca sorunları çözmek ve cevap bulmak için adım atılır.\n"
            "Talebini, şikayetini veya başvurunu açık ve net yaz.\n"
            "Biz, Avalon'un gözcüleri, seni yönlendireceğiz.\n\n"
            "*\"Cevap arayana değil, soruyu taşıyabilene görünür.\"*"
        ),
        color=0x2b2d31
    )
    
    await channel.send(embed=embed, view=TicketOpenButton())
    await interaction.response.send_message(f"✅ Ticket mesajı {channel.mention} kanalına gönderildi!", ephemeral=True)
    log(f"[TICKET] Ticket mesajı kuruldu - {interaction.user.name}")


# =========================================================
#          PERSISTENT VIEWS (Bot restart sonrası çalışsın)
# =========================================================
@bot.event
async def on_ready():
    # Persistent view'ları kaydet
    bot.add_view(VerifyButton())
    bot.add_view(TicketOpenButton())
    bot.add_view(TicketControlView())
    log("✅ Persistent views registered")


# =========================================================
#                   ACTIVITY COMMANDS
# =========================================================
def _format_duration(minutes: int) -> str:
    """Dakikayı saat:dakika formatına çevirir."""
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0:
        return f"{hours} saat {mins} dk"
    return f"{mins} dk"

@bot.tree.command(name="aktivite", description="Bir kullanıcının aktivite bilgilerini gösterir.", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(user="Aktivitesini görmek istediğin kullanıcı")
async def aktivite_cmd(interaction: discord.Interaction, user: discord.Member):
    state = _load_activity_state()
    user_data = state["users"].get(str(user.id))
    
    if user_data is None:
        return await interaction.response.send_message(
            f"📊 **{user.name}** için henüz aktivite verisi yok.",
            ephemeral=True
        )
    
    # Son aktivite
    last_activity = user_data.get("last_activity")
    if last_activity:
        try:
            last_dt = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
            days_ago = (datetime.now(UTC_TZ) - last_dt).days
            if days_ago == 0:
                last_str = "Bugün"
            elif days_ago == 1:
                last_str = "Dün"
            else:
                last_str = f"{days_ago} gün önce"
            last_type = user_data.get("last_activity_type", "bilinmiyor")
        except:
            last_str = "Bilinmiyor"
            last_type = "bilinmiyor"
    else:
        last_str = "Hiç"
        last_type = "-"
    
    # Durum belirleme
    if last_activity:
        try:
            last_dt = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
            days_inactive = (datetime.now(UTC_TZ) - last_dt).days
            if days_inactive >= 7:
                status = "🔴 Kritik İnaktif"
            elif days_inactive >= 5:
                status = "🟠 İnaktif"
            elif days_inactive >= 3:
                status = "🟡 Düşük Aktivite"
            else:
                status = "🟢 Aktif"
        except:
            status = "⚪ Belirsiz"
    else:
        status = "⚪ Veri Yok"
    
    embed = discord.Embed(
        title=f"📊 {user.name} - Aktivite",
        color=0x5865F2
    )
    embed.set_thumbnail(url=user.display_avatar.url if user.display_avatar else user.default_avatar.url)
    
    embed.add_field(
        name="Content Katılımı",
        value=f"{user_data.get('content_joins', 0)} content",
        inline=True
    )
    embed.add_field(
        name="Voice",
        value=_format_duration(user_data.get('voice_minutes', 0)),
        inline=True
    )
    embed.add_field(
        name="Son Aktivite",
        value=f"{last_str} ({last_type})",
        inline=True
    )
    embed.add_field(
        name="Durum",
        value=status,
        inline=True
    )
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="aktivite-top", description="En aktif 10 kullanıcıyı gösterir.", guild=discord.Object(id=GUILD_ID))
async def aktivite_top_cmd(interaction: discord.Interaction):
    state = _load_activity_state()
    guild = interaction.guild
    
    if not state["users"]:
        return await interaction.response.send_message("📊 Henüz aktivite verisi yok.", ephemeral=True)
    
    # Toplam aktivite puanı hesapla (content*10 + voice_minutes/30)
    scores = []
    for user_id_str, data in state["users"].items():
        try:
            user_id = int(user_id_str)
            member = guild.get_member(user_id)
            if member and not member.bot:
                score = (
                    data.get("content_joins", 0) * 10 +
                    data.get("voice_minutes", 0) / 30
                )
                scores.append((member, data, score))
        except:
            continue
    
    scores.sort(key=lambda x: x[2], reverse=True)
    top_10 = scores[:10]
    
    if not top_10:
        return await interaction.response.send_message("📊 Gösterilecek veri yok.", ephemeral=True)
    
    embed = discord.Embed(
        title="📊 En Aktif 10 Üye",
        color=0x5865F2
    )
    
    lines = []
    for i, (member, data, score) in enumerate(top_10, 1):
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        lines.append(
            f"{medal} **{member.name}** - "
            f"{data.get('content_joins', 0)}C / {_format_duration(data.get('voice_minutes', 0))}"
        )
    
    embed.description = "\n".join(lines)
    embed.set_footer(text="C=Content")
    
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="aktivite-inaktif", description="5+ gün inaktif üyeleri listeler.", guild=discord.Object(id=GUILD_ID))
@app_commands.default_permissions(administrator=True)
async def aktivite_inaktif_cmd(interaction: discord.Interaction):
    state = _load_activity_state()
    guild = interaction.guild
    now = datetime.now(UTC_TZ)
    
    inactive_list = []
    
    for member in guild.members:
        if member.bot:
            continue
        
        user_data = state["users"].get(str(member.id))
        
        if user_data is None:
            # Hiç verisi yok, katılma tarihine bak
            if member.joined_at:
                days_since_join = (now - member.joined_at.replace(tzinfo=UTC_TZ)).days
                if days_since_join >= ACTIVITY_INACTIVITY_DAYS:
                    inactive_list.append((member, days_since_join, "hiç aktivite yok"))
            continue
        
        last_activity = user_data.get("last_activity")
        if last_activity:
            try:
                last_dt = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
                days_inactive = (now - last_dt).days
                if days_inactive >= ACTIVITY_INACTIVITY_DAYS:
                    last_type = user_data.get("last_activity_type", "bilinmiyor")
                    inactive_list.append((member, days_inactive, f"son: {last_type}"))
            except:
                pass
    
    if not inactive_list:
        return await interaction.response.send_message("✅ 5+ gün inaktif üye yok!", ephemeral=True)
    
    # Gün sayısına göre sırala
    inactive_list.sort(key=lambda x: x[1], reverse=True)
    
    embed = discord.Embed(
        title=f"⚠️ {ACTIVITY_INACTIVITY_DAYS}+ Gün İnaktif Üyeler",
        color=0xe74c3c
    )
    
    lines = []
    for member, days, info in inactive_list[:20]:  # Max 20 kişi göster
        lines.append(f"• **{member.name}** - {days} gün ({info})")
    
    if len(inactive_list) > 20:
        lines.append(f"\n*...ve {len(inactive_list) - 20} kişi daha*")
    
    embed.description = "\n".join(lines)
    embed.set_footer(text=f"Toplam: {len(inactive_list)} kişi")
    
    await interaction.response.send_message(embed=embed)


# =========================================================
#                  ALBION ITEM SEARCH COMMAND
# =========================================================

@bot.tree.command(name="itemara", description="Albion Online item ara", guild=discord.Object(id=GUILD_ID))
@app_commands.describe(query="Aramak istediğin item (örn: claymore, guardian helmet)")
async def item_ara_cmd(interaction: discord.Interaction, query: str):
    if not _albion_items_loaded:
        load_albion_items_db()
    
    if not _albion_items_db:
        return await interaction.response.send_message(
            "❌ Item veritabanı yüklenmedi!\n"
            "Sunucuda şu komutu çalıştır:\n"
            "```bash\ncurl -sL 'https://raw.githubusercontent.com/ao-data/ao-bin-dumps/master/formatted/items.txt' -o albion_items.txt\n```",
            ephemeral=True
        )
    
    results = search_albion_items(query, limit=10)
    
    if not results:
        return await interaction.response.send_message(
            f"❌ `{query}` ile eşleşen item bulunamadı.",
            ephemeral=True
        )
    
    embed = discord.Embed(
        title=f"🔍 '{query}' Sonuçları",
        color=0x3498db
    )
    
    lines = []
    for item_id, item_name in results:
        lines.append(f"• **{item_name}**\n  `{item_id}`")
    
    embed.description = "\n".join(lines)
    
    # İlk sonucun görselini göster
    if results:
        embed.set_thumbnail(url=get_albion_item_image_url(results[0][0]))
    
    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.run(TOKEN)
