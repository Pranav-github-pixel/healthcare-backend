import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.services.supabase_client import supabase_admin

logger = logging.getLogger(__name__)

def get_calendar_service(user_id: str):
    """
    Builds and returns the Google Calendar API service for a specific user
    using their stored OAuth credentials.
    """
    try:
        # Fetch user's google_credentials from the database
        res = supabase_admin.table("profiles").select("google_credentials").eq("id", user_id).single().execute()
        if not res or not res.data or not res.data.get("google_credentials"):
            logger.warning(f"User {user_id} has no google_credentials connected.")
            return None
        
        creds_data = res.data["google_credentials"]
        
        creds = Credentials(
            token=creds_data.get("token"),
            refresh_token=creds_data.get("refresh_token"),
            token_uri=creds_data.get("token_uri"),
            client_id=creds_data.get("client_id"),
            client_secret=creds_data.get("client_secret"),
            scopes=creds_data.get("scopes")
        )
        
        service = build('calendar', 'v3', credentials=creds)
        return service
    except Exception as e:
        logger.error(f"Failed to build Google Calendar service for {user_id}: {e}")
        return None

async def create_calendar_event(
    user_id: str,
    doctor_email: str,
    patient_email: str,
    summary: str,
    description: str,
    start_time_iso: str,
    end_time_iso: str,
    appointment_id: str = None
) -> Optional[str]:
    """
    Creates an event on Google Calendar and invites the doctor and patient.
    Uses the OAuth token of `user_id` (usually the patient).
    """
    service = get_calendar_service(user_id)
    if not service:
        # Fallback for testing when no calendar connected
        return f"mock_evt_{datetime.utcnow().timestamp()}"

    try:
        event = {
            'summary': summary,
            'description': description,
            'start': {
                'dateTime': start_time_iso,
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': end_time_iso,
                'timeZone': 'UTC',
            },
            'attendees': [
                {'email': doctor_email},
                {'email': patient_email},
            ],
            'reminders': {
                'useDefault': False,
                'overrides': [
                    {'method': 'email', 'minutes': 24 * 60},
                    {'method': 'popup', 'minutes': 30},
                ],
            },
            'conferenceData': {
                'createRequest': {
                    'requestId': f"meet-{appointment_id or datetime.utcnow().timestamp()}",
                    'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                }
            }
        }

        # 'primary' means the calendar of the authenticated user
        event = service.events().insert(
            calendarId='primary',
            body=event,
            conferenceDataVersion=1,
            sendUpdates='all'
        ).execute()

        meet_link = event.get('hangoutLink')
        logger.info(f"Google Calendar event created: {event.get('htmlLink')} | Meet: {meet_link}")
        
        if appointment_id and meet_link:
            supabase_admin.table('appointments').update({'meet_link': meet_link}).eq('id', appointment_id).execute()

        return event.get('id')
    except Exception as e:
        logger.error(f"Error creating Google Calendar event: {e}")
        return None

async def update_calendar_event(
    user_id: str,
    event_id: str,
    doctor_email: str,
    patient_email: str,
    summary: str,
    description: str,
    start_time_iso: str,
    end_time_iso: str
) -> bool:
    """Updates an existing calendar event (e.g. for rescheduling)"""
    service = get_calendar_service(user_id)
    if not service or not event_id or event_id.startswith("mock_evt_"):
        return True

    try:
        event = {
            'summary': summary,
            'description': description,
            'start': {
                'dateTime': start_time_iso,
                'timeZone': 'UTC',
            },
            'end': {
                'dateTime': end_time_iso,
                'timeZone': 'UTC',
            },
            'attendees': [
                {'email': doctor_email},
                {'email': patient_email},
            ],
        }

        service.events().update(
            calendarId='primary',
            eventId=event_id,
            body=event,
            sendUpdates='all'
        ).execute()
        return True
    except Exception as e:
        logger.error(f"Error updating Google Calendar event: {e}")
        return False


async def delete_calendar_event(user_id: str, event_id: str) -> bool:
    """Deletes a previously created Google Calendar event."""
    service = get_calendar_service(user_id)
    if not service or not event_id or event_id.startswith("mock_evt_"):
        return True

    try:
        service.events().delete(
            calendarId='primary',
            eventId=event_id,
            sendUpdates='all'
        ).execute()
        logger.info(f"Google Calendar event {event_id} deleted successfully.")
        return True
    except Exception as e:
        logger.error(f"Error deleting Google Calendar event {event_id}: {e}")
        return False

async def create_medication_events(user_id: str, patient_email: str, schedules: List[Dict[str, Any]]):
    """
    Iterates through medication schedule timestamps and directly inserts 
    short 15-minute reminder events into the user's calendar.
    """
    service = get_calendar_service(user_id)
    if not service:
        logger.warning(f"No calendar service for user {user_id}, skipping medication calendar events.")
        return

    for sched in schedules:
        try:
            start_time = datetime.fromisoformat(sched["reminder_time"].replace('Z', '+00:00'))
            # create a 15-minute block for the reminder
            end_time = start_time + timedelta(minutes=15)
            
            med_name = sched["medication_name"]
            dosage = sched["dosage"]
            
            event = {
                'summary': f"Medication Reminder: {med_name}",
                'description': f"Please take your medication: {med_name} - {dosage}",
                'start': {
                    'dateTime': start_time.isoformat(),
                    'timeZone': 'UTC',
                },
                'end': {
                    'dateTime': end_time.isoformat(),
                    'timeZone': 'UTC',
                },
                # For medications, we just add it to their own calendar, no need to invite themselves as attendee
                'reminders': {
                    'useDefault': False,
                    'overrides': [
                        {'method': 'popup', 'minutes': 10},
                    ],
                },
            }
            
            service.events().insert(
                calendarId='primary',
                body=event
            ).execute()
            
        except Exception as e:
            logger.error(f"Failed to create medication calendar event: {e}")
