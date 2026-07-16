import base64
import unittest

import httpx
from pydantic import SecretStr

from backend.cliniko import ClinikoAPIError, ClinikoClient
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
