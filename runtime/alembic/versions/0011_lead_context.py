"""lead context: returning_client, practitioner and concern on items (plan L, L1)

Three closed columns, no free text: `returning_client` is a boolean, `practitioner` holds a
`team[].name` or "any", `concern` holds one of the tenant's `concerns`. All nullable,
because "not asked" and "did not say" are ordinary outcomes of a short call.

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0011"
down_revision: Union[str, Sequence[str], None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "items",
        sa.Column("returning_client", sa.Boolean(), nullable=True),
        schema="runtime",
    )
    op.add_column(
        "items",
        sa.Column("practitioner", sa.String(length=80), nullable=True),
        schema="runtime",
    )
    op.add_column(
        "items",
        sa.Column("concern", sa.String(length=40), nullable=True),
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_column("items", "concern", schema="runtime")
    op.drop_column("items", "practitioner", schema="runtime")
    op.drop_column("items", "returning_client", schema="runtime")
