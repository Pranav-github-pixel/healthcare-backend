from fastapi import APIRouter, HTTPException, status, Depends, Query, BackgroundTasks
from datetime import datetime, date, time, timezone
from app.models.schemas import DoctorLeaveCreateRequest, DoctorLeaveResponse, RoleEnum
from app.services.supabase_client import supabase_admin
from app.services.email_service import send_cancellation_email
from app.core.security import require_roles
from typing import List, Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin & Leaves"])

@router.post("/leaves", response_model=DoctorLeaveResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_roles([RoleEnum.ADMIN]))])
async def add_doctor_leave(payload: DoctorLeaveCreateRequest, background_tasks: BackgroundTasks):
    """
    Admin marks a doctor on leave for a specific date.
    Automatically finds all confirmed or held appointments on that date and cancels them.
    Dispatches cancellation notification emails to affected patients in the background.
    """
    try:
        # 1. Check if doctor exists
        doc_res = supabase_admin.table("profiles").select("id, full_name").eq("id", payload.doctor_id).eq("role", RoleEnum.DOCTOR.value).single().execute()
        if not doc_res or not doc_res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Doctor not found"
            )
        
        doctor_name = doc_res.data.get("full_name", "Doctor")

        # 2. Check if leave already exists for this date
        existing = supabase_admin.table("doctor_leaves") \
            .select("id") \
            .eq("doctor_id", payload.doctor_id) \
            .eq("leave_date", str(payload.leave_date)) \
            .execute()
            
        if existing.data and len(existing.data) > 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Doctor is already marked on leave for {payload.leave_date}"
            )

        # 3. Insert leave record
        leave_data = {
            "doctor_id": payload.doctor_id,
            "leave_date": str(payload.leave_date),
            "reason": payload.reason
        }
        
        leave_insert_res = supabase_admin.table("doctor_leaves").insert(leave_data).execute()
        if not leave_insert_res or not leave_insert_res.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to record doctor leave."
            )
            
        created_leave = leave_insert_res.data[0]

        # 4. Find all existing appointments for that doctor on that date and cancel them
        start_of_day_iso = datetime.combine(payload.leave_date, time.min, tzinfo=timezone.utc).isoformat()
        end_of_day_iso = datetime.combine(payload.leave_date, time.max, tzinfo=timezone.utc).isoformat()

        affected_appts_res = supabase_admin.table("appointments") \
            .select("id, patient_id, start_time") \
            .eq("doctor_id", payload.doctor_id) \
            .gte("start_time", start_of_day_iso) \
            .lte("start_time", end_of_day_iso) \
            .in_("status", ["CONFIRMED", "HOLD"]) \
            .execute()

        cancelled_count = 0
        if affected_appts_res.data:
            appt_ids = [a["id"] for a in affected_appts_res.data]
            cancelled_count = len(appt_ids)
            
            # Cancel all affected appointments
            supabase_admin.table("appointments") \
                .update({"status": "CANCELLED"}) \
                .in_("id", appt_ids) \
                .execute()

            # Enqueue cancellation emails for each affected patient
            for appt in affected_appts_res.data:
                patient_id = appt.get("patient_id")
                start_time_str = appt.get("start_time", "")
                
                try:
                    p_res = supabase_admin.auth.admin.get_user_by_id(patient_id)
                    if p_res and p_res.user and p_res.user.email:
                        background_tasks.add_task(
                            send_cancellation_email,
                            recipient_email=p_res.user.email,
                            recipient_name="Patient",
                            other_party_name=f"Dr. {doctor_name}",
                            appointment_time=start_time_str,
                            reason=f"Doctor is unavailable/on leave: {payload.reason or 'Scheduled absence'}"
                        )
                except Exception as e:
                    logger.warning(f"Could not enqueue cancellation email for patient {patient_id}: {e}")

        return DoctorLeaveResponse(
            id=created_leave["id"],
            doctor_id=created_leave["doctor_id"],
            leave_date=created_leave["leave_date"],
            reason=created_leave.get("reason"),
            cancelled_appointments_count=cancelled_count
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error managing doctor leave: {str(e)}"
        )

@router.get("/leaves", response_model=List[DoctorLeaveResponse], dependencies=[Depends(require_roles([RoleEnum.ADMIN]))])
async def list_doctor_leaves(
    doctor_id: Optional[str] = Query(None, description="Filter leaves by doctor ID")
):
    """
    List all recorded doctor leaves.
    """
    try:
        query = supabase_admin.table("doctor_leaves").select("*")
        if doctor_id:
            query = query.eq("doctor_id", doctor_id)
            
        res = query.order("leave_date", desc=True).execute()
        return res.data if res and res.data else []
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch leaves: {str(e)}"
        )

@router.delete("/leaves/{leave_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_roles([RoleEnum.ADMIN]))])
async def delete_doctor_leave(leave_id: int):
    """
    Remove a doctor's leave entry.
    """
    try:
        res = supabase_admin.table("doctor_leaves").delete().eq("id", leave_id).execute()
        return None
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete leave: {str(e)}"
        )
