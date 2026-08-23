from supabase import create_client, Client
from app.core.config import settings

def get_supabase_admin_client() -> Client:
    if not settings.SUPABASE_URL or not settings.SUPABASE_SECRET_KEY:
        raise ValueError("Supabase URL and Secret Key must be configured in environment variables.")
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SECRET_KEY)

# Global admin client for background jobs and system tasks
supabase_admin: Client = get_supabase_admin_client()

def get_user_supabase(token: str) -> Client:
    """
    Creates a new Supabase client for a specific user request, bound to their JWT.
    This guarantees that RLS policies are enforced on all queries made with this client.
    """
    if not settings.SUPABASE_URL or not settings.SUPABASE_PUBLISHABLE_KEY:
        raise ValueError("Supabase URL and Publishable Key must be configured in environment variables.")
    
    client = create_client(settings.SUPABASE_URL, settings.SUPABASE_PUBLISHABLE_KEY)
    # Inject the user's JWT token for the PostgREST requests
    client.postgrest.auth(token)
    return client
