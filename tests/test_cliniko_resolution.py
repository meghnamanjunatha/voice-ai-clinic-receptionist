import unittest
from datetime import date
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.cliniko_resolution import (
    ClinikoEntityConflictError,
    ClinikoEntityNotFoundError,
    get_appointment_type_id_by_name,
    get_business_id_by_name,
    get_practitioner_id_by_name,
    normalize_name,
)
from backend.main import app


class StubClinikoClient:
    def __init__(self, settings: object) -> None:
        self.availability_arguments: dict[str, object] | None = None

    async def __aenter__(self) -> "StubClinikoClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def list_businesses(self) -> list[dict[str, str]]:
        return [{"id": "1001", "business_name": "Whitefield"}]

    async def list_practitioners(self) -> list[dict[str, str]]:
        return [{"id": "2001", "full_name": "Dr. Ananya"}]

    async def list_appointment_types(self) -> list[dict[str, str | int]]:
        return [
            {
                "id": "3001",
                "name": "Initial Dermatology",
                "duration_in_minutes": 45,
            }
        ]

    async def list_available_times(self, **kwargs: object) -> list[dict[str, str]]:
        self.availability_arguments = kwargs
        return [
            {
                "start_time": "2026-07-25T09:30:00+05:30",
                "business_id": str(kwargs["business_id"]),
                "practitioner_id": str(kwargs["practitioner_id"]),
                "appointment_type_id": str(kwargs["appointment_type_id"]),
            }
        ]


class NameResolutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_exact_match(self) -> None:
        client = StubClinikoClient(object())

        self.assertEqual(await get_business_id_by_name(client, "Whitefield"), "1001")

    async def test_case_insensitive_match_ignores_surrounding_spaces(self) -> None:
        client = StubClinikoClient(object())

        self.assertEqual(
            await get_practitioner_id_by_name(client, " dr. ANANYA "), "2001"
        )

    async def test_partial_match_in_both_directions(self) -> None:
        client = StubClinikoClient(object())

        async def named_businesses() -> list[dict[str, str]]:
            return [
                {
                    "id": "1001",
                    "business_name": "HealthFirst Clinic - Whitefield",
                }
            ]

        client.list_businesses = named_businesses  # type: ignore[method-assign]

        self.assertEqual(await get_business_id_by_name(client, "Whitefield"), "1001")
        self.assertEqual(
            await get_appointment_type_id_by_name(client, "Dermatologist"),
            "3001",
        )

    async def test_punctuation_differences_are_ignored(self) -> None:
        client = StubClinikoClient(object())

        async def punctuated_practitioners() -> list[dict[str, str]]:
            return [{"id": "2001", "full_name": "Dr-Ananya_Rao, MD."}]

        client.list_practitioners = punctuated_practitioners  # type: ignore[method-assign]

        self.assertEqual(
            await get_practitioner_id_by_name(client, "dr ananya rao md"), "2001"
        )
        self.assertEqual(normalize_name(" Dr-Ananya_Rao, MD. "), "dr ananya rao md")

    async def test_resolver_raises_not_found_for_no_match(self) -> None:
        client = StubClinikoClient(object())

        with self.assertRaises(ClinikoEntityNotFoundError) as raised:
            await get_business_id_by_name(client, "Unknown clinic")

        self.assertIn("Unknown clinic", str(raised.exception))
        self.assertIn("Whitefield", str(raised.exception))

    async def test_resolver_raises_conflict_for_multiple_matches(self) -> None:
        client = StubClinikoClient(object())

        async def duplicate_practitioners() -> list[dict[str, str]]:
            return [
                {"id": "2001", "full_name": "Dr. Ananya"},
                {"id": "2002", "full_name": " dr. ananya "},
            ]

        client.list_practitioners = duplicate_practitioners  # type: ignore[method-assign]

        with self.assertRaises(ClinikoEntityConflictError) as raised:
            await get_practitioner_id_by_name(client, "Ananya")

        self.assertIn("Dr. Ananya", str(raised.exception))
        self.assertIn("dr. ananya", str(raised.exception))


class AvailabilityRouteTests(unittest.TestCase):
    def test_route_resolves_names_before_calling_existing_availability_method(self) -> None:
        created_clients: list[StubClinikoClient] = []

        def client_factory(settings: object) -> StubClinikoClient:
            client = StubClinikoClient(settings)
            created_clients.append(client)
            return client

        with (
            patch("backend.main.ClinikoClient", side_effect=client_factory),
            patch("backend.main.get_settings", return_value=object()),
            TestClient(app) as test_client,
        ):
            response = test_client.get(
                "/availability",
                params={
                    "business_name": " Whitefield ",
                    "practitioner_name": "DR. ANANYA",
                    "appointment_type_name": "initial dermatology",
                    "from_date": "2026-07-25",
                    "to_date": "2026-07-25",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            created_clients[0].availability_arguments,
            {
                "business_id": "1001",
                "practitioner_id": "2001",
                "appointment_type_id": "3001",
                "from_date": date(2026, 7, 25),
                "to_date": date(2026, 7, 25),
            },
        )

    def test_route_returns_404_for_unknown_name(self) -> None:
        with (
            patch("backend.main.ClinikoClient", StubClinikoClient),
            patch("backend.main.get_settings", return_value=object()),
            TestClient(app) as test_client,
        ):
            response = test_client.get(
                "/availability",
                params={
                    "business_name": "Unknown clinic",
                    "practitioner_name": "Dr. Ananya",
                    "appointment_type_name": "Initial Dermatology",
                    "from_date": "2026-07-25",
                    "to_date": "2026-07-25",
                },
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.json()["detail"],
            "No Cliniko business matches requested name 'Unknown clinic'. "
            "Available names: Whitefield",
        )

    def test_route_returns_409_and_matching_names_for_ambiguous_name(self) -> None:
        class AmbiguousClinikoClient(StubClinikoClient):
            async def list_businesses(self) -> list[dict[str, str]]:
                return [
                    {
                        "id": "1001",
                        "business_name": "HealthFirst Clinic - Whitefield",
                    },
                    {
                        "id": "1002",
                        "business_name": "HealthFirst Dental - Whitefield",
                    },
                ]

        with (
            patch("backend.main.ClinikoClient", AmbiguousClinikoClient),
            patch("backend.main.get_settings", return_value=object()),
            TestClient(app) as test_client,
        ):
            response = test_client.get(
                "/availability",
                params={
                    "business_name": "Whitefield",
                    "practitioner_name": "Dr. Ananya",
                    "appointment_type_name": "Initial Dermatology",
                    "from_date": "2026-07-25",
                    "to_date": "2026-07-25",
                },
            )

        self.assertEqual(response.status_code, 409)
        detail = response.json()["detail"]
        self.assertIn("HealthFirst Clinic - Whitefield", detail)
        self.assertIn("HealthFirst Dental - Whitefield", detail)
