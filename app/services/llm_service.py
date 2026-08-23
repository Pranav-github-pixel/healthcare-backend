import json
import re
import logging
from typing import Dict, Any, List
from app.core.config import settings

logger = logging.getLogger(__name__)

# Initialize Gemini if key is provided
try:
    from google import genai
    from google.genai import types
    if settings.GEMINI_API_KEY:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    else:
        _client = None
except Exception as e:
    logger.warning(f"Failed to initialize Google GenAI: {e}")
    _client = None

def _clean_and_parse_json(raw_text: str) -> Dict[str, Any]:
    """
    Extract and parse JSON from LLM output, handling markdown fences and extraneous text.
    """
    try:
        return json.loads(raw_text)
    except Exception:
        # Match ```json ... ``` or first { ... } block
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_text)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except Exception:
                pass
        
        # Match outermost curly braces
        match_braces = re.search(r"\{[\s\S]*\}", raw_text)
        if match_braces:
            try:
                return json.loads(match_braces.group(0).strip())
            except Exception:
                pass
        
        raise ValueError(f"Could not parse valid JSON from text: {raw_text[:200]}")

async def generate_pre_visit_summary(symptoms_raw: str) -> Dict[str, Any]:
    """
    Analyzes patient symptoms and returns urgency level, chief complaint, and suggested questions.
    """
    prompt = f"""
You are an expert clinical AI assistant.
Analyze these patient symptoms and return a strictly valid JSON object matching this exact schema:
{{
  "urgency_level": "Low" | "Medium" | "High",
  "chief_complaint": "Clear, concise summary of the primary concern",
  "suggested_questions": [
    "Question 1 for the doctor to ask",
    "Question 2 for the doctor to ask",
    "Question 3 for the doctor to ask"
  ]
}}

Patient Symptoms:
{symptoms_raw}

Return only the raw JSON object without markdown formatting or additional explanation.
"""

    if not _client or not settings.GEMINI_API_KEY:
        logger.warning("Gemini API key not configured or model unavailable. Using fallback response.")
        return {
            "urgency_level": "Medium",
            "chief_complaint": symptoms_raw[:120] if symptoms_raw else "Not specified",
            "suggested_questions": [
                "When did these symptoms first begin?",
                "Are you experiencing any other related symptoms?",
                "Have you taken any medications or treatments for this?"
            ]
        }

    try:
        response = _client.models.generate_content(
            model='gemini-3.6-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        )
        return _clean_and_parse_json(response.text)
    except Exception as e:
        logger.error(f"Gemini API error in pre-visit summary: {e}")
        # Graceful fallback so appointment flow never breaks
        return {
            "urgency_level": "Medium",
            "chief_complaint": symptoms_raw[:120] if symptoms_raw else "Reported symptoms",
            "suggested_questions": [
                "How long have you had these symptoms?",
                "Does anything worsen or improve the symptoms?",
                "Do you have any known allergies or current medications?"
            ],
            "_fallback_note": f"Auto-generated fallback due to LLM timeout: {str(e)}"
        }

async def generate_post_visit_summary(doctor_notes_raw: str) -> Dict[str, Any]:
    """
    Converts doctor clinical notes into a patient-friendly summary, follow-up steps, and medication schedules.
    """
    prompt = f"""
You are an expert medical AI assistant.
Convert these clinical notes into a patient-friendly summary with medication schedule and follow-up steps.
Return a strictly valid JSON object with this exact schema:
{{
  "summary": "Clear, compassionate, patient-friendly summary explaining the diagnosis and treatment plan",
  "follow_up_steps": [
    "Follow-up step or lifestyle advice 1",
    "Follow-up step 2"
  ],
  "medications": [
    {{
      "name": "Medication name and dosage (e.g., Amoxicillin 500mg)",
      "times_per_day": 3,
      "duration_days": 7,
      "instructions": "Take after meals"
    }}
  ]
}}

Clinical Notes:
{doctor_notes_raw}

Return only the raw JSON object without markdown formatting or extra text.
"""

    if not _client or not settings.GEMINI_API_KEY:
        logger.warning("Gemini API key not configured or model unavailable. Using fallback post-visit response.")
        return {
            "summary": f"Visit completed. Doctor's notes: {doctor_notes_raw}",
            "follow_up_steps": [
                "Follow doctor's verbal instructions",
                "Contact clinic if symptoms worsen"
            ],
            "medications": []
        }

    try:
        response = _client.models.generate_content(
            model='gemini-3.6-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        )
        return _clean_and_parse_json(response.text)
    except Exception as e:
        logger.error(f"Gemini API error in post-visit summary: {e}")
        return {
            "summary": f"Summary based on notes: {doctor_notes_raw}",
            "follow_up_steps": ["Rest and stay hydrated", "Follow up with your doctor if symptoms persist"],
            "medications": [],
            "_fallback_note": f"Auto-generated fallback due to LLM timeout: {str(e)}"
        }
