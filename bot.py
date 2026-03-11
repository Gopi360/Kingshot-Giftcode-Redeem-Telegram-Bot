"""
KingShot Gift Code Bot — Telegram Edition (Oracle Cloud / Polling Mode)
========================================================================
HashMap-based per-player code tracking:
  seen_codes.json = { "CODE123": ["pid1", "pid2"], "CODE456": ["pid1"] }

Thread safety:
  All file I/O is protected by threading.Lock() objects.
  check_and_redeem() uses an Event flag to prevent concurrent runs.

When a new player is added, any active codes they haven't claimed yet
are redeemed for them immediately in a background thread.

Network error handling:
  - Read timeouts  → silently ignored, polling auto-resumes
  - DNS failures   → waits RECONNECT_DELAY seconds and reconnects
  - Any crash      → outer while loop restarts polling immediately
"""

import os
import time
import json
import threading
import signal
import sys
import logging
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

import requests
import telebot
from apscheduler.schedulers.background import BackgroundScheduler

from redeemer import redeem_code_for_players

# ─── Config ────────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "PASTE_YOUR_TOKEN_HERE")
ADMIN_IDS = [
    int(x) for x in os.environ.get("ADMIN_IDS", "0").split(",")
    if x.strip().isdigit() and int(x.strip()) != 0
]
CHECK_INTERVAL  = int(os.environ.get("CHECK_INTERVAL", "2"))   # minutes
API_URL         = "https://kingshot.net/api/gift-codes"
PLAYERS_FILE    = "players.json"
SEEN_FILE       = "seen_codes.json"
RECONNECT_DELAY = 15   # seconds before reconnecting after a polling crash
BOT_START_TIME  = datetime.now()

# ─── Thread Safety ─────────────────────────────────────────────────────────
_players_lock  = threading.Lock()
_seen_lock     = threading.Lock()
_check_running = threading.Event()   # Set while check_and_redeem is active

# ─── Logging ───────────────────────────────────────────────────────────────
os.makedirs("logs", exist_ok=True)
log_file = f"logs/run_{datetime.now().strftime('%Y%m%d')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ─── Scheduler (global so commands can query next run time) ────────────────
scheduler = BackgroundScheduler()


# ─── Exception handler ─────────────────────────────────────────────────────

class BotExceptionHandler(telebot.ExceptionHandler):
    """
    Passed to infinity_polling so ALL exceptions are caught here
    instead of crashing the bot.
    Returning True = handled, polling continues.
    """
    def handle(self, exception):
        network_errors = (
            "Read timed out", "timed out", "getaddrinfo failed",
            "Failed to resolve", "ConnectionError", "Max retries exceeded",
            "RemoteDisconnected", "Connection reset", "Connection aborted",
            "NameResolutionError", "ConnectTimeoutError", "ReadTimeoutError",
        )
        err_str = str(exception)
        for kw in network_errors:
            if kw.lower() in err_str.lower():
                log.warning(f"⚠️  Network hiccup (auto-reconnect): {type(exception).__name__}")
                return True
        log.error(f"❌ Unhandled bot exception: {exception}", exc_info=True)
        return True  # Keep polling alive even on unknown errors


bot = telebot.TeleBot(BOT_TOKEN, threaded=True, exception_handler=BotExceptionHandler())


# ─── Storage helpers (all thread-safe) ─────────────────────────────────────

def load_players() -> list:
    with _players_lock:
        if not os.path.exists(PLAYERS_FILE):
            return []
        try:
            with open(PLAYERS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            log.error(f"Failed to load players: {e}")
            return []


def save_players(players: list):
    with _players_lock:
        try:
            with open(PLAYERS_FILE, "w", encoding="utf-8") as f:
                json.dump(players, f, indent=2, ensure_ascii=False)
        except IOError as e:
            log.error(f"Failed to save players: {e}")


def load_seen() -> dict:
    """HashMap: { "CODE123": ["pid1", "pid2"], ... }"""
    with _seen_lock:
        if not os.path.exists(SEEN_FILE):
            return {}
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            log.error(f"Failed to load seen codes: {e}")
            return {}


def save_seen(seen: dict):
    with _seen_lock:
        try:
            with open(SEEN_FILE, "w", encoding="utf-8") as f:
                json.dump(seen, f, indent=2, ensure_ascii=False)
        except IOError as e:
            log.error(f"Failed to save seen codes: {e}")


def mark_redeemed(seen: dict, code: str, pid: str):
    """Mark a player as having redeemed a code in the hashmap."""
    if code not in seen:
        seen[code] = []
    if pid not in seen[code]:
        seen[code].append(pid)


def has_redeemed(seen: dict, code: str, pid: str) -> bool:
    """Check hashmap — O(1) lookup."""
    return pid in seen.get(code, [])


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


# ─── Telegram helpers ──────────────────────────────────────────────────────

def safe_send(chat_id: int, text: str, parse_mode: str = "Markdown"):
    """Send a message, auto-splitting if it exceeds Telegram's 4096-char limit."""
    MAX = 4000
    if len(text) <= MAX:
        try:
            bot.send_message(chat_id, text, parse_mode=parse_mode)
        except Exception as e:
            log.warning(f"safe_send failed for {chat_id}: {e}")
        return
    # Split on newlines to preserve formatting
    chunks, current = [], ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > MAX:
            chunks.append(current)
            current = ""
        current += line + "\n"
    if current.strip():
        chunks.append(current)
    for chunk in chunks:
        try:
            bot.send_message(chat_id, chunk, parse_mode=parse_mode)
        except Exception as e:
            log.warning(f"safe_send chunk failed for {chat_id}: {e}")
        time.sleep(0.3)  # avoid flood limits


def notify_admins(text: str):
    for admin_id in ADMIN_IDS:
        safe_send(admin_id, text)


def get_uptime() -> str:
    delta = datetime.now() - BOT_START_TIME
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"


def get_next_check_str() -> str:
    try:
        job = scheduler.get_job("gift_code_check")
        if job and job.next_run_time:
            return job.next_run_time.strftime("%H:%M:%S")
    except Exception:
        pass
    return "Unknown"


# ─── Bot Commands ──────────────────────────────────────────────────────────

@bot.message_handler(commands=["start", "help"])
def cmd_help(message):
    bot.reply_to(message, (
        "🎮 *KingShot Gift Code Bot*\n\n"
        "━━━ *Player Management* ━━━\n"
        "`/addplayer <id> <name>` — Register one player\n"
        "`/addplayers` — Bulk add (one `id name` per line)\n"
        "`/removeplayer <id>` — Remove a player\n"
        "`/listplayers` — Show all registered players\n\n"
        "━━━ *Code Management* ━━━\n"
        "`/listcodes` — Show all tracked gift codes\n"
        "`/addcode <code>` — Manually force-redeem a code\n"
        "`/clearcode <code>` — Re-queue code for ALL players\n"
        "`/mystatus <id>` — Player's redemption history\n"
        "`/resetplayer <id>` — Re-queue all codes for a player\n\n"
        "━━━ *Bot Control* ━━━\n"
        "`/checkcode` — Force a gift code check right now\n"
        "`/nextcheck` — When is the next scheduled check\n"
        "`/status` — Bot status + uptime\n"
        "`/ping` — Quick alive check\n\n"
        f"_Auto-checks every {CHECK_INTERVAL} min_ 🚀"
    ), parse_mode="Markdown")


@bot.message_handler(commands=["ping"])
def cmd_ping(message):
    bot.reply_to(message, "🏓 Pong! Bot is alive and kicking.")


@bot.message_handler(commands=["addplayer"])
def cmd_add_player(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Access denied.")
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(message, (
            "❌ Usage: `/addplayer <player_id> <name>`\n"
            "Example: `/addplayer 876734319 Gopi`"
        ), parse_mode="Markdown")
        return
    pid, name = parts[1].strip(), parts[2].strip()
    if not pid.isdigit():
        bot.reply_to(message, "❌ Player ID must be numeric.", parse_mode="Markdown")
        return

    players = load_players()
    if any(p["id"] == pid for p in players):
        bot.reply_to(message, f"⚠️ Player `{pid}` is already registered.", parse_mode="Markdown")
        return

    players.append({"id": pid, "name": name, "added": datetime.now().isoformat()})
    save_players(players)

    seen      = load_seen()
    unclaimed = [code for code in seen if not has_redeemed(seen, code, pid)]

    msg = f"✅ Added *{name}* (`{pid}`)\n"
    if unclaimed:
        msg += f"\n🎁 Found *{len(unclaimed)}* active code(s) — redeeming now..."
        bot.reply_to(message, msg, parse_mode="Markdown")
        threading.Thread(
            target=redeem_for_new_player,
            args=(pid, name, unclaimed),
            daemon=True
        ).start()
    else:
        msg += "\n_No active codes right now — future ones will be auto-claimed._"
        bot.reply_to(message, msg, parse_mode="Markdown")
    log.info(f"Player added: {name} ({pid})")


@bot.message_handler(commands=["addplayers"])
def cmd_add_players_bulk(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Access denied.")
        return

    lines = message.text.split("\n")[1:]
    lines = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]

    if not lines:
        bot.reply_to(message, (
            "❌ Usage — one player per line after the command:\n\n"
            "`/addplayers`\n`876734319 Gopi`\n`123456789 Arjun`"
        ), parse_mode="Markdown")
        return

    players = load_players()
    seen    = load_seen()
    added, skipped = [], []

    for line in lines:
        parts = line.split(maxsplit=1)
        if len(parts) < 2:
            skipped.append(f"`{line}` — missing name")
            continue
        pid, name = parts[0].strip(), parts[1].strip()
        if not pid.isdigit():
            skipped.append(f"`{line}` — ID must be numeric")
            continue
        if any(p["id"] == pid for p in players):
            skipped.append(f"`{pid}` ({name}) — already exists")
            continue
        players.append({"id": pid, "name": name, "added": datetime.now().isoformat()})
        added.append((pid, name))

    if added:
        save_players(players)

    msg = ""
    if added:
        msg += f"✅ *Added {len(added)} player(s):*\n"
        msg += "\n".join(f"  • {n} (`{p}`)" for p, n in added)
    if skipped:
        msg += f"\n\n⚠️ *Skipped {len(skipped)}:*\n"
        msg += "\n".join(f"  • {s}" for s in skipped)

    bot.reply_to(message, msg or "Nothing to do.", parse_mode="Markdown")
    log.info(f"Bulk add: {len(added)} added, {len(skipped)} skipped")

    # Immediately redeem unclaimed codes for newly added players
    for pid, name in added:
        unclaimed = [code for code in seen if not has_redeemed(seen, code, pid)]
        if unclaimed:
            threading.Thread(
                target=redeem_for_new_player,
                args=(pid, name, unclaimed),
                daemon=True
            ).start()


@bot.message_handler(commands=["removeplayer"])
def cmd_remove_player(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Access denied.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "❌ Usage: `/removeplayer <player_id>`", parse_mode="Markdown")
        return
    pid     = parts[1].strip()
    players = load_players()
    target  = next((p for p in players if p["id"] == pid), None)
    if not target:
        bot.reply_to(message, f"❌ Player `{pid}` not found.", parse_mode="Markdown")
        return
    updated = [p for p in players if p["id"] != pid]
    save_players(updated)
    bot.reply_to(message, f"🗑 Removed *{target['name']}* (`{pid}`)", parse_mode="Markdown")
    log.info(f"Player removed: {target['name']} ({pid})")


@bot.message_handler(commands=["listplayers"])
def cmd_list_players(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Access denied.")
        return
    players = load_players()
    if not players:
        bot.reply_to(message, "No players yet.\nUse `/addplayer <id> <name>` to add one.", parse_mode="Markdown")
        return
    seen        = load_seen()
    total_codes = len(seen)
    lines = []
    for i, p in enumerate(players, 1):
        claimed = sum(1 for code in seen if has_redeemed(seen, code, p["id"]))
        bar = "▓" * claimed + "░" * (total_codes - claimed) if total_codes else ""
        lines.append(f"{i}. *{p['name']}* — `{p['id']}`\n   ✅ {claimed}/{total_codes} {bar}")
    safe_send(
        message.chat.id,
        f"👥 *Registered Players ({len(players)}):*\n\n" + "\n\n".join(lines)
    )


@bot.message_handler(commands=["listcodes"])
def cmd_list_codes(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Access denied.")
        return
    seen    = load_seen()
    players = load_players()
    total   = len(players)
    if not seen:
        bot.reply_to(message, "📭 No gift codes tracked yet.", parse_mode="Markdown")
        return
    lines = []
    for code, redeemed_by in seen.items():
        n   = len(redeemed_by)
        bar = "▓" * n + "░" * max(0, total - n) if total > 0 else ""
        lines.append(f"`{code}` — {n}/{total} {bar}")
    safe_send(
        message.chat.id,
        f"🎁 *Tracked Gift Codes ({len(seen)}):*\n\n" + "\n".join(lines)
    )


@bot.message_handler(commands=["addcode"])
def cmd_add_code(message):
    """Manually force-redeem a specific code for all players who haven't claimed it."""
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Access denied.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "❌ Usage: `/addcode <CODE>`", parse_mode="Markdown")
        return
    code    = parts[1].strip().upper()
    players = load_players()
    if not players:
        bot.reply_to(message, "⚠️ No players registered yet.", parse_mode="Markdown")
        return
    bot.reply_to(message, f"🚀 Queuing manual redemption for `{code}`...", parse_mode="Markdown")
    threading.Thread(target=_manual_redeem, args=(code,), daemon=True).start()


def _manual_redeem(code: str):
    """Background worker for /addcode."""
    seen    = load_seen()
    players = load_players()
    pending = [(p["id"], p["name"]) for p in players if not has_redeemed(seen, code, p["id"])]
    if not pending:
        notify_admins(f"ℹ️ All players have already claimed `{code}`.")
        return
    notify_admins(f"🎁 Manually redeeming `{code}` for *{len(pending)}* player(s)...")
    results = redeem_code_for_players(code, pending, log)
    for pid, name in pending:
        if results.get(pid):
            mark_redeemed(seen, code, pid)
    save_seen(seen)
    ok   = sum(1 for pid, _ in pending if results.get(pid))
    fail = len(pending) - ok
    notify_admins(f"📊 `{code}` manual redemption: ✅ {ok} claimed  ❌ {fail} failed")


@bot.message_handler(commands=["mystatus"])
def cmd_my_status(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Access denied.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "❌ Usage: `/mystatus <player_id>`", parse_mode="Markdown")
        return
    pid    = parts[1].strip()
    player = next((p for p in load_players() if p["id"] == pid), None)
    if not player:
        bot.reply_to(message, f"❌ Player `{pid}` not found.", parse_mode="Markdown")
        return
    seen      = load_seen()
    claimed   = [c for c in seen if has_redeemed(seen, c, pid)]
    unclaimed = [c for c in seen if not has_redeemed(seen, c, pid)]
    msg  = f"📊 *{player['name']}* (`{pid}`)\n\n"
    msg += f"✅ Claimed ({len(claimed)}): "
    msg += ("`" + "`, `".join(claimed) + "`" if claimed else "_none_") + "\n"
    msg += f"⏳ Pending ({len(unclaimed)}): "
    msg += ("`" + "`, `".join(unclaimed) + "`" if unclaimed else "_none_")
    safe_send(message.chat.id, msg)


@bot.message_handler(commands=["resetplayer"])
def cmd_reset_player(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Access denied.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "❌ Usage: `/resetplayer <player_id>`", parse_mode="Markdown")
        return
    pid    = parts[1].strip()
    player = next((p for p in load_players() if p["id"] == pid), None)
    if not player:
        bot.reply_to(message, f"❌ Player `{pid}` not found.", parse_mode="Markdown")
        return
    seen  = load_seen()
    count = 0
    for code in seen:
        if pid in seen[code]:
            seen[code].remove(pid)
            count += 1
    save_seen(seen)
    bot.reply_to(
        message,
        f"🔄 Reset *{count}* code(s) for *{player['name']}* — will re-redeem on next check.",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["clearcode"])
def cmd_clearcode(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Access denied.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "❌ Usage: `/clearcode <code>`", parse_mode="Markdown")
        return
    code = parts[1].strip().upper()
    seen = load_seen()
    if code not in seen:
        bot.reply_to(message, f"⚠️ Code `{code}` is not in the tracked list.", parse_mode="Markdown")
        return
    count = len(seen[code])
    del seen[code]
    save_seen(seen)
    bot.reply_to(
        message,
        f"✅ Cleared `{code}` — removed {count} redemption record(s).\n"
        f"Will re-run for all players on next check.",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["checkcode"])
def cmd_checkcode(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Access denied.")
        return
    if _check_running.is_set():
        bot.reply_to(message, "⏳ A check is already in progress. Please wait...", parse_mode="Markdown")
        return
    bot.reply_to(message, "🔍 Running a gift code check right now...")
    threading.Thread(target=check_and_redeem, daemon=True).start()


@bot.message_handler(commands=["nextcheck"])
def cmd_next_check(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔ Access denied.")
        return
    if _check_running.is_set():
        bot.reply_to(message, "🔄 A check is currently running...", parse_mode="Markdown")
    else:
        bot.reply_to(
            message,
            f"⏰ Next scheduled check at: `{get_next_check_str()}`",
            parse_mode="Markdown"
        )


@bot.message_handler(commands=["status"])
def cmd_status(message):
    players = load_players()
    seen    = load_seen()
    total_redemptions = sum(len(v) for v in seen.values())
    check_status = "🔄 *Running now*" if _check_running.is_set() else f"⏰ Next: `{get_next_check_str()}`"
    bot.reply_to(message, (
        "✅ *KingShot Bot — Status*\n\n"
        f"👥 Players registered : `{len(players)}`\n"
        f"🎁 Codes tracked      : `{len(seen)}`\n"
        f"🏅 Total redemptions  : `{total_redemptions}`\n"
        f"⏱  Check interval     : every `{CHECK_INTERVAL}` min\n"
        f"🕐 Uptime             : `{get_uptime()}`\n"
        f"📡 Scheduler          : {check_status}\n"
        f"🖥  Mode               : Polling (Oracle Cloud)"
    ), parse_mode="Markdown")


# ─── Core redemption logic ─────────────────────────────────────────────────

def fetch_active_codes() -> list:
    """
    Fetch active gift codes from the API.
    Retries up to 3 times on failure.
    Handles multiple possible API response shapes.
    """
    headers = {"User-Agent": "Mozilla/5.0 KingShot-GiftBot/2.0"}
    for attempt in range(1, 4):
        try:
            r = requests.get(API_URL, headers=headers, timeout=15)
            r.raise_for_status()
            data = r.json()

            # Try every known response shape
            raw = (
                data.get("data", {}).get("giftCodes")
                or data.get("giftCodes")
                or data.get("codes")
                or data.get("data")
                or []
            )
            if not isinstance(raw, list):
                log.warning(f"Unexpected API response shape: {type(raw)}")
                return []

            result = []
            for c in raw:
                if isinstance(c, str) and c.strip():
                    result.append(c.strip().upper())
                elif isinstance(c, dict):
                    code_val = (
                        c.get("code") or c.get("gift_code")
                        or c.get("giftCode") or c.get("name") or ""
                    )
                    if code_val:
                        result.append(str(code_val).strip().upper())
            return result

        except requests.exceptions.HTTPError as e:
            log.error(f"API HTTP error (attempt {attempt}/3): {e}")
        except requests.exceptions.ConnectionError as e:
            log.error(f"API connection error (attempt {attempt}/3): {e}")
        except requests.exceptions.Timeout:
            log.error(f"API timeout (attempt {attempt}/3)")
        except Exception as e:
            log.error(f"API unexpected error (attempt {attempt}/3): {e}")

        if attempt < 3:
            time.sleep(5)

    return []


def redeem_for_new_player(pid: str, name: str, codes: list):
    """Called immediately when a new player is added and has unclaimed codes."""
    seen = load_seen()
    ok_count = fail_count = 0
    for code in codes:
        if has_redeemed(seen, code, pid):
            continue
        log.info(f"Redeeming old code [{code}] for new player {name} ({pid})")
        results = redeem_code_for_players(code, [(pid, name)], log)
        if results.get(pid):
            mark_redeemed(seen, code, pid)
            save_seen(seen)
            ok_count += 1
        else:
            fail_count += 1
    notify_admins(
        f"✅ Finished catch-up for *{name}* (`{pid}`)\n"
        f"  ✅ {ok_count} claimed  ❌ {fail_count} failed"
    )


def check_and_redeem():
    """
    Main scheduled job — runs every CHECK_INTERVAL minutes.

    - Protected by _check_running Event to prevent concurrent runs.
    - Announces NEW codes with a special notification.
    - Failed players are NOT marked done — retried next cycle.
    - Saves seen_codes.json after every code to minimize data loss.
    """
    if _check_running.is_set():
        log.warning("check_and_redeem already running — skipping this cycle.")
        return

    _check_running.set()
    try:
        log.info("─── Checking for new gift codes ───")
        active_codes = fetch_active_codes()
        if not active_codes:
            log.info("No active codes returned from API.")
            return

        log.info(f"API returned {len(active_codes)} code(s): {active_codes}")
        players = load_players()
        if not players:
            log.warning("No players configured — skipping redemption.")
            return

        seen          = load_seen()
        any_work_done = False

        for code in active_codes:
            is_new = code not in seen
            pending = [
                (p["id"], p["name"])
                for p in players
                if not has_redeemed(seen, code, p["id"])
            ]

            if not pending:
                log.info(f"[{code}] All {len(players)} players already redeemed. Skipping.")
                continue

            any_work_done = True

            if is_new:
                notify_admins(
                    f"🆕 *New gift code detected!*\n"
                    f"Code: `{code}`\n"
                    f"Redeeming for *{len(pending)}* player(s)..."
                )
            else:
                log.info(f"[{code}] Retrying {len(pending)} failed player(s).")
                notify_admins(f"🔄 Retrying `{code}` for *{len(pending)}* failed player(s)...")

            results = redeem_code_for_players(code, pending, log)

            for pid, name in pending:
                if results.get(pid):
                    mark_redeemed(seen, code, pid)
                    log.info(f"  ✅ {name} ({pid}) → {code}")
                else:
                    log.warning(f"  ❌ {name} ({pid}) failed → will retry next cycle")

            # Save after every code so a crash doesn't lose all progress
            save_seen(seen)

            ok   = sum(1 for pid, _ in pending if results.get(pid))
            fail = len(pending) - ok
            notify_admins(f"📊 `{code}`: ✅ {ok} claimed  ❌ {fail} failed")

        if not any_work_done:
            log.info("Nothing to do — all players are up to date.")
        else:
            notify_admins("✅ *Redemption round complete!*")

        log.info("─── Check complete ───\n")

    except Exception as e:
        log.error(f"Unexpected error in check_and_redeem: {e}", exc_info=True)
        notify_admins(f"❌ Error during code check: `{e}`")
    finally:
        _check_running.clear()


# ─── Entry point ───────────────────────────────────────────────────────────

def main():
    log.info("╔═══════════════════════════════════════════════╗")
    log.info("║  KingShot Auto Gift Code Bot (Oracle Cloud)   ║")
    log.info("╚═══════════════════════════════════════════════╝")
    log.info(f"Admin IDs      : {ADMIN_IDS}")
    log.info(f"Check interval : {CHECK_INTERVAL} min")
    log.info(f"API endpoint   : {API_URL}")

    if not ADMIN_IDS:
        log.critical("❌ No valid ADMIN_IDS configured! Set ADMIN_IDS in .env or service file.")
        sys.exit(1)

    if BOT_TOKEN == "PASTE_YOUR_TOKEN_HERE":
        log.critical("❌ BOT_TOKEN not configured! Set TELEGRAM_BOT_TOKEN in .env or service file.")
        sys.exit(1)

    # Graceful shutdown on SIGINT/SIGTERM
    def shutdown(signum, frame):
        log.info("Shutting down gracefully...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Start background scheduler
    scheduler.add_job(
        check_and_redeem,
        "interval",
        minutes=CHECK_INTERVAL,
        id="gift_code_check"
    )
    scheduler.start()
    log.info(f"✅ Scheduler started — checks every {CHECK_INTERVAL} min")

    # Run one check immediately at startup
    threading.Thread(target=check_and_redeem, daemon=True).start()

    # Notify admins the bot has started
    notify_admins(
        f"🟢 *KingShot Bot started!*\n"
        f"👥 Players: `{len(load_players())}`\n"
        f"⏱ Auto-check every `{CHECK_INTERVAL}` min\n"
        f"Type /help for all commands."
    )

    # Telegram polling with outer while loop for crash recovery
    while True:
        try:
            log.info("✅ Starting Telegram polling...")
            bot.infinity_polling(
                timeout=60,
                long_polling_timeout=30,
                skip_pending=True
            )
        except Exception as e:
            log.error(f"❌ infinity_polling crashed: {e}")
            log.info(f"🔄 Reconnecting in {RECONNECT_DELAY}s...")
            time.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    main()