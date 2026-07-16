from datetime import date

from fastapi import FastAPI, HTTPException, Query

from .cliniko import (
    ClinikoAPIError,
    ClinikoAuthenticationError,
    ClinikoClient,
    ClinikoPatientConflictError,
    ClinikoRateLimitError,
    InvalidPhoneNumberError,
)
from .config import get_settings
from .schemas import AvailabilitySlot, PatientCreate, PatientResponse

app = FastAPI()

@app.get("/")
def root():
    return {"message": "Voice AI Clinic Receptionist API is running!"}


@app.get("/cliniko/businesses")
async def list_cliniko_businesses():
    try:
        async with ClinikoClient(get_settings()) as client:
            return await client.list_businesses()
    except ClinikoAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/cliniko/practitioners")
async def list_cliniko_practitioners():
    try:
        async with ClinikoClient(get_settings()) as client:
            return await client.list_practitioners()
    except ClinikoAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/cliniko/appointment-types")
async def list_cliniko_appointment_types():
    try:
        async with ClinikoClient(get_settings()) as client:
            return await client.list_appointment_types()
    except ClinikoAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/availability", response_model=list[AvailabilitySlot])
async def list_availability(
    business_id: str,
    practitioner_id: str,
    appointment_type_id: str,
    from_date: date = Query(),
    to_date: date = Query(),
):
    if to_date < from_date:
        raise HTTPException(
            status_code=422,
            detail="to_date must be on or after from_date",
        )
    if (to_date - from_date).days > 7:
        raise HTTPException(
            status_code=422,
            detail="Availability searches cannot span more than 7 days",
        )

    try:
        async with ClinikoClient(get_settings()) as client:
            return await client.list_available_times(
                business_id=business_id,
                practitioner_id=practitioner_id,
                appointment_type_id=appointment_type_id,
                from_date=from_date,
                to_date=to_date,
            )
    except ClinikoAuthenticationError as exc:
        raise HTTPException(
            status_code=502,
            detail="Cliniko authentication failed",
        ) from exc
    except ClinikoRateLimitError as exc:
        headers = {"X-RateLimit-Reset": exc.reset_at} if exc.reset_at else None
        raise HTTPException(
            status_code=429,
            detail="Cliniko rate limit exceeded",
            headers=headers,
        ) from exc
    except ClinikoAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to retrieve availability from Cliniko",
        ) from exc


@app.post("/patients", response_model=PatientResponse)
async def create_or_get_patient(patient: PatientCreate):
    try:
        async with ClinikoClient(get_settings()) as client:
            return await client.find_or_create_patient(
                full_name=patient.full_name,
                phone=patient.phone,
            )
    except InvalidPhoneNumberError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ClinikoPatientConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ClinikoAuthenticationError as exc:
        raise HTTPException(
            status_code=502,
            detail="Cliniko authentication failed",
        ) from exc
    except ClinikoRateLimitError as exc:
        headers = {"X-RateLimit-Reset": exc.reset_at} if exc.reset_at else None
        raise HTTPException(
            status_code=429,
            detail="Cliniko rate limit exceeded",
            headers=headers,
        ) from exc
    except ClinikoAPIError as exc:
        raise HTTPException(
            status_code=502,
            detail="Unable to find or create patient in Cliniko",
        ) from exc
