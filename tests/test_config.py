import unittest

from pydantic import SecretStr, ValidationError

from backend.config import Settings


class SettingsTests(unittest.TestCase):
    def test_cliniko_shard_builds_api_base_url(self) -> None:
        settings = Settings(
            _env_file=None,
            cliniko_api_key=SecretStr("test-key"),
            cliniko_shard="AU5",
            cliniko_user_agent="Test Receptionist (test@example.com)",
        )

        self.assertEqual(settings.cliniko_shard, "au5")
        self.assertEqual(
            settings.cliniko_api_base_url,
            "https://api.au5.cliniko.com/v1",
        )

    def test_explicit_api_base_url_remains_supported(self) -> None:
        settings = Settings(
            _env_file=None,
            cliniko_api_key=SecretStr("test-key"),
            cliniko_api_base_url="https://api.au1.cliniko.com/v1/",
            cliniko_user_agent="Test Receptionist (test@example.com)",
        )

        self.assertEqual(
            settings.cliniko_api_base_url,
            "https://api.au1.cliniko.com/v1",
        )

    def test_shard_or_base_url_is_required(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                cliniko_api_key=SecretStr("test-key"),
                cliniko_user_agent="Test Receptionist (test@example.com)",
            )
