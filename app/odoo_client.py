"""Cliente de Odoo vía XML-RPC.

Encapsula las consultas que necesita el agente: búsqueda de productos,
existencias, alta de productos y analítica de ventas (rentabilidad,
rotación, más vendidos). Usa solo la librería estándar (`xmlrpc.client`).

Referencia de la API externa de Odoo:
https://www.odoo.com/documentation/master/developer/reference/external_api.html
"""

from __future__ import annotations

import logging
import xmlrpc.client
from datetime import date, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# Estados de pedido de venta que cuentan como ventas reales.
_SALE_DONE_STATES = ["sale", "done"]


class OdooError(RuntimeError):
    """Error al comunicarse con Odoo."""


class OdooClient:
    def __init__(self, url: str, db: str, username: str, password: str):
        if not all([url, db, username, password]):
            raise OdooError(
                "Faltan credenciales de Odoo (ODOO_URL/DB/USERNAME/PASSWORD)."
            )
        self.url = url.rstrip("/")
        self.db = db
        self.username = username
        self.password = password
        self._uid: int | None = None
        self._common = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common")
        self._models = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/object")

    # ------------------------------------------------------------------ #
    # Infraestructura
    # ------------------------------------------------------------------ #
    @property
    def uid(self) -> int:
        if self._uid is None:
            uid = self._common.authenticate(self.db, self.username, self.password, {})
            if not uid:
                raise OdooError("Autenticación en Odoo fallida. Revisa credenciales.")
            self._uid = uid
        return self._uid

    def execute(self, model: str, method: str, *args: Any, **kwargs: Any) -> Any:
        try:
            return self._models.execute_kw(
                self.db, self.uid, self.password, model, method, list(args), kwargs
            )
        except xmlrpc.client.Fault as exc:
            logger.exception("Error en Odoo %s.%s", model, method)
            raise OdooError(f"Odoo respondió con un error: {exc.faultString}") from exc

    # ------------------------------------------------------------------ #
    # Productos y existencias
    # ------------------------------------------------------------------ #
    def buscar_productos(self, texto: str, limite: int = 5) -> list[dict]:
        """Busca productos por nombre o código de referencia interno."""
        domain = [
            "|",
            ("name", "ilike", texto),
            ("default_code", "ilike", texto),
        ]
        return self.execute(
            "product.product",
            "search_read",
            domain,
            fields=[
                "id",
                "name",
                "default_code",
                "list_price",
                "standard_price",
                "qty_available",
                "uom_id",
            ],
            limit=limite,
        )

    def get_product_image(self, product_id: int) -> str | None:
        """Devuelve la imagen del producto en base64 (image_1920) o None."""
        rows = self.execute(
            "product.product", "read", [product_id], fields=["image_1920"]
        )
        if rows and rows[0].get("image_1920"):
            return rows[0]["image_1920"]
        return None

    def get_products_images(self, product_ids: list[int]) -> dict[int, str]:
        """Devuelve {product_id: imagen_base64} para varios productos.

        Lee `image_1920` (la imagen del backend de Odoo), que existe aunque el
        producto NO esté publicado en la página web. Odoo devuelve la imagen de
        la variante o, si no tiene, la de la plantilla del producto.
        """
        if not product_ids:
            return {}
        rows = self.execute(
            "product.product", "read", product_ids, fields=["image_1920"]
        )
        return {r["id"]: r["image_1920"] for r in rows if r.get("image_1920")}

    def alta_producto(
        self,
        nombre: str,
        precio_venta: float,
        costo: float | None = None,
        codigo: str | None = None,
        cantidad_inicial: float | None = None,
        categoria: str | None = None,
    ) -> dict:
        """Da de alta un producto nuevo en Odoo.

        Crea un `product.template` que se puede vender y, opcionalmente,
        ajusta su existencia inicial.
        """
        vals: dict[str, Any] = {
            "name": nombre,
            "list_price": precio_venta,
            "sale_ok": True,
            "purchase_ok": True,
            "type": "product",  # producto almacenable (con inventario)
        }
        if costo is not None:
            vals["standard_price"] = costo
        if codigo:
            vals["default_code"] = codigo
        if categoria:
            cat_ids = self.execute(
                "product.category", "search", [("name", "ilike", categoria)], limit=1
            )
            if cat_ids:
                vals["categ_id"] = cat_ids[0]

        template_id = self.execute("product.template", "create", vals)

        # El product.product (variante) se crea automáticamente.
        variant_ids = self.execute(
            "product.product",
            "search",
            [("product_tmpl_id", "=", template_id)],
            limit=1,
        )
        variant_id = variant_ids[0] if variant_ids else None

        if cantidad_inicial and variant_id:
            self._ajustar_existencia(variant_id, cantidad_inicial)

        return {
            "template_id": template_id,
            "product_id": variant_id,
            "nombre": nombre,
            "precio_venta": precio_venta,
            "costo": costo,
            "codigo": codigo,
            "cantidad_inicial": cantidad_inicial,
        }

    def _ajustar_existencia(self, product_id: int, cantidad: float) -> None:
        """Fija la cantidad disponible de un producto en su almacén principal."""
        location_ids = self.execute(
            "stock.location",
            "search",
            [("usage", "=", "internal")],
            limit=1,
        )
        if not location_ids:
            logger.warning("No se encontró una ubicación de inventario interna.")
            return
        quant_vals = {
            "product_id": product_id,
            "location_id": location_ids[0],
            "inventory_quantity": cantidad,
        }
        try:
            quant_id = self.execute("stock.quant", "create", quant_vals)
            self.execute("stock.quant", "action_apply_inventory", [quant_id])
        except OdooError:
            logger.exception("No se pudo ajustar la existencia inicial.")

    # ------------------------------------------------------------------ #
    # Analítica de ventas
    # ------------------------------------------------------------------ #
    def _ventas_por_producto(self, dias: int) -> dict[int, dict]:
        """Agrega ventas por producto en los últimos `dias` días.

        Devuelve {product_id: {qty, importe, nombre}} usando `sale.report`.
        """
        desde = (date.today() - timedelta(days=dias)).isoformat()
        domain = [("date", ">=", desde), ("state", "in", _SALE_DONE_STATES)]
        groups = self.execute(
            "sale.report",
            "read_group",
            domain,
            fields=["product_uom_qty:sum", "price_subtotal:sum"],
            groupby=["product_id"],
            lazy=False,
        )
        ventas: dict[int, dict] = {}
        for g in groups:
            prod = g.get("product_id")
            if not prod:
                continue
            pid = prod[0]
            ventas[pid] = {
                "product_id": pid,
                "nombre": prod[1],
                "qty": g.get("product_uom_qty", 0.0) or 0.0,
                "importe": g.get("price_subtotal", 0.0) or 0.0,
            }
        return ventas

    def _costos(self, product_ids: list[int]) -> dict[int, float]:
        if not product_ids:
            return {}
        rows = self.execute(
            "product.product", "read", product_ids, fields=["standard_price"]
        )
        return {r["id"]: r.get("standard_price", 0.0) or 0.0 for r in rows}

    def mas_rentables(self, dias: int = 30, limite: int = 5) -> list[dict]:
        """Productos con mayor margen total (precio vendido − costo) en el período."""
        ventas = self._ventas_por_producto(dias)
        costos = self._costos(list(ventas))
        resultado = []
        for pid, v in ventas.items():
            costo_total = costos.get(pid, 0.0) * v["qty"]
            margen = v["importe"] - costo_total
            margen_pct = (margen / v["importe"] * 100) if v["importe"] else 0.0
            resultado.append(
                {
                    "nombre": v["nombre"],
                    "unidades_vendidas": round(v["qty"], 2),
                    "ingresos": round(v["importe"], 2),
                    "margen": round(margen, 2),
                    "margen_pct": round(margen_pct, 1),
                }
            )
        resultado.sort(key=lambda x: x["margen"], reverse=True)
        return resultado[:limite]

    def mas_vendidos(self, dias: int = 30, limite: int = 5) -> list[dict]:
        """Productos con más unidades vendidas en el período."""
        ventas = self._ventas_por_producto(dias)
        resultado = [
            {
                "nombre": v["nombre"],
                "unidades_vendidas": round(v["qty"], 2),
                "ingresos": round(v["importe"], 2),
            }
            for v in ventas.values()
        ]
        resultado.sort(key=lambda x: x["unidades_vendidas"], reverse=True)
        return resultado[:limite]

    def lenta_rotacion(self, dias: int = 90, limite: int = 5) -> list[dict]:
        """Productos con existencia en almacén pero poca o nula venta.

        Escanea los productos con más existencias y los ordena por menor
        rotación (unidades vendidas / existencia) en el período.
        """
        ventas = self._ventas_por_producto(dias)
        en_stock = self.execute(
            "product.product",
            "search_read",
            [("qty_available", ">", 0)],
            fields=["id", "name", "qty_available", "list_price"],
            order="qty_available desc",
            limit=200,
        )
        resultado = []
        for p in en_stock:
            pid = p["id"]
            vendidas = ventas.get(pid, {}).get("qty", 0.0)
            stock = p["qty_available"]
            rotacion = (vendidas / stock) if stock else 0.0
            resultado.append(
                {
                    "nombre": p["name"],
                    "existencia": round(stock, 2),
                    "unidades_vendidas": round(vendidas, 2),
                    "rotacion": round(rotacion, 3),
                    "valor_inmovilizado": round(stock * p.get("list_price", 0.0), 2),
                }
            )
        # Menor rotación primero; a igual rotación, más valor inmovilizado.
        resultado.sort(key=lambda x: (x["rotacion"], -x["valor_inmovilizado"]))
        return resultado[:limite]
