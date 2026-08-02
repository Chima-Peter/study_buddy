"""add user profile columns

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-08-02 03:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("gender", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("university", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("bio", sa.String(length=1500), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("timezone", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "timezone")
    op.drop_column("users", "bio")
    op.drop_column("users", "university")
    op.drop_column("users", "gender")
