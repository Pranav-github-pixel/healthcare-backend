import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, r"c:\projects\Healthcare_software\backend")

from app.services.supabase_client import supabase_admin

emails = [
    "pranavsatish.khadse2023@vitstudent.ac.in",
    "oynian@gmail.com",
    "swpkon@gmail.com",
    "psjkhadse@gmail.com"
]

def reset_passwords():
    try:
        response = supabase_admin.auth.admin.list_users()
        users = response.users if hasattr(response, 'users') else response
        
        for u in users:
            if u.email in emails:
                print(f"Found user {u.email} ({u.id}), updating password...")
                try:
                    supabase_admin.auth.admin.update_user_by_id(u.id, {"password": "password123"})
                    print(f"Successfully updated password for {u.email} to 'password123'")
                except Exception as update_err:
                    print(f"Failed to update {u.email}: {update_err}")
    except Exception as e:
        print(f"Error fetching users: {e}")

if __name__ == "__main__":
    reset_passwords()
