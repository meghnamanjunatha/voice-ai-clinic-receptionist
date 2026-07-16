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

    async def list_practitioners(self) -> list[dict[str, str | None]]:
        try:
            response = await self._client.get("/practitioners", params={"per_page": 100})
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ClinikoAPIError(
                "Unable to retrieve practitioners from Cliniko"
            ) from exc

        practitioners = (
            payload.get("practitioners") if isinstance(payload, dict) else None
        )
        if not isinstance(practitioners, list):
            raise ClinikoAPIError(
                "Cliniko returned an unexpected practitioners response"
            )

        essential_fields = []
        for practitioner in practitioners:
            if not isinstance(practitioner, dict) or "id" not in practitioner:
                raise ClinikoAPIError(
                    "Cliniko returned an unexpected practitioner record"
                )
            essential_fields.append(
                {
                    "id": str(practitioner["id"]),
                    "full_name": practitioner.get("display_name"),
                }
            )

        return essential_fields

    async def list_appointment_types(self) -> list[dict[str, str | int]]:
        try:
            response = await self._client.get(
                "/appointment_types", params={"per_page": 100}
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ClinikoAPIError(
                "Unable to retrieve appointment types from Cliniko"
            ) from exc

        appointment_types = (
            payload.get("appointment_types") if isinstance(payload, dict) else None
        )
        if not isinstance(appointment_types, list):
            raise ClinikoAPIError(
                "Cliniko returned an unexpected appointment types response"
            )

        essential_fields = []
        for appointment_type in appointment_types:
            required_fields = {"id", "name", "duration_in_minutes"}
            if not isinstance(appointment_type, dict) or not required_fields.issubset(
                appointment_type
            ):
                raise ClinikoAPIError(
                    "Cliniko returned an unexpected appointment type record"
                )
            essential_fields.append(
                {
                    "id": str(appointment_type["id"]),
                    "name": appointment_type["name"],
                    "duration_in_minutes": appointment_type["duration_in_minutes"],
                }
            )

        return essential_fields
