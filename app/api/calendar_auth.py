import os
import json
import logging
from typing import Dict, Any, Optional
import requests

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import RedirectResponse

from app.core.config import settings
from app.core.security import get_current_user
from app.services.supabase_client import supabase_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendar", tags=["Calendar OAuth"])

CLIENT_SECRETS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'client_secret.json')
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173")
REDIRECT_URI = "http://localhost:8000/api/v1/calendar/callback"

def get_client_config():
    if not os.path.exists(CLIENT_SECRETS_FILE):
        raise HTTPException(status_code=500, detail="client_secret.json not found.")
    with open(CLIENT_SECRETS_FILE, 'r') as f:
        data = json.load(f)
    return data.get("web") or data.get("installed")

@router.get("/auth")
async def calendar_auth(
    token: Optional[str] = Query(None, description="Bearer token passed via query for browser redirects"),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    try:
        config = get_client_config()
        client_id = config["client_id"]
        auth_uri = config["auth_uri"]
        
        # Build URL manually to prevent automatic PKCE code_challenge which causes missing verifier errors
        authorization_url = (
            f"{auth_uri}?"
            f"response_type=code&"
            f"client_id={client_id}&"
            f"redirect_uri={REDIRECT_URI}&"
            f"scope=https://www.googleapis.com/auth/calendar&"
            f"access_type=offline&"
            f"prompt=consent&"
            f"state={current_user['id']}"
        )
        return RedirectResponse(url=authorization_url)
    except Exception as e:
        logger.error(f"Error initializing OAuth flow: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/callback")
async def calendar_callback(
    state: str = Query(...), 
    code: str = Query(...)
):
    try:
        config = get_client_config()
        
        # Exchange code for token manually
        resp = requests.post(config["token_uri"], data={
            "code": code,
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code"
        })
        
        token_data = resp.json()
        if "error" in token_data:
            raise Exception(f"Google Token Error: {token_data}")
            
        creds_data = {
            'token': token_data.get('access_token'),
            'refresh_token': token_data.get('refresh_token'),
            'token_uri': config["token_uri"],
            'client_id': config["client_id"],
            'client_secret': config["client_secret"],
            'scopes': token_data.get('scope', '').split(' ') if token_data.get('scope') else []
        }

        user_id = state
        update_res = supabase_admin.table("profiles").update({
            "google_credentials": creds_data
        }).eq("id", user_id).execute()
        
        if not update_res or not update_res.data:
            logger.error(f"Failed to save Google credentials for user {user_id}")
            return RedirectResponse(url=f"{FRONTEND_URL}/patient?calendar=error")
        
        profile = update_res.data[0]
        role = profile.get("role", "PATIENT")
        redirect_path = "/doctor" if role == "DOCTOR" else "/admin" if role == "ADMIN" else "/patient"
        
        return RedirectResponse(url=f"{FRONTEND_URL}{redirect_path}?calendar=connected")
    except Exception as e:
        logger.error(f"Error in OAuth callback: {e}")
        return RedirectResponse(url=f"{FRONTEND_URL}/patient?calendar=error&detail={str(e)[:100]}")
