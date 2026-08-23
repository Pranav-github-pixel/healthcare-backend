import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import aiosmtplib
from app.core.config import settings
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

async def _send_email_async(to_email: str, subject: str, html_content: str, text_content: Optional[str] = None):
    """
    Sends an email asynchronously via SMTP. Logs errors gracefully without throwing exceptions.
    """
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning(f"SMTP credentials not configured. Skipping email to {to_email} with subject: '{subject}'")
        return False

    message = MIMEMultipart("alternative")
    message["From"] = f"{settings.PROJECT_NAME} <{settings.SMTP_USER}>"
    message["To"] = to_email
    message["Subject"] = subject

    if text_content:
        message.attach(MIMEText(text_content, "plain"))
    message.attach(MIMEText(html_content, "html"))

    try:
        await aiosmtplib.send(
            message,
            hostname=settings.SMTP_SERVER or "smtp.gmail.com",
            port=settings.SMTP_PORT or 587,
            start_tls=True,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            timeout=15
        )
        logger.info(f"Email successfully sent to {to_email} - Subject: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {e}")
        return False

async def send_booking_confirmation_patient(
    patient_email: str,
    patient_name: str,
    doctor_name: str,
    start_time: str,
    end_time: str
):
    subject = f"Appointment Confirmed with Dr. {doctor_name}"
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
        <h2 style="color: #2b6cb0;">Appointment Confirmed</h2>
        <p>Dear <strong>{patient_name}</strong>,</p>
        <p>Your appointment has been successfully scheduled and confirmed.</p>
        <div style="background-color: #f7fafc; padding: 15px; border-radius: 6px; margin: 15px 0;">
            <p style="margin: 5px 0;"><strong>Doctor:</strong> Dr. {doctor_name}</p>
            <p style="margin: 5px 0;"><strong>Start Time:</strong> {start_time}</p>
            <p style="margin: 5px 0;"><strong>End Time:</strong> {end_time}</p>
        </div>
        <p>Please arrive 10 minutes prior to your scheduled time.</p>
        <p style="color: #718096; font-size: 12px; margin-top: 20px;">Health Appointment & Follow-up Manager</p>
    </div>
    """
    await _send_email_async(patient_email, subject, html)

async def send_booking_notification_doctor(
    doctor_email: str,
    doctor_name: str,
    patient_name: str,
    start_time: str,
    end_time: str,
    symptoms: Optional[str] = None
):
    subject = f"New Appointment Scheduled: {patient_name}"
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
        <h2 style="color: #2b6cb0;">New Patient Appointment</h2>
        <p>Hello Dr. <strong>{doctor_name}</strong>,</p>
        <p>A new appointment has been scheduled with <strong>{patient_name}</strong>.</p>
        <div style="background-color: #f7fafc; padding: 15px; border-radius: 6px; margin: 15px 0;">
            <p style="margin: 5px 0;"><strong>Time:</strong> {start_time} - {end_time}</p>
            <p style="margin: 5px 0;"><strong>Reported Symptoms:</strong> {symptoms or 'None provided'}</p>
        </div>
        <p>You can review the AI symptom summary in your doctor dashboard.</p>
        <p style="color: #718096; font-size: 12px; margin-top: 20px;">Health Appointment & Follow-up Manager</p>
    </div>
    """
    await _send_email_async(doctor_email, subject, html)

async def send_cancellation_email(
    recipient_email: str,
    recipient_name: str,
    other_party_name: str,
    appointment_time: str,
    reason: Optional[str] = None
):
    subject = f"Appointment Cancelled - {appointment_time}"
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
        <h2 style="color: #c53030;">Appointment Cancellation Notice</h2>
        <p>Dear <strong>{recipient_name}</strong>,</p>
        <p>Your appointment on <strong>{appointment_time}</strong> with <strong>{other_party_name}</strong> has been cancelled.</p>
        {f'<p><strong>Reason:</strong> {reason}</p>' if reason else ''}
        <p>If you need to reschedule, please visit our online portal to book another available slot.</p>
        <p style="color: #718096; font-size: 12px; margin-top: 20px;">Health Appointment & Follow-up Manager</p>
    </div>
    """
    await _send_email_async(recipient_email, subject, html)

async def send_medication_reminder_email(
    patient_email: str,
    patient_name: str,
    medications: List[Dict[str, Any]],
    reminder_time: str
):
    meds_html = "".join([
        f"<li style='margin-bottom: 8px;'><strong>{m.get('name', 'Medication')}</strong>: {m.get('instructions', 'Take as prescribed')}</li>"
        for m in medications
    ]) if medications else "<li>Take your prescribed medication</li>"

    subject = f"Medication Reminder - {reminder_time}"
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 8px;">
        <h2 style="color: #319795;">⏰ Medication Reminder</h2>
        <p>Dear <strong>{patient_name}</strong>,</p>
        <p>This is a reminder to take your scheduled medication:</p>
        <ul style="background-color: #f7fafc; padding: 20px; border-radius: 6px;">
            {meds_html}
        </ul>
        <p>Please follow the dosage instructions provided by your doctor.</p>
        <p style="color: #718096; font-size: 12px; margin-top: 20px;">Health Appointment & Follow-up Manager</p>
    </div>
    """
    return await _send_email_async(patient_email, subject, html)
