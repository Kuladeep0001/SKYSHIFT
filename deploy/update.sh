#!/usr/bin/env bash
# Update SkyShift on the server to the newest code on GitHub and restart it. Downloaded pictures are kept.
#   bash ~/skyshift/deploy/update.sh
set -euo pipefail
cd "$(dirname "$0")"
git -C .. pull --ff-only
sudo docker compose up -d --build
sudo docker image prune -f >/dev/null 2>&1 || true
echo "Updated. Logs: sudo docker compose logs -f --tail 50"
