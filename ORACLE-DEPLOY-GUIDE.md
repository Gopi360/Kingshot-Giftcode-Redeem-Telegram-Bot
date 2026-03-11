# 🚀 KingShot Bot — Oracle Cloud Deployment Guide

> Deploy your Telegram gift-code bot on Oracle Cloud **Free Tier** — runs 24/7 at zero cost.

---

## Prerequisites (do these on your local PC first)

- A **Telegram bot token** from [@BotFather](https://t.me/BotFather)
- Your **Telegram user ID** — message [@userinfobot](https://t.me/userinfobot) to get it
- An Oracle Cloud account (we'll create this in Step 1)
- SSH key pair (we'll generate this in Step 2)

---

## PART 1 — Oracle Cloud Setup

### Step 1 — Create a Free Oracle Cloud Account

1. Go to **https://www.oracle.com/cloud/free/**
2. Click **Start for free** and sign up
3. ⚠️ A credit card is required for identity verification only — **you will NOT be charged**
4. Choose your **Home Region** carefully — pick the closest city to you — **you cannot change this later**
5. Wait for your account to be activated (usually a few minutes, sometimes up to 24 hours)

---

### Step 2 — Generate an SSH Key (on your local PC)

**Windows (PowerShell or Git Bash):**
```bash
ssh-keygen -t ed25519 -C "kingshot-bot"
```
Press Enter three times to accept defaults. This creates two files:
- `~/.ssh/id_ed25519` — your **private key** (keep secret, never share)
- `~/.ssh/id_ed25519.pub` — your **public key** (this goes to Oracle)

**Mac / Linux:**
```bash
ssh-keygen -t ed25519 -C "kingshot-bot"
```
Same as above.

**View your public key** (you'll need to paste it in the next step):
```bash
cat ~/.ssh/id_ed25519.pub
```

---

### Step 3 — Create a Free VM Instance

1. Log into your Oracle Cloud console at **https://cloud.oracle.com**
2. In the top-left menu → **Compute** → **Instances** → **Create Instance**
3. Configure these settings:

| Setting | Value |
|---------|-------|
| **Name** | `kingshot-bot` (or anything) |
| **Image** | Ubuntu 22.04 (click *Change Image* → *Ubuntu*) |
| **Shape** | Ampere → `VM.Standard.A1.Flex` (click *Change Shape*) |
| **OCPUs** | 1 (free quota: up to 4) |
| **Memory** | 6 GB (free quota: up to 24 GB) |
| **SSH Keys** | Paste your **public key** from Step 2 |

4. Leave everything else as default
5. Click **Create** — your VM will be ready in ~2 minutes
6. Copy the **Public IP address** shown on the instance page

---

### Step 4 — Open Network Ports (Oracle Firewall)

Oracle's default security list blocks most traffic. For a **polling bot** you don't need inbound ports — but run these commands to be safe:

1. In Oracle Console → **Networking** → **Virtual Cloud Networks**
2. Click your VCN → **Security Lists** → **Default Security List**
3. Verify that **Egress Rules** allow all outbound traffic (default: they do)

For the bot to work, only **outbound HTTPS (port 443)** is needed — no inbound rules required.

---

## PART 2 — Server Setup

### Step 5 — SSH into your VM

**Mac / Linux / Git Bash:**
```bash
ssh ubuntu@YOUR_VM_PUBLIC_IP
```

**Windows (PowerShell):**
```powershell
ssh ubuntu@YOUR_VM_PUBLIC_IP
```

If you get a fingerprint warning, type `yes` and press Enter.

---

### Step 6 — Upload Your Bot Files

**From your local PC**, upload the project files:

```bash
# Create the folder on the VM first
ssh ubuntu@YOUR_VM_IP "mkdir -p /home/ubuntu/kingshot-bot"

# Then upload all files
scp bot.py redeemer.py setup_oracle.sh kingshot.service .env.example \
    ubuntu@YOUR_VM_IP:/home/ubuntu/kingshot-bot/
```

Or if you have it in a GitHub repo:
```bash
# Run this ON the Oracle VM after SSH-ing in
git clone https://github.com/YOUR_USERNAME/kingshot-bot.git
cd kingshot-bot
```

---

### Step 7 — Run the Setup Script

On the Oracle VM:
```bash
cd /home/ubuntu/kingshot-bot
bash setup_oracle.sh
```

This installs Chrome, Python packages, and creates the needed folders. Takes ~2 minutes.

---

### Step 8 — Configure Your Tokens

```bash
cp .env.example .env
nano .env
```

Fill in these two values:
```ini
TELEGRAM_BOT_TOKEN=123456789:ABCdef_your_real_token
ADMIN_IDS=123456789
CHECK_INTERVAL=30
```

Save with `Ctrl+O`, `Enter`, then exit with `Ctrl+X`.

---

### Step 9 — Test the Bot Manually

```bash
cd /home/ubuntu/kingshot-bot
python3 bot.py
```

Expected output:
```
2025-01-01 12:00:00 [INFO] KingShot Auto Gift Code Bot (Oracle Cloud)
2025-01-01 12:00:00 [INFO] Admin IDs      : [123456789]
2025-01-01 12:00:00 [INFO] Check interval : 30 min
2025-01-01 12:00:00 [INFO] Scheduler started — checks every 30 min
2025-01-01 12:00:00 [INFO] Starting Telegram polling...
```

On Telegram, open your bot and send `/ping` — you should get back `🏓 Pong! Bot is alive.`

Once confirmed working, press `Ctrl+C` to stop.

---

## PART 3 — Auto-Start with systemd

### Step 10 — Install the Service File

```bash
sudo cp /home/ubuntu/kingshot-bot/kingshot.service /etc/systemd/system/kingshot.service
```

---

### Step 11 — Edit the Service File

```bash
sudo nano /etc/systemd/system/kingshot.service
```

**If you prefer environment variables in the service file** (instead of .env), replace the `Environment=` lines with your real values:
```ini
Environment=TELEGRAM_BOT_TOKEN=123456789:ABCdef_real_token
Environment=ADMIN_IDS=123456789
Environment=CHECK_INTERVAL=30
```

**If you prefer using the .env file** (more secure), comment out the three `Environment=` lines and uncomment:
```ini
EnvironmentFile=/home/ubuntu/kingshot-bot/.env
```

Save with `Ctrl+O`, `Enter`, `Ctrl+X`.

---

### Step 12 — Enable and Start the Service

```bash
# Reload systemd to pick up the new service file
sudo systemctl daemon-reload

# Enable — auto-start on every VM reboot
sudo systemctl enable kingshot

# Start it now
sudo systemctl start kingshot

# Verify it's running (should say "active (running)")
sudo systemctl status kingshot
```

You should see something like:
```
● kingshot.service - KingShot Auto Gift Code Bot (Telegram)
     Loaded: loaded (/etc/systemd/system/kingshot.service; enabled)
     Active: active (running) since Wed 2025-01-01 12:00:00 UTC; 5s ago
```

🎉 **Your bot is now running 24/7 and will auto-restart on any crash or reboot!**

---

## PART 4 — Daily Usage

### View live logs
```bash
journalctl -u kingshot -f
```
(`Ctrl+C` to stop following)

### View last 50 log lines
```bash
journalctl -u kingshot -n 50
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
git pull                              # If using GitHub
sudo systemctl restart kingshot
```

---

## PART 5 — Bot Commands Reference

| Command | Description | Admin Only |
|---------|-------------|------------|
| `/ping` | Quick alive check | No |
| `/help` | Show all commands | No |
| `/addplayer 876734319 Gopi` | Register a player | ✅ |
| `/addplayers` | Bulk add (one per line) | ✅ |
| `/removeplayer 876734319` | Remove a player | ✅ |
| `/listplayers` | Show all players + claim counts | ✅ |
| `/listcodes` | Show all tracked gift codes | ✅ |
| `/addcode CODE123` | Manually force-redeem a code | ✅ |
| `/clearcode CODE123` | Re-queue code for all players | ✅ |
| `/mystatus 876734319` | Show a player's claim history | ✅ |
| `/resetplayer 876734319` | Re-queue all codes for one player | ✅ |
| `/checkcode` | Force an immediate code check | ✅ |
| `/nextcheck` | Show next scheduled check time | ✅ |
| `/status` | Bot status, uptime, player count | ✅ |

---

## PART 6 — Troubleshooting

| Problem | Likely Cause | Fix |
|---------|--------------|-----|
| Bot doesn't respond | Wrong token or not running | Check `journalctl -u kingshot -n 50` |
| "Invalid token" in logs | Token typed wrong | Re-check `TELEGRAM_BOT_TOKEN` in service file |
| Chrome not found | Chrome not installed | Run `which google-chrome` → should return `/usr/bin/google-chrome`. Re-run `setup_oracle.sh`. |
| `systemctl status` shows "failed" | Code crash at start | Check `journalctl -u kingshot -n 50` for the Python error |
| VM unreachable after reboot | Oracle instance stopped | Log into Oracle Console → Compute → Start the instance |
| No codes being found | API URL changed or wrong response format | Check `journalctl -u kingshot` for API errors |
| Selenium timeout errors | Site layout changed | Check `screenshots/` folder for debug images |
| "No valid ADMIN_IDS" error | ADMIN_IDS not set | Make sure it's a plain number (e.g. `123456789`) |
| Bot starts twice | Old process still running | `sudo systemctl stop kingshot` then `start` |

---

## PART 7 — Multiple Admins

To add more than one admin, comma-separate the IDs in your `.env` or service file:

```ini
ADMIN_IDS=123456789,987654321,111222333
```

All listed users can run admin commands.

---

## PART 8 — Keeping the VM Alive

Oracle may terminate free instances they consider idle. To prevent this:

1. The bot itself generates constant outbound traffic (Telegram polling) — this is usually enough.
2. If you want extra assurance, add a cron job to ping something:
```bash
crontab -e
```
Add this line:
```
*/5 * * * * curl -s https://api.telegram.org > /dev/null
```

---

## PART 9 — Security Best Practices

1. **Never commit your `.env` file to GitHub** — add it to `.gitignore`:
```bash
echo ".env" >> .gitignore
```

2. **Use .env file, not service file** for tokens — the service file is world-readable by root:
```bash
chmod 600 /home/ubuntu/kingshot-bot/.env
```

3. **Keep your SSH private key safe** — if it leaks, regenerate it and update Oracle.

4. **Restrict SSH access** — in Oracle's Security List, limit SSH (port 22) to your IP only.

---

*Questions? Check the logs first: `journalctl -u kingshot -f`*