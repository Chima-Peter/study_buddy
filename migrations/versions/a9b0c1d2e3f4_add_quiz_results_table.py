"""add_quiz_results_table

Revision ID: a9b0c1d2e3f4
Revises: 8c74bf32cd19
Create Date: 2026-08-05 20:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a9b0c1d2e3f4"
down_revision: Union[str, Sequence[str], None] = "8c74bf32cd19"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "quiz_results",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
    )
    op.create_index(
        "idx_quiz_results_user_id",
        "quiz_results",
        ["user_id"],
    )
    op.create_index(
        "idx_quiz_results_document_id",
        "quiz_results",
        ["document_id"],
    )
    op.create_index(
        "idx_quiz_results_user_document",
        "quiz_results",
        ["user_id", "document_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_quiz_results_user_document", "quiz_results")
    op.drop_index("idx_quiz_results_document_id", "quiz_results")
    op.drop_index("idx_quiz_results_user_id", "quiz_results")
    op.drop_table("quiz_results")
