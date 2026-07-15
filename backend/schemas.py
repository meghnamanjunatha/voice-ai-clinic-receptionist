from pydantic import BaseModel


class PatientCreate(BaseModel):
    name: str
    phone: str

class AvailabilityRequest(BaseModel):
    specialty: str
    branch_id: int