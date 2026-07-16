import base64
import unittest
from datetime import date

import httpx
from pydantic import SecretStr

from backend.cliniko import (
    ClinikoAPIError,
    ClinikoAuthenticationError,
    ClinikoClient,
    ClinikoRateLimitError,
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
