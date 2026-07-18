import unicodedata
from collections.abc import Awaitable, Callable
from typing import Any

from .cliniko import ClinikoAPIError, ClinikoClient


class ClinikoEntityNotFoundError(Exception):
    def __init__(
        self, entity_type: str, name: str, available_names: list[str]
    ) -> None:
        available = ", ".join(available_names) if available_names else "none"
        super().__init__(
            f"No Cliniko {entity_type} matches requested name '{name}'. "
            f"Available names: {available}"
        )


class ClinikoEntityConflictError(Exception):
    def __init__(
        self, entity_type: str, name: str, matching_names: list[str]
    ) -> None:
        super().__init__(
            f"Multiple Cliniko {entity_type} records match requested name "
            f"'{name}'. Matching names: {', '.join(matching_names)}"
        )


def normalize_name(name: str) -> str:
    """Normalize case, surrounding space, and punctuation for name matching."""
    without_punctuation = "".join(
        " " if unicodedata.category(character).startswith("P") else character
        for character in name
    )
    return " ".join(without_punctuation.casefold().split())


def _names_match(requested_name: str, available_name: str) -> bool:
    requested = normalize_name(requested_name)
    available = normalize_name(available_name)
    if not requested or not available:
        return False

    requested_compact = requested.replace(" ", "")
    available_compact = available.replace(" ", "")
    if requested_compact in available_compact or available_compact in requested_compact:
        return True

    # This covers closely related service terms such as "Dermatologist" and
    # "Dermatology" without making short, unrelated name fragments equivalent.
    for requested_word in requested.split():
        for available_word in available.split():
            common_prefix_length = 0
            for requested_character, available_character in zip(
                requested_word, available_word
            ):
                if requested_character != available_character:
                    break
                common_prefix_length += 1
            if common_prefix_length >= 7:
                return True
    return False


async def _get_entity_id_by_name(
    *,
    entity_type: str,
    name: str,
    name_field: str,
    list_entities: Callable[[], Awaitable[list[dict[str, Any]]]],
) -> str:
    entities = await list_entities()
    available_names = [
        entity[name_field]
        for entity in entities
        if isinstance(entity.get(name_field), str) and entity[name_field].strip()
    ]
    matches = [
        entity
        for entity in entities
        if isinstance(entity.get(name_field), str)
        and _names_match(name, entity[name_field])
    ]

    if not matches:
        raise ClinikoEntityNotFoundError(entity_type, name, available_names)
    if len(matches) > 1:
        matching_names = [str(match[name_field]) for match in matches]
        raise ClinikoEntityConflictError(entity_type, name, matching_names)

    entity_id = matches[0].get("id")
    if entity_id is None:
        raise ClinikoAPIError(
            f"Cliniko returned a {entity_type} matching '{name}' without an id"
        )
    return str(entity_id)


async def get_business_id_by_name(client: ClinikoClient, name: str) -> str:
    return await _get_entity_id_by_name(
        entity_type="business",
        name=name,
        name_field="business_name",
        list_entities=client.list_businesses,
    )


async def get_practitioner_id_by_name(client: ClinikoClient, name: str) -> str:
    return await _get_entity_id_by_name(
        entity_type="practitioner",
        name=name,
        name_field="full_name",
        list_entities=client.list_practitioners,
    )


async def get_appointment_type_id_by_name(client: ClinikoClient, name: str) -> str:
    return await _get_entity_id_by_name(
        entity_type="appointment type",
        name=name,
        name_field="name",
        list_entities=client.list_appointment_types,
    )
