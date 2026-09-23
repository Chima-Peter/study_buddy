"""add message ids to chats

Revision ID: a8b9c0d1e2f3
Revises: 62ee14a36244
Create Date: 2026-09-23 00:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a8b9c0d1e2f3"
down_revision: Union[str, Sequence[str], None] = "62ee14a36244"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "chats",
        sa.Column("query_message_id", sa.String(), nullable=True),
    )
    op.add_column(
        "chats",
        sa.Column("response_message_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("chats", "response_message_id")
    op.drop_column("chats", "query_message_id")
