"""add status column

Revision ID: 96ddb45a443a
Revises: c2d3e4f5a6b7
Create Date: 2026-08-06 03:04:30.509891

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '96ddb45a443a'
down_revision: Union[str, Sequence[str], None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'conversations',
        sa.Column(
            'status',
            sa.String(length=255),
            nullable=False,
            server_default='active',
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('conversations', 'status')
