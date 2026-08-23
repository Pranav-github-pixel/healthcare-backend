import logging
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException

from app.core.security import get_current_user
from app.services.supabase_client import supabase_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["Notifications"])

def create_notification(user_id: str, type: str, message: str):
    """Helper function to insert a notification for a user."""
    try:
        supabase_admin.table("notifications").insert({
            "user_id": user_id,
            "type": type,
            "message": message
        }).execute()
    except Exception as e:
        logger.error(f"Failed to create notification: {e}")

@router.get("/", response_model=List[Dict[str, Any]])
async def get_my_notifications(
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Get all notifications for the logged-in user, ordered by newest."""
    try:
        res = supabase_admin.table("notifications").select("*")\
            .eq("user_id", current_user["id"])\
            .order("created_at", desc=True)\
            .limit(50)\
            .execute()
        return res.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """Marks a specific notification as read."""
    try:
        res = supabase_admin.table("notifications").update({
            "is_read": True
        }).eq("id", notification_id).eq("user_id", current_user["id"]).execute()
        
        if not res.data:
            raise HTTPException(status_code=404, detail="Notification not found")
        
        return {"status": "success", "message": "Notification marked as read"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
