from fastapi import APIRouter

from app.authentication.routers.auth_router import auth_router
from app.authentication.routers.user_router import user_router

authentication_router = APIRouter()
authentication_router.include_router(auth_router)
authentication_router.include_router(user_router)
