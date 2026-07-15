from datetime import datetime

from .database import SessionLocal, Base, engine
from .models import Branch, Doctor, Appointment, Patient

Base.metadata.create_all(bind=engine)

db = SessionLocal()

db.query(Appointment).delete()
db.query(Doctor).delete()
db.query(Branch).delete()
db.query(Patient).delete()

db.commit()

indiranagar = Branch(
    name="Indiranagar",
    address="100 Feet Road"
)

whitefield = Branch(
    name="Whitefield",
    address="ITPL Main Road"
)

db.add_all([indiranagar, whitefield])
db.commit()
db.refresh(indiranagar)
db.refresh(whitefield)

doctor1 = Doctor(
    name="Dr. Alice",
    specialty="Dermatologist",
    branch_id=indiranagar.id
)

doctor2 = Doctor(
    name="Dr. Bob",
    specialty="Dermatologist",
    branch_id=whitefield.id
)

doctor3 = Doctor(
    name="Dr. Carol",
    specialty="Cardiologist",
    branch_id=indiranagar.id
)

db.add_all([doctor1, doctor2, doctor3])
db.commit()

sample_patient = Patient(
    name="John Doe",
    phone="9999999999"
)

db.add(sample_patient)
db.commit()
db.refresh(sample_patient)

appointment1 = Appointment(
    patient_id=sample_patient.id,
    doctor_id=doctor1.id,
    appointment_datetime=datetime(2026, 7, 20, 10, 0),
    status="Booked"
)

db.add(appointment1)
db.commit()
