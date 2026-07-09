# Guía de instalación en tu VPS (para tener el link permanente)

Esta guía deja el **panel de conversaciones** corriendo en tu servidor de
Hostinger, con un link fijo como `http://72.60.24.3:8000/conversaciones`.

Todo se hace **tú** desde tu VPS (con la app **Termius** en el iPhone o la
Terminal del navegador de Hostinger). Yo te guío; las manos en el servidor son
tuyas. Nunca me des las credenciales por el chat.

---

## Requisitos

- Acceso a tu VPS (`ssh root@72.60.24.3`).
- Un **token de GitHub** para clonar el repo privado (ver paso 1).
- Tus credenciales de **WhatsApp Cloud API**, **Odoo** y **Anthropic**.

---

## Paso 1 — Token de GitHub (una vez)

1. En el navegador entra a: `https://github.com/settings/tokens`
2. **Generate new token → Fine-grained** → dale acceso de **solo lectura** al
   repositorio `astf77at-creator/Agente-interno`.
3. Copia el token (empieza con `github_pat_...`). Lo usarás en el paso 2.

## Paso 2 — Descargar el proyecto en el VPS

Entra al VPS y pega (reemplaza `TU_TOKEN`):

```bash
mkdir -p /opt && cd /opt
git clone https://TU_TOKEN@github.com/astf77at-creator/Agente-interno.git chabelita
cd chabelita
git checkout claude/whatsapp-chatbot-product-features-c404lp
```

## Paso 3 — Instalar

```bash
bash setup.sh
```

Esto instala todo y deja el servicio corriendo. Al final te muestra el link del
panel.

## Paso 4 — Configurar tus credenciales

```bash
nano /opt/chabelita/.env
```

Rellena los valores (WhatsApp, Odoo, Anthropic) y **cambia**
`PANEL_USER` / `PANEL_PASSWORD` (con eso entras al panel). Guarda con
`Ctrl+O`, Enter, y sal con `Ctrl+X`. Luego reinicia:

```bash
systemctl restart chabelita
```

## Paso 5 — Abrir el panel

En el navegador del iPhone:

```
http://72.60.24.3:8000/conversaciones
```

Te pedirá el usuario y contraseña del `.env`. ¡Ese es tu **link permanente**!

---

## Notas importantes

- **El panel se llena con las conversaciones nuevas** que reciba el bot. Para que
  el bot reciba mensajes, el **webhook de WhatsApp en Meta** debe apuntar a este
  servicio. Meta **exige HTTPS** para el webhook, así que necesitas un dominio con
  certificado (por ejemplo con **Caddy**, que saca el certificado solo). Si tu bot
  actual ya recibe WhatsApp, hay que decidir si este servicio lo reemplaza o si
  integramos el panel dentro de tu bot actual (para eso comparte su código).
- **HTTPS rápido con Caddy** (opcional, si tienes un dominio apuntando al VPS):

  ```bash
  apt-get install -y caddy
  caddy reverse-proxy --from tu-dominio.com --to localhost:8000
  ```

  Luego el link sería `https://tu-dominio.com/conversaciones` y el webhook
  `https://tu-dominio.com/webhook`.
- **Comandos útiles**:
  - Ver estado: `systemctl status chabelita`
  - Ver registros en vivo: `journalctl -u chabelita -f`
  - Reiniciar: `systemctl restart chabelita`
