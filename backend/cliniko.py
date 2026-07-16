from datetime import date, datetime
import logging
import re
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


class ClinikoPatientConflictError(ClinikoAPIError):
    """Raised when a phone number belongs to multiple Cliniko patients."""


class InvalidPhoneNumberError(ValueError):
    """Raised when a phone number cannot be normalized safely."""


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

    @staticmethod
    def normalize_phone(phone: str) -> str:
        normalized = re.sub(r"\D", "", phone)
        if not 7 <= len(normalized) <= 15:
            raise InvalidPhoneNumberError(
                "phone must contain between 7 and 15 digits"
            )
        return normalized

    def _raise_for_patient_response(self, response: httpx.Response) -> None:
        if response.status_code in {401, 403}:
            raise ClinikoAuthenticationError("Cliniko authentication failed")
        if response.status_code == 429:
            raise ClinikoRateLimitError(response.headers.get("X-RateLimit-Reset"))
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ClinikoAPIError("Cliniko patient request failed") from exc

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

    async def find_or_create_patient(
        self,
        full_name: str,
        phone: str,
    ) -> dict[str, str | bool]:
        normalized_phone = self.normalize_phone(phone)
        matches = await self._find_patients_by_phone(normalized_phone)

        if len(matches) > 1:
            raise ClinikoPatientConflictError(
                "Multiple Cliniko patients share this phone number"
            )
        if len(matches) == 1:
            return self._simplify_patient(
                matches[0], normalized_phone, is_new_patient=False
            )

        patient = await self._create_patient(full_name, normalized_phone)
        return self._simplify_patient(
            patient, normalized_phone, is_new_patient=True
        )

    async def _find_patients_by_phone(
        self,
        normalized_phone: str,
    ) -> list[dict[str, Any]]:
        matches = []
        page = 1

        while True:
            try:
                response = await self._client.get(
                    "/patients",
                    params={"page": page, "per_page": 100},
                )
            except httpx.RequestError as exc:
                raise ClinikoAPIError("Unable to search Cliniko patients") from exc

            self._raise_for_patient_response(response)
            try:
                payload = response.json()
            except ValueError as exc:
                raise ClinikoAPIError(
                    "Cliniko returned an invalid patients response"
                ) from exc

            patients = payload.get("patients") if isinstance(payload, dict) else None
            total_entries = (
                payload.get("total_entries") if isinstance(payload, dict) else None
            )
            if not isinstance(patients, list) or not isinstance(total_entries, int):
                raise ClinikoAPIError(
                    "Cliniko returned an unexpected patients response"
                )

            for patient in patients:
                if not isinstance(patient, dict):
                    raise ClinikoAPIError(
                        "Cliniko returned an unexpected patient record"
                    )
                if self._patient_has_phone(patient, normalized_phone):
                    matches.append(patient)

            if page * 100 >= total_entries or not patients:
                return matches
            page += 1

    def _patient_has_phone(
        self,
        patient: dict[str, Any],
        normalized_phone: str,
    ) -> bool:
        phone_numbers = patient.get("patient_phone_numbers") or []
        if not isinstance(phone_numbers, list):
            raise ClinikoAPIError(
                "Cliniko returned an unexpected patient phone number record"
            )

        for phone_number in phone_numbers:
            if not isinstance(phone_number, dict):
                raise ClinikoAPIError(
                    "Cliniko returned an unexpected patient phone number record"
                )
            cliniko_normalized = phone_number.get("normalized_number")
            if isinstance(cliniko_normalized, str):
                try:
                    if self.normalize_phone(cliniko_normalized) == normalized_phone:
                        return True
                except InvalidPhoneNumberError:
                    continue

            raw_number = phone_number.get("number")
            if isinstance(raw_number, str):
                try:
                    if self.normalize_phone(raw_number) == normalized_phone:
                        return True
                except InvalidPhoneNumberError:
                    continue

        return False

    async def _create_patient(
        self,
        full_name: str,
        normalized_phone: str,
    ) -> dict[str, Any]:
        first_name, separator, last_name = full_name.strip().partition(" ")
        if not separator:
            last_name = ""

        try:
            response = await self._client.post(
                "/patients",
                json={
                    "first_name": first_name,
                    "last_name": last_name,
                    "patient_phone_numbers": [
                        {
                            "number": normalized_phone,
                            "phone_type": "Mobile",
                        }
                    ],
                },
            )
        except httpx.RequestError as exc:
            raise ClinikoAPIError("Unable to create Cliniko patient") from exc

        self._raise_for_patient_response(response)
        try:
            patient = response.json()
        except ValueError as exc:
            raise ClinikoAPIError(
                "Cliniko returned an invalid patient response"
            ) from exc
        if not isinstance(patient, dict):
            raise ClinikoAPIError("Cliniko returned an unexpected patient response")
        return patient

    def _simplify_patient(
        self,
        patient: dict[str, Any],
        normalized_phone: str,
        is_new_patient: bool,
    ) -> dict[str, str | bool]:
        patient_id = patient.get("id")
        full_name = patient.get("label")
        if not isinstance(full_name, str) or not full_name.strip():
            name_parts = [patient.get("first_name"), patient.get("last_name")]
            full_name = " ".join(
                part.strip() for part in name_parts if isinstance(part, str) and part.strip()
            )

        if patient_id is None or not full_name:
            raise ClinikoAPIError("Cliniko returned an unexpected patient record")

        return {
            "id": str(patient_id),
            "full_name": full_name,
            "phone": normalized_phone,
            "is_new_patient": is_new_patient,
        }
