from datetime import datetime

from pydantic import BaseModel, field_validator


class PatientCreate(BaseModel):
    name: str
    phone: str

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
