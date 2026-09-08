"""Cross-row ownership/mode contracts at the PostgreSQL write boundary."""

from django.db import migrations


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
    CREATE TRIGGER payout_history_immutable BEFORE UPDATE OR DELETE ON finance_payout_instruction_confirmation
    FOR EACH ROW EXECUTE FUNCTION finance_payout_immutable();

    CREATE FUNCTION finance_payout_relation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_TABLE_NAME = 'finance_payout_method_version' THEN
        IF NOT EXISTS (SELECT 1 FROM finance_traveler_payout_method m WHERE m.id=NEW.method_id
          AND m.currency=NEW.currency AND ((m.method='manual' AND NEW.rail='manual') OR (m.method='stripe_connect' AND NEW.rail='stripe_transfer')))
          THEN RAISE EXCEPTION 'Method version pairing mismatch'; END IF;
        IF NEW.dzd_profile_revision_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM finance_dzd_profile_revision d WHERE d.id=NEW.dzd_profile_revision_id AND d.method_id=NEW.method_id)
          THEN RAISE EXCEPTION 'Postal revision owner mismatch'; END IF;
        IF NEW.stripe_account_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM finance_stripe_payout_account a JOIN finance_traveler_payout_method m ON m.traveler_id=a.traveler_id WHERE a.id=NEW.stripe_account_id AND m.id=NEW.method_id)
          THEN RAISE EXCEPTION 'Stripe destination owner mismatch'; END IF;
      ELSIF TG_TABLE_NAME = 'finance_traveler_payout_method' THEN
        IF NEW.current_version_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM finance_payout_method_version v WHERE v.id=NEW.current_version_id AND v.method_id=NEW.id AND v.currency=NEW.currency)
          THEN RAISE EXCEPTION 'Current method version owner mismatch'; END IF;
      ELSIF TG_TABLE_NAME = 'finance_payout_attempt' THEN
        IF TG_OP='UPDATE' AND ROW(NEW.payout_id, NEW.instruction_version_id, NEW.amount_revision_id, NEW.amount_eur_cents, NEW.currency, NEW.rail, NEW.provider_mode, NEW.sequence, NEW.idempotency_key, NEW.request_fingerprint)
          IS DISTINCT FROM ROW(OLD.payout_id, OLD.instruction_version_id, OLD.amount_revision_id, OLD.amount_eur_cents, OLD.currency, OLD.rail, OLD.provider_mode, OLD.sequence, OLD.idempotency_key, OLD.request_fingerprint)
          THEN RAISE EXCEPTION 'Prepared payout request is immutable'; END IF;
        IF NOT EXISTS (SELECT 1 FROM finance_payout p JOIN finance_payout_method_version v ON v.id=NEW.instruction_version_id
          JOIN finance_traveler_payout_method m ON m.id=v.method_id
          WHERE p.id=NEW.payout_id AND p.provider_mode=NEW.provider_mode AND p.method=NEW.rail AND p.payout_currency=NEW.currency
          AND p.amount_eur_cents=NEW.amount_eur_cents AND m.traveler_id=p.traveler_id AND v.rail=NEW.rail AND v.currency=NEW.currency)
          THEN RAISE EXCEPTION 'Payout attempt contract mismatch'; END IF;
        IF EXISTS (SELECT 1 FROM finance_payout_method_version v JOIN finance_stripe_payout_account a ON a.id=v.stripe_account_id WHERE v.id=NEW.instruction_version_id AND a.provider_mode<>NEW.provider_mode)
          THEN RAISE EXCEPTION 'Payout destination mode mismatch'; END IF;
      ELSIF TG_TABLE_NAME = 'finance_payout_provider_operation' THEN
        IF TG_OP='UPDATE' AND ROW(NEW.attempt_id, NEW.method_id, NEW.kind, NEW.account_scope, NEW.provider_mode, NEW.sequence, NEW.idempotency_key, NEW.request_fingerprint, NEW.amount_minor, NEW.currency)
          IS DISTINCT FROM ROW(OLD.attempt_id, OLD.method_id, OLD.kind, OLD.account_scope, OLD.provider_mode, OLD.sequence, OLD.idempotency_key, OLD.request_fingerprint, OLD.amount_minor, OLD.currency)
          THEN RAISE EXCEPTION 'Provider operation request is immutable'; END IF;
        IF NEW.attempt_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM finance_payout_attempt a WHERE a.id=NEW.attempt_id AND a.provider_mode=NEW.provider_mode)
          THEN RAISE EXCEPTION 'Provider operation mode mismatch'; END IF;
      ELSIF TG_TABLE_NAME = 'finance_payout_funding_allocation' THEN
        IF NOT EXISTS (SELECT 1 FROM finance_payout p JOIN finance_payment_attempt a ON a.id=NEW.source_attempt_id WHERE p.id=NEW.payout_id AND p.provider_mode=NEW.provider_mode AND a.provider_mode=NEW.provider_mode AND a.status='succeeded' AND NOT a.is_unapplied AND a.provider=NEW.provider)
          THEN RAISE EXCEPTION 'Payout funding allocation source mismatch'; END IF;
      ELSIF TG_TABLE_NAME = 'finance_stripe_payout_account' THEN
        IF TG_OP='UPDATE' AND ROW(NEW.traveler_id, NEW.platform_id, NEW.provider_account_id, NEW.provider_mode, NEW.creation_operation_key)
          IS DISTINCT FROM ROW(OLD.traveler_id, OLD.platform_id, OLD.provider_account_id, OLD.provider_mode, OLD.creation_operation_key)
          THEN RAISE EXCEPTION 'Provider account identity is immutable'; END IF;
      END IF;
      RETURN NEW;
    END; $$;
    """)
    for table in (
        "finance_payout_method_version",
        "finance_traveler_payout_method",
        "finance_payout_attempt",
        "finance_payout_provider_operation",
        "finance_payout_funding_allocation",
        "finance_stripe_payout_account",
    ):
        schema_editor.execute(
            f"CREATE TRIGGER payout_relation_guard BEFORE INSERT OR UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION finance_payout_relation_guard()"
        )


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in (
        "finance_payout_method_version",
        "finance_traveler_payout_method",
        "finance_payout_attempt",
        "finance_payout_provider_operation",
        "finance_payout_funding_allocation",
        "finance_stripe_payout_account",
    ):
        schema_editor.execute(f"DROP TRIGGER payout_relation_guard ON {table}")
    schema_editor.execute(
        "DROP TRIGGER payout_history_immutable ON finance_payout_instruction_confirmation"
    )
    schema_editor.execute("DROP FUNCTION finance_payout_relation_guard()")


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0016_payoutattempt_fin_payout_one_prepared_attempt_and_more")
    ]
    operations = [migrations.RunPython(install, uninstall)]
