from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from . import models
from .cliniko import ClinikoAPIError, ClinikoClient
from .config import get_settings
from .database import engine, get_db
from .models import Patient
from .schemas import PatientCreate

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
