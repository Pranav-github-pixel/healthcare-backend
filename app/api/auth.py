from fastapi import APIRouter, HTTPException, status, Depends
from app.models.schemas import RegisterRequest, LoginRequest, TokenResponse, AuthUserResponse, RoleEnum
from app.services.supabase_client import supabase_admin
from app.core.security import get_current_user
from typing import Dict, Any

router = APIRouter(prefix="/auth", tags=["Authentication"])

@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest):
    """
    Register a new user in Supabase Auth and create a profile record in the database.
    """
    try:
        # 1. Sign up user via Supabase Auth
        auth_res = supabase_admin.auth.sign_up({
            "email": payload.email,
            "password": payload.password,
            "options": {
                "data": {
                    "full_name": payload.full_name,
                    "role": payload.role.value
                }
            }
        })
        
        if not auth_res.user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User registration failed. Please check credentials or email confirmation settings."
            )
            
        user = auth_res.user
        
        # 2. Insert user profile into public.profiles
        profile_data = {
            "id": user.id,
            "role": payload.role.value,
            "full_name": payload.full_name,
            "specialization": payload.specialization if payload.role == RoleEnum.DOCTOR else None,
            "working_hours": payload.working_hours if payload.role == RoleEnum.DOCTOR else None,
            "slot_duration_minutes": payload.slot_duration_minutes if payload.role == RoleEnum.DOCTOR else 30
        }
        
        # Upsert profile in case trigger or prior record exists
        supabase_admin.table("profiles").upsert(profile_data).execute()
        
        # 3. Formulate token response
        access_token = auth_res.session.access_token if auth_res.session else ""
        
        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            user=AuthUserResponse(
                id=user.id,
                email=user.email or payload.email,
                role=payload.role,
                full_name=payload.full_name,
                specialization=profile_data.get("specialization"),
                working_hours=profile_data.get("working_hours"),
                slot_duration_minutes=profile_data.get("slot_duration_minutes")
            )
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Registration error: {str(e)}"
        )

@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest):
    """
    Authenticate an existing user with email and password via Supabase Auth.
    """
    try:
        auth_res = supabase_admin.auth.sign_in_with_password({
            "email": payload.email,
            "password": payload.password
        })
        
        if not auth_res.session or not auth_res.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
            
        user = auth_res.user
        
        # Retrieve user profile from DB
        profile_res = supabase_admin.table("profiles").select("*").eq("id", user.id).single().execute()
        profile = profile_res.data if profile_res and profile_res.data else {}
        
        user_role = profile.get("role", RoleEnum.PATIENT)
        
        return TokenResponse(
            access_token=auth_res.session.access_token,
            token_type="bearer",
            user=AuthUserResponse(
                id=user.id,
                email=user.email or payload.email,
                role=RoleEnum(user_role) if user_role in RoleEnum._value2member_map_ else RoleEnum.PATIENT,
                full_name=profile.get("full_name", user.email or ""),
                specialization=profile.get("specialization"),
                working_hours=profile.get("working_hours"),
                slot_duration_minutes=profile.get("slot_duration_minutes", 30)
            )
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Login failed: {str(e)}"
        )

@router.get("/me", response_model=AuthUserResponse)
async def get_me(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Get profile information of the currently authenticated user.
    """
    profile = current_user.get("profile", {})
    user_role = profile.get("role", current_user.get("role", RoleEnum.PATIENT))
    
    return AuthUserResponse(
        id=current_user["id"],
        email=current_user["email"],
        role=RoleEnum(user_role) if user_role in RoleEnum._value2member_map_ else RoleEnum.PATIENT,
        full_name=profile.get("full_name", current_user["email"]),
        specialization=profile.get("specialization"),
        working_hours=profile.get("working_hours"),
        slot_duration_minutes=profile.get("slot_duration_minutes", 30)
    )
