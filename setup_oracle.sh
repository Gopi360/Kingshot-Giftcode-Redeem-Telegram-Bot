#!/usr/bin/env bash
# setup_oracle.sh
# ─────────────────────────────────────────────────────────────────────────────
# One-shot setup script for Oracle Cloud Free Tier (Ubuntu 22.04 / 24.04)
# Run ONCE after SSH-ing into your Oracle VM:
#
#   bash setup_oracle.sh
#
# What it does:
#   1. Updates the system
#   2. Installs Google Chrome (for Selenium)
#   3. Installs Python 3 + pip
#   4. Installs all Python dependencies
#   5. Creates logs and screenshots directories
#   6. Configures the firewall
# ─────────────────────────────────────────────────────────────────────────────

set -e  # Stop on any error

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  KingShot Bot — Oracle Cloud Setup Script   ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── Step 1: System update ──────────────────────────────────────────────────
echo "▶ Step 1/5: Updating system packages..."
sudo apt-get update -qq
sudo apt-get upgrade -y -qq
sudo apt-get install -y -qq wget curl gnupg2 unzip python3 python3-pip git screen
echo "   ✅ System updated."

# ── Step 2: Install Google Chrome ─────────────────────────────────────────
echo "▶ Step 2/5: Installing Google Chrome..."
if command -v google-chrome &> /dev/null; then
    echo "   ℹ️  Chrome already installed: $(google-chrome --version)"
else
    wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | sudo apt-key add -
    echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" \
        | sudo tee /etc/apt/sources.list.d/google-chrome.list
    sudo apt-get update -qq
    sudo apt-get install -y -qq google-chrome-stable
    echo "   ✅ Installed: $(google-chrome --version)"
fi

# ── Step 3: Install Python dependencies ───────────────────────────────────
echo "▶ Step 3/5: Installing Python packages..."
pip3 install --upgrade pip -q
pip3 install \
    selenium==4.20.0 \
    requests==2.31.0 \
    pyTelegramBotAPI==4.18.0 \
    APScheduler==3.10.4 \
    python-dotenv==1.0.1 \
    -q
echo "   ✅ Python packages installed."

# ── Step 4: Create project directories ────────────────────────────────────
echo "▶ Step 4/5: Creating project directories..."
mkdir -p logs screenshots .selenium_cache
echo "   ✅ Directories created."

# ── Step 5: Open firewall ports ───────────────────────────────────────────
echo "▶ Step 5/5: Configuring firewall..."
# Oracle's internal iptables blocks everything by default.
# The bot uses outbound HTTPS only — no inbound ports needed.
sudo iptables -I OUTPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || true
sudo iptables -I INPUT  -m state --state ESTABLISHED,RELATED -j ACCEPT 2>/dev/null || true
echo "   ✅ Firewall configured."

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║  ✅ Setup complete!                                  ║"
echo "║                                                      ║"
echo "║  Next steps:                                         ║"
echo "║  1. cp .env.example .env                             ║"
echo "║  2. nano .env  ← paste your BOT_TOKEN + ADMIN_IDS   ║"
echo "║  3. python3 bot.py  ← test it first                 ║"
echo "║  4. Set up systemd for 24/7 auto-start               ║"
echo "║     (see ORACLE_DEPLOY_GUIDE.md)                     ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""