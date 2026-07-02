"""add transport to slot_field enum

Revision ID: 5e088f3a880e
Revises: 830386014486
Create Date: 2026-07-02 13:35:56.498939

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5e088f3a880e'
down_revision = '830386014486'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Alembic's autogenerate does not diff PostgreSQL native ENUM labels,
    # so this value must be added manually.
    op.execute("ALTER TYPE slot_field ADD VALUE IF NOT EXISTS 'transport'")


def downgrade() -> None:
    # PostgreSQL has no DROP VALUE for enums; removing 'transport' requires
    # recreating the type and is not safely automatable here.
    raise RuntimeError(
        "Cannot automatically downgrade: PostgreSQL does not support "
        "removing a value from an existing ENUM type. Recreate 'slot_field' "
        "manually without 'transport' if this must be reverted."
    )
