"""drop_document_category_description

Revision ID: a7b8c9d0e1f2
Revises: e3f4a5b6c7d8
Create Date: 2026-10-02 14:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "e3f4a5b6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("documents", "category")
    op.drop_column("documents", "description")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "documents",
        sa.Column("description", sa.String(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "category",
            sa.String(length=255),
            nullable=False,
            server_default="uncategorized",
        ),
    )
    op.alter_column("documents", "category", server_default=None)
