"""ops retention: run records, deletion receipts, conversation stage timings

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-02 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('ops_runs',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('kind', sa.String(length=64), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('ok', sa.Boolean(), nullable=False),
    sa.Column('summary', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='runtime'
    )
    op.create_table('deletion_receipts',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('tenant_id', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.Column('cutoff', sa.DateTime(timezone=True), nullable=False),
    sa.Column('run_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='runtime'
    )
    # Per-stage p95 for a call. Task E5 fills it; retention (E3) nulls it with latency_ms
    # when the transcript goes, so the column has to exist before that job first runs.
    op.add_column('conversations', sa.Column('stage_ms', postgresql.JSONB(astext_type=sa.Text()), nullable=True), schema='runtime')


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('conversations', 'stage_ms', schema='runtime')
    op.drop_table('deletion_receipts', schema='runtime')
    op.drop_table('ops_runs', schema='runtime')
