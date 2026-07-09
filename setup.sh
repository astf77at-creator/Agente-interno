#!/usr/bin/env bash
# Instalador del Agente Chabelita en un VPS Ubuntu.
# Deja el servicio corriendo con systemd y arrancando solo al reiniciar.
#
# Uso (como root):
#   cd /opt/chabelita && bash setup.sh
#
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$APP_DIR"

echo "==> 1/5 Instalando dependencias del sistema..."
apt-get update -y
apt-get install -y python3-venv python3-pip git

echo "==> 2/5 Creando entorno virtual e instalando librerías..."
python3 -m venv .venv
./.venv/bin/pip install -U pip >/dev/null
./.venv/bin/pip install -r requirements.txt

echo "==> 3/5 Preparando configuración (.env)..."
if [ ! -f .env ]; then
  cp .env.example .env
  echo "    >> Se creó .env desde la plantilla."
  echo "    >> EDÍTALO con tus credenciales:  nano $APP_DIR/.env"
fi

echo "==> 4/5 Instalando el servicio systemd..."
cat >/etc/systemd/system/chabelita.service <<UNIT
[Unit]
Description=Agente Chabelita (WhatsApp + Odoo)
After=network.target

[Service]
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$APP_DIR/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable chabelita
systemctl restart chabelita

echo "==> 5/5 Listo."
IP=$(hostname -I | awk '{print $1}')
echo
echo "   Panel de conversaciones:  http://$IP:8000/conversaciones"
echo "   Webhook para Meta:        http://$IP:8000/webhook  (requiere HTTPS, ver DEPLOY.md)"
echo
echo "   Estado:   systemctl status chabelita"
echo "   Registros: journalctl -u chabelita -f"
