"""add_status_column

Revision ID: ceeb51effa96
Revises: b3c8a1f5d902
Create Date: 2026-07-15 12:32:55.876320

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ceeb51effa96'
down_revision: Union[str, Sequence[str], None] = 'b3c8a1f5d902'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # values: pending, processing, completed, failed, cancelled
    op.add_column('documents', sa.Column('status', sa.String(
        length=255), nullable=True, default='pending'))
    op.create_index(op.f('ix_documents_status'), 'documents', ['status'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('documents', 'status')
    op.drop_index(op.f('ix_documents_status'), 'documents')
