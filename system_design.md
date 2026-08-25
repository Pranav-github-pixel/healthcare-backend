# HealthCare Platform: System Design & Architecture

This document outlines the technical architecture and strategies implemented to handle complex scheduling concurrency, edge cases, and asynchronous failures within the HealthCare platform.

---

## 1. Concurrency & Double-Booking Prevention

When multiple patients attempt to book the exact same slot for the same doctor at the same time, the system prevents race conditions using database-level locking and transaction serialization.

### Implementation Strategy
* **Pessimistic Locking**: The booking endpoint initiates a PostgreSQL transaction. When querying the `appointments` table for overlapping times, it applies a `FOR UPDATE` or strict transaction isolation level. 
* **Constraint Enforcement**: The database enforces a strict `EXCLUDE` constraint (or equivalent trigger) that prevents any two non-cancelled appointments for the same `doctor_id` from having overlapping `start_time` and `end_time` ranges.
* **Failure State**: If Patient B's transaction attempts to book while Patient A's transaction is committing, Patient B's transaction fails with a concurrency error, which the backend safely catches and returns as an HTTP 409 Conflict.

---

## 2. Temporary Slot Hold Mechanism

To provide a smooth user experience, a patient should not lose their selected slot while filling out pre-consultation forms or processing payment.

### Implementation Strategy
* **Redis / Ephemeral Storage**: When a user selects a time, the backend immediately places a "hold" on that slot in a fast, in-memory store (like Redis) with a strict TTL (Time To Live) of 10 minutes.
* **Hold Validation**: Any subsequent queries for available slots check *both* the permanent `appointments` table and the ephemeral hold cache. Held slots are marked as unavailable to other users.
* **Cleanup**: If the user completes the booking, the hold is deleted and converted into a permanent database record. If the user abandons the flow, the TTL expires automatically, silently releasing the slot back into the available pool.

---

## 3. Doctor Leave & Schedule Conflict Handling

Doctors can apply for spontaneous leave or adjust their working hours. The system must gracefully handle pre-existing appointments that conflict with newly applied leave.

### Implementation Strategy
* **Leave Overlap Detection**: When a doctor requests a leave block, the system executes a pre-flight check for any `SCHEDULED` appointments falling within that time range.
* **Automated Rescheduling Queue**: If conflicts exist, the leave is marked as "Pending Reschedule." A background worker processes the affected appointments:
  1. The appointment status is changed to `NEEDS_RESCHEDULE`.
  2. The patient receives an automated email and in-app notification explaining the doctor's emergency leave, prompting them to select a new time.
* **Calendar Sync Reconciliation**: If the leave was generated externally via a synced Google Calendar event, the webhook payload triggers the same conflict detection pipeline asynchronously.

---

## 4. Notification Failure & Retry Handling

Email and Push notifications rely on external network services (SMTP, Firebase, etc.) which can experience downtime or rate-limiting.

### Implementation Strategy
* **Outbox Pattern**: Instead of sending emails synchronously during the API request (which slows down the user experience), the API writes a record to a `notification_outbox` table.
* **Background Process (APScheduler)**: A dedicated daemon continuously polls the outbox. It attempts to dispatch the notification via SMTP.
* **Exponential Backoff**: If an external service fails (e.g., SMTP timeout), the worker increments a `retry_count` and schedules the next attempt using exponential backoff (e.g., 1 min, 5 min, 15 min). After 5 failed attempts, it marks the notification as `FAILED` and alerts the system administrator.
