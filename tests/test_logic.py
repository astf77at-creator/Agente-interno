"""Pruebas unitarias de la lógica que no depende de servicios externos."""

from app.sessions import SessionStore, normalizar


def test_normalizar_quita_acentos_y_mayusculas():
    assert normalizar("Oye CHABELITA") == "oye chabelita"
    assert "chabelita" in normalizar("Oye, Chabelíta!")


def test_palabra_clave_detectada():
    assert "chabelita" in normalizar("oye chabelita dame existencias")


def test_sesion_activa_tras_touch():
    store = SessionStore(ttl_minutes=15)
    assert store.is_active("521555") is False
    store.touch("521555")
    assert store.is_active("521555") is True
    store.end("521555")
    assert store.is_active("521555") is False


def test_worker_set_parsea_numeros(monkeypatch):
    from app.config import Settings

    s = Settings(worker_numbers="521111, 521222 ,")
    assert s.worker_set == {"521111", "521222"}
