"""add question count

Revision ID: ce5a4b053df0
Revises: f2a3b4c5d6e7
Create Date: 2026-08-07 10:27:30.990136

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ce5a4b053df0'
down_revision: Union[str, Sequence[str], None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "question_banks", 
        sa.Column(
            "question_count", 
            sa.Integer(), 
            nullable=False,
            default=0,
            server_default="0",
        )
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("question_banks", "question_count")
