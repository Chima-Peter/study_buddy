"""add_comment_column_to_documents

Revision ID: f1a2b3c4d5e6
Revises: ceeb51effa96
Create Date: 2026-07-17 07:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.system.schemas.document import DOCUMENT_STATUS_COMMENTS


# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "ceeb51effa96"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "documents",
        sa.Column(
            "comment",
            sa.String(length=500),
            nullable=True,
            server_default=DOCUMENT_STATUS_COMMENTS["pending"],
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("documents", "comment")
