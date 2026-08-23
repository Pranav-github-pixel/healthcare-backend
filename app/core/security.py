from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.services.supabase_client import supabase_admin, get_user_supabase
from app.models.schemas import RoleEnum
from typing import List, Dict, Any

security = HTTPBearer(auto_error=False)

async def get_current_user(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)) -> Dict[str, Any]:
    token = credentials.credentials if credentials else request.query_params.get("token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Missing Bearer token in headers or query.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        # Verify token with Supabase Auth using admin client (bypasses RLS)
        user_response = supabase_admin.auth.get_user(token)
        if not user_response or not user_response.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid, missing, or expired authentication token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user = user_response.user
        
        # Instantiate a user-specific client for this request
        user_client = get_user_supabase(token)
        
        # Fetch role and profile from public.profiles table (RLS applied on client, but we use admin here to be safe)
        profile_res = supabase_admin.table("profiles").select("*").eq("id", user.id).single().execute()
        profile = profile_res.data if profile_res and profile_res.data else {}
        
        return {
            "id": user.id,
            "email": user.email,
            "role": profile.get("role", RoleEnum.PATIENT.value),
            "profile": profile,
            "client": user_client
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Authentication failed: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

def require_roles(allowed_roles: List[RoleEnum]):
    """
    Dependency factory to check if the authenticated user has one of the allowed roles.
    """
    async def role_checker(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        user_role = current_user.get("role")
        if user_role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: requires one of roles {[r.value for r in allowed_roles]}"
            )
        return current_user
    return role_checker
