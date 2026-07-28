"""add_user_id_to_notifications

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-07-28 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add required notification ownership."""
    op.add_column(
        "notifications",
        sa.Column("user_id", sa.UUID(), nullable=True),
    )

    # Existing notifications have no trustworthy owner and must not leak.
    op.execute("DELETE FROM notifications")

    op.alter_column("notifications", "user_id", nullable=False)
    op.create_foreign_key(
        "fk_notifications_user_id",
        "notifications",
        "users",
        ["user_id"],
        ["id"],
    )
    op.create_index(
        "ix_notifications_user_id_id",
        "notifications",
        ["user_id", "id"],
    )


def downgrade() -> None:
    """Remove notification ownership."""
    op.drop_index("ix_notifications_user_id_id", table_name="notifications")
    op.drop_constraint(
        "fk_notifications_user_id",
        "notifications",
        type_="foreignkey",
    )
    op.drop_column("notifications", "user_id")
