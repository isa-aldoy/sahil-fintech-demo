"""database-level integrity guards

These rules hold even if application code has a bug:
  * audit_log and ledger_entries are append-only (UPDATE/DELETE/TRUNCATE rejected)
  * every transfer's ledger entries must sum to zero at commit time

Revision ID: 0002
Revises: 0001
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION sahil_reject_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only', TG_TABLE_NAME USING ERRCODE = 'integrity_constraint_violation';
        END $$;
    """)
    for table in ("audit_log", "ledger_entries"):
        op.execute(f"""
            CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION sahil_reject_change();
        """)
        op.execute(f"""
            CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION sahil_reject_change();
        """)
    op.execute("""
        CREATE FUNCTION sahil_ledger_balanced() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE total bigint;
        BEGIN
            SELECT COALESCE(SUM(amount_fils), 0) INTO total FROM ledger_entries WHERE transfer_id = NEW.transfer_id;
            IF total <> 0 THEN
                RAISE EXCEPTION 'ledger entries for transfer % do not balance (sum = %)', NEW.transfer_id, total
                    USING ERRCODE = 'integrity_constraint_violation';
            END IF;
            RETURN NULL;
        END $$;
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER ledger_entries_balanced AFTER INSERT ON ledger_entries
        DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION sahil_ledger_balanced();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS ledger_entries_balanced ON ledger_entries")
    for table in ("audit_log", "ledger_entries"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_truncate ON {table}")
    op.execute("DROP FUNCTION IF EXISTS sahil_ledger_balanced()")
    op.execute("DROP FUNCTION IF EXISTS sahil_reject_change()")
