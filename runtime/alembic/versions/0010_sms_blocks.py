"""sms flood guard: timed mutes and permanent blocks per tenant and number (plan F, F1)

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0010"
down_revision: Union[str, Sequence[str], None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "sms_blocks",
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["runtime.tenants.id"]),
        sa.PrimaryKeyConstraint("tenant_id", "phone"),
        schema="runtime",
    )
    op.create_index(
        "ix_sms_blocks_tenant_until", "sms_blocks", ["tenant_id", "until"], schema="runtime"
    )


def downgrade() -> None:
    op.drop_index("ix_sms_blocks_tenant_until", table_name="sms_blocks", schema="runtime")
    op.drop_table("sms_blocks", schema="runtime")
