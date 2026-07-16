from datetime import date, datetime
import logging
from typing import Any

import httpx

from .config import Settings

logger = logging.getLogger(__name__)


class ClinikoAPIError(Exception):
    """Raised when Cliniko cannot return a usable response."""


class ClinikoAuthenticationError(ClinikoAPIError):
    """Raised when Cliniko rejects the configured API credentials."""


class ClinikoRateLimitError(ClinikoAPIError):
    """Raised when Cliniko rate limits the configured API user."""

    def __init__(self, reset_at: str | None = None) -> None:
        super().__init__("Cliniko rate limit exceeded")
        self.reset_at = reset_at


class ClinikoClient:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = settings.cliniko_api_key.get_secret_value()
        self._client = httpx.AsyncClient(
            base_url=settings.cliniko_api_base_url.rstrip("/"),
            auth=(self._api_key, ""),
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

    def _redact_api_key(self, value: str) -> str:
        return value.replace(self._api_key, "[REDACTED]")

    def _log_response_error(
        self,
        response: httpx.Response,
        query_params: dict[str, str | int],
    ) -> None:
        logger.error(
            "Cliniko request failed: status_code=%s requested_url=%s "
            "query_params=%s response_body=%s",
            response.status_code,
            self._redact_api_key(str(response.request.url)),
            query_params,
            self._redact_api_key(response.text),
        )

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

    async def list_available_times(
        self,
        business_id: str,
        practitioner_id: str,
        appointment_type_id: str,
        from_date: date,
        to_date: date,
    ) -> list[dict[str, str]]:
        path = (
            f"/businesses/{business_id}/practitioners/{practitioner_id}"
            f"/appointment_types/{appointment_type_id}/available_times"
        )
        query_params = {
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
            "per_page": 100,
        }

        try:
            response = await self._client.get(path, params=query_params)
        except httpx.RequestError as exc:
            logger.error(
                "Cliniko request failed: status_code=unavailable requested_url=%s "
                "query_params=%s response_body=unavailable",
                self._redact_api_key(str(exc.request.url)),
                query_params,
            )
            raise ClinikoAPIError(
                "Unable to retrieve availability from Cliniko"
            ) from exc

        if response.status_code in {401, 403}:
            self._log_response_error(response, query_params)
            raise ClinikoAuthenticationError("Cliniko authentication failed")
        if response.status_code == 429:
            self._log_response_error(response, query_params)
            raise ClinikoRateLimitError(response.headers.get("X-RateLimit-Reset"))

        try:
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            self._log_response_error(response, query_params)
            raise ClinikoAPIError(
                "Unable to retrieve availability from Cliniko"
            ) from exc

        available_times = (
            payload.get("available_times") if isinstance(payload, dict) else None
        )
        if not isinstance(available_times, list):
            self._log_response_error(response, query_params)
            raise ClinikoAPIError(
                "Cliniko returned an unexpected availability response"
            )

        slots = []
        for available_time in available_times:
            if not isinstance(available_time, dict):
                self._log_response_error(response, query_params)
                raise ClinikoAPIError(
                    "Cliniko returned an unexpected availability record"
                )

            appointment_start = available_time.get("appointment_start")
            if not isinstance(appointment_start, str):
                self._log_response_error(response, query_params)
                raise ClinikoAPIError(
                    "Cliniko returned an unexpected availability record"
                )

            try:
                parsed_start = datetime.fromisoformat(
                    appointment_start.replace("Z", "+00:00")
                )
            except ValueError as exc:
                self._log_response_error(response, query_params)
                raise ClinikoAPIError(
                    "Cliniko returned an invalid availability timestamp"
                ) from exc

            if parsed_start.tzinfo is None or parsed_start.utcoffset() is None:
                self._log_response_error(response, query_params)
                raise ClinikoAPIError(
                    "Cliniko returned an availability timestamp without a timezone"
                )

            slots.append(
                {
                    "start_time": parsed_start.isoformat(),
                    "business_id": business_id,
                    "practitioner_id": practitioner_id,
                    "appointment_type_id": appointment_type_id,
                }
            )

        return slots
