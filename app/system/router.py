from fastapi import APIRouter

from app.system.chat.router import chat_router
from app.system.conversation.router import conversation_router
from app.system.document.router import document_router
from app.system.notification.router import notification_router
from app.system.quiz.router import quiz_router

system_router = APIRouter()
system_router.include_router(document_router)
system_router.include_router(chat_router)
system_router.include_router(conversation_router)
system_router.include_router(notification_router)
system_router.include_router(quiz_router)
