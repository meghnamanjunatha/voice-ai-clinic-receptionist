from datetime import UTC, date, datetime
import logging
import re
from typing import Any
from urllib.parse import urlparse

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


class ClinikoPatientNotFoundError(ClinikoAPIError):
    """Raised when a patient does not exist in Cliniko."""


class InvalidPhoneNumberError(ValueError):
    """Raised when a phone number cannot be normalized safely."""


class ClinikoSlotUnavailableError(ClinikoAPIError):
    """Raised when Cliniko rejects a no-longer-available appointment time."""


class ClinikoInvalidAppointmentIDsError(ClinikoAPIError):
    """Raised when Cliniko rejects an appointment's referenced resource IDs."""


class ClinikoAppointmentNotFoundError(ClinikoAPIError):
    """Raised when an individual appointment does not exist in Cliniko."""


class ClinikoInvalidAppointmentDateTimeError(ClinikoAPIError):
    """Raised when Cliniko rejects an appointment date-time."""


class ClinikoAppointmentAlreadyCancelledError(ClinikoAPIError):
    """Raised when an individual appointment is already cancelled."""


class ClinikoInvalidCancellationReasonError(ClinikoAPIError):
    """Raised when Cliniko rejects a cancellation reason."""


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
        query_params: dict[str, Any],
    ) -> None:
        logger.error(
            "Cliniko request failed: status_code=%s requested_url=%s "
            "query_params=%s response_body=%s",
            response.status_code,
            self._redact_api_key(str(response.request.url)),
            query_params,
            self._redact_api_key(response.text),
        )

    def _log_appointment_lookup_failure(
        self,
        *,
        query_params: dict[str, Any],
        exception: Exception,
        response: httpx.Response | None = None,
        request_url: str | None = None,
    ) -> None:
        logger.error(
            "Cliniko patient appointment lookup failed: status_code=%s "
            "requested_url=%s query_params=%s response_body=%s "
            "exception_type=%s exception_message=%s",
            response.status_code if response is not None else "unavailable",
            self._redact_api_key(
                str(response.request.url) if response is not None else request_url or "unavailable"
            ),
            query_params,
            self._redact_api_key(response.text) if response is not None else "unavailable",
            type(exception).__name__,
            self._redact_api_key(str(exception)),
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

    async def list_patient_appointments(
        self,
        patient_id: str,
        include_past: bool = False,
    ) -> list[dict[str, str]]:
        await self._verify_patient_exists(patient_id)

        now = datetime.now(UTC)
        filters = [f"patient_id:={patient_id}"]
        if not include_past:
            filters.append(f"starts_at:>{now.isoformat().replace('+00:00', 'Z')}")

        appointments: list[dict[str, str]] = []
        page = 1
        while True:
            query_params: dict[str, str | int | list[str]] = {
                "page": page,
                "per_page": 100,
                "sort": "starts_at:asc",
                "q[]": filters,
            }
            response = await self._get_appointment_lookup_page(
                "/individual_appointments",
                query_params,
            )
            try:
                payload = response.json()
            except ValueError as exc:
                self._log_appointment_lookup_failure(
                    response=response,
                    query_params=query_params,
                    exception=exc,
                )
                raise ClinikoAPIError(
                    "Cliniko returned an invalid appointments response"
                ) from exc

            records = (
                payload.get("individual_appointments")
                if isinstance(payload, dict)
                else None
            )
            total_entries = payload.get("total_entries") if isinstance(payload, dict) else None
            if not isinstance(records, list) or not isinstance(total_entries, int):
                exc = ClinikoAPIError(
                    "Cliniko returned an unexpected appointments response"
                )
                self._log_appointment_lookup_failure(
                    response=response,
                    query_params=query_params,
                    exception=exc,
                )
                raise exc

            for record in records:
                try:
                    simplified = self._simplify_patient_appointment(
                        record,
                        expected_patient_id=patient_id,
                    )
                except ClinikoAPIError as exc:
                    self._log_appointment_lookup_failure(
                        response=response,
                        query_params=query_params,
                        exception=exc,
                    )
                    raise
                if simplified["status"] == "cancelled":
                    continue
                starts_at = datetime.fromisoformat(simplified["starts_at"])
                if include_past or starts_at >= now:
                    appointments.append(simplified)

            if page * 100 >= total_entries or not records:
                break
            page += 1

        appointments.sort(key=lambda appointment: appointment["starts_at"])
        return appointments

    async def _verify_patient_exists(self, patient_id: str) -> None:
        query_params: dict[str, str | int | list[str]] = {}
        response = await self._get_appointment_lookup_page(
            f"/patients/{patient_id}",
            query_params,
        )
        try:
            patient = response.json()
        except ValueError as exc:
            self._log_appointment_lookup_failure(
                response=response,
                query_params=query_params,
                exception=exc,
            )
            raise ClinikoAPIError("Cliniko returned an invalid patient response") from exc
        if not isinstance(patient, dict) or str(patient.get("id")) != patient_id:
            exc = ClinikoAPIError("Cliniko returned an unexpected patient response")
            self._log_appointment_lookup_failure(
                response=response,
                query_params=query_params,
                exception=exc,
            )
            raise exc

    async def _get_appointment_lookup_page(
        self,
        path: str,
        query_params: dict[str, str | int | list[str]],
    ) -> httpx.Response:
        try:
            response = await self._client.get(path, params=query_params)
        except httpx.RequestError as exc:
            self._log_appointment_lookup_failure(
                request_url=str(exc.request.url),
                query_params=query_params,
                exception=exc,
            )
            raise ClinikoAPIError(
                "Unable to retrieve patient appointments from Cliniko"
            ) from exc

        if response.status_code in {401, 403}:
            self._log_response_error(response, query_params)
            raise ClinikoAuthenticationError("Cliniko authentication failed")
        if response.status_code == 404:
            self._log_response_error(response, query_params)
            raise ClinikoPatientNotFoundError("Cliniko patient not found")
        if response.status_code == 429:
            self._log_response_error(response, query_params)
            raise ClinikoRateLimitError(response.headers.get("X-RateLimit-Reset"))
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            self._log_appointment_lookup_failure(
                response=response,
                query_params=query_params,
                exception=exc,
            )
            raise ClinikoAPIError(
                "Unable to retrieve patient appointments from Cliniko"
            ) from exc
        return response

    def _simplify_patient_appointment(
        self,
        appointment: Any,
        expected_patient_id: str,
    ) -> dict[str, str]:
        if not isinstance(appointment, dict):
            raise ClinikoAPIError(
                "Cliniko appointment record must be an object"
            )
        for field in ("id", "starts_at"):
            if appointment.get(field) is None:
                raise ClinikoAPIError(
                    f"Cliniko appointment is missing required field '{field}'"
                )

        patient_id = self._extract_linked_resource_id(appointment, "patient")
        business_id = self._extract_linked_resource_id(appointment, "business")
        practitioner_id = self._extract_linked_resource_id(
            appointment, "practitioner"
        )
        appointment_type_id = self._extract_linked_resource_id(
            appointment, "appointment_type"
        )
        if patient_id != expected_patient_id:
            raise ClinikoAPIError("Cliniko returned an appointment for another patient")

        try:
            starts_at = datetime.fromisoformat(
                str(appointment["starts_at"]).replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ClinikoAPIError(
                "Cliniko returned an invalid appointment timestamp"
            ) from exc
        if starts_at.tzinfo is None or starts_at.utcoffset() is None:
            raise ClinikoAPIError(
                "Cliniko returned an appointment timestamp without a timezone"
            )

        if appointment.get("cancelled_at") is not None:
            status = "cancelled"
        elif appointment.get("deleted_at") is not None:
            status = "deleted"
        elif appointment.get("did_not_arrive") is True:
            status = "did_not_arrive"
        elif appointment.get("patient_arrived") is True:
            status = "arrived"
        else:
            status = "booked"

        return {
            "appointment_id": str(appointment["id"]),
            "patient_id": patient_id,
            "practitioner_id": practitioner_id,
            "business_id": business_id,
            "appointment_type_id": appointment_type_id,
            "starts_at": starts_at.isoformat(),
            "status": status,
        }

    def _extract_linked_resource_id(
        self,
        appointment: dict[str, Any],
        resource_name: str,
    ) -> str:
        link_field = f"{resource_name}.links.self"
        resource = appointment.get(resource_name)
        if not isinstance(resource, dict):
            raise ClinikoAPIError(
                f"Cliniko appointment is missing required link '{link_field}'"
            )
        links = resource.get("links")
        if not isinstance(links, dict):
            raise ClinikoAPIError(
                f"Cliniko appointment is missing required link '{link_field}'"
            )
        self_url = links.get("self")
        if not isinstance(self_url, str) or not self_url.strip():
            raise ClinikoAPIError(
                f"Cliniko appointment is missing required link '{link_field}'"
            )

        path_segments = [
            segment for segment in urlparse(self_url).path.split("/") if segment
        ]
        if not path_segments:
            raise ClinikoAPIError(
                f"Cliniko appointment has invalid link '{link_field}'"
            )
        resource_id = path_segments[-1]
        if not resource_id.isdigit() or resource_id == "0":
            raise ClinikoAPIError(
                f"Cliniko appointment has invalid resource ID in link '{link_field}'"
            )
        return resource_id

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

    async def create_individual_appointment(
        self,
        patient_id: str,
        business_id: str,
        practitioner_id: str,
        appointment_type_id: str,
        starts_at: datetime,
    ) -> dict[str, str]:
        request_body = {
            "patient_id": patient_id,
            "business_id": business_id,
            "practitioner_id": practitioner_id,
            "appointment_type_id": appointment_type_id,
            "starts_at": starts_at.isoformat(),
        }

        try:
            # Appointment creation is intentionally attempted exactly once.
            response = await self._client.post(
                "/individual_appointments",
                json=request_body,
            )
        except httpx.RequestError as exc:
            raise ClinikoAPIError("Unable to create Cliniko appointment") from exc

        if response.status_code in {401, 403}:
            raise ClinikoAuthenticationError("Cliniko authentication failed")
        if response.status_code == 429:
            raise ClinikoRateLimitError(response.headers.get("X-RateLimit-Reset"))
        if response.status_code == 409:
            raise ClinikoSlotUnavailableError(
                "The selected appointment time is no longer available"
            )
        if response.status_code == 404:
            raise ClinikoInvalidAppointmentIDsError(
                "One or more Cliniko IDs are invalid"
            )
        if response.status_code == 422:
            self._raise_for_booking_validation_error(response)

        try:
            response.raise_for_status()
            appointment = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ClinikoAPIError("Unable to create Cliniko appointment") from exc

        if not isinstance(appointment, dict):
            raise ClinikoAPIError(
                "Cliniko returned an unexpected appointment response"
            )

        appointment_id = appointment.get("id")
        response_starts_at = appointment.get("starts_at")
        if appointment_id is None or not isinstance(response_starts_at, str):
            raise ClinikoAPIError(
                "Cliniko returned an unexpected appointment response"
            )

        try:
            parsed_starts_at = datetime.fromisoformat(
                response_starts_at.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ClinikoAPIError(
                "Cliniko returned an invalid appointment timestamp"
            ) from exc
        if parsed_starts_at.tzinfo is None or parsed_starts_at.utcoffset() is None:
            raise ClinikoAPIError(
                "Cliniko returned an appointment timestamp without a timezone"
            )

        return {
            "appointment_id": str(appointment_id),
            "patient_id": patient_id,
            "business_id": business_id,
            "practitioner_id": practitioner_id,
            "appointment_type_id": appointment_type_id,
            "starts_at": parsed_starts_at.isoformat(),
            "status": "booked",
        }

    def _raise_for_booking_validation_error(self, response: httpx.Response) -> None:
        error_text = response.text.lower().replace("_", " ")
        slot_indicators = (
            "no longer available",
            "not available",
            "unavailable",
            "conflict",
            "overlap",
            "already taken",
        )
        invalid_id_indicators = (
            "invalid",
            "not found",
            "does not exist",
            "must exist",
        )
        invalid_datetime_indicators = (
            "invalid",
            "not valid",
            "must be",
            "can't be",
            "cannot be",
        )
        id_fields = (
            "patient id",
            "business id",
            "practitioner id",
            "appointment type id",
        )

        if any(indicator in error_text for indicator in slot_indicators):
            raise ClinikoSlotUnavailableError(
                "The selected appointment time is no longer available"
            )
        if "starts at" in error_text and any(
            indicator in error_text for indicator in invalid_datetime_indicators
        ):
            raise ClinikoInvalidAppointmentDateTimeError(
                "Cliniko rejected the appointment date-time"
            )
        if any(field in error_text for field in id_fields) and any(
            indicator in error_text for indicator in invalid_id_indicators
        ):
            raise ClinikoInvalidAppointmentIDsError(
                "One or more Cliniko IDs are invalid"
            )
        raise ClinikoAPIError("Cliniko rejected the appointment request")

    async def reschedule_individual_appointment(
        self,
        appointment_id: str,
        starts_at: datetime,
    ) -> dict[str, str]:
        path = f"/individual_appointments/{appointment_id}"

        try:
            existing_response = await self._client.get(path)
        except httpx.RequestError as exc:
            raise ClinikoAPIError("Unable to retrieve Cliniko appointment") from exc

        self._raise_for_appointment_response(existing_response)
        try:
            existing_appointment = existing_response.json()
        except ValueError as exc:
            raise ClinikoAPIError(
                "Cliniko returned an invalid appointment response"
            ) from exc
        if not isinstance(existing_appointment, dict):
            raise ClinikoAPIError(
                "Cliniko returned an unexpected appointment response"
            )
        if str(existing_appointment.get("id")) != appointment_id:
            raise ClinikoAPIError(
                "Cliniko returned an unexpected appointment response"
            )

        try:
            # The update is intentionally attempted exactly once.
            response = await self._client.patch(
                path,
                json={
                    "starts_at": starts_at.isoformat(),
                    "ends_at": None,
                },
            )
        except httpx.RequestError as exc:
            raise ClinikoAPIError("Unable to reschedule Cliniko appointment") from exc

        if response.status_code in {401, 403}:
            raise ClinikoAuthenticationError("Cliniko authentication failed")
        if response.status_code == 429:
            raise ClinikoRateLimitError(response.headers.get("X-RateLimit-Reset"))
        if response.status_code == 404:
            raise ClinikoAppointmentNotFoundError("Cliniko appointment not found")
        if response.status_code == 409:
            raise ClinikoSlotUnavailableError(
                "The selected appointment time is no longer available"
            )
        if response.status_code == 422:
            self._raise_for_booking_validation_error(response)

        try:
            response.raise_for_status()
            appointment = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ClinikoAPIError("Unable to reschedule Cliniko appointment") from exc

        return self._simplify_rescheduled_appointment(
            appointment_id,
            appointment,
        )

    def _raise_for_appointment_response(self, response: httpx.Response) -> None:
        if response.status_code in {401, 403}:
            raise ClinikoAuthenticationError("Cliniko authentication failed")
        if response.status_code == 429:
            raise ClinikoRateLimitError(response.headers.get("X-RateLimit-Reset"))
        if response.status_code == 404:
            raise ClinikoAppointmentNotFoundError("Cliniko appointment not found")
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ClinikoAPIError("Unable to retrieve Cliniko appointment") from exc

    def _simplify_rescheduled_appointment(
        self,
        appointment_id: str,
        appointment: Any,
    ) -> dict[str, str]:
        if not isinstance(appointment, dict):
            raise ClinikoAPIError(
                "Cliniko returned an unexpected appointment response"
            )

        returned_id = appointment.get("id")
        response_starts_at = appointment.get("starts_at")
        if returned_id is None or str(returned_id) != appointment_id:
            raise ClinikoAPIError(
                "Cliniko returned an unexpected appointment response"
            )
        if not isinstance(response_starts_at, str):
            raise ClinikoAPIError(
                "Cliniko returned an unexpected appointment response"
            )

        try:
            parsed_starts_at = datetime.fromisoformat(
                response_starts_at.replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ClinikoAPIError(
                "Cliniko returned an invalid appointment timestamp"
            ) from exc
        if parsed_starts_at.tzinfo is None or parsed_starts_at.utcoffset() is None:
            raise ClinikoAPIError(
                "Cliniko returned an appointment timestamp without a timezone"
            )

        return {
            "appointment_id": appointment_id,
            "starts_at": parsed_starts_at.isoformat(),
            "status": "rescheduled",
        }

    async def cancel_individual_appointment(
        self,
        appointment_id: str,
        cancellation_reason: int,
        note: str | None = None,
    ) -> dict[str, str | int]:
        appointment_path = f"/individual_appointments/{appointment_id}"

        try:
            existing_response = await self._client.get(
                appointment_path,
                params={"q[]": "cancelled_at:*"},
            )
        except httpx.RequestError as exc:
            raise ClinikoAPIError("Unable to retrieve Cliniko appointment") from exc

        self._raise_for_appointment_response(existing_response)
        try:
            existing_appointment = existing_response.json()
        except ValueError as exc:
            raise ClinikoAPIError(
                "Cliniko returned an invalid appointment response"
            ) from exc
        if not isinstance(existing_appointment, dict):
            raise ClinikoAPIError(
                "Cliniko returned an unexpected appointment response"
            )
        if str(existing_appointment.get("id")) != appointment_id:
            raise ClinikoAPIError(
                "Cliniko returned an unexpected appointment response"
            )
        if existing_appointment.get("cancelled_at") is not None:
            raise ClinikoAppointmentAlreadyCancelledError(
                "Cliniko appointment is already cancelled"
            )

        try:
            response = await self._client.patch(
                f"{appointment_path}/cancel",
                json={
                    "cancellation_reason": cancellation_reason,
                    "cancellation_note": note,
                    "apply_to_repeats": False,
                },
            )
        except httpx.RequestError as exc:
            raise ClinikoAPIError("Unable to cancel Cliniko appointment") from exc

        if response.status_code in {401, 403}:
            raise ClinikoAuthenticationError("Cliniko authentication failed")
        if response.status_code == 429:
            raise ClinikoRateLimitError(response.headers.get("X-RateLimit-Reset"))
        if response.status_code == 404:
            raise ClinikoAppointmentNotFoundError("Cliniko appointment not found")
        if response.status_code in {409, 410}:
            raise ClinikoAppointmentAlreadyCancelledError(
                "Cliniko appointment is already cancelled"
            )
        if response.status_code == 422:
            error_text = response.text.lower().replace("_", " ")
            if "already" in error_text and "cancel" in error_text:
                raise ClinikoAppointmentAlreadyCancelledError(
                    "Cliniko appointment is already cancelled"
                )
            raise ClinikoInvalidCancellationReasonError(
                "Cliniko rejected the cancellation reason"
            )

        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ClinikoAPIError("Unable to cancel Cliniko appointment") from exc

        return {
            "appointment_id": appointment_id,
            "status": "cancelled",
            "cancellation_reason": cancellation_reason,
        }
