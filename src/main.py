import logging

from fastapi import FastAPI, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import pms
from rules import RuleError
from schemas import UnitOut, VisitTypeOut, ErrorOut, DoctorOut, SlotsOut, SlotOption, VerifyRequest, VerifyResponse, AppointmentOut, CreateAppointmentRequest, RescheduleRequest, TokenRequest

log = logging.getLogger("uvicorn.error")

app = FastAPI(title="Asnan Tower PMS (mock)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],   # React dev server
    allow_methods=["*"],
    allow_headers=["*"],
)

def errors(*codes):
    """Shows the standard error body for these status codes in /docs."""
    return {c: {"model": ErrorOut, "description": "Rule or validation error"} for c in codes}


# ---------- error handling ----------
@app.exception_handler(RuleError)
async def rule_error_handler(request, exc: RuleError):
    return JSONResponse(status_code=exc.http_status, content=exc.to_dict())


@app.exception_handler(Exception)
async def unexpected_error_handler(request, exc: Exception):
    log.exception("Unexpected error")          # the real error stays in the server log
    return JSONResponse(status_code=500,
                        content={"error": "INTERNAL", "message": "Something went wrong."})


# ---------- routes ----------
@app.get("/health", tags=["System"], status_code=200)
def health():
    return {"status": "ok"}


@app.get("/units", response_model=list[UnitOut], tags=["Catalogue"], status_code=200)
def get_units():
    return pms.list_units()


@app.get("/visit-types", response_model=list[VisitTypeOut], tags=["Catalogue"], status_code=200)
def get_visit_types():
    return pms.list_visit_types()

# The doctor can be either called by their names or their units
@app.get("/doctors", response_model=list[DoctorOut] , tags=["Catalogue"], status_code=200)
def getDoctor(name : str | None = None, unit_id : int | None = None):
    return pms.list_doctors(unit_id=unit_id , name=name)

@app.get("/slots" , response_model=SlotsOut, tags=["Availability"], responses=errors(400, 404), status_code=200)
def getSlots(doctor_id : int, date : str, rov_id : int):
    return pms.get_slots(doctor_id=doctor_id, date = date, rov_id=rov_id)

@app.get("/next-available", response_model=list[SlotOption],tags=["Availability"],responses=errors(400, 404), status_code=200)
def getNextSlotsAvailable(rov_id : int, doctor_id : int | None = None, unit_id : int | None = None , from_date : str | None  = None , days_ahead : int = 14 ,limit: int = 4):
    return pms.get_next_available(rov_id=rov_id, doctor_id=doctor_id, unit_id=unit_id, from_date=from_date, days_ahead=days_ahead, limit=limit  )

@app.post("/patients/verify", response_model=VerifyResponse, tags=["Identity"],responses=errors(400, 403, 429), status_code=200)
def verify(body: VerifyRequest):
    return pms.verify_patient(body.patient_id, body.name, body.phone)

@app.get("/patients/me/appointments" , response_model=list[AppointmentOut],tags=["Appointments"],responses=errors(401), status_code=200)
def getAppointments(verification_token = Header(alias="X-Verification-Token"),upcoming_only : bool = True):
    return pms.get_patient_appointments(token=verification_token, upcoming_only=upcoming_only)

@app.post("/appointments", response_model=AppointmentOut ,tags=["Appointments"],responses=errors(400, 401, 404, 409), status_code=201)
def postAppointment(body: CreateAppointmentRequest):
    return pms.create_appointment(token=body.token, doctor_id=body.doctor_id, rov_id=body.rov_id, date=body.date, time=body.time, notes=body.notes)

@app.post("/appointments/{appointment_id}/reschedule" , response_model=AppointmentOut,tags=["Appointments"],responses=errors(400, 401, 404, 409), status_code=200)
def rescheduleAppointment(appointment_id : int , body : RescheduleRequest):
    return pms.reschedule_appointment(token=body.token,appointment_id=appointment_id, new_date=body.new_date, new_time=body.new_time, new_doctor_id=body.new_doctor_id)

@app.post("/appointments/{appointment_id}/cancel" , response_model=AppointmentOut,tags=["Appointments"],responses=errors( 401, 404, 409), status_code=200)
def cancelAppointment(appointment_id : int, body : TokenRequest):
    return pms.cancel_appointment(token=body.token, appointment_id=appointment_id)

@app.post("/appointments/{appointment_id}/confirm",tags=["Appointments"],responses=errors( 401, 404, 409), status_code=200)
def confirmAppointment(appointment_id : int, body : TokenRequest):
    return pms.confirm_appointment(token=body.token, appointment_id=appointment_id)