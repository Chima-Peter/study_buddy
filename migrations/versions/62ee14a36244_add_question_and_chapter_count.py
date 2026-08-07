"""add question and chapter count to study_cards

Revision ID: 62ee14a36244
Revises: ce5a4b053df0
Create Date: 2026-08-07 10:27:56.739784

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "62ee14a36244"
down_revision: Union[str, Sequence[str], None] = "ce5a4b053df0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add count columns to study_cards (question_banks.question_count already exists)."""
    op.add_column(
        "study_cards",
        sa.Column(
            "question_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "study_cards",
        sa.Column(
            "chapter_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("study_cards", "chapter_count")
    op.drop_column("study_cards", "question_count")
