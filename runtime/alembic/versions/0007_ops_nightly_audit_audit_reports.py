"""ops nightly audit: audit reports

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-02 17:51:32.619109

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # One night's audit per tenant. Unique on (day, tenant_id) so a re-run of the same
    # night replaces its verdict instead of accumulating a second opinion; `day` is the
    # tenant's own local day (operations plan, Task E4).
    op.create_table('audit_reports',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('report', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('day', 'tenant_id'),
    schema='runtime'
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('audit_reports', schema='runtime')
