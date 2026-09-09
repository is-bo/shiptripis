"""Write-boundary guards for H3's execution rows (PostgreSQL authority).

Application services are the place these rules are expressed readably; this is
the place they are true. A management command, a data migration, an admin bulk
update and a future refactor all reach the database without going through
`payout_execution`, and every one of them is a way for an external money
instruction's identity to be edited after the fact.

Four things are protected here:

* a funding *release* is append-only, like every other payout history row;
* the link between a provider operation and the exact source slice or
  disbursement it executes cannot be repointed after the operation exists;
* a disbursement's economic identity — account, mode, currency, amount, method
  — is fixed at creation, and its provider payout id cannot be swapped once
  Stripe has assigned one;
* allocations cannot be repointed or repriced, and the amounts allocated to one
  bank payout can never exceed the payout itself.
"""

from django.db import migrations


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
    CREATE TRIGGER payout_history_immutable
      BEFORE UPDATE OR DELETE ON finance_payout_funding_release
      FOR EACH ROW EXECUTE FUNCTION finance_payout_immutable();

    CREATE FUNCTION finance_payout_execution_guard() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE allocated bigint;
    BEGIN
      IF TG_TABLE_NAME = 'finance_payout_provider_operation' THEN
        IF TG_OP = 'UPDATE' AND ROW(NEW.funding_allocation_id, NEW.disbursement_id)
          IS DISTINCT FROM ROW(OLD.funding_allocation_id, OLD.disbursement_id)
          THEN RAISE EXCEPTION 'Provider operation execution link is immutable'; END IF;
        IF NEW.funding_allocation_id IS NOT NULL AND NEW.kind <> 'transfer_create'
          THEN RAISE EXCEPTION 'Only a transfer executes a funding allocation'; END IF;
        IF NEW.disbursement_id IS NOT NULL
          AND NEW.kind NOT IN ('bank_payout_create', 'bank_payout_cancel')
          THEN RAISE EXCEPTION 'Only a bank payout operation owns a disbursement'; END IF;
        IF NEW.funding_allocation_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM finance_payout_funding_allocation a
            WHERE a.id = NEW.funding_allocation_id
              AND a.attempt_id = NEW.attempt_id
              AND a.provider_mode = NEW.provider_mode
              AND a.amount_eur_cents = NEW.amount_minor)
          THEN RAISE EXCEPTION 'Transfer does not match its funding allocation'; END IF;
        IF NEW.disbursement_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM finance_stripe_disbursement d
            WHERE d.id = NEW.disbursement_id AND d.provider_mode = NEW.provider_mode)
          THEN RAISE EXCEPTION 'Bank payout operation mode mismatch'; END IF;

      ELSIF TG_TABLE_NAME = 'finance_stripe_disbursement' THEN
        IF TG_OP = 'UPDATE' AND ROW(NEW.account_id, NEW.provider_mode, NEW.currency,
             NEW.amount_minor, NEW.method, NEW.public_reference)
          IS DISTINCT FROM ROW(OLD.account_id, OLD.provider_mode, OLD.currency,
             OLD.amount_minor, OLD.method, OLD.public_reference)
          THEN RAISE EXCEPTION 'Disbursement identity is immutable'; END IF;
        IF TG_OP = 'UPDATE' AND OLD.provider_payout_id <> ''
          AND NEW.provider_payout_id <> OLD.provider_payout_id
          THEN RAISE EXCEPTION 'Disbursement provider identity is immutable'; END IF;
        IF NOT EXISTS (SELECT 1 FROM finance_stripe_payout_account a
             WHERE a.id = NEW.account_id AND a.provider_mode = NEW.provider_mode)
          THEN RAISE EXCEPTION 'Disbursement account mode mismatch'; END IF;

      ELSIF TG_TABLE_NAME = 'finance_stripe_disbursement_allocation' THEN
        IF TG_OP = 'UPDATE' AND ROW(NEW.disbursement_id, NEW.payout_id, NEW.attempt_id,
             NEW.amount_eur_cents)
          IS DISTINCT FROM ROW(OLD.disbursement_id, OLD.payout_id, OLD.attempt_id,
             OLD.amount_eur_cents)
          THEN RAISE EXCEPTION 'Disbursement allocation is immutable'; END IF;
        IF NOT EXISTS (SELECT 1 FROM finance_payout p
             JOIN finance_stripe_disbursement d ON d.id = NEW.disbursement_id
             WHERE p.id = NEW.payout_id AND p.provider_mode = d.provider_mode
               AND p.payout_currency = d.currency)
          THEN RAISE EXCEPTION 'Disbursement allocation contract mismatch'; END IF;
        SELECT COALESCE(SUM(amount_eur_cents), 0) INTO allocated
          FROM finance_stripe_disbursement_allocation
          WHERE disbursement_id = NEW.disbursement_id AND id <> NEW.id;
        IF allocated + NEW.amount_eur_cents > (
             SELECT amount_minor FROM finance_stripe_disbursement
             WHERE id = NEW.disbursement_id)
          THEN RAISE EXCEPTION 'Allocations exceed the bank payout amount'; END IF;
      END IF;
      RETURN NEW;
    END; $$;
    """)
    for table in (
        "finance_payout_provider_operation",
        "finance_stripe_disbursement",
        "finance_stripe_disbursement_allocation",
    ):
        schema_editor.execute(
            f"CREATE TRIGGER payout_execution_guard BEFORE INSERT OR UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION finance_payout_execution_guard()"
        )


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in (
        "finance_payout_provider_operation",
        "finance_stripe_disbursement",
        "finance_stripe_disbursement_allocation",
    ):
        schema_editor.execute(f"DROP TRIGGER payout_execution_guard ON {table}")
    schema_editor.execute(
        "DROP TRIGGER payout_history_immutable ON finance_payout_funding_release"
    )
    schema_editor.execute("DROP FUNCTION finance_payout_execution_guard()")


class Migration(migrations.Migration):
    dependencies = [("finance", "0020_phase8fh3_execution")]
    operations = [migrations.RunPython(install, uninstall)]
