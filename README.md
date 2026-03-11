# KingShot Gift Code Bot — Oracle Cloud Edition

> Runs 24/7 for free on Oracle Cloud Free Tier.
> No Flask, no webhooks, no UptimeRobot — just a simple persistent bot.

---

## 📖 Full Deployment Guide

**New to this? Follow the complete step-by-step guide:**

👉 **[ORACLE-DEPLOY-GUIDE.md](./ORACLE-DEPLOY-GUIDE.md)**

It covers everything: creating an Oracle account, launching a VM, uploading files, configuring tokens, setting up systemd, and troubleshooting.

---

## Quick Start (if you've done this before)

```bash
# 1. SSH into your VM
ssh ubuntu@YOUR_VM_PUBLIC_IP

# 2. Upload files and run setup
bash setup_oracle.sh

# 3. Configure your tokens
cp .env.example .env
nano .env

# 4. Test manually
python3 bot.py

# 5. Install as a system service
sudo cp kingshot.service /etc/systemd/system/kingshot.service
sudo systemctl daemon-reload
sudo systemctl enable kingshot
sudo systemctl start kingshot
sudo systemctl status kingshot
```

---

## Daily Usage

### View live logs
```bash
journalctl -u kingshot -f
```

### Restart the bot
```bash
sudo systemctl restart kingshot
```

### Stop the bot
```bash
sudo systemctl stop kingshot
```

### Update the code
```bash
cd /home/ubuntu/kingshot-bot
git pull                             # If using GitHub
sudo systemctl restart kingshot
```

---

## Bot Commands (via Telegram)

### Player Management
| Command | Description |
|---------|-------------|
| `/addplayer 876734319 Gopi` | Register a player (admin only) |
| `/addplayers` | Bulk add players — one `id name` per line (admin only) |
| `/removeplayer 876734319` | Remove a player (admin only) |
| `/listplayers` | Show all players with redemption progress |

### Code Management
| Command | Description |
|---------|-------------|
| `/listcodes` | Show all tracked gift codes and claim counts |
| `/addcode CODE123` | Manually force-redeem a code for all players (admin only) |
| `/clearcode CODE123` | Re-queue a code to be redeemed again for all players (admin only) |
| `/mystatus 876734319` | Show which codes a specific player has claimed |
| `/resetplayer 876734319` | Re-queue ALL codes for one player (admin only) |

### Bot Control
| Command | Description |
|---------|-------------|
| `/checkcode` | Force a gift code check right now (admin only) |
| `/nextcheck` | Show when the next scheduled check fires (admin only) |
| `/status` | Show bot status, uptime, and player count |
| `/ping` | Quick alive check |
| `/help` | Show command list |

---

## File Structure

| File | Purpose |
|------|---------|
| `bot.py` | Main bot — Telegram polling + APScheduler |
| `redeemer.py` | Selenium redemption logic |
| `.env.example` | Template for your tokens — copy to `.env` |
| `.env` | Your actual tokens (never commit this to GitHub) |
| `kingshot.service` | systemd service for auto-start |
| `setup_oracle.sh` | One-shot setup script for the VM |
| `ORACLE-DEPLOY-GUIDE.md` | Full step-by-step deployment guide |
| `players.json` | Auto-created — stores registered player IDs |
| `seen_codes.json` | Auto-created — tracks redeemed codes per player |
| `logs/` | Daily log files |
| `screenshots/` | Auto-saved on Selenium errors |

---

## Why polling is better than webhooks on Oracle

- Oracle VM is **always on** — no need for Telegram to push to you
- No Flask web server needed — simpler, fewer dependencies
- No public URL needed — bot connects outbound to Telegram's servers
- Works even if Oracle's public IP changes
- `bot.infinity_polling()` automatically reconnects on network drops

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Bot doesn't respond | Check `journalctl -u kingshot -f` for errors |
| "Invalid token" error | Double-check `TELEGRAM_BOT_TOKEN` in `.env` or service file |
| Chrome not found | Run `which google-chrome` — should return `/usr/bin/google-chrome`. Re-run `setup_oracle.sh`. |
| systemd shows "failed" | Check logs with `journalctl -u kingshot -n 50` |
| VM unreachable after reboot | Check Oracle Console — instance may be stopped |
| No codes being found | Check logs for API errors — endpoint may have changed |

For more detailed troubleshooting, see [ORACLE-DEPLOY-GUIDE.md](./ORACLE-DEPLOY-GUIDE.md).