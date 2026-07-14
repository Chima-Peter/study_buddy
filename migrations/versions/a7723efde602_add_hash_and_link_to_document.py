"""add_hash_and_link_to_document

Revision ID: a7723efde602
Revises: e78e3c778ab5
Create Date: 2026-07-14 16:24:00.017773

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7723efde602'
down_revision: Union[str, Sequence[str], None] = 'e78e3c778ab5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('documents', sa.Column('hash', sa.String(length=255), nullable=True))
    op.add_column('documents', sa.Column('link', sa.String(length=255), nullable=True))

    op.create_unique_constraint('uq_documents_hash_user_id', 'documents', ['hash', 'user_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_documents_hash_user_id', 'documents')
    op.drop_column('documents', 'hash')
    op.drop_column('documents', 'link')
