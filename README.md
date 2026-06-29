# Agente Chabelita 🤖 — WhatsApp + Odoo para YOOHOO

Agente conversacional para WhatsApp que atiende por la palabra clave
**"oye Chabelita"** y se conecta a tu **Odoo** para:

- 🔎 **Consultar productos**: precio, existencias e imagen (lo que ya hacía).
- ➕ **Dar de alta productos** nuevos en Odoo desde WhatsApp.
- 📊 **Responder consultas de negocio** en lenguaje natural sobre YOOHOO:
  artículos **más rentables**, **más vendidos** y de **lenta rotación**.

Usa **Claude** (Anthropic) como cerebro del agente y la **WhatsApp Cloud API**
de Meta para enviar y recibir mensajes.

> Este servicio es independiente y está pensado para desplegarse en tu VPS
> (junto al chatbot actual o reemplazándolo). Solo necesita un webhook público.

---

## ¿Cómo funciona?

```
WhatsApp ──▶ POST /webhook ──▶ ¿"oye Chabelita" o sesión activa?
                                        │ sí
                                        ▼
                          Agente Claude (decide herramientas)
                                        │
                          ┌─────────────┼───────────────┐
                          ▼             ▼               ▼
                   buscar_producto  alta_producto   analítica
                          └─────────────┴───────────────┘
                                        │ (Odoo XML-RPC)
                                        ▼
                          Respuesta + imagen ──▶ WhatsApp
```

- El bot **solo responde** si el mensaje contiene la palabra clave (`chabelita`,
  sin importar mayúsculas/acentos) **o** si hay una conversación activa (15 min
  por defecto). Así no contesta a todo en grupos.
- **Permisos**: dar de alta productos y ver analítica (rentabilidad, rotación)
  está reservado a **números de trabajadores** (`WORKER_NUMBERS`). Los clientes
  solo ven productos, precios y existencias; nunca costos ni márgenes.

---

## Funcionalidades por rol

| Acción | Cliente | Trabajador |
|---|:---:|:---:|
| Buscar producto / precio / existencia | ✅ | ✅ |
| Ver imagen del producto | ✅ | ✅ |
| Dar de alta un producto nuevo | ❌ | ✅ |
| Artículos más rentables | ❌ | ✅ |
| Artículos más vendidos | ❌ | ✅ |
| Artículos de lenta rotación | ❌ | ✅ |

### Ejemplos de conversación (trabajador)

- "Oye Chabelita, ¿cuántas existencias hay del tenis modelo X?"
- "Oye Chabelita, dame de alta el producto *Gorra YOOHOO azul*, precio 199, costo 80, 50 piezas."
- "Oye Chabelita, ¿cuáles son los 5 productos más rentables del último mes?"
- "Oye Chabelita, ¿qué artículos tienen lenta rotación?"

---

## Instalación y despliegue en tu VPS

### 1. Requisitos

- Python 3.12+ (o Docker).
- Un número de la **WhatsApp Cloud API** y un **token permanente** (System User).
- Acceso a tu **Odoo** por XML-RPC (usuario + contraseña o API key).
- Una **API key de Anthropic** (Claude).

### 2. Configuración

```bash
git clone <este-repo>
cd Agente-interno
cp .env.example .env
# Edita .env con tus credenciales (ver tabla abajo)
```

| Variable | Qué es |
|---|---|
| `WA_TOKEN` | Token permanente de la app de WhatsApp en Meta |
| `WA_PHONE_NUMBER_ID` | ID del número (no el número visible) |
| `WA_VERIFY_TOKEN` | Texto que tú inventas; se usa al verificar el webhook |
| `ODOO_URL` / `ODOO_DB` / `ODOO_USERNAME` / `ODOO_PASSWORD` | Conexión a Odoo |
| `ANTHROPIC_API_KEY` | Tu clave de Claude |
| `WORKER_NUMBERS` | Números de trabajadores, con país y sin `+`, separados por comas |
| `BRAND_NAME` | Marca que usa el agente (por defecto `YOOHOO`) |

### 3. Ejecutar

**Con Python:**

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Con Docker:**

```bash
docker build -t chabelita .
docker run -d --env-file .env -p 8000:8000 --name chabelita chabelita
```

### 4. Exponer el webhook y registrarlo en Meta

1. Pon el servicio detrás de HTTPS (Nginx, Caddy o un túnel). La URL pública
   del webhook será `https://tu-dominio/webhook`.
2. En el panel de Meta (WhatsApp > Configuración > Webhooks):
   - **Callback URL**: `https://tu-dominio/webhook`
   - **Verify token**: el mismo valor de `WA_VERIFY_TOKEN`.
   - Suscríbete al campo **messages**.

Meta hará un `GET /webhook` de verificación; el servicio responde
automáticamente con el `challenge`.

---

## Estructura del proyecto

```
app/
  main.py         FastAPI: webhook (GET verificación, POST mensajes) y enrutado
  config.py       Configuración desde variables de entorno
  whatsapp.py     Cliente de WhatsApp Cloud API (texto, imágenes, parseo)
  odoo_client.py  Cliente de Odoo (productos, existencias, alta, analítica)
  agent.py        Agente Claude con herramientas + control de permisos
  sessions.py     Sesiones en memoria (ventana tras la palabra clave)
tests/            Pruebas unitarias (lógica sin servicios externos)
Dockerfile        Imagen lista para producción
.env.example      Plantilla de configuración
```

---

## Pruebas

```bash
pip install pytest
pytest -q
```

---

## Notas y siguientes pasos

- **Analítica de Odoo**: usa el modelo `sale.report`. Los cálculos de margen
  toman `list_price`/`standard_price`; si tu Odoo maneja costos por método
  distinto (AVCO/FIFO), revisa `odoo_client.py` para ajustarlo a tu realidad.
- **Sesiones en memoria**: si despliegas varias instancias, cambia
  `SessionStore` por Redis para compartir estado.
- **Modelo de Claude**: por defecto `claude-sonnet-4-6` (buen costo/calidad).
  Puedes subirlo a Opus para analítica más compleja con `ANTHROPIC_MODEL`.
- **Seguridad**: ninguna credencial vive en el código; todo va por `.env`
  (ignorado por git). Verifica que `WORKER_NUMBERS` esté bien configurado antes
  de exponer la analítica.
