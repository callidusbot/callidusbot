"""
panel_bridge.py  —  Web panel ↔ Discord bot köprüsü
====================================================
Circular import YOK. Bot modülü referansları start() içinde inject edilir.
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


QUEUE_POLL_SECONDS = 3
ACTIVE_EVENTS_FLUSH_DEBOUNCE = 1


def _atomic_write_json(path: Path, data: Any) -> None:
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        print(f"[BRIDGE] write hatası ({path.name}): {e}")
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def _read_json(path: Path, fallback: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[BRIDGE] read hatası ({path.name}): {e}")
    return fallback


def _snowflake_to_ts(snowflake_id: int) -> int:
    try:
        return int((int(snowflake_id) >> 22) / 1000 + 1420070400)
    except Exception:
        return 0


class PanelBridge:
    def __init__(self, bot, base_dir: str):
        self.bot = bot
        self.base = Path(base_dir)

        self.active_events_file = self.base / "data" / "active_events.json"
        self.puan_config_file   = self.base / "data" / "puan_config.json"
        self.queue_file         = self.base / "bot_commands" / "queue.jsonl"
        self.queue_done_file    = self.base / "bot_commands" / "queue_done.jsonl"

        for f in [self.active_events_file, self.queue_file]:
            f.parent.mkdir(parents=True, exist_ok=True)

        self._last_flush: float = 0.0
        self._processed_queue_keys: set = set()
        self._bm: Any = None  # bot module ref

        print("[BRIDGE] PanelBridge oluşturuldu.")

    # ── Public API ─────────────────────────────────────────────────────────

    async def start(self) -> None:
        await self.bot.wait_until_ready()
        try:
            import importlib
            self._bm = importlib.import_module("bot")
            print("[BRIDGE] Bot modülü referansı alındı.")
        except Exception as e:
            print(f"[BRIDGE] Bot modülü alınamadı: {e}")

        self._apply_puan_config()
        self._write_active_events()
        self.bot.loop.create_task(self._queue_loop())
        print(f"[BRIDGE] Hazır.")

    def flush_active_events(self) -> None:
        now = time.monotonic()
        if now - self._last_flush < ACTIVE_EVENTS_FLUSH_DEBOUNCE:
            return
        self._last_flush = now
        self._write_active_events()

    def flush_active_events_force(self) -> None:
        self._last_flush = 0.0
        self._write_active_events()

    # ── active_events.json ─────────────────────────────────────────────────

    def _write_active_events(self) -> None:
        bm = self._bm
        if bm is None:
            return

        EVENTS       = getattr(bm, "EVENTS", {})
        SHEET_EVENTS = getattr(bm, "SHEET_EVENTS", {})
        guild_id     = getattr(bm, "GUILD_ID", 0)
        guild        = self.bot.get_guild(guild_id)

        def _member_info(owner_id):
            name, avatar = "Unknown", ""
            if guild:
                m = guild.get_member(owner_id)
                if m:
                    name = m.display_name
                    try:
                        avatar = str(m.display_avatar.replace(size=64).url)
                    except Exception:
                        pass
            return name, avatar

        events: List[Dict] = []

        for msg_id, state in list(EVENTS.items()):
            try:
                tpl = state.template
                pids: List[int] = []
                seen: set = set()
                for role, _ in tpl.roles:
                    for uid in state.roster.get(role, []):
                        if uid not in seen:
                            pids.append(uid); seen.add(uid)
                name, avatar = _member_info(state.owner_id)
                events.append({
                    "event_id": f"ev_{msg_id}", "template_key": tpl.key,
                    "template_title": tpl.title, "started_by": state.owner_id,
                    "started_by_name": name, "started_by_avatar": avatar,
                    "started_at": _snowflake_to_ts(msg_id), "thread_id": state.thread_id,
                    "participants": pids, "participant_count": len(pids),
                    "status": "active", "source": "normal",
                })
            except Exception as e:
                print(f"[BRIDGE] EventState hata {msg_id}: {e}")

        for msg_id, st in list(SHEET_EVENTS.items()):
            try:
                pids = list(getattr(st, "user_slot", {}).keys())
                name, avatar = _member_info(st.owner_id)
                events.append({
                    "event_id": f"sh_{msg_id}", "template_key": getattr(st, "sheet_tab", "sheet"),
                    "template_title": getattr(st, "title", "Sheet Event"), "started_by": st.owner_id,
                    "started_by_name": name, "started_by_avatar": avatar,
                    "started_at": _snowflake_to_ts(msg_id), "thread_id": st.thread_id,
                    "participants": pids, "participant_count": len(pids),
                    "status": "active", "source": "sheet",
                })
            except Exception as e:
                print(f"[BRIDGE] SheetEventState hata {msg_id}: {e}")

        _atomic_write_json(self.active_events_file, events)
        print(f"[BRIDGE] active_events.json → {len(events)} event")

    # ── puan_config.json ───────────────────────────────────────────────────

    def _apply_puan_config(self) -> None:
        bm = self._bm
        cfg = _read_json(self.puan_config_file)
        if not cfg or not isinstance(cfg, dict) or bm is None:
            return
        voice = cfg.get("voice", {})
        if not isinstance(voice, dict):
            return
        changed = []
        if (v := voice.get("puan_per_minute")) is not None:
            bm.PUAN_PER_MINUTE = float(v); changed.append(f"ppm={v}")
        if (v := voice.get("daily_max")) is not None:
            bm.PUAN_DAILY_MAX = float(v); changed.append(f"dmax={v}")
        if (v := voice.get("warning_threshold")) is not None:
            bm.PUAN_WARNING_THRESHOLD = float(v); changed.append(f"warn={v}")
        if (v := voice.get("kick_threshold")) is not None:
            bm.PUAN_KICK_THRESHOLD = float(v); changed.append(f"kick={v}")
        if changed:
            print(f"[BRIDGE] Puan config: {', '.join(changed)}")

    # ── Queue loop ─────────────────────────────────────────────────────────

    async def _queue_loop(self) -> None:
        print(f"[BRIDGE] Queue loop başladı ({QUEUE_POLL_SECONDS}s)")
        while not self.bot.is_closed():
            try:
                await self._process_queue()
            except Exception as e:
                print(f"[BRIDGE] Queue loop hatası: {e}")
            await asyncio.sleep(QUEUE_POLL_SECONDS)

    async def _process_queue(self) -> None:
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
        for line in lines:
            try:
                cmd = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = f"{cmd.get('action','')}_{cmd.get('ts', id(cmd))}"
            if key not in self._processed_queue_keys:
                pending.append((key, cmd))

        try:
            self.queue_file.write_text("", encoding="utf-8")
        except Exception:
            pass

        if not pending:
            return

        processed = []
        for key, cmd in pending:
            action = cmd.get("action", "")
            try:
                if action == "close_content":
                    await self._handle_close_content(cmd)
                elif action == "reset_points":
                    await self._handle_reset_points(cmd)
                elif action == "reload_templates":
                    bm = self._bm
                    if bm and hasattr(bm, "reload_presets"):
                        bm.reload_presets()
                        print("[BRIDGE] Templates yeniden yüklendi.")
                else:
                    print(f"[BRIDGE] Bilinmeyen action: {action}")
                self._processed_queue_keys.add(key)
                processed.append({**cmd, "processed_at": datetime.now(timezone.utc).isoformat()})
            except Exception as e:
                print(f"[BRIDGE] Komut hatası [{action}]: {e}")

        if processed:
            try:
                with self.queue_done_file.open("a", encoding="utf-8") as f:
                    for c in processed:
                        f.write(json.dumps(c, ensure_ascii=False) + "\n")
            except Exception:
                pass

        if len(self._processed_queue_keys) > 2000:
            self._processed_queue_keys = set(list(self._processed_queue_keys)[-1000:])

    # ── close_content handler ──────────────────────────────────────────────

    async def _handle_close_content(self, cmd: Dict) -> None:
        bm = self._bm
        if bm is None:
            return

        EVENTS       = getattr(bm, "EVENTS", {})
        SHEET_EVENTS = getattr(bm, "SHEET_EVENTS", {})
        guild_id     = getattr(bm, "GUILD_ID", 0)

        event_id   = cmd.get("event_id", "")
        thread_id  = int(cmd.get("thread_id") or 0)
        start_loot = bool(cmd.get("start_loot", False))
        req_name   = cmd.get("requested_by_name") or "Panel"

        msg_id: Optional[int] = None
        if event_id.startswith("ev_"):
            try: msg_id = int(event_id[3:])
            except ValueError: pass
        elif event_id.startswith("sh_"):
            try: msg_id = int(event_id[3:])
            except ValueError: pass

        guild = self.bot.get_guild(guild_id)
        if not guild:
            print("[BRIDGE] close_content: Guild bulunamadı.")
            return

        state = sheet_state = None
        if msg_id:
            state = EVENTS.get(msg_id)
            if not state:
                sheet_state = SHEET_EVENTS.get(msg_id)

        if not state and not sheet_state and thread_id:
            for mid, s in list(EVENTS.items()):
                if s.thread_id == thread_id:
                    state = s; msg_id = mid; break
            if not state:
                for mid, s in list(SHEET_EVENTS.items()):
                    if s.thread_id == thread_id:
                        sheet_state = s; msg_id = mid; break

        if not state and not sheet_state:
            print(f"[BRIDGE] close_content: {event_id} bulunamadı.")
            self.flush_active_events_force()
            return

        participant_ids: List[int] = []
        names: List[str] = []
        content_name = ""

        if state:
            content_name = (state.template.thread_name or state.template.key or "CONTENT").strip()
            seen: set = set()
            for role, _ in state.template.roles:
                for uid in state.roster.get(role, []):
                    if uid not in seen:
                        participant_ids.append(uid); seen.add(uid)
        else:
            content_name = (getattr(sheet_state, "title", "") or "SHEET CONTENT").strip()
            participant_ids = list(getattr(sheet_state, "user_slot", {}).keys())

        for uid in participant_ids:
            m = guild.get_member(uid)
            names.append(m.display_name if m else str(uid))

        print(f"[BRIDGE] close_content: '{content_name}' ({len(participant_ids)} kişi) — {req_name}")

        if thread_id:
            try:
                thread = self.bot.get_channel(thread_id)
                if thread:
                    await thread.send(
                        f"🔒 **Content kapatıldı** — **{req_name}** (Panel)\n"
                        f"Katılımcı: **{len(participant_ids)}**"
                    )
            except Exception as e:
                print(f"[BRIDGE] Thread mesajı hatası: {e}")

        if start_loot and thread_id and participant_ids:
            try:
                thread = self.bot.get_channel(thread_id)
                if thread:
                    ls = "\n".join(f"• {n}" for n in names[:20])
                    if len(names) > 20:
                        ls += f"\n… +{len(names)-20} kişi"
                    await thread.send(f"💰 Loot için `/loot` komutunu kullan.\nKatılımcılar:\n{ls}")
            except Exception as e:
                print(f"[BRIDGE] Loot mesajı hatası: {e}")

        try:
            TR_TZ = getattr(bm, "TR_TZ", None)
            gcreds = getattr(bm, "GOOGLE_CREDS_JSON", None)
            sheet_id = getattr(bm, "ACTIVITY_SHEET_ID", None)
            if gcreds and sheet_id and TR_TZ:
                date_str = datetime.now(TR_TZ).strftime("%Y-%m-%d")
                time_str = getattr(state, "time_tr", "") if state else ""
                loot_col, tick_col = await bm._add_content_to_log(content_name, date_str, time_str or "")
                if tick_col and names:
                    await bm._mark_content_participation(tick_col, names)
                await bm._write_content_count_to_puan_log(names)
        except Exception as e:
            print(f"[BRIDGE] Sheet log hatası: {e}")

        if msg_id:
            if msg_id in EVENTS:
                try:
                    ch = self.bot.get_channel(state.channel_id)
                    if ch:
                        msg = await ch.fetch_message(msg_id)
                        await msg.edit(view=None)
                except Exception:
                    pass
                EVENTS.pop(msg_id, None)

            if msg_id in SHEET_EVENTS:
                try:
                    ch = self.bot.get_channel(sheet_state.channel_id)
                    if ch:
                        msg = await ch.fetch_message(msg_id)
                        await msg.edit(view=None)
                except Exception:
                    pass
                SHEET_EVENTS.pop(msg_id, None)
                try:
                    bm._save_sheet_events()
                except Exception:
                    pass

        try:
            if msg_id and hasattr(self.bot, "content_reminders"):
                task = self.bot.content_reminders.pop(msg_id, None)
                if task:
                    task.cancel()
        except Exception:
            pass

        self.flush_active_events_force()
        print(f"[BRIDGE] close_content tamamlandı: '{content_name}'")

    # ── reset_points handler ───────────────────────────────────────────────

    async def _handle_reset_points(self, cmd: Dict) -> None:
        bm = self._bm
        if bm is None:
            return

        req_name = cmd.get("requested_by_name") or "Panel"
        try:
            state = bm._load_puan_state()
            count = 0
            for _, ud in state.get("users", {}).items():
                if isinstance(ud, dict):
                    ud["total_points"] = 0.0
                    ud["daily_points"] = 0.0
                    ud["daily_minutes_counted"] = 0
                    count += 1
            state["warned_users"] = []
            state["kick_warned_users"] = []
            bm._save_puan_state(state)
            print(f"[BRIDGE] reset_points: {count} kullanıcı sıfırlandı ({req_name})")

            ch_id = getattr(bm, "PUAN_LOG_CHANNEL_ID", 0)
            if ch_id:
                try:
                    import discord as _discord
                    ch = self.bot.get_channel(int(ch_id))
                    if ch:
                        embed = _discord.Embed(
                            title="🔄 Puan Sıfırlama",
                            description=f"Tüm puanlar sıfırlandı.\n**Yapan:** {req_name} (Panel)\n**Etkilenen:** {count} kullanıcı",
                            color=0xFEE75C,
                        )
                        await ch.send(embed=embed)
                except Exception as e:
                    print(f"[BRIDGE] Log kanalı hatası: {e}")
        except Exception as e:
            print(f"[BRIDGE] reset_points hatası: {e}")
