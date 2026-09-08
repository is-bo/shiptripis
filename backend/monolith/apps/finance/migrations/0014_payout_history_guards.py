"""Database immutability, including bulk/raw SQL (PostgreSQL authority)."""

from django.db import migrations

TABLES = (
    "finance_dzd_profile_revision",
    "finance_payout_method_version",
    "finance_payout_identity_attestation",
    "finance_payout_identity_revocation",
    "finance_payout_amount_revision",
    "finance_payout_instruction_amendment",
    "finance_payout_event",
    "finance_payout_funding_allocation",
    "finance_payout_profile_review",
    "finance_payout_evidence",
)


def install(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute("""
        CREATE FUNCTION finance_payout_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'Payout history is immutable'; END; $$;
    """)
    for table in TABLES:
        schema_editor.execute(
            f"CREATE TRIGGER payout_history_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION finance_payout_immutable()"
        )
    schema_editor.execute("""
        CREATE FUNCTION finance_payout_snapshot_guard() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP='INSERT' AND NEW.snapshot_version > 0 AND NEW.amount_eur_cents = 0
              THEN RAISE EXCEPTION 'Funded payout must start with a positive obligation'; END IF;
            IF OLD.snapshot_version > 0 AND ROW(
                NEW.snapshot_version, NEW.funded_amount_eur_cents,
                NEW.original_settlement_amount_minor, NEW.method, NEW.payout_currency,
                NEW.payout_amount_exponent, NEW.fx_rate_micros, NEW.fx_settings_version_id,
                NEW.fx_source, NEW.fx_snapshot_at, NEW.fx_source_attempt_id,
                NEW.rounding_policy, NEW.method_version_id, NEW.stripe_account_id,
                NEW.dzd_profile_revision_id, NEW.snapshot_at, NEW.funding_attempt_id,
                NEW.funding_provider_snapshot, NEW.provider_mode, NEW.routing_policy_version
            ) IS DISTINCT FROM ROW(
                OLD.snapshot_version, OLD.funded_amount_eur_cents,
                OLD.original_settlement_amount_minor, OLD.method, OLD.payout_currency,
                OLD.payout_amount_exponent, OLD.fx_rate_micros, OLD.fx_settings_version_id,
                OLD.fx_source, OLD.fx_snapshot_at, OLD.fx_source_attempt_id,
                OLD.rounding_policy, OLD.method_version_id, OLD.stripe_account_id,
                OLD.dzd_profile_revision_id, OLD.snapshot_at, OLD.funding_attempt_id,
                OLD.funding_provider_snapshot, OLD.provider_mode, OLD.routing_policy_version
            ) THEN RAISE EXCEPTION 'Funded payout snapshot is immutable'; END IF;
            IF OLD.snapshot_version > 0 AND ROW(NEW.amount_eur_cents, NEW.payout_amount_minor) IS DISTINCT FROM ROW(OLD.amount_eur_cents, OLD.payout_amount_minor)
              AND NOT EXISTS (SELECT 1 FROM finance_payout_amount_revision r
                WHERE r.payout_id=NEW.id AND r.previous_amount_eur_cents=OLD.amount_eur_cents
                AND r.amount_eur_cents=NEW.amount_eur_cents
                AND r.previous_settlement_amount_minor IS NOT DISTINCT FROM OLD.payout_amount_minor
                AND r.settlement_amount_minor IS NOT DISTINCT FROM NEW.payout_amount_minor
                AND r.settlement_reference=NEW.eligibility_decision_reference)
              THEN RAISE EXCEPTION 'Amount change requires explicit revision'; END IF;
            IF OLD.snapshot_version > 0 AND NEW.active_instruction_version_id IS DISTINCT FROM OLD.active_instruction_version_id
              AND NOT EXISTS (SELECT 1 FROM finance_payout_instruction_amendment a
                WHERE a.payout_id=NEW.id AND a.old_version_id=OLD.active_instruction_version_id
                AND a.new_version_id=NEW.active_instruction_version_id AND a.expected_state_version=OLD.state_version)
              THEN RAISE EXCEPTION 'Destination change requires explicit amendment'; END IF;
            IF NEW.snapshot_version > 0 AND NEW.amount_eur_cents = 0 AND NOT EXISTS (
                SELECT 1 FROM finance_payout_amount_revision r WHERE r.payout_id = NEW.id
                AND r.amount_eur_cents = 0 AND r.settlement_reference = NEW.eligibility_decision_reference
            ) THEN RAISE EXCEPTION 'Zero award requires settlement revision'; END IF;
            RETURN NEW;
        END; $$;
        CREATE TRIGGER payout_snapshot_immutable BEFORE INSERT OR UPDATE ON finance_payout
        FOR EACH ROW EXECUTE FUNCTION finance_payout_snapshot_guard();
    """)


def uninstall(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for table in TABLES:
        schema_editor.execute(f"DROP TRIGGER payout_history_immutable ON {table}")
    schema_editor.execute("DROP TRIGGER payout_snapshot_immutable ON finance_payout")
    schema_editor.execute("DROP FUNCTION finance_payout_snapshot_guard()")
    schema_editor.execute("DROP FUNCTION finance_payout_immutable()")


class Migration(migrations.Migration):
    dependencies = [("finance", "0013_payout_constraints")]
    operations = [migrations.RunPython(install, uninstall)]
