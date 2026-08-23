# HealthCare Platform - Backend API

Welcome to the backend repository for the **HealthCare** platform. This repository contains the core API, database interactions, and business logic that powers the clinical scheduling system.

*If you are looking for the user interface and client application, please visit the [HealthCare Frontend Repository](https://github.com/YOUR-USERNAME/healthcare-frontend).*

## Tech Stack
- **Framework:** FastAPI (Python 3)
- **Database:** PostgreSQL (via Supabase)
- **Authentication:** Supabase Admin API & GoTrue
- **AI/LLM:** Google Gemini Integration (for AI-powered scheduling and chat)
- **External APIs:** Google Calendar (for syncing doctor schedules)
- **Scheduling:** APScheduler (for background tasks and cron jobs)

## Key Features
- **Intelligent Appointment System:** Robust endpoints for managing bookings, handling doctor availability, and preventing double-booking using database-level locking and slot-hold mechanisms.
- **LLM Medical AI:** Integrates with Gemini to provide intelligent pre-consultation insights and automated symptom routing.
- **Google Calendar Sync:** Securely connects to doctors' Google Calendars via OAuth to sync their clinical shifts.
- **Background Jobs:** Handles automated email notifications, appointment reminders, and cleanup of expired held slots.
- **Role-Based API Security:** Dependency-injected endpoint protection to ensure strict separation between Patient, Doctor, and Admin privileges.

## Quick Start (Local Development)

1. Create a virtual environment and install dependencies:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Or .venv\Scripts\activate on Windows
   pip install -r requirements.txt
   ```
2. Set up your `.env` file using `.env.example` as a template.
3. Start the FastAPI development server:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

*Designed with ❤️ for a secure and reliable healthcare architecture.*
