"""Agente conversacional "Chabelita" basado en Claude con uso de herramientas.

Recibe el texto del usuario, decide qué herramientas de Odoo llamar
(buscar productos, existencias, alta de producto, analítica) y redacta
una respuesta en español para WhatsApp.

La autorización se aplica AQUÍ: las herramientas de trabajador
(alta de producto y analítica) solo se exponen a números autorizados.
"""

from __future__ import annotations

import json
import logging

import anthropic

from .odoo_client import OdooClient, OdooError

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Definición de herramientas (esquema para Claude)
# --------------------------------------------------------------------------- #
TOOL_BUSCAR = {
    "name": "buscar_producto",
    "description": (
        "Busca productos en el catálogo de Odoo por nombre o código. "
        "Devuelve precio de venta, existencia disponible e identificadores. "
        "Úsala cuando el cliente pregunte por un producto, su precio o si hay stock."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "texto": {"type": "string", "description": "Nombre o código a buscar"},
            "limite": {"type": "integer", "description": "Máx. resultados (def. 5)"},
        },
        "required": ["texto"],
    },
}

TOOL_ALTA = {
    "name": "alta_producto",
    "description": (
        "Da de alta un producto NUEVO en Odoo. Solo para trabajadores. "
        "Pide confirmación de los datos antes de crear si falta algo importante."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "nombre": {"type": "string"},
            "precio_venta": {"type": "number"},
            "costo": {"type": "number", "description": "Costo/compra (opcional)"},
            "codigo": {"type": "string", "description": "Referencia interna (opcional)"},
            "cantidad_inicial": {
                "type": "number",
                "description": "Existencia inicial (opcional)",
            },
            "categoria": {"type": "string", "description": "Categoría (opcional)"},
        },
        "required": ["nombre", "precio_venta"],
    },
}

TOOL_RENTABLES = {
    "name": "productos_mas_rentables",
    "description": (
        "Lista los productos con mayor margen de ganancia (ingresos menos costo) "
        "en un período. Solo para trabajadores."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "dias": {"type": "integer", "description": "Período en días (def. 30)"},
            "limite": {"type": "integer", "description": "Cuántos listar (def. 5)"},
        },
    },
}

TOOL_VENDIDOS = {
    "name": "productos_mas_vendidos",
    "description": (
        "Lista los productos con más unidades vendidas en un período. "
        "Solo para trabajadores."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "dias": {"type": "integer"},
            "limite": {"type": "integer"},
        },
    },
}

TOOL_LENTA = {
    "name": "productos_lenta_rotacion",
    "description": (
        "Lista productos con existencia en almacén pero poca o nula venta "
        "(lenta rotación / capital inmovilizado). Solo para trabajadores."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "dias": {"type": "integer", "description": "Período en días (def. 90)"},
            "limite": {"type": "integer"},
        },
    },
}

CUSTOMER_TOOLS = [TOOL_BUSCAR]
WORKER_TOOLS = [TOOL_BUSCAR, TOOL_ALTA, TOOL_RENTABLES, TOOL_VENDIDOS, TOOL_LENTA]


def _system_prompt(brand: str, is_worker: bool) -> str:
    rol = (
        "Estás atendiendo a un TRABAJADOR autorizado: puedes dar de alta "
        "productos y compartir analítica de ventas, rentabilidad y rotación."
        if is_worker
        else "Estás atendiendo a un CLIENTE: solo informa de productos, precios "
        "y existencias. No reveles costos, márgenes ni analítica interna."
    )
    return (
        f"Eres Chabelita, la asistente de WhatsApp de {brand}. Hablas en español "
        "de forma cercana, breve y clara (es para WhatsApp). Usas los datos reales "
        f"de Odoo a través de tus herramientas; nunca inventes precios o existencias. "
        f"{rol} "
        "Cuando muestres listas, usa viñetas cortas. Si una herramienta falla o no "
        "hay datos, dilo con naturalidad y sugiere una alternativa. Antes de dar de "
        "alta un producto, confirma nombre y precio con el trabajador."
    )


class ChabelitaAgent:
    def __init__(
        self,
        odoo: OdooClient,
        anthropic_api_key: str,
        model: str,
        max_tokens: int,
        brand: str,
    ):
        self.odoo = odoo
        self.client = anthropic.Anthropic(api_key=anthropic_api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.brand = brand

    def run(self, user_text: str, is_worker: bool) -> tuple[str, list[dict]]:
        """Procesa el mensaje y devuelve (texto_respuesta, imagenes_a_enviar).

        imagenes_a_enviar: lista de {"image_b64": str, "caption": str}.
        """
        tools = WORKER_TOOLS if is_worker else CUSTOMER_TOOLS
        system = _system_prompt(self.brand, is_worker)
        messages: list[dict] = [{"role": "user", "content": user_text}]
        images: list[dict] = []

        # Bucle de uso de herramientas (máx. 6 vueltas por seguridad).
        for _ in range(6):
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system,
                tools=tools,
                messages=messages,
            )
            if resp.stop_reason != "tool_use":
                return self._collect_text(resp), images

            messages.append({"role": "assistant", "content": resp.content})
            tool_results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                result_text, imgs = self._dispatch(block.name, block.input, is_worker)
                images.extend(imgs)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        return ("Disculpa, no pude completar la consulta. ¿La intentamos de nuevo?", images)

    @staticmethod
    def _collect_text(resp) -> str:
        parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        return "\n".join(parts).strip() or "¿En qué te puedo ayudar?"

    # ------------------------------------------------------------------ #
    # Ejecución de herramientas
    # ------------------------------------------------------------------ #
    def _dispatch(
        self, name: str, args: dict, is_worker: bool
    ) -> tuple[str, list[dict]]:
        worker_only = {
            "alta_producto",
            "productos_mas_rentables",
            "productos_mas_vendidos",
            "productos_lenta_rotacion",
        }
        if name in worker_only and not is_worker:
            return ("ACCESO DENEGADO: esta acción es solo para trabajadores.", [])

        try:
            if name == "buscar_producto":
                return self._buscar(args)
            if name == "alta_producto":
                data = self.odoo.alta_producto(
                    nombre=args["nombre"],
                    precio_venta=args["precio_venta"],
                    costo=args.get("costo"),
                    codigo=args.get("codigo"),
                    cantidad_inicial=args.get("cantidad_inicial"),
                    categoria=args.get("categoria"),
                )
                return (json.dumps(data, ensure_ascii=False), [])
            if name == "productos_mas_rentables":
                data = self.odoo.mas_rentables(
                    args.get("dias", 30), args.get("limite", 5)
                )
                return (json.dumps(data, ensure_ascii=False), [])
            if name == "productos_mas_vendidos":
                data = self.odoo.mas_vendidos(
                    args.get("dias", 30), args.get("limite", 5)
                )
                return (json.dumps(data, ensure_ascii=False), [])
            if name == "productos_lenta_rotacion":
                data = self.odoo.lenta_rotacion(
                    args.get("dias", 90), args.get("limite", 5)
                )
                return (json.dumps(data, ensure_ascii=False), [])
        except OdooError as exc:
            return (f"Error consultando Odoo: {exc}", [])
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error en herramienta %s", name)
            return (f"Error inesperado: {exc}", [])

        return (f"Herramienta desconocida: {name}", [])

    def _buscar(self, args: dict) -> tuple[str, list[dict]]:
        productos = self.odoo.buscar_productos(args["texto"], args.get("limite", 5))
        images: list[dict] = []
        # Adjunta la imagen del primer resultado, si existe.
        if productos:
            img = self.odoo.get_product_image(productos[0]["id"])
            if img:
                images.append(
                    {"image_b64": img, "caption": productos[0]["name"]}
                )
        # No exponemos standard_price (costo) en el texto que ve el modelo
        # para clientes; el system prompt ya lo restringe, pero limpiamos aquí.
        limpio = [
            {
                "nombre": p["name"],
                "codigo": p.get("default_code"),
                "precio": p.get("list_price"),
                "existencia": p.get("qty_available"),
            }
            for p in productos
        ]
        return (json.dumps(limpio, ensure_ascii=False), images)
