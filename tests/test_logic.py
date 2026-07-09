"""Pruebas unitarias de la lógica que no depende de servicios externos."""

from app.sessions import MODO_ASISTENTE, MODO_CLIENTE, SessionStore, normalizar


def test_normalizar_quita_acentos_y_mayusculas():
    assert normalizar("Oye CHABELITA") == "oye chabelita"
    assert "chabelita" in normalizar("Oye, Chabelíta!")


def test_palabra_clave_detectada():
    assert "chabelita" in normalizar("oye chabelita dame existencias")


def test_raiz_chabel_despierta_con_chabela_y_chabelita():
    # La raíz "chabel" debe reconocer ambas variantes que usa el negocio.
    raiz = "chabel"
    assert raiz in normalizar("Oye Chabela, muéstrame los tenis")
    assert raiz in normalizar("oye CHABELITA dame existencias")
    assert raiz not in normalizar("hola, quiero unos zapatos")


def test_sesion_activa_tras_touch():
    store = SessionStore(ttl_minutes=15)
    assert store.is_active("521555") is False
    store.touch("521555")
    assert store.is_active("521555") is True
    store.end("521555")
    assert store.is_active("521555") is False


def test_modo_por_defecto_es_cliente_y_es_pegajoso():
    store = SessionStore(ttl_minutes=15)
    # Por defecto, cualquier número está en atención al cliente.
    assert store.get_modo("521777") == MODO_CLIENTE
    # "oye Chabela" -> asistente; se mantiene aunque expire la ventana.
    store.set_modo("521777", MODO_ASISTENTE)
    assert store.get_modo("521777") == MODO_ASISTENTE
    # "bye Chabela" -> vuelve a atención al cliente.
    store.set_modo("521777", MODO_CLIENTE)
    assert store.get_modo("521777") == MODO_CLIENTE


def test_deteccion_de_comandos_oye_y_bye():
    # La lógica del webhook usa estas mismas comprobaciones sobre el texto normalizado.
    oye = normalizar("Oye Chabela, ¿los más rentables?")
    bye = normalizar("Bye Chabela")
    assert "chabel" in oye and "bye" not in oye
    assert "chabel" in bye and "bye" in bye


def test_worker_set_parsea_numeros(monkeypatch):
    from app.config import Settings

    s = Settings(worker_numbers="521111, 521222 ,")
    assert s.worker_set == {"521111", "521222"}
