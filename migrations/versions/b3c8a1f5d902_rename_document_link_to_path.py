"""rename_document_link_to_path

Revision ID: b3c8a1f5d902
Revises: a7723efde602
Create Date: 2026-07-15 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b3c8a1f5d902"
down_revision: Union[str, Sequence[str], None] = "a7723efde602"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("documents", "link", new_column_name="path")


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column("documents", "path", new_column_name="link")
