"""whatsapp windows

Revision ID: 0008_whatsapp
Revises: 0007
Create Date: 2026-09-02 18:22:07.420062

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0008_whatsapp'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # The 24-hour customer-service window anchor, one row per (tenant, staff number):
    # delivery reads it to choose between free-form buttons and an approved template
    # (whatsapp plan, Task W1).
    op.create_table('whatsapp_windows',
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('phone', sa.String(length=32), nullable=False),
    sa.Column('last_inbound_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('tenant_id', 'phone'),
    schema='runtime'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('whatsapp_windows', schema='runtime')
