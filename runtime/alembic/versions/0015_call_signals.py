"""call signals: the rung-0 trouble log on conversations (model words, runtime record, §6)

Counts and a capped tail of a call's own trouble signals — repeats, re-prompts, repairs,
refused tools, barge-in-and-repeat, guard blocks, and what the turn analyser thought. Closed
labels and numbers only: `spatalk.ops.signals` refuses any value that could hold a word
somebody said, which is why retention keeps this column when it takes the transcript. It is
the only history the phase-C trouble score will have to set a threshold against, and it dies
with the conversation stub.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-11
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: Union[str, Sequence[str], None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("signals", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_column("conversations", "signals", schema="runtime")
