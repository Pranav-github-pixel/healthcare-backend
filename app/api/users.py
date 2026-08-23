from fastapi import APIRouter, HTTPException, status, Depends, Query
from app.models.schemas import ProfileResponse, ProfileUpdateRequest, RoleEnum
from app.services.supabase_client import supabase_admin
from app.core.security import get_current_user, require_roles
from typing import List, Optional, Dict, Any

router = APIRouter(prefix="/users", tags=["Users & Profiles"])

@router.get("/specializations", response_model=List[str])
async def list_specializations():
    """
    Returns a list of distinct doctor specializations available in the system.
    Used by the booking flow to let patients filter by specialty first.
    """
    try:
        res = supabase_admin.table("profiles").select("specialization").eq("role", RoleEnum.DOCTOR.value).execute()
        doctors = res.data if res and res.data else []
        # Collect unique non-null specializations
        specs = set()
        for doc in doctors:
            spec = doc.get("specialization")
            if spec and spec.strip():
                specs.add(spec.strip())
        # Always include a "General Physician" option
        specs.add("General Physician")
        return sorted(list(specs))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch specializations: {str(e)}"
        )

@router.get("/doctors", response_model=List[ProfileResponse])
async def list_doctors(
    specialization: Optional[str] = Query(None, description="Filter doctors by specialization")
):
    """
    Search and list doctors with working hours and specializations.
    """
    try:
        query = supabase_admin.table("profiles").select("*").eq("role", RoleEnum.DOCTOR.value)
        if specialization:
            query = query.ilike("specialization", f"%{specialization}%")
            
        res = query.execute()
        doctors = res.data if res and res.data else []
        return doctors
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch doctors: {str(e)}"
        )

@router.get("/doctors/{doctor_id}", response_model=ProfileResponse)
async def get_doctor_by_id(doctor_id: str):
    """
    Get detailed profile of a specific doctor.
    """
    try:
        res = supabase_admin.table("profiles").select("*").eq("id", doctor_id).eq("role", RoleEnum.DOCTOR.value).single().execute()
        if not res or not res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Doctor not found"
            )
        return res.data
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving doctor profile: {str(e)}"
        )

@router.put("/profile", response_model=ProfileResponse)
async def update_profile(
    payload: ProfileUpdateRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Update the authenticated user's profile information.
    """
    try:
        user_client = current_user["client"]
        update_data = {k: v for k, v in payload.model_dump().items() if v is not None}
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields provided to update"
            )
            
        res = user_client.table("profiles").update(update_data).eq("id", current_user["id"]).execute()
        if not res or not res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Profile could not be updated"
            )
        return res.data[0]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Profile update failed: {str(e)}"
        )

@router.get("/profiles", response_model=List[ProfileResponse], dependencies=[Depends(require_roles([RoleEnum.ADMIN]))])
async def list_all_profiles():
    """
    Admin endpoint to view all system profiles.
    """
    try:
        res = supabase_admin.table("profiles").select("*").execute()
        return res.data if res and res.data else []
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch profiles: {str(e)}"
        )
