import logging
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.services.supabase_client import supabase_admin
from app.services.email_service import send_medication_reminder_email

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

async def process_medication_reminders():
    """
    Periodic job that finds pending medication reminders scheduled for current time or earlier,
    sends out email reminders to patients, and updates the reminder status.
    """
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        
        # 1. Query pending reminders where reminder_time <= now
        res = supabase_admin.table("medication_schedules") \
            .select("*, appointments!inner(patient_id, post_visit_summary)") \
            .eq("status", "PENDING") \
            .lte("reminder_time", now_iso) \
            .limit(50) \
            .execute()
            
        pending_reminders = res.data if res and res.data else []
        if not pending_reminders:
            return

        logger.info(f"Processing {len(pending_reminders)} pending medication reminders...")

        for reminder in pending_reminders:
            reminder_id = reminder["id"]
            patient_id = reminder["patient_id"]
            reminder_time = reminder.get("reminder_time", "")
            
            # Fetch patient details if not joined
            patient_email = None
            patient_name = "Patient"
            
            patient_info = reminder.get("profiles")
            if patient_info:
                patient_name = patient_info.get("full_name", "Patient")
            
            # Fetch user email from Supabase Auth / profiles
            try:
                profile_res = supabase_admin.table("profiles").select("full_name").eq("id", patient_id).single().execute()
                if profile_res.data:
                    patient_name = profile_res.data.get("full_name", patient_name)
            except Exception:
                pass

            # Fetch appointment's post visit summary
            medications = []
            appointment_data = reminder.get("appointments")
            if not appointment_data:
                appt_res = supabase_admin.table("appointments").select("post_visit_summary").eq("id", reminder.get("appointment_id")).single().execute()
                if appt_res.data:
                    appointment_data = appt_res.data
            
            if appointment_data:
                p_summary = appointment_data.get("post_visit_summary") or {}
                medications = p_summary.get("medications") or []

            # We can attempt to query the auth user email
            # In Supabase, if auth.users is accessible or email is passed:
            patient_email = f"patient_{patient_id[:8]}@clinic.com" # Default placeholder fallback
            try:
                # Try fetching email if stored
                user_res = supabase_admin.auth.admin.get_user_by_id(patient_id)
                if user_res and user_res.user and user_res.user.email:
                    patient_email = user_res.user.email
            except Exception:
                pass

            # Send Email
            success = await send_medication_reminder_email(
                patient_email=patient_email,
                patient_name=patient_name,
                medications=medications,
                reminder_time=reminder_time
            )

            # Update schedule status
            new_status = "SENT" if success else "FAILED"
            supabase_admin.table("medication_schedules") \
                .update({"status": new_status}) \
                .eq("id", reminder_id) \
                .execute()

    except Exception as e:
        logger.error(f"Error executing medication reminder background job: {e}")

async def cleanup_expired_holds():
    """
    Periodic job to mark expired HOLD appointments as CANCELLED.
    """
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        
        # Find expired holds
        res = supabase_admin.table("appointments") \
            .update({"status": "CANCELLED"}) \
            .eq("status", "HOLD") \
            .lt("hold_expires_at", now_iso) \
            .execute()
            
        if res.data and len(res.data) > 0:
            logger.info(f"Cleaned up {len(res.data)} expired slot holds.")
    except Exception as e:
        logger.error(f"Error during expired holds cleanup: {e}")

def start_scheduler():
    """
    Registers periodic background tasks and starts APScheduler.
    """
    # Check medication reminders every 1 minute
    scheduler.add_job(
        process_medication_reminders,
        'interval',
        minutes=1,
        id='medication_reminders_job',
        replace_existing=True
    )
    
    # Cleanup expired slot holds every 2 minutes
    scheduler.add_job(
        cleanup_expired_holds,
        'interval',
        minutes=2,
        id='cleanup_holds_job',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("APScheduler started successfully with medication reminder and cleanup jobs.")

def shutdown_scheduler():
    """
    Gracefully shuts down APScheduler.
    """
    if scheduler.running:
        scheduler.shutdown()
        logger.info("APScheduler shut down.")
