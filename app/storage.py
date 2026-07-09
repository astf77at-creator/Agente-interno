"""Almacenamiento de conversaciones en SQLite.

Guarda cada mensaje entrante y saliente (texto, imágenes, audio, video,
stickers, documentos, emojis) para poder verlos en el panel web.
Los archivos multimedia se guardan en disco y aquí se registra su nombre.

Usa solo la librería estándar (`sqlite3`).
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_media_dir: str = "./data/media"


def init(data_dir: str) -> None:
    """Inicializa la base de datos y la carpeta de medios."""
    global _conn, _media_dir
    os.makedirs(data_dir, exist_ok=True)
    _media_dir = os.path.join(data_dir, "media")
    os.makedirs(_media_dir, exist_ok=True)
    _conn = sqlite3.connect(
        os.path.join(data_dir, "conversaciones.db"), check_same_thread=False
    )
    _conn.row_factory = sqlite3.Row
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            wa_number    TEXT NOT NULL,
            contact_name TEXT,
            direction    TEXT NOT NULL,   -- 'in' | 'out'
            msg_type     TEXT NOT NULL,   -- text|image|audio|video|sticker|document
            body         TEXT,            -- texto o pie de foto
            media_file   TEXT,            -- nombre de archivo en la carpeta media
            media_mime   TEXT,
            ts           INTEGER NOT NULL -- epoch en segundos
        )
        """
    )
    _conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_msg_number_ts ON messages(wa_number, ts)"
    )
    _conn.commit()


def media_dir() -> str:
    return _media_dir


def save_media(data: bytes, mime: str | None) -> str:
    """Guarda bytes de un medio en disco y devuelve su nombre de archivo."""
    ext = _ext_from_mime(mime)
    # Nombre único basado en el tiempo y el tamaño (sin depender de random).
    name = f"{int(time.time() * 1000)}_{len(data)}{ext}"
    with open(os.path.join(_media_dir, name), "wb") as f:
        f.write(data)
    return name


def add_message(
    wa_number: str,
    direction: str,
    msg_type: str,
    body: str | None = None,
    media_file: str | None = None,
    media_mime: str | None = None,
    contact_name: str | None = None,
    ts: int | None = None,
) -> None:
    assert _conn is not None, "storage.init() no fue llamado"
    with _lock:
        _conn.execute(
            """INSERT INTO messages
               (wa_number, contact_name, direction, msg_type, body,
                media_file, media_mime, ts)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                wa_number,
                contact_name,
                direction,
                msg_type,
                body,
                media_file,
                media_mime,
                ts or int(time.time()),
            ),
        )
        _conn.commit()


def conversations() -> list[dict]:
    """Lista de conversaciones con su último mensaje (más recientes primero)."""
    assert _conn is not None
    rows = _conn.execute(
        """
        SELECT m.wa_number,
               MAX(m.ts)                              AS last_ts,
               COUNT(*)                               AS total,
               (SELECT contact_name FROM messages
                  WHERE wa_number = m.wa_number AND contact_name IS NOT NULL
                  ORDER BY ts DESC LIMIT 1)           AS contact_name,
               (SELECT body FROM messages
                  WHERE wa_number = m.wa_number ORDER BY ts DESC LIMIT 1) AS last_body,
               (SELECT msg_type FROM messages
                  WHERE wa_number = m.wa_number ORDER BY ts DESC LIMIT 1) AS last_type
        FROM messages m
        GROUP BY m.wa_number
        ORDER BY last_ts DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


def thread(wa_number: str, limit: int = 500) -> list[dict]:
    """Mensajes de una conversación en orden cronológico."""
    assert _conn is not None
    rows = _conn.execute(
        """SELECT id, direction, msg_type, body, media_file, media_mime, ts,
                  contact_name
           FROM messages WHERE wa_number = ? ORDER BY ts ASC, id ASC LIMIT ?""",
        (wa_number, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def _ext_from_mime(mime: str | None) -> str:
    if not mime:
        return ".bin"
    mime = mime.split(";")[0].strip()
    return {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "video/mp4": ".mp4",
        "audio/ogg": ".ogg",
        "audio/mpeg": ".mp3",
        "audio/mp4": ".m4a",
        "audio/aac": ".aac",
        "application/pdf": ".pdf",
    }.get(mime, ".bin")
