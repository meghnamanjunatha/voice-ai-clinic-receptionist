from collections.abc import Awaitable, Callable
from typing import Any

from .cliniko import ClinikoAPIError, ClinikoClient


class ClinikoEntityNotFoundError(Exception):
    def __init__(self, entity_type: str, name: str) -> None:
        super().__init__(f"No Cliniko {entity_type} matches the name '{name}'")


class ClinikoEntityConflictError(Exception):
    def __init__(self, entity_type: str, name: str) -> None:
        super().__init__(f"Multiple Cliniko {entity_type} records match the name '{name}'")


async def _get_entity_id_by_name(
    *,
    entity_type: str,
    name: str,
    name_field: str,
    list_entities: Callable[[], Awaitable[list[dict[str, Any]]]],
) -> str:
    normalized_name = name.strip().casefold()
    entities = await list_entities()
    matches = [
        entity
        for entity in entities
        if isinstance(entity.get(name_field), str)
        and entity[name_field].strip().casefold() == normalized_name
    ]

    if not matches:
        raise ClinikoEntityNotFoundError(entity_type, name)
    if len(matches) > 1:
        raise ClinikoEntityConflictError(entity_type, name)

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
