from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class PatientCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=511)
    phone: str = Field(min_length=1, max_length=50)

    @field_validator("full_name")
    @classmethod
    def normalize_full_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("full_name must not be blank")
        return normalized


class PatientResponse(BaseModel):
    id: str
    full_name: str
    phone: str
    is_new_patient: bool

class AvailabilityRequest(BaseModel):
    specialty: str
    branch_id: int


class AvailabilitySlot(BaseModel):
    start_time: datetime
    business_id: str
    practitioner_id: str
    appointment_type_id: str

    @field_validator("start_time")
    @classmethod
    def start_time_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("start_time must include a timezone")
        return value
