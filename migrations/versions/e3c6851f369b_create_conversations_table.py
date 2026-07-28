"""create_conversations_table

Revision ID: e3c6851f369b
Revises: da4ee5e8acb8
Create Date: 2026-07-28 10:57:19.286441

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'e3c6851f369b'
down_revision: Union[str, Sequence[str], None] = 'da4ee5e8acb8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'conversations',
        sa.Column('id', sa.UUID(), primary_key=True),
        sa.Column('title', sa.String(255), nullable=True),
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column(
            'created_at',
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
    )
    op.create_index(
        'ix_conversations_user_id',
        'conversations',
        ['user_id'],
    )
    op.add_column(
        'chats',
        sa.Column('conversation_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'chats_conversation_id_fkey',
        'chats',
        'conversations',
        ['conversation_id'],
        ['id'],
    )
    op.execute(
        """
        INSERT INTO conversations (id, user_id, created_at)
        SELECT id, user_id, created_at FROM chats
        """
    )
    op.execute('UPDATE chats SET conversation_id = id')
    op.alter_column('chats', 'conversation_id', nullable=False)
    op.create_index(
        'ix_chats_conversation_id',
        'chats',
        ['conversation_id'],
    )
    op.drop_column('chats', 'user_id')


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        'chats',
        sa.Column('user_id', sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        'chats_user_id_fkey',
        'chats',
        'users',
        ['user_id'],
        ['id'],
    )
    op.execute(
        """
        UPDATE chats
        SET user_id = conversations.user_id
        FROM conversations
        WHERE chats.conversation_id = conversations.id
        """
    )
    op.alter_column('chats', 'user_id', nullable=False)
    op.create_index('ix_chats_user_id', 'chats', ['user_id'])
    op.drop_index('ix_chats_conversation_id', table_name='chats')
    op.drop_constraint(
        'chats_conversation_id_fkey',
        'chats',
        type_='foreignkey',
    )
    op.drop_column('chats', 'conversation_id')
    op.drop_index('ix_conversations_user_id', table_name='conversations')
    op.drop_table('conversations')
