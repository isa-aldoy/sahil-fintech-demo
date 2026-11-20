"""payment requests

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("requester_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("amount_fils", sa.BigInteger(), nullable=False),
        sa.Column("note", sa.String(140), nullable=False),
        sa.Column("status", sa.String(10), server_default="pending", nullable=False),
        sa.Column("transfer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("transfers.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("amount_fils > 0", name="ck_requests_positive"),
        sa.CheckConstraint("requester_id <> payer_id", name="ck_requests_distinct"),
        sa.CheckConstraint("status IN ('pending','paid','declined','cancelled')", name="ck_requests_status"),
    )
    op.create_index("ix_payment_requests_requester_id", "payment_requests", ["requester_id"])
    op.create_index("ix_payment_requests_payer_id", "payment_requests", ["payer_id"])
    # A paid request must point at its transfer, and only a paid request may.
    op.create_check_constraint(
        "ck_requests_paid_has_transfer", "payment_requests", "(status = 'paid') = (transfer_id IS NOT NULL)")


def downgrade() -> None:
    op.drop_table("payment_requests")
