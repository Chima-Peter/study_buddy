"""remove_name_unique_constraint

Revision ID: 8c74bf32cd19
Revises: 16c98ef27d61
Create Date: 2026-08-04 19:09:23.880504

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8c74bf32cd19'
down_revision: Union[str, Sequence[str], None] = '16c98ef27d61'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint('uq_documents_name', 'documents')


def downgrade() -> None:
    """Downgrade schema."""
    op.create_unique_constraint('uq_documents_name', 'documents', ['name'])
