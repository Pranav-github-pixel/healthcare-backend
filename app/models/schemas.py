from enum import Enum
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, Dict, Any, List
from datetime import datetime, date

class RoleEnum(str, Enum):
    ADMIN = "ADMIN"
    DOCTOR = "DOCTOR"
    PATIENT = "PATIENT"

class AppointmentStatusEnum(str, Enum):
    HOLD = "HOLD"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"

# --- Authentication Schemas ---

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, description="Password must be at least 6 characters")
    full_name: str = Field(..., min_length=1)
    role: RoleEnum = RoleEnum.PATIENT
    specialization: Optional[str] = None
    working_hours: Optional[Dict[str, List[str]]] = None
    slot_duration_minutes: Optional[int] = 30

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class AuthUserResponse(BaseModel):
    id: str
    email: EmailStr
    role: RoleEnum
    full_name: str
    specialization: Optional[str] = None
    working_hours: Optional[Dict[str, List[str]]] = None
    slot_duration_minutes: Optional[int] = 30

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUserResponse

# --- Profile Schemas ---

class ProfileResponse(BaseModel):
    id: str
    role: RoleEnum
    full_name: str
    specialization: Optional[str] = None
    working_hours: Optional[Dict[str, List[str]]] = None
    slot_duration_minutes: Optional[int] = 30

class ProfileUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    specialization: Optional[str] = None
    working_hours: Optional[Dict[str, List[str]]] = None
    slot_duration_minutes: Optional[int] = None

# --- Appointment Schemas ---

class AvailableSlot(BaseModel):
    start_time: str
    end_time: str

class AvailableSlotsResponse(BaseModel):
    doctor_id: str
    date: date
    slot_duration_minutes: int
    slots: List[AvailableSlot]

class AppointmentHoldRequest(BaseModel):
    doctor_id: str
    start_time: str = Field(..., description="ISO 8601 string e.g. 2026-08-25T09:00:00Z")
    end_time: str = Field(..., description="ISO 8601 string e.g. 2026-08-25T09:30:00Z")

class AppointmentConfirmRequest(BaseModel):
    appointment_id: str
    symptoms_raw: str = Field(..., min_length=5, description="Symptoms described by the patient")

class AppointmentCancelRequest(BaseModel):
    reason: Optional[str] = None

class AppointmentResponse(BaseModel):
    id: str
    patient_id: str
    doctor_id: str
    start_time: str
    end_time: str
    status: AppointmentStatusEnum
    hold_expires_at: Optional[str] = None
    symptoms_raw: Optional[str] = None
    pre_visit_summary: Optional[Dict[str, Any]] = None
    doctor_notes_raw: Optional[str] = None
    post_visit_summary: Optional[Dict[str, Any]] = None
    meet_link: Optional[str] = None
    rescheduled_by_doctor: Optional[bool] = None
    doctor_name: Optional[str] = None
    patient_name: Optional[str] = None
    doctor: Optional[ProfileResponse] = None
    patient: Optional[ProfileResponse] = None

# --- Doctor Leaves Schemas ---

class DoctorLeaveCreateRequest(BaseModel):
    doctor_id: str
    leave_date: date
    reason: Optional[str] = None

class DoctorLeaveResponse(BaseModel):
    id: int
    doctor_id: str
    leave_date: date
    reason: Optional[str] = None
    cancelled_appointments_count: Optional[int] = 0

# --- LLM & Clinical Schemas (Phase 3) ---

class PreVisitSummary(BaseModel):
    urgency_level: str
    chief_complaint: str
    suggested_questions: List[str]

class MedicationItem(BaseModel):
    name: str
    times_per_day: int = 1
    duration_days: int = 1
    instructions: Optional[str] = None

class PostVisitSummary(BaseModel):
    summary: str
    follow_up_steps: List[str]
    medications: List[MedicationItem]

class PostVisitNotesRequest(BaseModel):
    doctor_notes_raw: str = Field(..., min_length=5, description="Clinical notes entered by the doctor")

class PostVisitResponse(BaseModel):
    appointment_id: str
    status: AppointmentStatusEnum
    doctor_notes_raw: str
    post_visit_summary: Dict[str, Any]
    scheduled_reminders_count: int
