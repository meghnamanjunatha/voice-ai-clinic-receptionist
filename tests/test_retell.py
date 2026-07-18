import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.cliniko import ClinikoAPIError
from backend.config import Settings, get_settings
from backend.main import app


def make_settings() -> Settings:
    return Settings(
        cliniko_api_key=SecretStr("test-cliniko-key"),
        cliniko_api_base_url="https://api.au5.cliniko.com/v1",
        cliniko_user_agent="Test Receptionist (test@example.com)",
        retell_api_key=SecretStr("test-retell-key"),
    )


class FakeClinikoClient:
    def __init__(self) -> None:
        self.reschedule_individual_appointment = AsyncMock(
            return_value={
                "appointment_id": "40",
                "starts_at": "2026-07-21T11:00:00+05:30",
                "status": "rescheduled",
            }
        )
        self.cancel_individual_appointment = AsyncMock(
            return_value={
                "appointment_id": "40",
                "status": "cancelled",
                "cancellation_reason": 50,
            }
        )

    async def __aenter__(self) -> "FakeClinikoClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


class RetellAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = make_settings()
        app.dependency_overrides[get_settings] = lambda: self.settings
        self.settings_patcher = patch(
            "backend.main.get_settings",
            return_value=self.settings,
        )
        self.settings_patcher.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        self.settings_patcher.stop()
        app.dependency_overrides.clear()

    def test_valid_signature_is_accepted(self) -> None:
        fake_client = FakeClinikoClient()
        with (
            patch("backend.retell.verify", return_value=True) as verify,
            patch("backend.main.ClinikoClient", return_value=fake_client),
        ):
            response = self.client.patch(
                "/retell/appointments/reschedule",
                headers={"X-Retell-Signature": "valid-signature"},
                json={
                    "appointment_id": "40",
                    "starts_at": "2026-07-21T11:00:00+05:30",
                },
            )

        self.assertEqual(response.status_code, 200)
        raw_body = response.request.content.decode("utf-8")
        verify.assert_called_once_with(
            raw_body,
            "test-retell-key",
            "valid-signature",
        )

    def test_missing_signature_returns_401(self) -> None:
        with patch("backend.retell.verify") as verify:
            response = self.client.post(
                "/retell/appointments/cancel",
                json={"appointment_id": "40", "cancellation_reason": 50},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Unauthorized"})
        verify.assert_not_called()

    def test_invalid_signature_returns_401(self) -> None:
        with patch("backend.retell.verify", return_value=False):
            response = self.client.post(
                "/retell/appointments/cancel",
                headers={"X-Retell-Signature": "invalid-signature"},
                json={"appointment_id": "40", "cancellation_reason": 50},
            )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Unauthorized"})

    def test_successful_reschedule_reuses_existing_logic(self) -> None:
        fake_client = FakeClinikoClient()
        with (
            patch("backend.retell.verify", return_value=True),
            patch("backend.main.ClinikoClient", return_value=fake_client),
        ):
            response = self.client.patch(
                "/retell/appointments/reschedule",
                headers={"X-Retell-Signature": "valid-signature"},
                json={
                    "appointment_id": "40",
                    "starts_at": "2026-07-21T11:00:00+05:30",
                },
            )

        self.assertEqual(
            response.json(),
            {
                "appointment_id": "40",
                "starts_at": "2026-07-21T11:00:00+05:30",
                "status": "rescheduled",
            },
        )
        fake_client.reschedule_individual_appointment.assert_awaited_once_with(
            appointment_id="40",
            starts_at=datetime.fromisoformat("2026-07-21T11:00:00+05:30"),
        )

    def test_successful_cancellation_reuses_existing_logic(self) -> None:
        fake_client = FakeClinikoClient()
        with (
            patch("backend.retell.verify", return_value=True),
            patch("backend.main.ClinikoClient", return_value=fake_client),
        ):
            response = self.client.post(
                "/retell/appointments/cancel",
                headers={"X-Retell-Signature": "valid-signature"},
                json={
                    "appointment_id": "40",
                    "cancellation_reason": 50,
                    "note": "Patient requested cancellation",
                },
            )

        self.assertEqual(
            response.json(),
            {
                "appointment_id": "40",
                "status": "cancelled",
                "cancellation_reason": 50,
            },
        )
        fake_client.cancel_individual_appointment.assert_awaited_once_with(
            appointment_id="40",
            cancellation_reason=50,
            note="Patient requested cancellation",
        )

    def test_reschedule_upstream_error_preserves_existing_502(self) -> None:
        fake_client = FakeClinikoClient()
        fake_client.reschedule_individual_appointment.side_effect = ClinikoAPIError(
            "upstream failure"
        )
        with (
            patch("backend.retell.verify", return_value=True),
            patch("backend.main.ClinikoClient", return_value=fake_client),
        ):
            response = self.client.patch(
                "/retell/appointments/reschedule",
                headers={"X-Retell-Signature": "valid-signature"},
                json={
                    "appointment_id": "40",
                    "starts_at": "2026-07-21T11:00:00+05:30",
                },
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json(),
            {"detail": "Unable to reschedule appointment in Cliniko"},
        )

    def test_cancellation_upstream_error_preserves_existing_502(self) -> None:
        fake_client = FakeClinikoClient()
        fake_client.cancel_individual_appointment.side_effect = ClinikoAPIError(
            "upstream failure"
        )
        with (
            patch("backend.retell.verify", return_value=True),
            patch("backend.main.ClinikoClient", return_value=fake_client),
        ):
            response = self.client.post(
                "/retell/appointments/cancel",
                headers={"X-Retell-Signature": "valid-signature"},
                json={"appointment_id": "40", "cancellation_reason": 50},
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(
            response.json(),
            {"detail": "Unable to cancel appointment in Cliniko"},
        )
