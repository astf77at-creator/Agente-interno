"""Servicio web del agente Chabelita (FastAPI).

Webhook de WhatsApp Cloud API:
  - GET  /webhook  -> verificación del webhook (Meta).
  - POST /webhook  -> recepción de mensajes entrantes (todos los tipos).
  - GET  /health   -> chequeo de salud.

Panel web de conversaciones (protegido con usuario/contraseña):
  - GET  /conversaciones            -> página web tipo WhatsApp.
  - GET  /api/conversaciones        -> lista de chats (JSON).
  - GET  /api/conversaciones/{num}  -> mensajes de un chat (JSON).
  - GET  /media/{archivo}           -> archivo multimedia guardado.

Flujo: WhatsApp -> webhook -> se guarda el mensaje -> si es texto y hay
palabra clave/sesión -> agente (Claude+Odoo) -> respuesta (que también se guarda).
"""

from __future__ import annotations

import logging
import os
import secrets

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from . import storage
from .agent import ChabelitaAgent
from .config import get_settings
from .odoo_client import OdooClient
from .sessions import SessionStore, normalizar
from .whatsapp import WhatsAppClient, parse_incoming

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("chabelita")

settings = get_settings()
app = FastAPI(title="Agente Chabelita", version="1.0.0")

wa = WhatsAppClient(
    token=settings.wa_token,
    phone_number_id=settings.wa_phone_number_id,
    api_version=settings.wa_api_version,
)
sessions = SessionStore(settings.session_ttl_minutes)
storage.init(settings.data_dir)

security = HTTPBasic()
_STATIC = os.path.join(os.path.dirname(__file__), "static")


def _build_agent() -> ChabelitaAgent:
    odoo = OdooClient(
        url=settings.odoo_url,
        db=settings.odoo_db,
        username=settings.odoo_username,
        password=settings.odoo_password,
    )
    return ChabelitaAgent(
        odoo=odoo,
        anthropic_api_key=settings.anthropic_api_key,
        model=settings.anthropic_model,
        max_tokens=settings.anthropic_max_tokens,
        brand=settings.brand_name,
    )


def _auth(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    """Autenticación básica para el panel (comparación en tiempo constante)."""
    ok_user = secrets.compare_digest(credentials.username, settings.panel_user)
    ok_pass = secrets.compare_digest(credentials.password, settings.panel_password)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# --------------------------------------------------------------------------- #
# Salud y webhook
# --------------------------------------------------------------------------- #
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "chabelita"}


@app.get("/webhook")
def verify_webhook(request: Request) -> Response:
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == settings.wa_verify_token
    ):
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    return Response(status_code=403)


@app.post("/webhook")
async def receive_webhook(request: Request, background: BackgroundTasks) -> dict:
    payload = await request.json()
    msg = parse_incoming(payload)
    if msg:
        background.add_task(_ingest_and_maybe_reply, msg)
    return {"status": "received"}


# --------------------------------------------------------------------------- #
# Procesamiento de mensajes
# --------------------------------------------------------------------------- #
def _ingest_and_maybe_reply(msg: dict) -> None:
    """Guarda el mensaje entrante (con su medio) y responde si procede."""
    sender = msg["from"]
    name = msg.get("name") or None

    # 1) Guardar el mensaje entrante (descargando el medio si lo trae).
    media_file = None
    mime = msg.get("mime")
    if msg.get("media_id"):
        try:
            data, mime = wa.download_media(msg["media_id"])
            media_file = storage.save_media(data, mime)
        except Exception:  # noqa: BLE001
            logger.exception("No se pudo descargar el medio %s", msg.get("media_id"))
    body = msg.get("text") if msg["type"] == "text" else msg.get("caption") or ""
    storage.add_message(
        wa_number=sender,
        direction="in",
        msg_type=msg["type"],
        body=body,
        media_file=media_file,
        media_mime=mime,
        contact_name=name,
        ts=msg.get("ts"),
    )

    # 2) El bot solo actúa con mensajes de TEXTO + palabra clave o sesión activa.
    if msg["type"] != "text":
        return
    text = msg["text"]
    is_worker = sender in settings.worker_set
    despierto = sessions.is_active(sender)
    if not despierto and settings.wake_word not in normalizar(text):
        return
    sessions.touch(sender)

    try:
        agent = _build_agent()
        respuesta, imagenes = agent.run(text, is_worker=is_worker)
    except Exception:  # noqa: BLE001
        logger.exception("Error procesando mensaje de %s", sender)
        err = "Uy, tuve un problema técnico. Inténtalo de nuevo en un momento. 🙏"
        wa.send_text(sender, err)
        storage.add_message(sender, "out", "text", body=err)
        return

    # 3) Enviar y guardar la respuesta (fotos primero, luego texto).
    for img in imagenes:
        caption = img.get("caption", "")
        wa.send_image(sender, img["image_b64"], caption)
        try:
            import base64

            fname = storage.save_media(base64.b64decode(img["image_b64"]), "image/jpeg")
        except Exception:  # noqa: BLE001
            fname = None
        storage.add_message(
            sender, "out", "image", body=caption, media_file=fname,
            media_mime="image/jpeg",
        )
    if respuesta:
        wa.send_text(sender, respuesta)
        storage.add_message(sender, "out", "text", body=respuesta)


# --------------------------------------------------------------------------- #
# Panel web de conversaciones
# --------------------------------------------------------------------------- #
@app.get("/conversaciones", response_class=HTMLResponse)
def panel(_: str = Depends(_auth)) -> HTMLResponse:
    with open(os.path.join(_STATIC, "inbox.html"), encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/api/conversaciones")
def api_conversaciones(_: str = Depends(_auth)) -> list[dict]:
    # El panel muestra SOLO conversaciones con clientes: se ocultan los
    # números de trabajadores (WORKER_NUMBERS).
    workers = settings.worker_set
    return [c for c in storage.conversations() if c["wa_number"] not in workers]


@app.get("/api/conversaciones/{numero}")
def api_thread(numero: str, _: str = Depends(_auth)) -> list[dict]:
    if numero in settings.worker_set:
        return []  # No se exponen las conversaciones con trabajadores.
    return storage.thread(numero)


@app.get("/media/{archivo}")
def media(archivo: str, _: str = Depends(_auth)) -> FileResponse:
    # Evita path traversal: solo el nombre base, dentro de la carpeta de medios.
    safe = os.path.basename(archivo)
    path = os.path.join(storage.media_dir(), safe)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="No encontrado")
    return FileResponse(path)
