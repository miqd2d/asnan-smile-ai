"""
schemas.py - The shapes of requests and responses (Pydantic v2).

FastAPI uses these to validate incoming JSON automatically, to build the
/docs page, and to document exactly what the AI tools must send.
"""
from pydantic import BaseModel, Field

DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"      # 2026-11-03
TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"  # 14:30


# ---------------------------------------------------------- requests
class VerifyRequest(BaseModel):
    patient_id: int = Field(gt=0, description="Patient file number")
    name: str = Field(min_length=2, max_length=100, description="Name as the caller says it")


class CreateAppointmentRequest(BaseModel):
    token: str = Field(description="From /patients/verify")
    doctor_id: int
    rov_id: int = Field(description="Visit type id from /visit-types")
    date: str = Field(pattern=DATE_PATTERN, examples=["2026-11-03"])
    time: str = Field(pattern=TIME_PATTERN, examples=["14:30"])
    notes: str | None = Field(default=None, max_length=500,
                              description="The patient's own words, e.g. 'toothache since last night'")


class RescheduleRequest(BaseModel):
    token: str
    new_date: str = Field(pattern=DATE_PATTERN)
    new_time: str = Field(pattern=TIME_PATTERN)
    new_doctor_id: int | None = Field(default=None, description="Leave empty to keep the same doctor")


class TokenRequest(BaseModel):
    """Used by cancel and confirm."""
    token: str


# ---------------------------------------------------------- responses
class VerifyResponse(BaseModel):
    verified: bool
    token: str
    patient_id: int
    first_name: str


class UnitOut(BaseModel):
    unit_id: int
    name: str
    doctors: int


class VisitTypeOut(BaseModel):
    rov_id: int
    name: str
    duration_min: int


class DoctorOut(BaseModel):
    doctor_id: int
    name: str
    unit_id: int
    unit: str


class SlotsOut(BaseModel):
    doctor_id: int
    doctor: str
    date: str
    weekday: str
    visit_type: str
    duration_min: int
    slots: list[str]


class SlotOption(BaseModel):
    doctor_id: int
    doctor: str
    unit: str
    date: str
    time: str
    weekday: str


class AppointmentOut(BaseModel):
    reference_number: int
    appointment_id: int
    doctor_id: int
    doctor: str
    unit: str | None
    visit_type: str | None
    date: str
    time: str
    weekday: str
    duration_min: int
    status: str
    notes: str | None = None


class ErrorOut(BaseModel):
    error: str     # e.g. SLOT_TAKEN
    message: str   # safe to read to the caller
