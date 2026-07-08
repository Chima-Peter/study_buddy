"""add hashed_password column to user table

Revision ID: bf8e5a1d0413
Revises: 582275237697
Create Date: 2026-07-08 18:26:53.161099

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bf8e5a1d0413'
down_revision: Union[str, Sequence[str], None] = '582275237697'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('users', sa.Column(
        'hashed_password', sa.String, nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'hashed_password')
