"""Cliente de la WhatsApp Cloud API (Meta).

Permite verificar el webhook, enviar mensajes de texto e imágenes.
Documentación: https://developers.facebook.com/docs/whatsapp/cloud-api
"""

from __future__ import annotations

import base64
import logging

import httpx

logger = logging.getLogger(__name__)


class WhatsAppClient:
    def __init__(self, token: str, phone_number_id: str, api_version: str = "v21.0"):
        self.token = token
        self.phone_number_id = phone_number_id
        self.base_url = f"https://graph.facebook.com/{api_version}"
        self._headers = {"Authorization": f"Bearer {token}"}

    def send_text(self, to: str, body: str) -> None:
        """Envía un mensaje de texto. WhatsApp limita el cuerpo a 4096 chars."""
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body[:4096]},
        }
        self._post(f"/{self.phone_number_id}/messages", json=payload)

    def send_image(self, to: str, image_b64: str, caption: str = "") -> None:
        """Sube una imagen (base64, p.ej. de Odoo) y la envía por su media_id."""
        try:
            media_id = self._upload_media(image_b64)
        except Exception:  # noqa: BLE001 — degradar a solo texto si la imagen falla
            logger.exception("No se pudo subir la imagen; se omite.")
            if caption:
                self.send_text(to, caption)
            return
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": {"id": media_id, "caption": caption[:1024]},
        }
        self._post(f"/{self.phone_number_id}/messages", json=payload)

    def _upload_media(self, image_b64: str, mime: str = "image/jpeg") -> str:
        data = base64.b64decode(image_b64)
        files = {
            "file": ("producto.jpg", data, mime),
            "messaging_product": (None, "whatsapp"),
            "type": (None, mime),
        }
        resp = httpx.post(
            f"{self.base_url}/{self.phone_number_id}/media",
            headers=self._headers,
            files=files,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["id"]

    def _post(self, path: str, json: dict) -> None:
        try:
            resp = httpx.post(
                f"{self.base_url}{path}",
                headers={**self._headers, "Content-Type": "application/json"},
                json=json,
                timeout=30,
            )
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.exception("Error enviando mensaje a WhatsApp")


def parse_incoming(payload: dict) -> dict | None:
    """Extrae el primer mensaje de texto entrante del webhook.

    Devuelve {"from": <numero>, "text": <texto>, "name": <perfil>} o None
    si el evento no es un mensaje de texto (p.ej. un status de entrega).
    """
    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]["value"]
        messages = change.get("messages")
        if not messages:
            return None
        msg = messages[0]
        if msg.get("type") != "text":
            return None
        contacts = change.get("contacts", [{}])
        name = contacts[0].get("profile", {}).get("name", "")
        return {
            "from": msg["from"],
            "text": msg["text"]["body"],
            "name": name,
        }
    except (KeyError, IndexError, TypeError):
        return None
