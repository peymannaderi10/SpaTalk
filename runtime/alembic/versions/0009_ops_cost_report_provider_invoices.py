"""ops cost report: provider invoices

Revision ID: 0009
Revises: 0008_whatsapp
Create Date: 2026-09-02 20:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008_whatsapp'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # What a provider actually billed for one UTC calendar month, in Canadian dollars.
    # Unique on (provider, month) so a corrected invoice replaces the figure rather than
    # adding a second one to the same month (operations plan, Task E9).
    op.create_table('provider_invoices',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('provider', sa.String(length=40), nullable=False),
    sa.Column('month', sa.String(length=7), nullable=False),
    sa.Column('amount_cad', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('entered_at', sa.DateTime(timezone=True), server_default=sa.text('now()'),
              nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider', 'month'),
    schema='runtime'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('provider_invoices', schema='runtime')
