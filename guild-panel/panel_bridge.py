"""
panel_bridge.py
===============
Web panel ↔ Discord bot köprüsü.

Görevler:
  1. active_events.json  → EVENTS + SHEET_EVENTS'ten besle (panel okur)
  2. puan_config.json    → Bot sabitlerini güncelle
  3. content_templates.json → Panel'den gelen şablonları oku (bot okur)
  4. dynamic_sheets.json → Panel-bot format uyumu
  5. queue.jsonl         → Panel komutlarını işle (close_content, reset_points)

Kullanım (bot.py içinden):
    from panel_bridge import PanelBridge
    bridge = PanelBridge(bot, BASE_DIR)
    # on_ready içinde:
    bot.loop.create_task(bridge.start())
    # Event oluşturulduğunda:
    bridge.flush_active_events()
    # Event kapandığında:
    bridge.flush_active_events()
"""

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    pass  # CallidusBot forward reference - circular import'u önle

# ── Sabitler ─────────────────────────────────────────────────────────────────

QUEUE_POLL_SECONDS = 3        # Queue kaç saniyede bir kontrol edilsin
ACTIVE_EVENTS_FLUSH_DEBOUNCE = 1  # Saniye - çok sık yazma önleme

# ── Yardımcı ─────────────────────────────────────────────────────────────────

def _atomic_write(path: Path, data: Any) -> None:
    """JSON'ı tmp → rename ile atomik yazar."""
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        print(f"[BRIDGE] atomic_write hatası ({path.name}): {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _read_json(path: Path, fallback: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[BRIDGE] read_json hatası ({path.name}): {e}")
    return fallback


# ── Ana Sınıf ────────────────────────────────────────────────────────────────

class PanelBridge:
    def __init__(self, bot, base_dir: str):
        self.bot = bot
        self.base = Path(base_dir)

        # Dosya yolları
        self.active_events_file = self.base / "data" / "active_events.json"
        self.puan_config_file   = self.base / "data" / "puan_config.json"
        self.templates_file     = self.base / "data" / "content_templates.json"
        self.sheets_file        = self.base / "data" / "dynamic_sheets.json"
        self.queue_file         = self.base / "bot_commands" / "queue.jsonl"
        self.queue_done_file    = self.base / "bot_commands" / "queue_done.jsonl"

        # Dizinleri oluştur
        for f in [self.active_events_file, self.queue_file]:
            f.parent.mkdir(parents=True, exist_ok=True)

        # Son flush zamanı (debounce)
        self._last_flush: float = 0.0

        # İşlenen queue satırları (ts+action key ile duplicate önle)
        self._processed_queue_keys: set = set()

        print("[BRIDGE] Panel köprüsü başlatıldı.")

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """on_ready'de çağrılır. Tüm loop'ları başlatır."""
        await self.bot.wait_until_ready()
        print("[BRIDGE] Loop'lar başlatılıyor…")

        # İlk flush
        self.flush_active_events()
        self._apply_puan_config()

        # Queue işleyici loop
        self.bot.loop.create_task(self._queue_loop())
        print("[BRIDGE] Hazır.")

    def flush_active_events(self) -> None:
        """
        EVENTS + SHEET_EVENTS'i active_events.json'a yazar.
        Debounce: aynı saniye içinde çok kez çağrılırsa sadece bir kez yazar.
        """
        now = time.monotonic()
        if now - self._last_flush < ACTIVE_EVENTS_FLUSH_DEBOUNCE:
            return
        self._last_flush = now
        self._write_active_events()

    def flush_active_events_force(self) -> None:
        """Debounce'sız zorunlu flush (event kapandığında kullan)."""
        self._last_flush = 0.0
        self._write_active_events()

    # ── active_events.json ───────────────────────────────────────────────────

    def _write_active_events(self) -> None:
        """
        Bot'un bellekteki tüm aktif event'leri JSON'a yazar.
        Bot modülündeki EVENTS ve SHEET_EVENTS global dict'lerine erişir.
        """
        try:
            import bot as bot_module  # Circular import'u runtime'da çöz
        except ImportError:
            print("[BRIDGE] bot modülü import edilemedi, flush atlandı.")
            return

        events: list = []

        # ── Normal EVENTS (EventState) ────────────────────────────────────
        for msg_id, state in list(getattr(bot_module, "EVENTS", {}).items()):
            try:
                tpl = state.template
                # Katılımcı listesi (tüm roller)
                participant_ids: list = []
                seen: set = set()
                for role, _cap in tpl.roles:
                    for uid in state.roster.get(role, []):
                        if uid not in seen:
                            participant_ids.append(uid)
                            seen.add(uid)

                # started_by_name: owner Discord member'ından al
                started_by_name = "Unknown"
                started_by_avatar = ""
                guild = self.bot.get_guild(
                    int(os.getenv("GUILD_ID", "0"))
                )
                if guild:
                    member = guild.get_member(state.owner_id)
                    if member:
                        started_by_name = member.display_name
                        started_by_avatar = str(
                            member.display_avatar.replace(size=64).url
                        )

                events.append({
                    "event_id":           f"ev_{msg_id}",
                    "template_key":       tpl.key,
                    "template_title":     tpl.title,
                    "started_by":         state.owner_id,
                    "started_by_name":    started_by_name,
                    "started_by_avatar":  started_by_avatar,
                    "started_at":         int(
                        getattr(state, "created_at", msg_id / 4194304 + 1420070400)
                        if isinstance(getattr(state, "created_at", None), (int, float))
                        else _snowflake_to_ts(msg_id)
                    ),
                    "thread_id":          state.thread_id,
                    "participants":       participant_ids,
                    "participant_count":  len(participant_ids),
                    "status":             "active",
                    "source":             "normal",
                })
            except Exception as e:
                print(f"[BRIDGE] EventState serializasyon hatası {msg_id}: {e}")

        # ── SHEET_EVENTS (SheetEventState) ───────────────────────────────
        for msg_id, st in list(getattr(bot_module, "SHEET_EVENTS", {}).items()):
            try:
                participant_ids = list(getattr(st, "user_slot", {}).keys())

                started_by_name = "Unknown"
                started_by_avatar = ""
                guild = self.bot.get_guild(int(os.getenv("GUILD_ID", "0")))
                if guild:
                    member = guild.get_member(st.owner_id)
                    if member:
                        started_by_name = member.display_name
                        started_by_avatar = str(
                            member.display_avatar.replace(size=64).url
                        )

                events.append({
                    "event_id":           f"sh_{msg_id}",
                    "template_key":       getattr(st, "sheet_tab", "sheet"),
                    "template_title":     getattr(st, "title", "Sheet Event"),
                    "started_by":         st.owner_id,
                    "started_by_name":    started_by_name,
                    "started_by_avatar":  started_by_avatar,
                    "started_at":         _snowflake_to_ts(msg_id),
                    "thread_id":          st.thread_id,
                    "participants":       participant_ids,
                    "participant_count":  len(participant_ids),
                    "status":             "active",
                    "source":             "sheet",
                })
            except Exception as e:
                print(f"[BRIDGE] SheetEventState serializasyon hatası {msg_id}: {e}")

        _atomic_write(self.active_events_file, events)
        print(f"[BRIDGE] active_events.json güncellendi ({len(events)} event).")

    # ── puan_config.json ─────────────────────────────────────────────────────

    def _apply_puan_config(self) -> None:
        """
        puan_config.json'dan bot'un puan sabitlerini günceller.
        Bot modülündeki global değişkenlere yazar.
        """
        cfg = _read_json(self.puan_config_file)
        if not cfg or not isinstance(cfg, dict):
            return

        try:
            import bot as bot_module  # type: ignore
        except ImportError:
            return

        voice = cfg.get("voice", {})
        if not isinstance(voice, dict):
            return

        changed = []

        ppm = voice.get("puan_per_minute")
        if ppm is not None and isinstance(ppm, (int, float)):
            bot_module.PUAN_PER_MINUTE = float(ppm)
            changed.append(f"PUAN_PER_MINUTE={ppm}")

        dmax = voice.get("daily_max")
        if dmax is not None and isinstance(dmax, (int, float)):
            bot_module.PUAN_DAILY_MAX = float(dmax)
            changed.append(f"PUAN_DAILY_MAX={dmax}")

        wt = voice.get("warning_threshold")
        if wt is not None and isinstance(wt, (int, float)):
            bot_module.PUAN_WARNING_THRESHOLD = float(wt)
            changed.append(f"PUAN_WARNING_THRESHOLD={wt}")

        kt = voice.get("kick_threshold")
        if kt is not None and isinstance(kt, (int, float)):
            bot_module.PUAN_KICK_THRESHOLD = float(kt)
            changed.append(f"PUAN_KICK_THRESHOLD={kt}")

        if changed:
            print(f"[BRIDGE] Puan config uygulandı: {', '.join(changed)}")

    # ── Queue İşleyici ───────────────────────────────────────────────────────

    async def _queue_loop(self) -> None:
        """Her QUEUE_POLL_SECONDS'da queue.jsonl'ı kontrol eder."""
        print(f"[BRIDGE] Queue loop başladı (her {QUEUE_POLL_SECONDS}s).")
        while not self.bot.is_closed():
            try:
                await self._process_queue()
            except Exception as e:
                print(f"[BRIDGE] Queue loop hatası: {e}")
            await asyncio.sleep(QUEUE_POLL_SECONDS)

    async def _process_queue(self) -> None:
        """queue.jsonl'daki bekleyen komutları işler ve dosyayı temizler."""
        if not self.queue_file.exists():
            return

        try:
            raw = self.queue_file.read_text(encoding="utf-8").strip()
        except Exception:
            return

        if not raw:
            return

        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        pending = []
        processed = []

        for line in lines:
            try:
                cmd = json.loads(line)
            except json.JSONDecodeError:
                print(f"[BRIDGE] Geçersiz JSON satırı atlandı: {line[:80]}")
                continue

            # Duplicate kontrolü
            key = f"{cmd.get('action','')}_{cmd.get('ts', id(cmd))}"
            if key in self._processed_queue_keys:
                continue  # zaten işlendi

            pending.append((key, cmd))

        if not pending:
            # Tüm satırlar duplicate, dosyayı temizle
            _atomic_write(self.queue_file, "")
            self.queue_file.write_text("", encoding="utf-8")
            return

        # Dosyayı hemen temizle (önce oku, sonra sil — double processing önle)
        try:
            self.queue_file.write_text("", encoding="utf-8")
        except Exception as e:
            print(f"[BRIDGE] Queue temizleme hatası: {e}")

        for key, cmd in pending:
            action = cmd.get("action", "")
            try:
                if action == "close_content":
                    await self._handle_close_content(cmd)
                elif action == "reset_points":
                    await self._handle_reset_points(cmd)
                else:
                    print(f"[BRIDGE] Bilinmeyen action: {action}")

                self._processed_queue_keys.add(key)
                processed.append({**cmd, "processed_at": datetime.now(timezone.utc).isoformat()})
            except Exception as e:
                print(f"[BRIDGE] Komut işleme hatası [{action}]: {e}")

        # Done log'a yaz
        if processed:
            try:
                existing = ""
                if self.queue_done_file.exists():
                    existing = self.queue_done_file.read_text(encoding="utf-8")
                with self.queue_done_file.open("a", encoding="utf-8") as f:
                    for cmd in processed:
                        f.write(json.dumps(cmd, ensure_ascii=False) + "\n")
            except Exception as e:
                print(f"[BRIDGE] Done log yazma hatası: {e}")

        # Processed keys seti büyümesin
        if len(self._processed_queue_keys) > 2000:
            self._processed_queue_keys = set(
                list(self._processed_queue_keys)[-1000:]
            )

    # ── Komut Handler'ları ───────────────────────────────────────────────────

    async def _handle_close_content(self, cmd: Dict) -> None:
        """
        Panel'den gelen close_content komutunu işler.

        cmd örnek:
        {
            "action": "close_content",
            "event_id": "ev_1234567890",   # "ev_MSGID" veya "sh_MSGID"
            "thread_id": 9876543210,
            "start_loot": true,
            "requested_by": 111111111,
            "requested_by_name": "Tunç",
            "ts": 1708200000
        }
        """
        try:
            import bot as bot_module  # type: ignore
        except ImportError:
            print("[BRIDGE] bot modülü import edilemedi.")
            return

        event_id: str = cmd.get("event_id", "")
        thread_id: int = int(cmd.get("thread_id") or 0)
        start_loot: bool = bool(cmd.get("start_loot", False))
        req_name: str = cmd.get("requested_by_name") or "Panel"

        # event_id'den msg_id çıkar
        msg_id: Optional[int] = None
        if event_id.startswith("ev_"):
            try:
                msg_id = int(event_id[3:])
            except ValueError:
                pass
        elif event_id.startswith("sh_"):
            try:
                msg_id = int(event_id[3:])
            except ValueError:
                pass

        guild = self.bot.get_guild(int(os.getenv("GUILD_ID", "0")))
        if not guild:
            print("[BRIDGE] close_content: Guild bulunamadı.")
            return

        # ── Normal EventState ──────────────────────────────────────────
        state = None
        sheet_state = None

        if msg_id:
            state = bot_module.EVENTS.get(msg_id)
            if not state:
                sheet_state = bot_module.SHEET_EVENTS.get(msg_id)

        # thread_id ile de ara (msg_id bulunamadıysa)
        if not state and not sheet_state and thread_id:
            for mid, s in bot_module.EVENTS.items():
                if s.thread_id == thread_id:
                    state = s
                    msg_id = mid
                    break
            if not state:
                for mid, s in bot_module.SHEET_EVENTS.items():
                    if s.thread_id == thread_id:
                        sheet_state = s
                        msg_id = mid
                        break

        if not state and not sheet_state:
            print(f"[BRIDGE] close_content: event_id={event_id} bulunamadı (belki zaten kapandı).")
            self.flush_active_events_force()
            return

        # ── Katılımcıları topla ────────────────────────────────────────
        participant_ids: list = []
        content_name = ""

        if state:
            content_name = (state.template.thread_name or state.template.key or "").strip() or "CONTENT"
            seen: set = set()
            for role, _cap in state.template.roles:
                for uid in state.roster.get(role, []):
                    if uid not in seen:
                        participant_ids.append(uid)
                        seen.add(uid)
        else:
            content_name = (
                getattr(sheet_state, "thread_name", "")
                or getattr(sheet_state, "title", "")
                or "SHEET CONTENT"
            ).strip()
            participant_ids = list(getattr(sheet_state, "user_slot", {}).keys())

        # ── İsimleri çöz ──────────────────────────────────────────────
        names: list = []
        for uid in participant_ids:
            member = guild.get_member(uid)
            names.append(member.display_name if member else str(uid))

        print(
            f"[BRIDGE] close_content: '{content_name}' kapatılıyor "
            f"({len(participant_ids)} katılımcı, start_loot={start_loot}) "
            f"— {req_name} tarafından (panel)"
        )

        # ── Thread'e kapanış mesajı gönder ────────────────────────────
        if thread_id:
            try:
                thread = self.bot.get_channel(thread_id)
                if thread:
                    await thread.send(
                        f"🔒 **Content kapatıldı** — Panel üzerinden **{req_name}** tarafından.\n"
                        f"Katılımcı sayısı: **{len(participant_ids)}**"
                    )
            except Exception as e:
                print(f"[BRIDGE] Thread mesajı gönderilemedi: {e}")

        # ── Loot başlatma ─────────────────────────────────────────────
        if start_loot and thread_id and participant_ids:
            try:
                thread = self.bot.get_channel(thread_id)
                if thread:
                    participant_names_str = "\n".join(
                        [f"• {n}" for n in names[:20]]
                    )
                    if len(names) > 20:
                        participant_names_str += f"\n... +{len(names)-20} kişi"
                    await thread.send(
                        f"💰 **Loot dağıtımı başlatıldı!**\n"
                        f"Katılımcılar:\n{participant_names_str}\n\n"
                        f"Loot dağıtmak için thread içinde `/loot` komutunu kullan."
                    )
            except Exception as e:
                print(f"[BRIDGE] Loot mesajı gönderilemedi: {e}")

        # ── Google Sheets log (mevcut fonksiyonları çağır) ────────────
        try:
            if (
                getattr(bot_module, "GOOGLE_CREDS_JSON", None)
                and getattr(bot_module, "ACTIVITY_SHEET_ID", None)
            ):
                from datetime import datetime as _dt
                date_str = _dt.now(bot_module.TR_TZ).strftime("%Y-%m-%d")
                time_str = getattr(state, "time_tr", "") if state else ""

                # Content Log'a ekle
                loot_col, tick_col = await bot_module._add_content_to_log(
                    content_name, date_str, time_str or ""
                )
                if tick_col and names:
                    await bot_module._mark_content_participation(tick_col, names)

                # Puan Log
                await bot_module._write_content_count_to_puan_log(names)
        except Exception as e:
            print(f"[BRIDGE] Sheet log hatası: {e}")

        # ── State temizle ─────────────────────────────────────────────
        if msg_id:
            if msg_id in bot_module.EVENTS:
                # Ana mesajın view'ını kaldır
                try:
                    ch = self.bot.get_channel(
                        state.channel_id if state else 0
                    )
                    if ch:
                        msg = await ch.fetch_message(msg_id)
                        await msg.edit(view=None)
                except Exception:
                    pass
                bot_module.EVENTS.pop(msg_id, None)

            if msg_id in bot_module.SHEET_EVENTS:
                try:
                    ch = self.bot.get_channel(
                        sheet_state.channel_id if sheet_state else 0
                    )
                    if ch:
                        msg = await ch.fetch_message(msg_id)
                        await msg.edit(view=None)
                except Exception:
                    pass
                bot_module.SHEET_EVENTS.pop(msg_id, None)
                bot_module._save_sheet_events()

        # Reminder task iptal
        try:
            if msg_id and hasattr(self.bot, "content_reminders"):
                task = self.bot.content_reminders.pop(msg_id, None)
                if task:
                    task.cancel()
        except Exception:
            pass

        # active_events.json güncelle
        self.flush_active_events_force()
        print(f"[BRIDGE] close_content tamamlandı: '{content_name}'")

    async def _handle_reset_points(self, cmd: Dict) -> None:
        """
        Panel'den gelen reset_points komutunu işler.
        Tüm kullanıcıların total_points'ini sıfırlar.

        cmd örnek:
        {
            "action": "reset_points",
            "requested_by": 111111111,
            "requested_by_name": "Tunç",
            "ts": 1708200000
        }
        """
        try:
            import bot as bot_module  # type: ignore
        except ImportError:
            return

        req_name = cmd.get("requested_by_name") or "Panel"

        try:
            state = bot_module._load_puan_state()
            reset_count = 0

            for user_id_str, user_data in state.get("users", {}).items():
                if isinstance(user_data, dict):
                    user_data["total_points"] = 0.0
                    user_data["daily_points"] = 0.0
                    user_data["daily_minutes_counted"] = 0
                    reset_count += 1

            # Uyarı listelerini temizle
            state["warned_users"] = []
            state["kick_warned_users"] = []

            bot_module._save_puan_state(state)
            print(f"[BRIDGE] reset_points: {reset_count} kullanıcı sıfırlandı ({req_name} tarafından panel)")

            # Log kanalına bildir
            log_ch_id = getattr(bot_module, "PUAN_LOG_CHANNEL_ID", 0)
            if log_ch_id:
                try:
                    import discord as discord_module
                    ch = self.bot.get_channel(log_ch_id)
                    if ch:
                        embed = discord_module.Embed(
                            title="🔄 Puan Sıfırlama",
                            description=(
                                f"Tüm puanlar sıfırlandı.\n"
                                f"**İşlemi yapan:** {req_name} (Panel)\n"
                                f"**Etkilenen:** {reset_count} kullanıcı"
                            ),
                            color=0xFEE75C,
                        )
                        await ch.send(embed=embed)
                except Exception as e:
                    print(f"[BRIDGE] reset_points log kanalı hatası: {e}")

        except Exception as e:
            print(f"[BRIDGE] reset_points hatası: {e}")


# ── Yardımcı Fonksiyonlar ────────────────────────────────────────────────────

def _snowflake_to_ts(snowflake_id: int) -> int:
    """Discord Snowflake ID'den Unix timestamp (saniye) çıkarır."""
    try:
        return int((int(snowflake_id) >> 22) / 1000 + 1420070400)
    except Exception:
        return 0
