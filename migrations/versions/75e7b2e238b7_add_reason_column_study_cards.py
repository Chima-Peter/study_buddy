"""add_reason_column_study_cards

Revision ID: 75e7b2e238b7
Revises: 96ddb45a443a
Create Date: 2026-08-07 05:46:36.640739

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '75e7b2e238b7'
down_revision: Union[str, Sequence[str], None] = '96ddb45a443a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('study_cards', sa.Column('reason', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('study_cards', 'reason')
