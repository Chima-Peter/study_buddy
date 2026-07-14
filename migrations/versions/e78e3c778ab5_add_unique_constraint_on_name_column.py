"""add_unique_constraint_on_name_column

Revision ID: e78e3c778ab5
Revises: 71839933b3f1
Create Date: 2026-07-14 14:00:40.059954

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e78e3c778ab5'
down_revision: Union[str, Sequence[str], None] = '71839933b3f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint('uq_documents_name', 'documents', ['name'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_documents_name', 'documents')
