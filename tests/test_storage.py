"""Pruebas del almacenamiento de conversaciones (SQLite en carpeta temporal)."""

import tempfile

from app import storage


def test_guarda_y_lista_conversaciones():
    with tempfile.TemporaryDirectory() as d:
        storage.init(d)
        storage.add_message("521999", "in", "text", body="Hola", contact_name="Ana", ts=100)
        storage.add_message("521999", "out", "text", body="¿Qué buscas?", ts=101)
        storage.add_message("521888", "in", "image", body="", media_file="a.jpg",
                            media_mime="image/jpeg", contact_name="Beto", ts=200)

        convs = storage.conversations()
        # El chat más reciente (521888) va primero.
        assert convs[0]["wa_number"] == "521888"
        assert convs[0]["contact_name"] == "Beto"
        assert convs[0]["last_type"] == "image"

        hilo = storage.thread("521999")
        assert [m["body"] for m in hilo] == ["Hola", "¿Qué buscas?"]
        assert hilo[0]["direction"] == "in"


def test_guarda_medio_en_disco():
    with tempfile.TemporaryDirectory() as d:
        storage.init(d)
        nombre = storage.save_media(b"binario-de-prueba", "image/png")
        assert nombre.endswith(".png")
        import os
        assert os.path.isfile(os.path.join(storage.media_dir(), nombre))
