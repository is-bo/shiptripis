from django.db import migrations


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
    CREATE TRIGGER payout_history_immutable BEFORE UPDATE OR DELETE
      ON finance_manual_payout_receipt FOR EACH ROW EXECUTE FUNCTION finance_payout_immutable();
    CREATE FUNCTION finance_manual_receipt_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_TABLE_NAME = 'finance_manual_payout_receipt' THEN
        IF NOT EXISTS (SELECT 1 FROM finance_payout_attempt a JOIN finance_payout_evidence e
          ON e.id=NEW.evidence_id WHERE a.id=NEW.attempt_id AND a.rail='manual'
          AND a.status IN ('dispatch_committed','sent') AND a.committed_at IS NOT NULL
          AND a.operator_id=NEW.operator_id AND e.owner_id=NEW.operator_id
          AND e.purpose='transfer_receipt' AND e.upload_state='complete'
          AND e.digest<>'' AND e.object_key<>'')
          THEN RAISE EXCEPTION 'Manual receipt contract mismatch'; END IF;
      ELSIF TG_TABLE_NAME = 'finance_payout' THEN
        IF NEW.snapshot_version>0 AND NEW.method='manual' AND NEW.status IN ('sent','paid') THEN
          IF NEW.sent_at IS NULL OR NOT EXISTS (
            SELECT 1 FROM finance_payout_attempt a JOIN finance_manual_payout_receipt r
              ON r.attempt_id=a.id WHERE a.payout_id=NEW.id
              AND a.instruction_version_id=NEW.active_instruction_version_id
              AND a.amount_eur_cents=NEW.amount_eur_cents AND a.committed_at IS NOT NULL
              AND (NEW.status='sent' OR r.completed_attested))
            THEN RAISE EXCEPTION 'Manual settlement requires committed receipt evidence'; END IF;
        END IF;
      ELSIF TG_TABLE_NAME = 'finance_payout_attempt' THEN
        IF OLD.rail='manual' AND ROW(NEW.operator_id, NEW.committed_at)
          IS DISTINCT FROM ROW(OLD.operator_id, OLD.committed_at)
          AND (NEW.operator_id IS DISTINCT FROM OLD.operator_id OR OLD.committed_at IS NOT NULL)
          THEN RAISE EXCEPTION 'Manual operator commitment is immutable'; END IF;
      END IF;
      RETURN NEW;
    END; $$;
    CREATE TRIGGER manual_receipt_guard BEFORE INSERT ON finance_manual_payout_receipt
      FOR EACH ROW EXECUTE FUNCTION finance_manual_receipt_guard();
    CREATE TRIGGER manual_receipt_guard BEFORE UPDATE ON finance_payout
      FOR EACH ROW EXECUTE FUNCTION finance_manual_receipt_guard();
    CREATE TRIGGER manual_receipt_guard BEFORE UPDATE ON finance_payout_attempt
      FOR EACH ROW EXECUTE FUNCTION finance_manual_receipt_guard();
    """)


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in (
        "finance_manual_payout_receipt",
        "finance_payout",
        "finance_payout_attempt",
    ):
        schema_editor.execute(f"DROP TRIGGER manual_receipt_guard ON {table}")
    schema_editor.execute(
        "DROP TRIGGER payout_history_immutable ON finance_manual_payout_receipt"
    )
    schema_editor.execute("DROP FUNCTION finance_manual_receipt_guard()")


class Migration(migrations.Migration):
    dependencies = [("finance", "0023_manualpayoutreceipt")]
    operations = [migrations.RunPython(install, uninstall)]
