from typing import Annotated

from fastapi import FastAPI, HTTPException, Path, Query

from .cliniko import (
    ClinikoAPIError,
    ClinikoAppointmentAlreadyCancelledError,
    ClinikoAppointmentNotFoundError,
    ClinikoAuthenticationError,
    ClinikoClient,
    ClinikoInvalidAppointmentDateTimeError,
    ClinikoInvalidAppointmentIDsError,
    ClinikoInvalidCancellationReasonError,
    ClinikoPatientConflictError,
    ClinikoPatientNotFoundError,
    ClinikoRateLimitError,
    ClinikoSlotUnavailableError,
    InvalidPhoneNumberError,
)
from .config import get_settings
from .cliniko_resolution import (
    ClinikoEntityConflictError,
    ClinikoEntityNotFoundError,
    get_appointment_type_id_by_name,
    get_business_id_by_name,
    get_practitioner_id_by_name,
)
from .retell import router as retell_router
from .schemas import (
    AppointmentCancellation,
    AppointmentCancellationResponse,
    AppointmentCreate,
    AppointmentReschedule,
    AppointmentRescheduleResponse,
    AppointmentResponse,
    AvailabilitySearchRequest,
    AvailabilitySlot,
    PatientCreate,
    PatientAppointmentResponse,
    PatientResponse,
    RetellAppointmentCancellation,
    RetellAppointmentReschedule,
)

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
    search: Annotated[AvailabilitySearchRequest, Query()],
):
    if search.to_date < search.from_date:
        raise HTTPException(
            status_code=422,
            detail="to_date must be on or after from_date",
        )
    if (search.to_date - search.from_date).days > 7:
        raise HTTPException(
            status_code=422,
            detail="Availability searches cannot span more than 7 days",
        )

    try:
        async with ClinikoClient(get_settings()) as client:
            business_id = await get_business_id_by_name(
                client, search.business_name
            )
            practitioner_id = await get_practitioner_id_by_name(
                client, search.practitioner_name
            )
            appointment_type_id = await get_appointment_type_id_by_name(
                client, search.appointment_type_name
            )
            return await client.list_available_times(
                business_id=business_id,
                practitioner_id=practitioner_id,
                appointment_type_id=appointment_type_id,
                from_date=search.from_date,
                to_date=search.to_date,
            )
    except ClinikoEntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ClinikoEntityConflictError as exc:
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


@app.get(
    "/patients/{patient_id}/appointments",
    response_model=list[PatientAppointmentResponse],
)
async def list_patient_appointments(
    patient_id: str = Path(pattern=r"^[1-9]\d*$"),
    include_past: bool = Query(default=False),
):
    try:
        async with ClinikoClient(get_settings()) as client:
            return await client.list_patient_appointments(
                patient_id=patient_id,
                include_past=include_past,
            )
    except ClinikoPatientNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Cliniko patient not found") from exc
    except ClinikoAuthenticationError as exc:
        raise HTTPException(status_code=502, detail="Cliniko authentication failed") from exc
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
            detail="Unable to retrieve patient appointments from Cliniko",
        ) from exc


@app.post("/appointments", response_model=AppointmentResponse, status_code=201)
async def create_appointment(appointment: AppointmentCreate):
    try:
        async with ClinikoClient(get_settings()) as client:
            return await client.create_individual_appointment(
                patient_id=appointment.patient_id,
                business_id=appointment.business_id,
                practitioner_id=appointment.practitioner_id,
                appointment_type_id=appointment.appointment_type_id,
                starts_at=appointment.starts_at,
            )
    except ClinikoSlotUnavailableError as exc:
        raise HTTPException(
            status_code=409,
            detail="The selected appointment time is no longer available",
        ) from exc
    except ClinikoInvalidAppointmentIDsError as exc:
        raise HTTPException(
            status_code=422,
            detail="One or more Cliniko IDs are invalid",
        ) from exc
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
            detail="Unable to create appointment in Cliniko",
        ) from exc


@app.patch(
    "/appointments/{appointment_id}",
    response_model=AppointmentRescheduleResponse,
)
async def reschedule_appointment(
    appointment: AppointmentReschedule,
    appointment_id: str = Path(pattern=r"^[1-9]\d*$"),
):
    try:
        async with ClinikoClient(get_settings()) as client:
            return await client.reschedule_individual_appointment(
                appointment_id=appointment_id,
                starts_at=appointment.starts_at,
            )
    except ClinikoAppointmentNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Cliniko appointment not found",
        ) from exc
    except ClinikoSlotUnavailableError as exc:
        raise HTTPException(
            status_code=409,
            detail="The selected appointment time is no longer available",
        ) from exc
    except ClinikoInvalidAppointmentDateTimeError as exc:
        raise HTTPException(
            status_code=422,
            detail="Cliniko rejected the appointment date-time",
        ) from exc
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
            detail="Unable to reschedule appointment in Cliniko",
        ) from exc


@app.post(
    "/appointments/{appointment_id}/cancel",
    response_model=AppointmentCancellationResponse,
)
async def cancel_appointment(
    cancellation: AppointmentCancellation,
    appointment_id: str = Path(pattern=r"^[1-9]\d*$"),
):
    try:
        async with ClinikoClient(get_settings()) as client:
            return await client.cancel_individual_appointment(
                appointment_id=appointment_id,
                cancellation_reason=cancellation.cancellation_reason.value,
                note=cancellation.note,
            )
    except ClinikoAppointmentNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail="Cliniko appointment not found",
        ) from exc
    except ClinikoAppointmentAlreadyCancelledError as exc:
        raise HTTPException(
            status_code=409,
            detail="Cliniko appointment is already cancelled",
        ) from exc
    except ClinikoInvalidCancellationReasonError as exc:
        raise HTTPException(
            status_code=422,
            detail="Cliniko rejected the cancellation reason",
        ) from exc
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
            detail="Unable to cancel appointment in Cliniko",
        ) from exc


@retell_router.patch(
    "/appointments/reschedule",
    response_model=AppointmentRescheduleResponse,
)
async def retell_reschedule_appointment(
    request: RetellAppointmentReschedule,
):
    return await reschedule_appointment(
        appointment=AppointmentReschedule(starts_at=request.starts_at),
        appointment_id=request.appointment_id,
    )


@retell_router.post(
    "/appointments/cancel",
    response_model=AppointmentCancellationResponse,
)
async def retell_cancel_appointment(
    request: RetellAppointmentCancellation,
):
    return await cancel_appointment(
        cancellation=AppointmentCancellation(
            cancellation_reason=request.cancellation_reason,
            note=request.note,
        ),
        appointment_id=request.appointment_id,
    )


app.include_router(retell_router)
