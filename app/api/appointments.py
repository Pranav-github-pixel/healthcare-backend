from fastapi import APIRouter, HTTPException, status, Depends, Query, BackgroundTasks
from datetime import datetime, date, time, timedelta, timezone
from app.models.schemas import (
    AvailableSlotsResponse,
    AvailableSlot,
    AppointmentHoldRequest,
    AppointmentConfirmRequest,
    AppointmentCancelRequest,
    AppointmentResponse,
    AppointmentStatusEnum,
    RoleEnum,
    ProfileResponse,
    PostVisitNotesRequest,
    PostVisitResponse
)
from app.services.supabase_client import supabase_admin
from app.services.llm_service import generate_pre_visit_summary, generate_post_visit_summary
from app.services.email_service import (
    send_booking_confirmation_patient,
    send_booking_notification_doctor,
    send_cancellation_email
)
from app.api.notifications import create_notification
from app.services.calendar_service import create_calendar_event, delete_calendar_event, create_medication_events, update_calendar_event
from app.core.security import get_current_user, require_roles
from typing import List, Optional, Dict, Any
import dateutil.parser
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/appointments", tags=["Appointments"])

def parse_iso_datetime(dt_str: str) -> datetime:
    try:
        dt = dateutil.parser.isoparse(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid datetime format: {dt_str}. Please use ISO 8601 format."
        )

@router.get("/available-slots", response_model=AvailableSlotsResponse)
async def get_available_slots(
    doctor_id: str = Query(..., description="Doctor's user ID"),
    date_val: date = Query(..., alias="date", description="Date to check available slots (YYYY-MM-DD)")
):
    """
    Get all available appointment slots for a specific doctor on a given date.
    Calculated purely using database records (working hours, leaves, and booked/held slots).
    """
    try:
        # 1. Check if doctor is on leave on this date
        leave_res = supabase_admin.table("doctor_leaves") \
            .select("id") \
            .eq("doctor_id", doctor_id) \
            .eq("leave_date", str(date_val)) \
            .execute()
            
        if leave_res.data and len(leave_res.data) > 0:
            return AvailableSlotsResponse(
                doctor_id=doctor_id,
                date=date_val,
                slot_duration_minutes=30,
                slots=[]
            )

        # 2. Fetch doctor profile for working hours and slot duration
        doc_res = supabase_admin.table("profiles") \
            .select("*") \
            .eq("id", doctor_id) \
            .eq("role", RoleEnum.DOCTOR.value) \
            .single() \
            .execute()
            
        if not doc_res or not doc_res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Doctor profile not found"
            )
            
        doctor_profile = doc_res.data
        working_hours = doctor_profile.get("working_hours") or {}
        slot_duration = doctor_profile.get("slot_duration_minutes") or 30

        # Day of week name, e.g., 'monday'
        day_name = date_val.strftime("%A").lower()
        day_hours = working_hours.get(day_name)
        
        # Normalize day_hours to always be a list of blocks: [["start", "end"], ["start", "end"]]
        blocks = []
        if not day_hours or len(day_hours) == 0:
            if date_val.weekday() < 5:  # Mon-Fri default
                blocks = [["09:00", "17:00"]]
            else:
                return AvailableSlotsResponse(
                    doctor_id=doctor_id,
                    date=date_val,
                    slot_duration_minutes=slot_duration,
                    slots=[]
                )
        elif isinstance(day_hours[0], list):
            blocks = day_hours
        elif len(day_hours) == 2 and isinstance(day_hours[0], str):
            blocks = [day_hours]
            
        candidates = []
        for block in blocks:
            if len(block) != 2:
                continue
            start_hour_str, end_hour_str = block[0], block[1]
            start_h, start_m = map(int, start_hour_str.split(":"))
            end_h, end_m = map(int, end_hour_str.split(":"))

            block_start_dt = datetime.combine(date_val, time(start_h, start_m), tzinfo=timezone.utc)
            block_end_dt = datetime.combine(date_val, time(end_h, end_m), tzinfo=timezone.utc)

            curr = block_start_dt
            while curr + timedelta(minutes=slot_duration) <= block_end_dt:
                slot_end = curr + timedelta(minutes=slot_duration)
                candidates.append((curr, slot_end))
                curr = slot_end

        # 3. Query existing booked or actively held appointments for this doctor on this day
        start_of_day_iso = datetime.combine(date_val, time.min, tzinfo=timezone.utc).isoformat()
        end_of_day_iso = datetime.combine(date_val, time.max, tzinfo=timezone.utc).isoformat()
        
        now_utc = datetime.now(timezone.utc)

        appts_res = supabase_admin.table("appointments") \
            .select("start_time, end_time, status, hold_expires_at") \
            .eq("doctor_id", doctor_id) \
            .gte("start_time", start_of_day_iso) \
            .lte("start_time", end_of_day_iso) \
            .in_("status", ["CONFIRMED", "HOLD"]) \
            .execute()

        existing_appointments = appts_res.data if appts_res and appts_res.data else []

        # Filter occupied intervals
        occupied_intervals = []
        for appt in existing_appointments:
            appt_status = appt.get("status")
            appt_start = parse_iso_datetime(appt["start_time"])
            appt_end = parse_iso_datetime(appt["end_time"])

            if appt_status == "CONFIRMED":
                occupied_intervals.append((appt_start, appt_end))
            elif appt_status == "HOLD":
                hold_exp_str = appt.get("hold_expires_at")
                if hold_exp_str:
                    hold_exp = parse_iso_datetime(hold_exp_str)
                    if hold_exp > now_utc:
                        occupied_intervals.append((appt_start, appt_end))

        # Filter available slots
        available_slots = []
        for c_start, c_end in candidates:
            is_occupied = False
            for occ_start, occ_end in occupied_intervals:
                if max(c_start, occ_start) < min(c_end, occ_end):
                    is_occupied = True
                    break
            
            if not is_occupied and c_start > now_utc:
                available_slots.append(AvailableSlot(
                    start_time=c_start.isoformat(),
                    end_time=c_end.isoformat()
                ))

        return AvailableSlotsResponse(
            doctor_id=doctor_id,
            date=date_val,
            slot_duration_minutes=slot_duration,
            slots=available_slots
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch available slots: {str(e)}"
        )

@router.post("/hold", response_model=AppointmentResponse, status_code=status.HTTP_201_CREATED)
async def hold_slot(
    payload: AppointmentHoldRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Temporarily reserve/hold a slot for 10 minutes to allow the patient to fill the symptom form.
    Guarantees concurrency safety using database conflict check.
    """
    try:
        start_dt = parse_iso_datetime(payload.start_time)
        end_dt = parse_iso_datetime(payload.end_time)
        slot_date = start_dt.date()

        # 1. Leave Validation
        leave_res = supabase_admin.table("doctor_leaves") \
            .select("id") \
            .eq("doctor_id", payload.doctor_id) \
            .eq("leave_date", str(slot_date)) \
            .execute()
            
        if leave_res.data and len(leave_res.data) > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Doctor is on leave on this date. Booking is unavailable."
            )

        now_utc = datetime.now(timezone.utc)
        hold_expires_at = (now_utc + timedelta(minutes=10)).isoformat()

        # 2. Check for existing active holds or confirmed bookings on this overlapping slot
        overlap_res = supabase_admin.table("appointments") \
            .select("id, status, hold_expires_at") \
            .eq("doctor_id", payload.doctor_id) \
            .lt("start_time", end_dt.isoformat()) \
            .gt("end_time", start_dt.isoformat()) \
            .in_("status", ["CONFIRMED", "HOLD"]) \
            .execute()

        if overlap_res.data:
            for item in overlap_res.data:
                if item["status"] == "CONFIRMED":
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="This slot is already booked."
                    )
                elif item["status"] == "HOLD":
                    exp_str = item.get("hold_expires_at")
                    if exp_str and parse_iso_datetime(exp_str) > now_utc:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail="This slot is currently held by another patient. Please choose another slot or try again in a few minutes."
                        )

        # 3. Create appointment with HOLD status
        new_appt = {
            "patient_id": current_user["id"],
            "doctor_id": payload.doctor_id,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "status": "HOLD",
            "hold_expires_at": hold_expires_at
        }

        res = supabase_admin.table("appointments").insert(new_appt).execute()
        if not res or not res.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to hold slot"
            )
            
        return res.data[0]
    except HTTPException:
        raise
    except Exception as e:
        err_msg = str(e)
        if "no_double_booking" in err_msg or "duplicate" in err_msg or "violates exclusion constraint" in err_msg:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This slot was just taken or held by another user. Please choose a different slot."
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Slot hold failed: {err_msg}"
        )

@router.post("/confirm", response_model=AppointmentResponse)
async def confirm_appointment(
    payload: AppointmentConfirmRequest,
    background_tasks: BackgroundTasks,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Confirm a held appointment, record symptoms, and generate AI pre-visit summary.
    Dispatches background email confirmations and Google Calendar sync.
    """
    try:
        # 1. Fetch the held appointment
        res = supabase_admin.table("appointments") \
            .select("*") \
            .eq("id", payload.appointment_id) \
            .single() \
            .execute()
            
        if not res or not res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Appointment not found"
            )

        appt = res.data
        
        # Verify ownership (or admin)
        if appt["patient_id"] != current_user["id"] and current_user.get("role") != RoleEnum.ADMIN.value:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only confirm your own appointment."
            )

        if appt["status"] == "CONFIRMED":
            return appt

        if appt["status"] != "HOLD":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot confirm appointment with status '{appt['status']}'"
            )

        # 2. Check hold expiration
        hold_exp_str = appt.get("hold_expires_at")
        if hold_exp_str:
            hold_exp = parse_iso_datetime(hold_exp_str)
            if datetime.now(timezone.utc) > hold_exp:
                supabase_admin.table("appointments").update({"status": "CANCELLED"}).eq("id", payload.appointment_id).execute()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Your 10-minute slot hold has expired. Please select and hold a slot again."
                )

        # 3. Generate Pre-Visit Summary using LLM
        pre_visit_summary = await generate_pre_visit_summary(payload.symptoms_raw)

        # 4. Update to CONFIRMED with symptoms and pre-visit AI summary
        update_data = {
            "status": "CONFIRMED",
            "symptoms_raw": payload.symptoms_raw,
            "pre_visit_summary": pre_visit_summary,
            "hold_expires_at": None
        }

        update_res = supabase_admin.table("appointments").update(update_data).eq("id", payload.appointment_id).execute()
        if not update_res or not update_res.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to confirm appointment."
            )

        confirmed_appt = update_res.data[0]

        # 5. Fetch doctor details for notifications
        doc_profile = {}
        try:
            doc_res = supabase_admin.table("profiles").select("full_name").eq("id", appt["doctor_id"]).single().execute()
            if doc_res.data:
                doc_profile = doc_res.data
        except Exception:
            pass

        doctor_name = doc_profile.get("full_name", "Doctor")
        patient_name = current_user.get("profile", {}).get("full_name", current_user.get("email", "Patient"))
        patient_email = current_user.get("email", "")
        
        # Look up doctor email if available
        doctor_email = f"dr_{appt['doctor_id'][:8]}@clinic.com"
        try:
            doc_user_res = supabase_admin.auth.admin.get_user_by_id(appt["doctor_id"])
            if doc_user_res and doc_user_res.user and doc_user_res.user.email:
                doctor_email = doc_user_res.user.email
        except Exception:
            pass

        # 6. Dispatch background notifications (Email & Google Calendar)
        if patient_email:
            background_tasks.add_task(
                send_booking_confirmation_patient,
                patient_email=patient_email,
                patient_name=patient_name,
                doctor_name=doctor_name,
                start_time=appt["start_time"],
                end_time=appt["end_time"]
            )
        
        if doctor_email:
            background_tasks.add_task(
                send_booking_notification_doctor,
                doctor_email=doctor_email,
                doctor_name=doctor_name,
                patient_name=patient_name,
                start_time=appt["start_time"],
                end_time=appt["end_time"],
                symptoms=payload.symptoms_raw
            )

        background_tasks.add_task(
            create_calendar_event,
            user_id=appt["patient_id"],
            doctor_email=doctor_email,
            patient_email=patient_email,
            summary=f"Appointment: {patient_name} with Dr. {doctor_name}",
            description=f"Symptoms: {payload.symptoms_raw}",
            start_time_iso=appt["start_time"],
            end_time_iso=appt["end_time"],
            appointment_id=appt["id"]
        )
        # Notify doctor
        background_tasks.add_task(
            create_notification,
            user_id=appt["doctor_id"],
            type="NEW_BOOKING",
            message=f"New appointment booked by {patient_name} for {appt['start_time']}"
        )

        return confirmed_appt
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Confirmation error: {str(e)}"
        )

@router.post("/{appointment_id}/post-visit", response_model=PostVisitResponse)
async def submit_post_visit_notes(
    appointment_id: str,
    payload: PostVisitNotesRequest,
    background_tasks: BackgroundTasks,
    current_user: Dict[str, Any] = Depends(require_roles([RoleEnum.DOCTOR, RoleEnum.ADMIN]))
):
    """
    Doctor submits post-visit clinical notes.
    LLM converts notes into a patient-friendly summary and extracts medication schedule.
    Automatically populates the medication_schedules table for reminders.
    """
    try:
        # 1. Fetch appointment
        res = supabase_admin.table("appointments").select("*").eq("id", appointment_id).single().execute()
        if not res or not res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Appointment not found"
            )

        appt = res.data
        
        # Verify doctor is assigned to this appointment (or admin)
        if current_user.get("role") != RoleEnum.ADMIN.value and appt["doctor_id"] != current_user["id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You are only allowed to submit notes for your own appointments."
            )

        # 2. Call LLM for Post-Visit Summary & Schedule Extraction
        post_visit_summary = await generate_post_visit_summary(payload.doctor_notes_raw)

        # 3. Update appointment to COMPLETED with post-visit data
        update_data = {
            "status": "COMPLETED",
            "doctor_notes_raw": payload.doctor_notes_raw,
            "post_visit_summary": post_visit_summary
        }
        
        supabase_admin.table("appointments").update(update_data).eq("id", appointment_id).execute()

        # Notify patient
        background_tasks.add_task(
            create_notification,
            user_id=appt["patient_id"],
            type="POST_VISIT_NOTES",
            message=f"Dr. has submitted your post-visit summary and prescriptions."
        )
        
        # 4. Insert medication schedules if any
        medications = post_visit_summary.get("medications", []) or []
        created_reminders_count = 0

        if medications and isinstance(medications, list):
            now_dt = datetime.now(timezone.utc)
            schedules_to_insert = []
            calendar_schedules = []

            for med in medications:
                times_per_day = med.get("times_per_day", 1)
                duration_days = med.get("duration_days", 1)
                med_name = med.get("name", "Medication")
                dosage = med.get("dosage", "")
                
                # Standard hours depending on frequency
                if times_per_day == 1:
                    dose_hours = [9] # 9 AM
                elif times_per_day == 2:
                    dose_hours = [9, 21] # 9 AM, 9 PM
                elif times_per_day == 3:
                    dose_hours = [8, 14, 20] # 8 AM, 2 PM, 8 PM
                elif times_per_day >= 4:
                    dose_hours = [8, 12, 16, 20] # 8 AM, 12 PM, 4 PM, 8 PM
                else:
                    dose_hours = [9]

                for day_offset in range(duration_days):
                    target_date = (now_dt + timedelta(days=day_offset)).date()
                    for hour in dose_hours:
                        reminder_time = datetime.combine(target_date, time(hour, 0), tzinfo=timezone.utc)
                        if reminder_time > now_dt:
                            schedules_to_insert.append({
                                "appointment_id": appointment_id,
                                "patient_id": appt["patient_id"],
                                "reminder_time": reminder_time.isoformat(),
                                "medication_name": med_name,
                                "dosage": dosage,
                                "status": "PENDING"
                            })
                            calendar_schedules.append({
                                "reminder_time": reminder_time.isoformat(),
                                "medication_name": med_name,
                                "dosage": dosage
                            })

            if schedules_to_insert:
                sched_res = supabase_admin.table("medication_schedules").insert(schedules_to_insert).execute()
                created_reminders_count = len(sched_res.data) if sched_res and sched_res.data else len(schedules_to_insert)
                
                # Dispatch Google Calendar Events creation
                try:
                    patient_res = supabase_admin.auth.admin.get_user_by_id(appt["patient_id"])
                    if patient_res and patient_res.user and patient_res.user.email:
                        patient_email = patient_res.user.email
                        background_tasks.add_task(
                            create_medication_events,
                            user_id=appt["patient_id"],
                            patient_email=patient_email,
                            schedules=calendar_schedules
                        )
                except Exception as ex:
                    logger.error(f"Failed to look up patient email for calendar events: {ex}")

        return PostVisitResponse(
            appointment_id=appointment_id,
            status=AppointmentStatusEnum.COMPLETED,
            doctor_notes_raw=payload.doctor_notes_raw,
            post_visit_summary=post_visit_summary,
            scheduled_reminders_count=created_reminders_count
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting post-visit notes: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Post-visit processing failed: {str(e)}"
        )

@router.get("/my", response_model=List[AppointmentResponse])
async def get_my_appointments(
    status_filter: Optional[AppointmentStatusEnum] = Query(None, alias="status"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get all appointments relevant to the current user (Patient sees theirs, Doctor sees their visits, Admin sees all).
    Enriches each appointment with doctor_name and patient_name for convenient frontend display.
    """
    try:
        user_id = current_user["id"]
        user_role = current_user.get("role")

        query = supabase_admin.table("appointments").select("*")
        if user_role == RoleEnum.DOCTOR.value:
            query = query.eq("doctor_id", user_id)
        elif user_role == RoleEnum.PATIENT.value:
            query = query.eq("patient_id", user_id)
        
        if status_filter:
            query = query.eq("status", status_filter.value)
            
        res = query.order("start_time", desc=True).execute()
        appointments = res.data if res and res.data else []

        # Collect unique doctor_ids and patient_ids to batch-fetch names
        profile_ids = set()
        for appt in appointments:
            profile_ids.add(appt["doctor_id"])
            profile_ids.add(appt["patient_id"])
        
        profiles_map = {}
        if profile_ids:
            profiles_res = supabase_admin.table("profiles").select("id, full_name, specialization").in_("id", list(profile_ids)).execute()
            if profiles_res and profiles_res.data:
                for p in profiles_res.data:
                    profiles_map[p["id"]] = p

        # Enrich appointments with names
        enriched = []
        for appt in appointments:
            doc_profile = profiles_map.get(appt["doctor_id"], {})
            pat_profile = profiles_map.get(appt["patient_id"], {})
            appt["doctor_name"] = doc_profile.get("full_name", "Unknown Doctor")
            appt["patient_name"] = pat_profile.get("full_name", "Unknown Patient")
            enriched.append(appt)

        return enriched
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch appointments: {str(e)}"
        )

@router.get("/{appointment_id}", response_model=AppointmentResponse)
async def get_appointment_by_id(
    appointment_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Get details of a single appointment.
    """
    try:
        res = supabase_admin.table("appointments").select("*").eq("id", appointment_id).single().execute()
        if not res or not res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Appointment not found"
            )
            
        appt = res.data
        if current_user.get("role") != RoleEnum.ADMIN.value:
            if appt["patient_id"] != current_user["id"] and appt["doctor_id"] != current_user["id"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied to this appointment"
                )
                
        return appt
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving appointment: {str(e)}"
        )

@router.post("/{appointment_id}/cancel", response_model=AppointmentResponse)
async def cancel_appointment(
    appointment_id: str,
    background_tasks: BackgroundTasks,
    payload: Optional[AppointmentCancelRequest] = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Cancel an appointment and dispatch cancellation notification emails.
    """
    try:
        res = supabase_admin.table("appointments").select("*").eq("id", appointment_id).single().execute()
        if not res or not res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Appointment not found"
            )
            
        appt = res.data
        if current_user.get("role") != RoleEnum.ADMIN.value:
            if appt["patient_id"] != current_user["id"] and appt["doctor_id"] != current_user["id"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not authorized to cancel this appointment."
                )

        update_res = supabase_admin.table("appointments") \
            .update({"status": "CANCELLED"}) \
            .eq("id", appointment_id) \
            .execute()
            
        if not update_res or not update_res.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to cancel appointment"
            )

        cancelled_appt = update_res.data[0]

        # Dispatch cancellation email notifications
        reason = payload.reason if payload else "Cancelled by user"
        
        # Try fetching patient email
        try:
            p_res = supabase_admin.auth.admin.get_user_by_id(appt["patient_id"])
            if p_res and p_res.user and p_res.user.email:
                background_tasks.add_task(
                    send_cancellation_email,
                    recipient_email=p_res.user.email,
                    recipient_name="Patient",
                    other_party_name="Doctor",
                    appointment_time=appt["start_time"],
                    reason=reason
                )
        except Exception:
            pass

        return cancelled_appt
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cancel failed: {str(e)}"
        )


@router.post("/{appointment_id}/reschedule", response_model=AppointmentResponse)
async def reschedule_appointment(
    appointment_id: str,
    payload: AppointmentHoldRequest,
    background_tasks: BackgroundTasks,
    current_user: Dict[str, Any] = Depends(require_roles([RoleEnum.DOCTOR, RoleEnum.ADMIN]))
):
    """
    Doctor reschedules a confirmed appointment. Can only be done once.
    """
    try:
        res = supabase_admin.table("appointments").select("*").eq("id", appointment_id).single().execute()
        if not res or not res.data:
            raise HTTPException(status_code=404, detail="Appointment not found")

        appt = res.data
        if current_user.get("role") != RoleEnum.ADMIN.value and appt["doctor_id"] != current_user["id"]:
            raise HTTPException(status_code=403, detail="Access denied.")

        if appt["status"] != "CONFIRMED":
            raise HTTPException(status_code=400, detail="Only confirmed appointments can be rescheduled.")

        if appt.get("rescheduled_by_doctor", False):
            raise HTTPException(status_code=400, detail="This appointment has already been rescheduled once.")

        start_time_iso = payload.start_time
        end_time_iso = payload.end_time

        update_data = {
            "start_time": start_time_iso,
            "end_time": end_time_iso,
            "rescheduled_by_doctor": True
        }
        update_res = supabase_admin.table("appointments").update(update_data).eq("id", appointment_id).execute()
        if not update_res or not update_res.data:
            raise HTTPException(status_code=500, detail="Reschedule failed")

        updated_appt = update_res.data[0]
        
        # Dispatch background task for calendar update
        try:
            doc_user_res = supabase_admin.auth.admin.get_user_by_id(appt["doctor_id"])
            doctor_email = doc_user_res.user.email if doc_user_res and doc_user_res.user else ""
            
            pat_user_res = supabase_admin.auth.admin.get_user_by_id(appt["patient_id"])
            patient_email = pat_user_res.user.email if pat_user_res and pat_user_res.user else ""
            
            # Since we don't store the event ID, we'll just try to create a new one for now 
            # or in a real system we'd use the stored google_calendar_event_id.
            # But we can simply recreate it as an updated invite.
            background_tasks.add_task(
                create_calendar_event,
                user_id=appt["patient_id"],
                doctor_email=doctor_email,
                patient_email=patient_email,
                summary=f"RESCHEDULED Appointment",
                description=f"This appointment was rescheduled.",
                start_time_iso=start_time_iso,
                end_time_iso=end_time_iso,
                appointment_id=appt["id"]
            )
        except Exception as ex:
            logger.error(f"Failed to dispatch calendar update for reschedule: {ex}")
            
        return updated_appt
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/medications/{schedule_id}/take")
async def mark_medication_taken(
    schedule_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Mark a medication reminder as TAKEN"""
    try:
        # Verify the medication belongs to this patient
        res = supabase_admin.table("medication_schedules").select("id, appointments!inner(patient_id)").eq("id", schedule_id).single().execute()
        if not res or not res.data:
            raise HTTPException(status_code=404, detail="Schedule not found")
        
        if res.data["appointments"]["patient_id"] != current_user["id"] and current_user.get("role") != "ADMIN":
            raise HTTPException(status_code=403, detail="Not authorized")

        update_res = supabase_admin.table("medication_schedules").update({"status": "TAKEN"}).eq("id", schedule_id).execute()
        return {"status": "success", "message": "Medication marked as taken"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
