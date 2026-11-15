#!/usr/bin/env bash
# SkyShift one-line installer for a fresh Ubuntu server (made for Oracle Cloud "Always Free", Arm or x86).
#
#   curl -fsSL https://raw.githubusercontent.com/Kuladeep0001/SKYSHIFT/main/deploy/install.sh | bash -s -- skyshift.duckdns.org
#
# The last word is your site's address (a free DuckDNS name). Leave it out to serve on the bare IP (http only).
# Safe to run again any time: it updates the code and restarts the site, keeping the downloaded pictures.
set -euo pipefail

DOMAIN="${1:-}"
REPO="https://github.com/Kuladeep0001/SKYSHIFT.git"
DIR="$HOME/skyshift"
say() { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }

say "1/5  Installing Docker and Git"
export DEBIAN_FRONTEND=noninteractive
sudo -E apt-get update -qq
sudo -E apt-get install -y -qq git curl ca-certificates >/dev/null
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$USER" 2>/dev/null || true

say "2/5  Opening ports 80 and 443 on this server's own firewall"
# Oracle's Ubuntu images block everything except SSH in iptables (on top of the cloud "security list").
for rule in "-p tcp --dport 80" "-p tcp --dport 443" "-p udp --dport 443"; do
  # shellcheck disable=SC2086
  sudo iptables -C INPUT $rule -j ACCEPT 2>/dev/null || sudo iptables -I INPUT 1 $rule -j ACCEPT
done
if command -v netfilter-persistent >/dev/null 2>&1; then
  sudo netfilter-persistent save >/dev/null 2>&1 || true
else
  sudo -E apt-get install -y -qq iptables-persistent >/dev/null 2>&1 && sudo netfilter-persistent save >/dev/null 2>&1 || true
fi

# a small server (under 4 GB RAM) gets 2 GB of swap so the build doesn't run out of memory
if [ "$(free -m | awk '/Mem:/{print $2}')" -lt 4000 ] && [ ! -f /swapfile ]; then
  say "     Adding 2 GB swap (small server)"
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

say "3/5  Getting SkyShift"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull --ff-only
else
  git clone --depth 1 "$REPO" "$DIR"
fi
cd "$DIR/deploy"
[ -f .env ] || cp .env.example .env
if [ -n "$DOMAIN" ]; then
  sed -i "s|^SKYSHIFT_DOMAIN=.*|SKYSHIFT_DOMAIN=$DOMAIN|" .env
fi
mkdir -p data

say "4/5  Building and starting SkyShift (the first time takes 5-10 minutes)"
sudo docker compose up -d --build
sudo docker image prune -f >/dev/null 2>&1 || true

say "5/5  Done"
IP="$(curl -fsS -4 --max-time 5 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
SET_DOMAIN="$(grep '^SKYSHIFT_DOMAIN=' .env | cut -d= -f2-)"
echo
if [ -n "$SET_DOMAIN" ]; then
  echo "  Open:  https://$SET_DOMAIN"
  echo "         (DuckDNS must point $SET_DOMAIN at this server's IP: $IP. The first https visit can take ~30 s while the certificate is made.)"
else
  echo "  Open:  http://$IP     (no domain yet: Listen mode's microphone needs https, see deploy/README.md)"
fi
echo
echo "  Prewarm the demo stars (about 30 min, keeps running in the background):"
echo "      cd $DIR/deploy && sudo docker compose exec -T skyshift python -m scripts.prewarm"
echo "  Watch the logs:        cd $DIR/deploy && sudo docker compose logs -f --tail 50"
echo "  Update to the newest:  bash $DIR/deploy/update.sh"
echo
