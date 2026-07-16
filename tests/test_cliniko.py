import base64
import json
import unittest
from datetime import date, datetime

import httpx
from pydantic import SecretStr

from backend.cliniko import (
    ClinikoAPIError,
    ClinikoAppointmentNotFoundError,
    ClinikoAuthenticationError,
    ClinikoClient,
    ClinikoInvalidAppointmentDateTimeError,
    ClinikoInvalidAppointmentIDsError,
    ClinikoPatientConflictError,
    ClinikoRateLimitError,
    ClinikoSlotUnavailableError,
)
from backend.config import Settings


def make_settings() -> Settings:
    return Settings(
        cliniko_api_key=SecretStr("test-key-au1"),
        cliniko_api_base_url="https://api.au1.cliniko.com/v1",
        cliniko_user_agent="Test Receptionist (test@example.com)",
    )


class ClinikoClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_businesses_returns_business_list(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            expected_auth = base64.b64encode(b"test-key-au1:").decode()
            self.assertEqual(request.url.path, "/v1/businesses")
            self.assertEqual(
                request.headers["Authorization"], f"Basic {expected_auth}"
            )
            self.assertEqual(request.headers["Accept"], "application/json")
            self.assertEqual(
                request.headers["User-Agent"],
                "Test Receptionist (test@example.com)",
            )
            return httpx.Response(
                200,
                json={"businesses": [{"id": "1", "display_name": "Main Clinic"}]},
            )

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            businesses = await client.list_businesses()

        self.assertEqual(
            businesses, [{"id": "1", "display_name": "Main Clinic"}]
        )

    async def test_list_businesses_rejects_upstream_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "Unauthorized"})

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertRaises(ClinikoAPIError):
                await client.list_businesses()

    async def test_list_practitioners_returns_only_essential_fields(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v1/practitioners")
            self.assertEqual(request.url.params["per_page"], "100")
            return httpx.Response(
                200,
                json={
                    "practitioners": [
                        {
                            "id": "10",
                            "display_name": "Dr Alice Smith",
                            "first_name": "Alice",
                            "last_name": "Smith",
                            "active": True,
                        }
                    ]
                },
            )

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            practitioners = await client.list_practitioners()

        self.assertEqual(
            practitioners,
            [{"id": "10", "full_name": "Dr Alice Smith"}],
        )

    async def test_list_practitioners_rejects_upstream_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "Server error"})

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertRaises(ClinikoAPIError):
                await client.list_practitioners()

    async def test_list_appointment_types_returns_only_requested_fields(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v1/appointment_types")
            self.assertEqual(request.url.params["per_page"], "100")
            return httpx.Response(
                200,
                json={
                    "appointment_types": [
                        {
                            "id": "20",
                            "name": "Initial Consultation",
                            "duration_in_minutes": 45,
                            "description": "Not included in the API response",
                            "show_in_online_bookings": True,
                        }
                    ]
                },
            )

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            appointment_types = await client.list_appointment_types()

        self.assertEqual(
            appointment_types,
            [
                {
                    "id": "20",
                    "name": "Initial Consultation",
                    "duration_in_minutes": 45,
                }
            ],
        )

    async def test_list_appointment_types_rejects_upstream_error(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"error": "Service unavailable"})

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertRaises(ClinikoAPIError):
                await client.list_appointment_types()

    async def test_list_available_times_returns_simplified_slots(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(
                request.url.path,
                "/v1/businesses/1/practitioners/2/appointment_types/3/available_times",
            )
            self.assertEqual(request.url.params["from"], "2026-07-20")
            self.assertEqual(request.url.params["to"], "2026-07-21")
            self.assertEqual(request.url.params["per_page"], "100")
            return httpx.Response(
                200,
                json={
                    "available_times": [
                        {"appointment_start": "2026-07-20T10:00:00+05:30"},
                        {"appointment_start": "2026-07-20T11:00:00Z"},
                    ],
                    "total_entries": 2,
                },
            )

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            slots = await client.list_available_times(
                business_id="1",
                practitioner_id="2",
                appointment_type_id="3",
                from_date=date(2026, 7, 20),
                to_date=date(2026, 7, 21),
            )

        self.assertEqual(
            slots,
            [
                {
                    "start_time": "2026-07-20T10:00:00+05:30",
                    "business_id": "1",
                    "practitioner_id": "2",
                    "appointment_type_id": "3",
                },
                {
                    "start_time": "2026-07-20T11:00:00+00:00",
                    "business_id": "1",
                    "practitioner_id": "2",
                    "appointment_type_id": "3",
                },
            ],
        )

    async def test_list_available_times_returns_empty_list(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"available_times": [], "total_entries": 0},
            )

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            slots = await client.list_available_times(
                business_id="1",
                practitioner_id="2",
                appointment_type_id="3",
                from_date=date(2026, 7, 20),
                to_date=date(2026, 7, 20),
            )

        self.assertEqual(slots, [])

    async def test_list_available_times_rejects_upstream_failure(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                500,
                text="Server error containing test-key-au1",
            )

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertLogs("backend.cliniko", level="ERROR") as logs:
                with self.assertRaises(ClinikoAPIError):
                    await client.list_available_times(
                        business_id="1",
                        practitioner_id="2",
                        appointment_type_id="3",
                        from_date=date(2026, 7, 20),
                        to_date=date(2026, 7, 20),
                    )

        log_output = "\n".join(logs.output)
        self.assertIn("status_code=500", log_output)
        self.assertIn(
            "requested_url=https://api.au1.cliniko.com/v1/businesses/1/"
            "practitioners/2/appointment_types/3/available_times",
            log_output,
        )
        self.assertIn("'from': '2026-07-20'", log_output)
        self.assertIn("'to': '2026-07-20'", log_output)
        self.assertIn("response_body=Server error containing [REDACTED]", log_output)
        self.assertNotIn("test-key-au1", log_output)
        self.assertNotIn("Authorization", log_output)

    async def test_list_available_times_classifies_credentials_and_rate_limit(
        self,
    ) -> None:
        responses = iter(
            [
                httpx.Response(401, json={"error": "Unauthorized"}),
                httpx.Response(
                    429,
                    headers={"X-RateLimit-Reset": "1784534400"},
                    json={"error": "Rate limited"},
                ),
            ]
        )

        async def handler(request: httpx.Request) -> httpx.Response:
            return next(responses)

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertRaises(ClinikoAuthenticationError):
                await client.list_available_times(
                    "1", "2", "3", date(2026, 7, 20), date(2026, 7, 20)
                )

            with self.assertRaises(ClinikoRateLimitError) as context:
                await client.list_available_times(
                    "1", "2", "3", date(2026, 7, 20), date(2026, 7, 20)
                )

        self.assertEqual(context.exception.reset_at, "1784534400")

    async def test_find_or_create_patient_returns_existing_patient(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.path, "/v1/patients")
            self.assertEqual(request.url.params["page"], "1")
            self.assertEqual(request.url.params["per_page"], "100")
            return httpx.Response(
                200,
                json={
                    "patients": [
                        {
                            "id": "30",
                            "label": "Jane Doe",
                            "patient_phone_numbers": [
                                {
                                    "number": "+91 98765 43210",
                                    "normalized_number": "919876543210",
                                    "phone_type": "Mobile",
                                }
                            ],
                        }
                    ],
                    "total_entries": 1,
                },
            )

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            patient = await client.find_or_create_patient(
                full_name="Jane Doe",
                phone="+91 (98765) 43210",
            )

        self.assertEqual(
            patient,
            {
                "id": "30",
                "full_name": "Jane Doe",
                "phone": "919876543210",
                "is_new_patient": False,
            },
        )

    async def test_find_or_create_patient_creates_new_patient(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={"patients": [], "total_entries": 0},
                )

            self.assertEqual(request.method, "POST")
            self.assertEqual(request.url.path, "/v1/patients")
            self.assertEqual(
                json.loads(request.content),
                {
                    "first_name": "John",
                    "last_name": "Michael Smith",
                    "patient_phone_numbers": [
                        {"number": "919999999999", "phone_type": "Mobile"}
                    ],
                },
            )
            return httpx.Response(
                201,
                json={
                    "id": "31",
                    "label": "John Michael Smith",
                    "patient_phone_numbers": [
                        {
                            "number": "919999999999",
                            "normalized_number": "919999999999",
                            "phone_type": "Mobile",
                        }
                    ],
                },
            )

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            patient = await client.find_or_create_patient(
                full_name="John Michael Smith",
                phone="+91 99999-99999",
            )

        self.assertEqual(
            patient,
            {
                "id": "31",
                "full_name": "John Michael Smith",
                "phone": "919999999999",
                "is_new_patient": True,
            },
        )

    async def test_find_or_create_patient_rejects_multiple_matches(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            phone_number = {
                "number": "919876543210",
                "normalized_number": "919876543210",
                "phone_type": "Mobile",
            }
            return httpx.Response(
                200,
                json={
                    "patients": [
                        {
                            "id": "30",
                            "label": "Jane Doe",
                            "patient_phone_numbers": [phone_number],
                        },
                        {
                            "id": "32",
                            "label": "Janet Doe",
                            "patient_phone_numbers": [phone_number],
                        },
                    ],
                    "total_entries": 2,
                },
            )

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertRaises(ClinikoPatientConflictError):
                await client.find_or_create_patient(
                    full_name="Jane Doe",
                    phone="+91 98765 43210",
                )

    async def test_find_or_create_patient_rejects_upstream_failure(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "Server error"})

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertRaises(ClinikoAPIError):
                await client.find_or_create_patient(
                    full_name="Jane Doe",
                    phone="+91 98765 43210",
                )

    async def test_create_individual_appointment_succeeds_once(self) -> None:
        request_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.url.path, "/v1/individual_appointments")
            self.assertEqual(
                json.loads(request.content),
                {
                    "patient_id": "30",
                    "business_id": "1",
                    "practitioner_id": "2",
                    "appointment_type_id": "3",
                    "starts_at": "2026-07-20T10:00:00+05:30",
                },
            )
            return httpx.Response(
                201,
                json={
                    "id": "40",
                    "starts_at": "2026-07-20T10:00:00+05:30",
                    "ends_at": "2026-07-20T10:45:00+05:30",
                },
            )

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            appointment = await client.create_individual_appointment(
                patient_id="30",
                business_id="1",
                practitioner_id="2",
                appointment_type_id="3",
                starts_at=datetime.fromisoformat("2026-07-20T10:00:00+05:30"),
            )

        self.assertEqual(request_count, 1)
        self.assertEqual(
            appointment,
            {
                "appointment_id": "40",
                "patient_id": "30",
                "business_id": "1",
                "practitioner_id": "2",
                "appointment_type_id": "3",
                "starts_at": "2026-07-20T10:00:00+05:30",
                "status": "booked",
            },
        )

    async def test_create_individual_appointment_handles_unavailable_slot(
        self,
    ) -> None:
        request_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            return httpx.Response(
                422,
                json={"errors": {"starts_at": ["is no longer available"]}},
            )

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertRaises(ClinikoSlotUnavailableError):
                await client.create_individual_appointment(
                    "30",
                    "1",
                    "2",
                    "3",
                    datetime.fromisoformat("2026-07-20T10:00:00+05:30"),
                )

        self.assertEqual(request_count, 1)

    async def test_create_individual_appointment_handles_invalid_ids(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                422,
                json={"errors": {"patient_id": ["is invalid"]}},
            )

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertRaises(ClinikoInvalidAppointmentIDsError):
                await client.create_individual_appointment(
                    "999",
                    "1",
                    "2",
                    "3",
                    datetime.fromisoformat("2026-07-20T10:00:00+05:30"),
                )

    async def test_create_individual_appointment_handles_rate_limit(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                429,
                headers={"X-RateLimit-Reset": "1784534400"},
                json={"error": "Rate limited"},
            )

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertRaises(ClinikoRateLimitError) as context:
                await client.create_individual_appointment(
                    "30",
                    "1",
                    "2",
                    "3",
                    datetime.fromisoformat("2026-07-20T10:00:00+05:30"),
                )

        self.assertEqual(context.exception.reset_at, "1784534400")

    async def test_create_individual_appointment_handles_upstream_failure(
        self,
    ) -> None:
        request_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal request_count
            request_count += 1
            return httpx.Response(500, json={"error": "Server error"})

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertRaises(ClinikoAPIError):
                await client.create_individual_appointment(
                    "30",
                    "1",
                    "2",
                    "3",
                    datetime.fromisoformat("2026-07-20T10:00:00+05:30"),
                )

        self.assertEqual(request_count, 1)

    async def test_reschedule_individual_appointment_succeeds_once(self) -> None:
        patch_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal patch_count
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "id": "40",
                        "starts_at": "2026-07-20T10:00:00+05:30",
                    },
                )

            patch_count += 1
            self.assertEqual(request.method, "PATCH")
            self.assertEqual(request.url.path, "/v1/individual_appointments/40")
            self.assertEqual(
                json.loads(request.content),
                {
                    "starts_at": "2026-07-21T11:00:00+05:30",
                    "ends_at": None,
                },
            )
            return httpx.Response(
                200,
                json={
                    "id": "40",
                    "starts_at": "2026-07-21T11:00:00+05:30",
                },
            )

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            appointment = await client.reschedule_individual_appointment(
                appointment_id="40",
                starts_at=datetime.fromisoformat("2026-07-21T11:00:00+05:30"),
            )

        self.assertEqual(patch_count, 1)
        self.assertEqual(
            appointment,
            {
                "appointment_id": "40",
                "starts_at": "2026-07-21T11:00:00+05:30",
                "status": "rescheduled",
            },
        )

    async def test_reschedule_individual_appointment_handles_not_found(self) -> None:
        patch_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal patch_count
            if request.method == "PATCH":
                patch_count += 1
            return httpx.Response(404, json={"error": "Not found"})

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertRaises(ClinikoAppointmentNotFoundError):
                await client.reschedule_individual_appointment(
                    "999",
                    datetime.fromisoformat("2026-07-21T11:00:00+05:30"),
                )

        self.assertEqual(patch_count, 0)

    async def test_reschedule_individual_appointment_handles_unavailable_slot(
        self,
    ) -> None:
        patch_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal patch_count
            if request.method == "GET":
                return httpx.Response(200, json={"id": "40"})
            patch_count += 1
            return httpx.Response(
                422,
                json={"errors": {"starts_at": ["is no longer available"]}},
            )

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertRaises(ClinikoSlotUnavailableError):
                await client.reschedule_individual_appointment(
                    "40",
                    datetime.fromisoformat("2026-07-21T11:00:00+05:30"),
                )

        self.assertEqual(patch_count, 1)

    async def test_reschedule_individual_appointment_handles_invalid_datetime(
        self,
    ) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(200, json={"id": "40"})
            return httpx.Response(
                422,
                json={"errors": {"starts_at": ["is invalid"]}},
            )

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertRaises(ClinikoInvalidAppointmentDateTimeError):
                await client.reschedule_individual_appointment(
                    "40",
                    datetime.fromisoformat("2026-07-21T11:00:00+05:30"),
                )

    async def test_reschedule_individual_appointment_handles_rate_limit(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                429,
                headers={"X-RateLimit-Reset": "1784534400"},
                json={"error": "Rate limited"},
            )

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertRaises(ClinikoRateLimitError) as context:
                await client.reschedule_individual_appointment(
                    "40",
                    datetime.fromisoformat("2026-07-21T11:00:00+05:30"),
                )

        self.assertEqual(context.exception.reset_at, "1784534400")

    async def test_reschedule_individual_appointment_handles_upstream_failure(
        self,
    ) -> None:
        patch_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal patch_count
            if request.method == "GET":
                return httpx.Response(200, json={"id": "40"})
            patch_count += 1
            return httpx.Response(500, json={"error": "Server error"})

        async with ClinikoClient(
            make_settings(), transport=httpx.MockTransport(handler)
        ) as client:
            with self.assertRaises(ClinikoAPIError):
                await client.reschedule_individual_appointment(
                    "40",
                    datetime.fromisoformat("2026-07-21T11:00:00+05:30"),
                )

        self.assertEqual(patch_count, 1)
