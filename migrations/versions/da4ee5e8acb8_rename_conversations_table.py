"""rename_conversations_table

Revision ID: da4ee5e8acb8
Revises: e6f7a8b9c0d1
Create Date: 2026-07-28 10:52:13.614369

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'da4ee5e8acb8'
down_revision: Union[str, Sequence[str], None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.rename_table('conversations', 'chats')
    op.alter_column('chats', 'conversation', new_column_name='chat')
    op.execute('ALTER INDEX ix_conversations_user_id RENAME TO ix_chats_user_id')
    op.execute(
        'ALTER INDEX idx_conversations_created_at RENAME TO idx_chats_created_at'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(
        'ALTER INDEX idx_chats_created_at RENAME TO idx_conversations_created_at'
    )
    op.execute('ALTER INDEX ix_chats_user_id RENAME TO ix_conversations_user_id')
    op.alter_column('chats', 'chat', new_column_name='conversation')
    op.rename_table('chats', 'conversations')
