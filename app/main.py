"""Servicio web del agente Chabelita (FastAPI).

Expone el webhook de WhatsApp Cloud API:
  - GET  /webhook  -> verificación del webhook (Meta).
  - POST /webhook  -> recepción de mensajes entrantes.
  - GET  /health   -> chequeo de salud.

Flujo: WhatsApp -> webhook -> ¿despierto? -> agente (Claude+Odoo) -> respuesta.
"""

from __future__ import annotations

import logging

from fastapi import BackgroundTasks, FastAPI, Request, Response

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


def _build_agent() -> ChabelitaAgent:
    """Crea el agente bajo demanda (autentica con Odoo al primer uso)."""
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


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "chabelita"}


@app.get("/webhook")
def verify_webhook(request: Request) -> Response:
    """Verificación del webhook que exige Meta al configurarlo."""
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == settings.wa_verify_token
    ):
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    return Response(status_code=403)


@app.post("/webhook")
async def receive_webhook(request: Request, background: BackgroundTasks) -> dict:
    """Recibe el evento, responde 200 de inmediato y procesa en segundo plano.

    WhatsApp reintenta si no respondes rápido; por eso el trabajo pesado
    (Claude + Odoo) se hace en una tarea de fondo.
    """
    payload = await request.json()
    msg = parse_incoming(payload)
    if msg:
        background.add_task(_handle_message, msg)
    return {"status": "received"}


def _handle_message(msg: dict) -> None:
    sender = msg["from"]
    text = msg["text"]
    is_worker = sender in settings.worker_set

    despierto = sessions.is_active(sender)
    contiene_clave = settings.wake_word in normalizar(text)

    if not despierto and not contiene_clave:
        return  # El bot solo actúa con la palabra clave o sesión activa.

    sessions.touch(sender)

    try:
        agent = _build_agent()
        respuesta, imagenes = agent.run(text, is_worker=is_worker)
    except Exception:  # noqa: BLE001
        logger.exception("Error procesando mensaje de %s", sender)
        wa.send_text(
            sender,
            "Uy, tuve un problema técnico. Inténtalo de nuevo en un momento. 🙏",
        )
        return

    for img in imagenes:
        wa.send_image(sender, img["image_b64"], img.get("caption", ""))
    if respuesta:
        wa.send_text(sender, respuesta)
