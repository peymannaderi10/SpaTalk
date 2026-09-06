"""slack integration: the channel and the encrypted incoming webhook on tenant_integrations
(onboarding roadmap, section 3: Slack one-click connect)

A clinic installs the Front Desk app in its own workspace from the portal. The install answers
a bot token (stored in access_token_enc like a Meta token), the channel the workspace chose
and that channel's incoming-webhook URL. Anyone holding the URL can post to the channel, so it
is Fernet ciphertext too. Both columns are nullable: a Meta row has neither.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-06
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0014"
down_revision: Union[str, Sequence[str], None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenant_integrations",
        sa.Column("channel_id", sa.String(length=32), nullable=True),
        schema="runtime",
    )
    op.add_column(
        "tenant_integrations",
        sa.Column("webhook_url_enc", sa.Text(), nullable=True),
        schema="runtime",
    )


def downgrade() -> None:
    op.drop_column("tenant_integrations", "webhook_url_enc", schema="runtime")
    op.drop_column("tenant_integrations", "channel_id", schema="runtime")
