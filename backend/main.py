from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from . import models
from .database import engine, get_db
from .models import Patient
from .schemas import PatientCreate

app = FastAPI()

models.Base.metadata.create_all(bind=engine)

@app.get("/")
def root():
    return {"message": "Voice AI Clinic Receptionist API is running!"}

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
