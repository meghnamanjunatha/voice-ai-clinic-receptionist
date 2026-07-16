from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Query
from sqlalchemy.orm import Session

from . import models
from .cliniko import (
    ClinikoAPIError,
    ClinikoAuthenticationError,
    ClinikoClient,
    ClinikoRateLimitError,
)
from .config import get_settings
from .database import engine, get_db
from .models import Patient
from .schemas import AvailabilitySlot, PatientCreate

app = FastAPI()

models.Base.metadata.create_all(bind=engine)

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


@app.post("/patients")
def create_or_get_patient(patient: PatientCreate, db: Session = Depends(get_db)):
    existing_patient = db.query(Patient).filter(
        Patient.phone == patient.phone
    ).first()

    if existing_patient:
        return existing_patient

    new_patient = Patient(
        name=patient.name,
        phone=patient.phone
    )

    db.add(new_patient)
    db.commit()
    db.refresh(new_patient)

    return new_patient
