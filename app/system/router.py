from fastapi import APIRouter

from app.system.routers.chat_router import chat_router
from app.system.routers.document_router import document_router
from app.system.routers.notification_router import notification_router

system_router = APIRouter(prefix="/system", tags=["system"])
system_router.include_router(document_router)
system_router.include_router(chat_router)
system_router.include_router(notification_router)
