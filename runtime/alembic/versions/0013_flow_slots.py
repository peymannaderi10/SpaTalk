"""flow: the slot engine's record on conversations (slot engine design, §6.3)

What the runtime knows about the open request: which flow, which slots are filled, which
confirmation is pending. Written after every turn on every channel so a dropped call or a
text thread resumed within its window picks up at the open step. Nullable: most
conversations never open a request. Nothing here is free text; the values are the closed
ones the item will carry. Nulled with the transcript by the retention job.

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("flow", postgresql.JSONB(), nullable=True),
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_column("conversations", "flow", schema="runtime")
