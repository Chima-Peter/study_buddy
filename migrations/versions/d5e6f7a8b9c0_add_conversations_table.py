"""add_conversations_table

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-07-27 15:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "conversations",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("query", sa.String(), nullable=False),
        sa.Column("conversation", sa.String(), nullable=False),
        sa.Column(
            "audit",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )
    op.create_index(
        "ix_conversations_user_id",
        "conversations",
        ["user_id"],
    )
    op.create_index(
        "idx_conversations_created_at",
        "conversations",
        ["created_at"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_conversations_created_at", table_name="conversations")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_table("conversations")
