"""widen conversation summary to 1500 chars

Revision ID: a1b2c3d4e5f6
Revises: 3888caa2efde
Create Date: 2026-08-02 03:14:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "3888caa2efde"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "conversations",
        "summary",
        existing_type=sa.String(length=255),
        type_=sa.String(length=1500),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "conversations",
        "summary",
        existing_type=sa.String(length=1500),
        type_=sa.String(length=255),
        existing_nullable=True,
    )
