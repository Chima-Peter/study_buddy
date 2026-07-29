"""add summary to conversations

Revision ID: 3888caa2efde
Revises: e3c6851f369b
Create Date: 2026-07-29 23:13:35.704447

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3888caa2efde'
down_revision: Union[str, Sequence[str], None] = 'e3c6851f369b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "conversations",
        sa.Column("summary", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("conversations", "summary")
