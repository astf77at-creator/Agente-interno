"""Configuración del servicio cargada desde variables de entorno (.env).

Todas las credenciales se leen del entorno; nunca se escriben en el código.
Copia `.env.example` a `.env` y rellena tus valores.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- WhatsApp Cloud API (Meta) ---
    wa_token: str = ""  # Token permanente del System User
    wa_phone_number_id: str = ""  # ID del número de teléfono de WhatsApp
    wa_verify_token: str = "chabelita"  # Token para verificar el webhook
    wa_api_version: str = "v21.0"

    # --- Odoo (XML-RPC) ---
    odoo_url: str = ""  # ej. https://miempresa.odoo.com
    odoo_db: str = ""
    odoo_username: str = ""
    odoo_password: str = ""  # contraseña o API key de Odoo

    # --- Anthropic (Claude) ---
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    anthropic_max_tokens: int = 1024

    # --- Lógica del agente ---
    # Palabra clave para "despertar" al bot (sin acentos, en minúsculas).
    wake_word: str = "chabelita"
    # Números (con código de país, sin +) autorizados como TRABAJADORES.
    # Pueden dar de alta productos y ver analítica de rentabilidad/rotación.
    # Separados por comas. ej. "5215512345678,5215587654321"
    worker_numbers: str = ""
    # Minutos que dura una conversación activa tras la palabra clave.
    session_ttl_minutes: int = 15
    # Marca de la empresa, usada en respuestas del agente.
    brand_name: str = "YOOHOO"

    @property
    def worker_set(self) -> set[str]:
        return {n.strip() for n in self.worker_numbers.split(",") if n.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
