"""Gestión de sesiones de conversación en memoria.

Tras decir la palabra clave ("oye Chabelita"), el usuario tiene una ventana
de tiempo durante la cual el bot responde sin repetir la palabra clave.

Nota: es un almacén en memoria. Para varios procesos/instancias usa Redis.
"""

from __future__ import annotations

import time
import unicodedata


def normalizar(texto: str) -> str:
    """Pasa a minúsculas y quita acentos para comparar la palabra clave."""
    nfkd = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# Modos de operación por número.
MODO_ASISTENTE = "asistente"  # "oye Chabela": ayuda al trabajador (analítica, alta)
MODO_CLIENTE = "cliente"  # "bye Chabela": atención al cliente (productos/fotos)


class SessionStore:
    def __init__(self, ttl_minutes: int):
        self.ttl = ttl_minutes * 60
        self._active: dict[str, float] = {}
        # El modo es "pegajoso": se mantiene hasta que el usuario lo cambie
        # explícitamente ("oye Chabela" / "bye Chabela"), sin caducar.
        self._modo: dict[str, str] = {}

    def is_active(self, sender: str) -> bool:
        exp = self._active.get(sender)
        if exp is None:
            return False
        if exp < self._now():
            self._active.pop(sender, None)
            return False
        return True

    def touch(self, sender: str) -> None:
        self._active[sender] = self._now() + self.ttl

    def end(self, sender: str) -> None:
        self._active.pop(sender, None)

    def get_modo(self, sender: str) -> str:
        return self._modo.get(sender, MODO_CLIENTE)

    def set_modo(self, sender: str, modo: str) -> None:
        self._modo[sender] = modo

    @staticmethod
    def _now() -> float:
        return time.monotonic()
