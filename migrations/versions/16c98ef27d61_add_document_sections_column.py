"""add_document_sections_column

Revision ID: 16c98ef27d61
Revises: 5a08578fa065
Create Date: 2026-08-04 16:18:49.507013

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '16c98ef27d61'
down_revision: Union[str, Sequence[str], None] = '5a08578fa065'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
