from typing import Any

import httpx

from .config import Settings


class ClinikoAPIError(Exception):
    """Raised when Cliniko cannot return a usable response."""


class ClinikoClient:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.cliniko_api_base_url.rstrip("/"),
            auth=(settings.cliniko_api_key.get_secret_value(), ""),
            headers={
                "Accept": "application/json",
                "User-Agent": settings.cliniko_user_agent,
            },
            timeout=settings.cliniko_timeout_seconds,
            transport=transport,
        )

    async def __aenter__(self) -> "ClinikoClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_businesses(self) -> list[dict[str, Any]]:
        try:
            response = await self._client.get("/businesses")
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ClinikoAPIError("Unable to retrieve businesses from Cliniko") from exc

        businesses = payload.get("businesses") if isinstance(payload, dict) else None
        if not isinstance(businesses, list):
            raise ClinikoAPIError("Cliniko returned an unexpected businesses response")

        return businesses
