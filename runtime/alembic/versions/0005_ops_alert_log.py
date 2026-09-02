"""ops alert log

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-02 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('alert_log',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('key', sa.String(length=200), nullable=False),
    sa.Column('subject', sa.String(length=400), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='runtime'
    )
    op.create_index('ix_alert_key_sent', 'alert_log', ['key', 'sent_at'], unique=False, schema='runtime')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_alert_key_sent', table_name='alert_log', schema='runtime')
    op.drop_table('alert_log', schema='runtime')
