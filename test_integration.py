import os
import sys
import uuid
import time
from datetime import datetime, date, timedelta, timezone

# Add the project root to sys.path so we can import app
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi.testclient import TestClient
from app.main import app
from app.services.supabase_client import supabase_admin
from app.core.config import settings

client = TestClient(app)

def create_test_user(email: str, password: str, role: str, name: str):
    """Creates a user in auth.users and sets their profile role"""
    from supabase import create_client
    temp_client = create_client(settings.SUPABASE_URL, settings.SUPABASE_PUBLISHABLE_KEY)
    
    # 1. Create in auth.users using admin API
    user_id = None
    try:
        user_res = supabase_admin.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {"full_name": name}
        })
        user_id = user_res.user.id
        print(f"Created user {email} with ID {user_id}")
    except Exception as e:
        if "already been registered" in str(e):
            print(f"User {email} already exists, attempting login...")
            login_res = temp_client.auth.sign_in_with_password({
                "email": email,
                "password": password
            })
            user_id = login_res.user.id
        else:
            print(f"Failed to create user via admin API: {e}")
            raise

    # 2. Update profile role using admin (since the trigger creates it as PATIENT)
    supabase_admin.table("profiles").update({
        "role": role,
        "full_name": name,
        "working_hours": {"monday": [["09:00", "13:00"], ["14:00", "18:00"]], "tuesday": [["09:00", "13:00"], ["14:00", "18:00"]], "wednesday": [["09:00", "13:00"], ["14:00", "18:00"]], "thursday": [["09:00", "13:00"], ["14:00", "18:00"]], "friday": [["09:00", "13:00"], ["14:00", "18:00"]]} if role == "DOCTOR" else None
    }).eq("id", user_id).execute()

    # 3. Login to get token using a fresh client
    login_res = temp_client.auth.sign_in_with_password({
        "email": email,
        "password": password
    })
    
    token = login_res.session.access_token
    
    return user_id, token

def run_tests():
    print("=========================================")
    print("Starting Integration Tests")
    print("=========================================")
    
    # Check if SUPABASE_KEY is a service role key
    if "sb_publishable" in settings.SUPABASE_SECRET_KEY:
        print("ERROR: SUPABASE_KEY in .env appears to be the anon/publishable key.")
        print("Please change it to the service_role key before running tests.")
        return

    # Setup
    doc_email = "pranavsatish.khadse2023@vitstudent.ac.in"
    pat_email = "oynian@gmail.com"
    adm_email = "psjkhadse@gmail.com"
    password = "TestPassword123!"

    print("\n[1] Creating Test Users...")
    doc_id, doc_token = create_test_user(doc_email, password, "DOCTOR", "Dr. Test")
    pat_id, pat_token = create_test_user(pat_email, password, "PATIENT", "Pat Test")
    adm_id, adm_token = create_test_user(adm_email, password, "ADMIN", "Admin Test")
    
    doc_headers = {"Authorization": f"Bearer {doc_token}"}
    pat_headers = {"Authorization": f"Bearer {pat_token}"}
    adm_headers = {"Authorization": f"Bearer {adm_token}"}

    print("\n[2] Testing: Get Available Slots")
    # Get next Monday
    today = date.today()
    next_monday = today + timedelta(days=-today.weekday() + 7)
    
    res = client.get(f"/api/appointments/available-slots?doctor_id={doc_id}&date={next_monday.isoformat()}", headers=pat_headers)
    assert res.status_code == 200, res.text
    slots = res.json()["slots"]
    print(f"Found {len(slots)} available slots for next Monday.")
    assert len(slots) > 0, "No slots found!"
    
    slot_to_book = slots[0]
    
    print("\n[3] Testing: Hold Slot")
    hold_payload = {
        "doctor_id": doc_id,
        "start_time": slot_to_book["start_time"],
        "end_time": slot_to_book["end_time"]
    }
    res = client.post("/api/appointments/hold", json=hold_payload, headers=pat_headers)
    assert res.status_code == 201, res.text
    appt = res.json()
    appt_id = appt["id"]
    print(f"Held appointment ID: {appt_id}")
    
    print("\n[4] Testing: Concurrency (Double Booking Hold)")
    res = client.post("/api/appointments/hold", json=hold_payload, headers=pat_headers)
    assert res.status_code == 409, "Expected 409 Conflict for double booking!"
    print("Successfully blocked double booking.")
    
    print("\n[5] Testing: Confirm Appointment (Triggers LLM Pre-Visit)")
    confirm_payload = {
        "appointment_id": appt_id,
        "symptoms_raw": "I have had a severe headache and slight fever for 2 days."
    }
    res = client.post("/api/appointments/confirm", json=confirm_payload, headers=pat_headers)
    assert res.status_code == 200, res.text
    confirmed_appt = res.json()
    print("Appointment confirmed! Pre-visit summary:")
    print(confirmed_appt.get("pre_visit_summary"))
    
    print("\n[6] Testing: Post-Visit Notes (Triggers LLM Post-Visit & Reminders)")
    post_payload = {
        "doctor_notes_raw": "Patient has a mild viral infection. Prescribed Paracetamol 500mg, 3 times a day for 3 days. Drink plenty of water."
    }
    res = client.post(f"/api/appointments/{appt_id}/post-visit", json=post_payload, headers=doc_headers)
    assert res.status_code == 200, res.text
    post_res = res.json()
    print("Post-visit processed! Summary:")
    print(post_res.get("post_visit_summary"))
    print(f"Scheduled Reminders Count: {post_res.get('scheduled_reminders_count')}")
    
    print("\n[7] Testing: Admin Leave (Cascading Cancellations)")
    # Book another slot for today
    leave_date = date.today().isoformat()
    # Find a slot today
    res = client.get(f"/api/appointments/available-slots?doctor_id={doc_id}&date={leave_date}", headers=pat_headers)
    if res.status_code == 200 and len(res.json()["slots"]) > 0:
        today_slot = res.json()["slots"][0]
        # Hold
        h_res = client.post("/api/appointments/hold", json={
            "doctor_id": doc_id,
            "start_time": today_slot["start_time"],
            "end_time": today_slot["end_time"]
        }, headers=pat_headers)
        if h_res.status_code == 201:
            today_appt_id = h_res.json()["id"]
            # Confirm
            client.post("/api/appointments/confirm", json={
                "appointment_id": today_appt_id,
                "symptoms_raw": "Test symptoms"
            }, headers=pat_headers)
            
            # Now add leave
            leave_payload = {
                "doctor_id": doc_id,
                "leave_date": leave_date,
                "reason": "Sick leave"
            }
            res = client.post("/api/admin/leaves", json=leave_payload, headers=adm_headers)
            assert res.status_code == 201, res.text
            leave_data = res.json()
            print(f"Admin leave created. Cancelled appointments count: {leave_data.get('cancelled_appointments_count')}")
            assert leave_data.get("cancelled_appointments_count") >= 1
    
    print("\n=========================================")
    print("ALL TESTS PASSED SUCCESSFULLY!")
    print("=========================================")

if __name__ == "__main__":
    run_tests()
