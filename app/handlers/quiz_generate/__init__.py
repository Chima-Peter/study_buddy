from app.handlers.quiz_generate.consumer import handle_quiz_generate
from app.handlers.quiz_generate.dlq import handle_quiz_generate_dead_letter_queue

__all__ = ["handle_quiz_generate", "handle_quiz_generate_dead_letter_queue"]
