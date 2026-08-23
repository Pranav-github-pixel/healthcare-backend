from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.auth import router as auth_router
from app.api.users import router as users_router
from app.api.appointments import router as appointments_router
from app.api.admin import router as admin_router
from app.api.calendar_auth import router as calendar_auth_router
from app.api.notifications import router as notifications_router
from app.services.scheduler import start_scheduler, shutdown_scheduler

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start APScheduler
    start_scheduler()
    yield
    # Shutdown: Gracefully stop APScheduler
    shutdown_scheduler()

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Backend API for Healthcare Appointment & Follow-up Manager",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(users_router, prefix=settings.API_V1_STR)
app.include_router(appointments_router, prefix=settings.API_V1_STR)
app.include_router(admin_router, prefix=settings.API_V1_STR)
app.include_router(calendar_auth_router, prefix=settings.API_V1_STR)
app.include_router(notifications_router, prefix=settings.API_V1_STR)

@app.get("/", tags=["Health"])
async def root():
    return {
        "status": "healthy",
        "message": f"Welcome to {settings.PROJECT_NAME} API",
        "docs": "/docs"
    }

@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok"}
