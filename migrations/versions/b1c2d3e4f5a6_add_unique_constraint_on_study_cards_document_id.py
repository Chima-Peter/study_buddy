"""add_unique_constraint_on_study_cards_document_id

Revision ID: b1c2d3e4f5a6
Revises: a9b0c1d2e3f4
Create Date: 2026-08-06 01:40:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "a9b0c1d2e3f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("idx_study_cards_document_id", table_name="study_cards")
    op.create_unique_constraint(
        "uq_study_cards_document_id",
        "study_cards",
        ["document_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_study_cards_document_id", "study_cards", type_="unique")
    op.create_index(
        "idx_study_cards_document_id",
        "study_cards",
        ["document_id"],
    )
