from fastapi import APIRouter

from app.system.chat.router import chat_router
from app.system.conversation.router import conversation_router
from app.system.document.router import document_router
from app.system.notification.router import notification_router
from app.system.study_cards.router import study_cards_router
from app.system.user.router import user_router

system_router = APIRouter()
system_router.include_router(document_router)
system_router.include_router(chat_router)
system_router.include_router(conversation_router)
system_router.include_router(notification_router)
system_router.include_router(study_cards_router)
system_router.include_router(user_router)
