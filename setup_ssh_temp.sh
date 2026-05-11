#!/bin/bash
set -e

PUBKEY='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKS+B8NKA3m3mov2yADa5605Z0UYH0uqCz8Xv1z1YVz2 diego@finanzasbo-vscode'

mkdir -p /home/binance/.ssh
chmod 700 /home/binance/.ssh

if [ -f /home/binance/.ssh/authorized_keys ]; then
  grep -qF "$PUBKEY" /home/binance/.ssh/authorized_keys || echo "$PUBKEY" >> /home/binance/.ssh/authorized_keys
else
  echo "$PUBKEY" > /home/binance/.ssh/authorized_keys
fi

chown -R binance /home/binance/.ssh
chgrp -R binance /home/binance/.ssh
chmod 600 /home/binance/.ssh/authorized_keys

echo ""
echo "=== Contenido final de authorized_keys ==="
cat /home/binance/.ssh/authorized_keys
