#!/usr/bin/env bash
# ОДНОРАЗОВО на VPS (или после его переустановки): разрешить reverse-туннель по ключу.
# Запускать НА ДОМАШНЕЙ машине (там лежит ключ туннеля) — спросит пароль root VPS ОДИН раз:
#   ./scripts/vps_provision.sh
#
# Кладёт pubkey домашней машины в authorized_keys root@VPS, включает GatewayPorts yes
# (нужно для публичного reverse-форварда) и открывает порты. Пароль НИКУДА не пишется.
set -euo pipefail
VPS_HOST="${AIDND_VPS_HOST:-154.222.8.94}"
PUB="${AIDND_HOME_PUBKEY:-$HOME/.ssh/id_ed25519.pub}"
PUBLIC_PORT="${AIDND_PUBLIC_PORT:-80}"
[ -f "$PUB" ] || { echo "нет pubkey $PUB — создай: ssh-keygen -t ed25519"; exit 1; }

echo "→ ставлю ключ на root@$VPS_HOST (введи пароль root один раз):"
ssh-copy-id -i "$PUB" -o StrictHostKeyChecking=accept-new "root@$VPS_HOST"

echo "→ GatewayPorts yes + ufw на VPS:"
ssh "root@$VPS_HOST" "
  sed -i '/^[[:space:]]*GatewayPorts/d' /etc/ssh/sshd_config
  echo 'GatewayPorts yes' >> /etc/ssh/sshd_config
  sshd -t && (systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || systemctl restart ssh 2>/dev/null || true)
  command -v ufw >/dev/null 2>&1 && { ufw allow ${PUBLIC_PORT}/tcp >/dev/null 2>&1; ufw allow 22/tcp >/dev/null 2>&1; }
  echo PROVISIONED
"
echo "✓ VPS готов. Теперь обычный деплой: ./scripts/deploy.sh"
