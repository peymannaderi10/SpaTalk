"""call notes: notes, notes_model and notes_at on conversations (call-notes plan, N1)

A few sentences drafted from the conversation's own transcript, for the person who picks up
the request card. They are stored on the conversation, never on an item: `items` gains no
column here and never will (CLAUDE.md non-negotiable 2). All three are nullable, because a
conversation with nothing worth saying is the ordinary case, and the nightly retention job
nulls all three when it deletes the transcript they were drafted from.

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("notes", sa.Text(), nullable=True),
        schema="runtime",
    )
    op.add_column(
        "conversations",
        sa.Column("notes_model", sa.String(length=80), nullable=True),
        schema="runtime",
    )
    op.add_column(
        "conversations",
        sa.Column("notes_at", sa.DateTime(timezone=True), nullable=True),
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_column("conversations", "notes_at", schema="runtime")
    op.drop_column("conversations", "notes_model", schema="runtime")
    op.drop_column("conversations", "notes", schema="runtime")
