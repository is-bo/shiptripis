--
-- PostgreSQL database dump
--

\restrict 1QaaFWYDRe9UoFz85mvL9WZWCdBzkQMXDvsnOGw4NevVp16ZViey90zPQdo36lk

-- Dumped from database version 16.2
-- Dumped by pg_dump version 16.2

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: finance_manual_receipt_guard(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.finance_manual_receipt_guard() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: finance_payout_execution_guard(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.finance_payout_execution_guard() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: finance_payout_immutable(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.finance_payout_immutable() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN RAISE EXCEPTION 'Payout history is immutable'; END; $$;


--
-- Name: finance_payout_relation_guard(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.finance_payout_relation_guard() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


--
-- Name: finance_payout_snapshot_guard(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.finance_payout_snapshot_guard() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: accounts_emailverificationcode; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.accounts_emailverificationcode (
    id bigint NOT NULL,
    code_hash character varying(200) NOT NULL,
    attempts smallint NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    user_id bigint NOT NULL,
    CONSTRAINT accounts_emailverificationcode_attempts_check CHECK ((attempts >= 0))
);


--
-- Name: accounts_emailverificationcode_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.accounts_emailverificationcode ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.accounts_emailverificationcode_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: accounts_oauthidentity; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.accounts_oauthidentity (
    id bigint NOT NULL,
    provider character varying(16) NOT NULL,
    subject character varying(128) NOT NULL,
    email_at_link character varying(254) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    user_id bigint NOT NULL
);


--
-- Name: accounts_oauthidentity_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.accounts_oauthidentity ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.accounts_oauthidentity_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: accounts_passwordresetcode; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.accounts_passwordresetcode (
    id bigint NOT NULL,
    code_hash character varying(200) NOT NULL,
    attempts smallint NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    user_id bigint NOT NULL,
    CONSTRAINT accounts_passwordresetcode_attempts_check CHECK ((attempts >= 0))
);


--
-- Name: accounts_passwordresetcode_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.accounts_passwordresetcode ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.accounts_passwordresetcode_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: accounts_user; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.accounts_user (
    id bigint NOT NULL,
    password character varying(128) NOT NULL,
    last_login timestamp with time zone,
    is_superuser boolean NOT NULL,
    username character varying(150) NOT NULL,
    first_name character varying(150) NOT NULL,
    last_name character varying(150) NOT NULL,
    is_staff boolean NOT NULL,
    is_active boolean NOT NULL,
    date_joined timestamp with time zone NOT NULL,
    email character varying(254) NOT NULL,
    full_name character varying(120) NOT NULL,
    phone character varying(32) NOT NULL,
    wilaya character varying(2) NOT NULL,
    role character varying(16) NOT NULL,
    is_phone_verified boolean NOT NULL,
    is_email_verified boolean NOT NULL,
    is_kyc_verified boolean NOT NULL,
    is_banned boolean NOT NULL,
    preferred_language character varying(2) NOT NULL
);


--
-- Name: accounts_user_groups; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.accounts_user_groups (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    group_id integer NOT NULL
);


--
-- Name: accounts_user_groups_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.accounts_user_groups ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.accounts_user_groups_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: accounts_user_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.accounts_user ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.accounts_user_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: accounts_user_user_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.accounts_user_user_permissions (
    id bigint NOT NULL,
    user_id bigint NOT NULL,
    permission_id integer NOT NULL
);


--
-- Name: accounts_user_user_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.accounts_user_user_permissions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.accounts_user_user_permissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: admin_panel_audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.admin_panel_audit_log (
    id uuid NOT NULL,
    action character varying(128) NOT NULL,
    target_type character varying(128) NOT NULL,
    target_id character varying(128) NOT NULL,
    reason character varying(500) NOT NULL,
    reference character varying(200) NOT NULL,
    before jsonb NOT NULL,
    after jsonb NOT NULL,
    metadata jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    actor_id bigint
);


--
-- Name: admin_panel_invitation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.admin_panel_invitation (
    id uuid NOT NULL,
    email character varying(254) NOT NULL,
    role character varying(32) NOT NULL,
    token_hash character varying(64) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone,
    revoked_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    accepted_by_id bigint,
    invited_by_id bigint NOT NULL,
    CONSTRAINT admin_invite_email_nonempty CHECK ((NOT ((email)::text = ''::text))),
    CONSTRAINT admin_invite_expiry_after_created CHECK ((expires_at > created_at))
);


--
-- Name: auth_group; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_group (
    id integer NOT NULL,
    name character varying(150) NOT NULL
);


--
-- Name: auth_group_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_group ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_group_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_group_permissions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_group_permissions (
    id bigint NOT NULL,
    group_id integer NOT NULL,
    permission_id integer NOT NULL
);


--
-- Name: auth_group_permissions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_group_permissions ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_group_permissions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: auth_permission; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.auth_permission (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    content_type_id integer NOT NULL,
    codename character varying(100) NOT NULL
);


--
-- Name: auth_permission_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.auth_permission ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.auth_permission_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: boosts_intent_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.boosts_intent_event (
    id bigint NOT NULL,
    reason character varying(32) NOT NULL,
    previous_eur_cents bigint NOT NULL,
    amount_eur_cents bigint NOT NULL,
    commission_rate_bps smallint NOT NULL,
    ranking_weight smallint NOT NULL,
    request_status character varying(16) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    actor_id bigint,
    business_settings_version_id bigint,
    deal_id bigint,
    delivery_request_id bigint NOT NULL,
    CONSTRAINT boosts_intent_commission_bps CHECK ((commission_rate_bps <= 10000)),
    CONSTRAINT boosts_intent_event_amount_eur_cents_check CHECK ((amount_eur_cents >= 0)),
    CONSTRAINT boosts_intent_event_commission_rate_bps_check CHECK ((commission_rate_bps >= 0)),
    CONSTRAINT boosts_intent_event_previous_eur_cents_check CHECK ((previous_eur_cents >= 0)),
    CONSTRAINT boosts_intent_event_ranking_weight_check CHECK ((ranking_weight >= 0))
);


--
-- Name: boosts_intent_event_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.boosts_intent_event ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.boosts_intent_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: boosts_purchase; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.boosts_purchase (
    id bigint NOT NULL,
    public_reference uuid NOT NULL,
    package_code character varying(32) NOT NULL,
    package_snapshot jsonb NOT NULL,
    duration_seconds integer NOT NULL,
    amount_eur_cents bigint NOT NULL,
    ranking_weight smallint NOT NULL,
    status character varying(20) NOT NULL,
    activated_at timestamp with time zone,
    expires_at timestamp with time zone,
    cancelled_at timestamp with time zone,
    disposition_reason character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    business_settings_version_id bigint NOT NULL,
    buyer_id bigint NOT NULL,
    delivery_request_id bigint NOT NULL,
    payment_order_id bigint,
    deal_id bigint,
    economics_version character varying(24) NOT NULL,
    platform_boost_eur_cents bigint NOT NULL,
    traveler_boost_eur_cents bigint NOT NULL,
    traveler_share_bps smallint NOT NULL,
    CONSTRAINT boosts_active_requires_window CHECK (((NOT ((status)::text = 'active'::text)) OR ((activated_at IS NOT NULL) AND (expires_at IS NOT NULL)))),
    CONSTRAINT boosts_duration_positive CHECK ((duration_seconds > 0)),
    CONSTRAINT boosts_economic_split_consistent CHECK ((((economics_version)::text = 'visibility_only'::text) OR ((traveler_share_bps >= 5001) AND (traveler_share_bps <= 9999) AND (amount_eur_cents = (traveler_boost_eur_cents + platform_boost_eur_cents))))),
    CONSTRAINT boosts_price_positive CHECK ((amount_eur_cents > 0)),
    CONSTRAINT boosts_purchase_duration_seconds_check CHECK ((duration_seconds >= 0)),
    CONSTRAINT boosts_purchase_platform_boost_eur_cents_check CHECK ((platform_boost_eur_cents >= 0)),
    CONSTRAINT boosts_purchase_price_eur_cents_check CHECK ((amount_eur_cents >= 0)),
    CONSTRAINT boosts_purchase_ranking_weight_check CHECK ((ranking_weight >= 0)),
    CONSTRAINT boosts_purchase_traveler_boost_eur_cents_check CHECK ((traveler_boost_eur_cents >= 0)),
    CONSTRAINT boosts_purchase_traveler_share_bps_check CHECK ((traveler_share_bps >= 0)),
    CONSTRAINT boosts_weight_positive CHECK ((ranking_weight > 0))
);


--
-- Name: boosts_purchase_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.boosts_purchase ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.boosts_purchase_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: chat_message; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.chat_message (
    id bigint NOT NULL,
    body text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    read_at timestamp with time zone,
    match_id bigint NOT NULL,
    sender_id bigint NOT NULL,
    client_message_id uuid
);


--
-- Name: chat_message_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.chat_message ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.chat_message_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: core_business_settings_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.core_business_settings_version (
    id bigint NOT NULL,
    version integer NOT NULL,
    status character varying(12) NOT NULL,
    canonical_currency character varying(3) NOT NULL,
    commission_rate_bps smallint NOT NULL,
    pricing_version character varying(32) NOT NULL,
    policy jsonb NOT NULL,
    activated_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    created_by_id bigint,
    CONSTRAINT core_business_settings_version_commission_rate_bps_check CHECK ((commission_rate_bps >= 0)),
    CONSTRAINT core_business_settings_version_version_check CHECK ((version >= 0)),
    CONSTRAINT core_settings_commission_bps CHECK ((commission_rate_bps <= 10000)),
    CONSTRAINT core_settings_currency_eur CHECK (((canonical_currency)::text = 'EUR'::text))
);


--
-- Name: core_business_settings_version_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.core_business_settings_version ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.core_business_settings_version_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: core_published_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.core_published_event (
    id uuid NOT NULL,
    channel character varying(128) NOT NULL,
    event_id character varying(64) NOT NULL,
    payload_hash character varying(64) NOT NULL,
    published_at timestamp with time zone NOT NULL,
    delivered_at timestamp with time zone
);


--
-- Name: deals_arrival_report; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.deals_arrival_report (
    id bigint NOT NULL,
    reported_at timestamp with time zone NOT NULL,
    reported_deal_status character varying(24) NOT NULL,
    scheduled_arrival_at timestamp with time zone NOT NULL,
    early_by_seconds integer NOT NULL,
    threshold_seconds integer NOT NULL,
    basis character varying(48) NOT NULL,
    status character varying(24) NOT NULL,
    decided_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deal_id bigint NOT NULL,
    decided_by_id bigint,
    reported_by_id bigint NOT NULL,
    CONSTRAINT deals_arrival_decision_complete CHECK ((((decided_at IS NULL) AND (decided_by_id IS NULL) AND ((status)::text = 'pending_confirmation'::text)) OR ((decided_at IS NOT NULL) AND (decided_by_id IS NOT NULL) AND ((status)::text = ANY ((ARRAY['confirmed'::character varying, 'declined'::character varying])::text[]))))),
    CONSTRAINT deals_arrival_positive_earliness CHECK ((early_by_seconds > 0)),
    CONSTRAINT deals_arrival_report_early_by_seconds_check CHECK ((early_by_seconds >= 0)),
    CONSTRAINT deals_arrival_report_threshold_seconds_check CHECK ((threshold_seconds >= 0))
);


--
-- Name: deals_arrival_report_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.deals_arrival_report ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.deals_arrival_report_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: deals_deal; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.deals_deal (
    id bigint NOT NULL,
    status character varying(24) NOT NULL,
    is_legacy boolean NOT NULL,
    funded_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    accepted_offer_id bigint NOT NULL,
    delivery_request_id bigint NOT NULL,
    journey_id bigint NOT NULL,
    match_id bigint NOT NULL,
    sender_id bigint NOT NULL,
    traveler_id bigint NOT NULL,
    agreed_pickup_at timestamp with time zone,
    cancellation_reason character varying(64) NOT NULL,
    cancelled_at timestamp with time zone,
    cancelled_by_id bigint,
    completed_at timestamp with time zone,
    delivery_code_available_at timestamp with time zone,
    delivery_code_released_at timestamp with time zone,
    delivery_confirmed_at timestamp with time zone,
    lifecycle_policy jsonb NOT NULL,
    no_show_note character varying(255) NOT NULL,
    no_show_party character varying(10) NOT NULL,
    no_show_recorded_at timestamp with time zone,
    no_show_recorded_by_id bigint,
    pickup_confirmed_at timestamp with time zone,
    protection_ends_at timestamp with time zone,
    rating_window_ends_at timestamp with time zone,
    arrival_confirmed_at timestamp with time zone,
    arrival_snapshot jsonb NOT NULL,
    funded_scheduled_arrival_floor_at timestamp with time zone,
    CONSTRAINT deals_arrival_floor_requires_funding CHECK (((funded_scheduled_arrival_floor_at IS NULL) OR (funded_at IS NOT NULL))),
    CONSTRAINT deals_arrival_requires_funding CHECK (((arrival_confirmed_at IS NULL) OR (funded_at IS NOT NULL))),
    CONSTRAINT deals_delivery_after_code_release CHECK (((delivery_confirmed_at IS NULL) OR (delivery_code_released_at IS NOT NULL))),
    CONSTRAINT deals_delivery_code_after_pickup CHECK (((delivery_code_available_at IS NULL) OR (pickup_confirmed_at IS NOT NULL))),
    CONSTRAINT deals_no_show_requires_actor CHECK ((((no_show_party)::text = ''::text) OR ((no_show_recorded_at IS NOT NULL) AND (no_show_recorded_by_id IS NOT NULL)))),
    CONSTRAINT deals_protection_requires_delivery CHECK (((protection_ends_at IS NULL) OR (delivery_confirmed_at IS NOT NULL))),
    CONSTRAINT deals_release_after_availability CHECK (((delivery_code_released_at IS NULL) OR (delivery_code_available_at IS NOT NULL))),
    CONSTRAINT deals_sender_neq_traveler CHECK ((NOT (sender_id = traveler_id)))
);


--
-- Name: deals_deal_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.deals_deal ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.deals_deal_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: deals_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.deals_event (
    id bigint NOT NULL,
    kind character varying(32) NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    actor_id bigint,
    deal_id bigint NOT NULL
);


--
-- Name: deals_event_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.deals_event ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.deals_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: deals_leg_allocation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.deals_leg_allocation (
    id bigint NOT NULL,
    allocated_weight_kg numeric(8,3) NOT NULL,
    status character varying(20) NOT NULL,
    reserved_at timestamp with time zone NOT NULL,
    released_at timestamp with time zone,
    deal_id bigint NOT NULL,
    journey_leg_id bigint NOT NULL,
    expires_at timestamp with time zone,
    release_reason character varying(64) NOT NULL,
    CONSTRAINT deals_allocation_positive_weight CHECK ((allocated_weight_kg > (0)::numeric))
);


--
-- Name: deals_leg_allocation_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.deals_leg_allocation ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.deals_leg_allocation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: deals_recipient; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.deals_recipient (
    id bigint NOT NULL,
    full_name character varying(120) NOT NULL,
    email character varying(254) NOT NULL,
    phone character varying(32) NOT NULL,
    delivery_note text NOT NULL,
    revision integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    created_by_id bigint NOT NULL,
    deal_id bigint NOT NULL,
    updated_by_id bigint,
    communication_language character varying(2) NOT NULL,
    CONSTRAINT deals_recipient_email_required CHECK ((NOT ((email)::text = ''::text))),
    CONSTRAINT deals_recipient_name_required CHECK ((NOT ((full_name)::text = ''::text))),
    CONSTRAINT deals_recipient_revision_check CHECK ((revision >= 0))
);


--
-- Name: deals_recipient_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.deals_recipient ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.deals_recipient_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: deals_terms_snapshot; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.deals_terms_snapshot (
    id bigint NOT NULL,
    currency character varying(3) NOT NULL,
    traveler_reward_minor bigint NOT NULL,
    commission_rate_bps smallint NOT NULL,
    platform_fee_minor bigint NOT NULL,
    sender_total_minor bigint NOT NULL,
    pricing_version character varying(32) NOT NULL,
    policy_snapshot jsonb NOT NULL,
    is_legacy boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    business_settings_version_id bigint,
    deal_id bigint NOT NULL,
    boost_amount_minor bigint NOT NULL,
    boost_platform_fee_minor bigint NOT NULL,
    boost_traveler_bonus_minor bigint NOT NULL,
    boost_commission_rate_bps smallint NOT NULL,
    boost_economics_version character varying(24) NOT NULL,
    CONSTRAINT deals_terms_boost_additive_bonus CHECK (((NOT ((boost_economics_version)::text = 'additive_commission_v2'::text)) OR (boost_amount_minor = boost_traveler_bonus_minor))),
    CONSTRAINT deals_terms_boost_commission_bps CHECK ((boost_commission_rate_bps <= 10000)),
    CONSTRAINT deals_terms_boost_total_sum CHECK (((NOT ((boost_economics_version)::text = 'traveler_split_v1'::text)) OR (boost_amount_minor = (boost_traveler_bonus_minor + boost_platform_fee_minor)))),
    CONSTRAINT deals_terms_commission_bps CHECK ((commission_rate_bps <= 10000)),
    CONSTRAINT deals_terms_new_currency_eur CHECK ((is_legacy OR ((business_settings_version_id IS NOT NULL) AND ((currency)::text = 'EUR'::text)))),
    CONSTRAINT deals_terms_snapshot_boost_amount_minor_check CHECK ((boost_amount_minor >= 0)),
    CONSTRAINT deals_terms_snapshot_boost_commission_rate_bps_check CHECK ((boost_commission_rate_bps >= 0)),
    CONSTRAINT deals_terms_snapshot_boost_platform_fee_minor_check CHECK ((boost_platform_fee_minor >= 0)),
    CONSTRAINT deals_terms_snapshot_boost_traveler_bonus_minor_check CHECK ((boost_traveler_bonus_minor >= 0)),
    CONSTRAINT deals_terms_snapshot_commission_rate_bps_check CHECK ((commission_rate_bps >= 0)),
    CONSTRAINT deals_terms_snapshot_platform_fee_minor_check CHECK ((platform_fee_minor >= 0)),
    CONSTRAINT deals_terms_snapshot_sender_total_minor_check CHECK ((sender_total_minor >= 0)),
    CONSTRAINT deals_terms_snapshot_traveler_reward_minor_check CHECK ((traveler_reward_minor >= 0)),
    CONSTRAINT deals_terms_total_sum CHECK ((sender_total_minor = (traveler_reward_minor + platform_fee_minor)))
);


--
-- Name: deals_terms_snapshot_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.deals_terms_snapshot ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.deals_terms_snapshot_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: disputes_dispute; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.disputes_dispute (
    id bigint NOT NULL,
    public_reference uuid NOT NULL,
    opened_by_role character varying(10) NOT NULL,
    status character varying(20) NOT NULL,
    category character varying(20) NOT NULL,
    reason_text text NOT NULL,
    evidence_bundle jsonb NOT NULL,
    protection_ends_at timestamp with time zone,
    opened_at timestamp with time zone NOT NULL,
    resolution character varying(24) NOT NULL,
    sender_refund_eur_cents bigint,
    traveler_payout_eur_cents bigint,
    platform_fee_eur_cents bigint,
    collected_total_eur_cents bigint,
    resolution_note text NOT NULL,
    resolved_at timestamp with time zone,
    closed_at timestamp with time zone,
    payout_frozen boolean NOT NULL,
    payout_already_settled boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deal_id bigint NOT NULL,
    opened_by_id bigint NOT NULL,
    resolved_by_id bigint,
    CONSTRAINT disputes_dispute_collected_total_eur_cents_check CHECK ((collected_total_eur_cents >= 0)),
    CONSTRAINT disputes_dispute_platform_fee_eur_cents_check CHECK ((platform_fee_eur_cents >= 0)),
    CONSTRAINT disputes_dispute_sender_refund_eur_cents_check CHECK ((sender_refund_eur_cents >= 0)),
    CONSTRAINT disputes_dispute_traveler_payout_eur_cents_check CHECK ((traveler_payout_eur_cents >= 0)),
    CONSTRAINT disputes_resolution_reconciles CHECK (((collected_total_eur_cents IS NULL) OR (collected_total_eur_cents = ((sender_refund_eur_cents + traveler_payout_eur_cents) + platform_fee_eur_cents)))),
    CONSTRAINT disputes_resolved_requires_evidence CHECK (((NOT ((status)::text = 'resolved'::text)) OR ((NOT ((resolution)::text = ''::text)) AND (resolved_at IS NOT NULL) AND (resolved_by_id IS NOT NULL))))
);


--
-- Name: disputes_dispute_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.disputes_dispute ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.disputes_dispute_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: disputes_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.disputes_event (
    id bigint NOT NULL,
    kind character varying(24) NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    actor_id bigint,
    dispute_id bigint NOT NULL
);


--
-- Name: disputes_event_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.disputes_event ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.disputes_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: disputes_evidence; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.disputes_evidence (
    id bigint NOT NULL,
    kind character varying(10) NOT NULL,
    text text NOT NULL,
    storage_bucket character varying(64) NOT NULL,
    storage_key character varying(255) NOT NULL,
    content_type character varying(64) NOT NULL,
    size_bytes bigint,
    content_sha256 character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    dispute_id bigint NOT NULL,
    submitted_by_id bigint NOT NULL,
    CONSTRAINT disputes_evidence_payload_matches_kind CHECK (((((kind)::text = 'text'::text) AND ((storage_key)::text = ''::text) AND (NOT (text = ''::text))) OR ((NOT ((kind)::text = 'text'::text)) AND (NOT ((storage_key)::text = ''::text))))),
    CONSTRAINT disputes_evidence_size_bytes_check CHECK ((size_bytes >= 0))
);


--
-- Name: disputes_evidence_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.disputes_evidence ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.disputes_evidence_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_admin_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_admin_log (
    id integer NOT NULL,
    action_time timestamp with time zone NOT NULL,
    object_id text,
    object_repr character varying(200) NOT NULL,
    action_flag smallint NOT NULL,
    change_message text NOT NULL,
    content_type_id integer,
    user_id bigint NOT NULL,
    CONSTRAINT django_admin_log_action_flag_check CHECK ((action_flag >= 0))
);


--
-- Name: django_admin_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_admin_log ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_admin_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_content_type; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_content_type (
    id integer NOT NULL,
    app_label character varying(100) NOT NULL,
    model character varying(100) NOT NULL
);


--
-- Name: django_content_type_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_content_type ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_content_type_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_migrations (
    id bigint NOT NULL,
    app character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    applied timestamp with time zone NOT NULL
);


--
-- Name: django_migrations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.django_migrations ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.django_migrations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: django_session; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.django_session (
    session_key character varying(40) NOT NULL,
    session_data text NOT NULL,
    expire_date timestamp with time zone NOT NULL
);


--
-- Name: finance_dzd_profile_revision; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_dzd_profile_revision (
    id bigint NOT NULL,
    public_reference uuid NOT NULL,
    sequence integer NOT NULL,
    first_name_encrypted text NOT NULL,
    last_name_encrypted text NOT NULL,
    ccp_number_encrypted text NOT NULL,
    ccp_key_encrypted text NOT NULL,
    rip_encrypted text NOT NULL,
    ccp_last_four character varying(4) NOT NULL,
    rip_last_four character varying(4) NOT NULL,
    account_fingerprint character varying(64) NOT NULL,
    status character varying(24) NOT NULL,
    submitted_at timestamp with time zone NOT NULL,
    method_id bigint NOT NULL,
    evidence_id bigint,
    identity_attestation_id bigint,
    CONSTRAINT finance_dzd_profile_revision_sequence_check CHECK ((sequence >= 0))
);


--
-- Name: finance_dzd_profile_revision_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_dzd_profile_revision ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_dzd_profile_revision_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_guest_payment_link; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_guest_payment_link (
    id bigint NOT NULL,
    token_hash character varying(64) NOT NULL,
    label character varying(80) NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    revoked_at timestamp with time zone,
    consumed_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    created_by_id bigint NOT NULL,
    order_id bigint NOT NULL,
    communication_language character varying(2) NOT NULL
);


--
-- Name: finance_guest_payment_link_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_guest_payment_link ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_guest_payment_link_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_hold; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_hold (
    id bigint NOT NULL,
    kind character varying(24) NOT NULL,
    reason_code character varying(64) NOT NULL,
    source_reference character varying(160) NOT NULL,
    amount_exposure_eur_cents bigint,
    opened_at timestamp with time zone NOT NULL,
    cleared_at timestamp with time zone,
    generation bigint NOT NULL,
    cleared_by_id bigint,
    deal_id bigint,
    opened_by_id bigint,
    payout_id bigint,
    source_attempt_id bigint,
    account_id bigint,
    CONSTRAINT fin_hold_exactly_one_scope CHECK ((((account_id IS NULL) AND (deal_id IS NOT NULL) AND (payout_id IS NULL) AND (source_attempt_id IS NULL)) OR ((account_id IS NULL) AND (deal_id IS NULL) AND (payout_id IS NOT NULL) AND (source_attempt_id IS NULL)) OR ((account_id IS NOT NULL) AND (deal_id IS NULL) AND (payout_id IS NULL) AND (source_attempt_id IS NULL)) OR ((account_id IS NULL) AND (deal_id IS NULL) AND (payout_id IS NULL) AND (source_attempt_id IS NOT NULL)))),
    CONSTRAINT finance_hold_amount_exposure_eur_cents_check CHECK ((amount_exposure_eur_cents >= 0)),
    CONSTRAINT finance_hold_generation_check CHECK ((generation >= 0))
);


--
-- Name: finance_hold_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_hold ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_hold_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_ledger_entry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_ledger_entry (
    id bigint NOT NULL,
    account character varying(24) NOT NULL,
    amount_eur_cents bigint NOT NULL,
    currency character varying(3) NOT NULL,
    note character varying(255) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    deal_id bigint,
    user_id bigint,
    transaction_id bigint NOT NULL,
    attempt_id bigint,
    order_id bigint,
    refund_id bigint,
    payout_id bigint,
    CONSTRAINT fin_ledger_amount_nonzero CHECK ((NOT (amount_eur_cents = 0))),
    CONSTRAINT fin_ledger_currency_eur CHECK (((currency)::text = 'EUR'::text))
);


--
-- Name: finance_ledger_entry_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_ledger_entry ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_ledger_entry_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_ledger_transaction; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_ledger_transaction (
    id bigint NOT NULL,
    key character varying(160) NOT NULL,
    kind character varying(24) NOT NULL,
    note character varying(255) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    reverses_id bigint,
    provider_mode character varying(16) NOT NULL
);


--
-- Name: finance_ledger_transaction_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_ledger_transaction ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_ledger_transaction_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_manual_payout_receipt; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_manual_payout_receipt (
    id bigint NOT NULL,
    revision integer NOT NULL,
    completed_attested boolean NOT NULL,
    recorded_at timestamp with time zone NOT NULL,
    attempt_id bigint NOT NULL,
    evidence_id bigint NOT NULL,
    operator_id bigint NOT NULL,
    CONSTRAINT finance_manual_payout_receipt_revision_check CHECK ((revision >= 0))
);


--
-- Name: finance_manual_payout_receipt_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_manual_payout_receipt ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_manual_payout_receipt_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_payment_attempt; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_payment_attempt (
    id bigint NOT NULL,
    provider character varying(16) NOT NULL,
    guest_email character varying(254) NOT NULL,
    amount_eur_cents bigint NOT NULL,
    payment_currency character varying(3) NOT NULL,
    provider_amount_minor bigint NOT NULL,
    provider_amount_exponent smallint NOT NULL,
    fx_rate_micros bigint,
    fx_source character varying(64) NOT NULL,
    fx_snapshot_at timestamp with time zone,
    provider_session_id character varying(255) NOT NULL,
    provider_payment_id character varying(255) NOT NULL,
    idempotency_key character varying(128) NOT NULL,
    checkout_url character varying(1024) NOT NULL,
    status character varying(20) NOT NULL,
    failure_code character varying(64) NOT NULL,
    failure_message character varying(255) NOT NULL,
    is_unapplied boolean NOT NULL,
    expires_at timestamp with time zone,
    succeeded_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    fx_settings_version_id bigint,
    guest_link_id bigint,
    payer_id bigint,
    order_id bigint NOT NULL,
    operational_resolution character varying(16) NOT NULL,
    operational_resolution_reason character varying(500) NOT NULL,
    operational_resolved_at timestamp with time zone,
    operational_resolved_by_id bigint,
    mode_evidence character varying(64) NOT NULL,
    provider_charge_id character varying(255) NOT NULL,
    provider_mode character varying(16) NOT NULL,
    CONSTRAINT fin_attempt_amount_positive CHECK ((amount_eur_cents > 0)),
    CONSTRAINT fin_attempt_fx_required_for_conversion CHECK ((((fx_rate_micros IS NULL) AND ((payment_currency)::text = 'EUR'::text)) OR ((NOT ((payment_currency)::text = 'EUR'::text)) AND (fx_rate_micros IS NOT NULL)))),
    CONSTRAINT fin_attempt_resolution_complete CHECK (((((operational_resolution)::text = ''::text) AND ((operational_resolution_reason)::text = ''::text) AND (operational_resolved_at IS NULL) AND (operational_resolved_by_id IS NULL)) OR ((NOT ((operational_resolution)::text = ''::text)) AND (operational_resolved_at IS NOT NULL) AND (NOT ((operational_resolution_reason)::text = ''::text))))),
    CONSTRAINT finance_payment_attempt_amount_eur_cents_check CHECK ((amount_eur_cents >= 0)),
    CONSTRAINT finance_payment_attempt_fx_rate_micros_check CHECK ((fx_rate_micros >= 0)),
    CONSTRAINT finance_payment_attempt_provider_amount_exponent_check CHECK ((provider_amount_exponent >= 0)),
    CONSTRAINT finance_payment_attempt_provider_amount_minor_check CHECK ((provider_amount_minor >= 0))
);


--
-- Name: finance_payment_attempt_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_payment_attempt ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_payment_attempt_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_payment_order; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_payment_order (
    id bigint NOT NULL,
    public_reference uuid NOT NULL,
    purpose character varying(20) NOT NULL,
    currency character varying(3) NOT NULL,
    amount_eur_cents bigint NOT NULL,
    credited_eur_cents bigint NOT NULL,
    paid_eur_cents bigint NOT NULL,
    refunded_eur_cents bigint NOT NULL,
    status character varying(20) NOT NULL,
    boost_reference character varying(64) NOT NULL,
    terms_snapshot jsonb NOT NULL,
    paid_at timestamp with time zone,
    cancelled_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    business_settings_version_id bigint,
    credit_source_id bigint,
    deal_id bigint,
    delivery_request_id bigint,
    owner_id bigint NOT NULL,
    CONSTRAINT fin_order_amount_positive CHECK ((amount_eur_cents > 0)),
    CONSTRAINT fin_order_currency_eur CHECK (((currency)::text = 'EUR'::text)),
    CONSTRAINT fin_order_no_overcollection CHECK ((amount_eur_cents >= (credited_eur_cents + paid_eur_cents))),
    CONSTRAINT fin_order_reference_required CHECK ((((delivery_request_id IS NOT NULL) AND ((purpose)::text = 'posting_deposit'::text)) OR ((deal_id IS NOT NULL) AND ((purpose)::text = 'deal_balance'::text)) OR ((delivery_request_id IS NOT NULL) AND ((purpose)::text = 'boost'::text)))),
    CONSTRAINT fin_order_refund_within_capture CHECK ((refunded_eur_cents <= paid_eur_cents)),
    CONSTRAINT finance_payment_order_amount_eur_cents_check CHECK ((amount_eur_cents >= 0)),
    CONSTRAINT finance_payment_order_credited_eur_cents_check CHECK ((credited_eur_cents >= 0)),
    CONSTRAINT finance_payment_order_paid_eur_cents_check CHECK ((paid_eur_cents >= 0)),
    CONSTRAINT finance_payment_order_refunded_eur_cents_check CHECK ((refunded_eur_cents >= 0))
);


--
-- Name: finance_payment_order_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_payment_order ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_payment_order_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_payment_refund; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_payment_refund (
    id bigint NOT NULL,
    amount_eur_cents bigint NOT NULL,
    provider character varying(16) NOT NULL,
    provider_refund_id character varying(255) NOT NULL,
    idempotency_key character varying(128) NOT NULL,
    reason character varying(24) NOT NULL,
    status character varying(12) NOT NULL,
    failure_code character varying(64) NOT NULL,
    failure_message character varying(255) NOT NULL,
    succeeded_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    attempt_id bigint NOT NULL,
    order_id bigint NOT NULL,
    requested_by_id bigint,
    settled_by_id bigint,
    settlement_note character varying(255) NOT NULL,
    settlement_reference character varying(128) NOT NULL,
    last_provider_check_at timestamp with time zone,
    next_retry_at timestamp with time zone,
    processing_attempts smallint NOT NULL,
    processing_started_at timestamp with time zone,
    requires_manual_action boolean NOT NULL,
    provider_mode character varying(16) NOT NULL,
    CONSTRAINT fin_refund_amount_positive CHECK ((amount_eur_cents > 0)),
    CONSTRAINT fin_refund_manual_requires_reference CHECK (((settled_by_id IS NULL) OR (NOT ((settlement_reference)::text = ''::text)))),
    CONSTRAINT finance_payment_refund_amount_eur_cents_check CHECK ((amount_eur_cents >= 0)),
    CONSTRAINT finance_payment_refund_processing_attempts_check CHECK ((processing_attempts >= 0))
);


--
-- Name: finance_payment_refund_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_payment_refund ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_payment_refund_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_payout; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_payout (
    id bigint NOT NULL,
    amount_eur_cents bigint NOT NULL,
    method character varying(20) NOT NULL,
    status character varying(16) NOT NULL,
    eligible_at timestamp with time zone,
    scheduled_for timestamp with time zone,
    payout_currency character varying(3) NOT NULL,
    payout_amount_minor bigint,
    payout_amount_exponent smallint,
    fx_rate_micros bigint,
    provider_payout_id character varying(255) NOT NULL,
    reference character varying(128) NOT NULL,
    receipt_url character varying(1024) NOT NULL,
    notes text NOT NULL,
    failure_code character varying(64) NOT NULL,
    paid_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    admin_actor_id bigint,
    deal_id bigint NOT NULL,
    traveler_id bigint NOT NULL,
    block_reason character varying(64) NOT NULL,
    eligibility_basis character varying(32) NOT NULL,
    eligibility_decision_reference character varying(160) NOT NULL,
    funded_amount_eur_cents bigint,
    funding_attempt_id bigint,
    funding_provider_snapshot character varying(16) NOT NULL,
    fx_settings_version_id bigint,
    fx_snapshot_at timestamp with time zone,
    fx_source character varying(64) NOT NULL,
    fx_source_attempt_id bigint,
    legacy_classification character varying(64) NOT NULL,
    next_action_at timestamp with time zone,
    original_settlement_amount_minor bigint,
    provider_mode character varying(16) NOT NULL,
    public_reference uuid NOT NULL,
    rounding_policy character varying(32) NOT NULL,
    routing_policy_version character varying(64) NOT NULL,
    sent_at timestamp with time zone,
    settled_at timestamp with time zone,
    settlement_basis character varying(64) NOT NULL,
    snapshot_at timestamp with time zone,
    snapshot_version smallint NOT NULL,
    state_version bigint NOT NULL,
    dzd_profile_revision_id bigint,
    active_instruction_version_id bigint,
    method_version_id bigint,
    stripe_account_id bigint,
    CONSTRAINT fin_payout_amount_positive CHECK (((amount_eur_cents > 0) OR ((amount_eur_cents = 0) AND (snapshot_version > 0) AND ((status)::text = 'cancelled'::text) AND (NOT ((eligibility_decision_reference)::text = ''::text))))),
    CONSTRAINT fin_payout_dzd_fx_snapshot CHECK (((snapshot_version = 0) OR (NOT ((payout_currency)::text = 'DZD'::text)) OR ((fx_rate_micros > 0) AND (fx_rate_micros IS NOT NULL) AND (fx_settings_version_id IS NOT NULL) AND (fx_snapshot_at IS NOT NULL) AND (payout_amount_minor IS NOT NULL)) OR (((block_reason)::text = 'fx_snapshot_missing'::text) AND (fx_rate_micros IS NULL) AND (payout_amount_minor IS NULL)))),
    CONSTRAINT fin_payout_funded_snapshot CHECK (((snapshot_version = 0) OR ((funded_amount_eur_cents > 0) AND (funded_amount_eur_cents IS NOT NULL) AND (snapshot_at IS NOT NULL)))),
    CONSTRAINT fin_payout_paid_requires_evidence CHECK (((NOT ((status)::text = 'paid'::text)) OR (NOT ((provider_payout_id)::text = ''::text)) OR ((admin_actor_id IS NOT NULL) AND (NOT ((reference)::text = ''::text))))),
    CONSTRAINT fin_payout_paid_requires_timestamp CHECK (((NOT ((status)::text = 'paid'::text)) OR (paid_at IS NOT NULL))),
    CONSTRAINT fin_payout_release_requires_eligibility CHECK (((NOT ((status)::text = ANY ((ARRAY['eligible'::character varying, 'scheduled'::character varying, 'processing'::character varying, 'sent'::character varying, 'paid'::character varying])::text[]))) OR (eligible_at IS NOT NULL))),
    CONSTRAINT fin_payout_snapshot_pairing CHECK (((snapshot_version = 0) OR (((method)::text = 'manual'::text) AND (payout_amount_exponent = 0) AND ((payout_currency)::text = 'DZD'::text) AND (stripe_account_id IS NULL)) OR ((dzd_profile_revision_id IS NULL) AND (fx_rate_micros IS NULL) AND (fx_settings_version_id IS NULL) AND (fx_source_attempt_id IS NULL) AND ((method)::text = 'stripe_transfer'::text) AND (payout_amount_exponent = 2) AND ((payout_currency)::text = 'EUR'::text)) OR (((block_reason)::text = 'payout_preference_required'::text) AND ((method)::text = 'undecided'::text) AND ((payout_currency)::text = ''::text)))),
    CONSTRAINT finance_payout_amount_eur_cents_check CHECK ((amount_eur_cents >= 0)),
    CONSTRAINT finance_payout_funded_amount_eur_cents_check CHECK ((funded_amount_eur_cents >= 0)),
    CONSTRAINT finance_payout_fx_rate_micros_check CHECK ((fx_rate_micros >= 0)),
    CONSTRAINT finance_payout_original_settlement_amount_minor_check CHECK ((original_settlement_amount_minor >= 0)),
    CONSTRAINT finance_payout_payout_amount_exponent_check CHECK ((payout_amount_exponent >= 0)),
    CONSTRAINT finance_payout_payout_amount_minor_check CHECK ((payout_amount_minor >= 0)),
    CONSTRAINT finance_payout_snapshot_version_check CHECK ((snapshot_version >= 0)),
    CONSTRAINT finance_payout_state_version_check CHECK ((state_version >= 0))
);


--
-- Name: finance_payout_amount_revision; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_payout_amount_revision (
    id bigint NOT NULL,
    revision integer NOT NULL,
    previous_amount_eur_cents bigint NOT NULL,
    amount_eur_cents bigint NOT NULL,
    previous_settlement_amount_minor bigint,
    settlement_amount_minor bigint,
    fx_rate_micros bigint,
    settlement_reference character varying(160) NOT NULL,
    reason_code character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    actor_id bigint,
    fx_settings_version_id bigint,
    ledger_transaction_id bigint,
    payout_id bigint NOT NULL,
    CONSTRAINT finance_payout_amount_revisi_previous_settlement_amount_m_check CHECK ((previous_settlement_amount_minor >= 0)),
    CONSTRAINT finance_payout_amount_revision_amount_eur_cents_check CHECK ((amount_eur_cents >= 0)),
    CONSTRAINT finance_payout_amount_revision_fx_rate_micros_check CHECK ((fx_rate_micros >= 0)),
    CONSTRAINT finance_payout_amount_revision_previous_amount_eur_cents_check CHECK ((previous_amount_eur_cents >= 0)),
    CONSTRAINT finance_payout_amount_revision_revision_check CHECK ((revision >= 0)),
    CONSTRAINT finance_payout_amount_revision_settlement_amount_minor_check CHECK ((settlement_amount_minor >= 0))
);


--
-- Name: finance_payout_amount_revision_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_payout_amount_revision ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_payout_amount_revision_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_payout_attempt; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_payout_attempt (
    id bigint NOT NULL,
    sequence integer NOT NULL,
    amount_eur_cents bigint NOT NULL,
    currency character varying(3) NOT NULL,
    rail character varying(20) NOT NULL,
    provider_mode character varying(16) NOT NULL,
    status character varying(24) NOT NULL,
    idempotency_key character varying(160) NOT NULL,
    request_fingerprint character varying(64) NOT NULL,
    fencing_generation bigint NOT NULL,
    committed_at timestamp with time zone,
    result_at timestamp with time zone,
    failure_code character varying(64) NOT NULL,
    provider_request_id character varying(255) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    amount_revision_id bigint,
    operator_id bigint,
    payout_id bigint NOT NULL,
    instruction_version_id bigint NOT NULL,
    CONSTRAINT fin_payout_attempt_known_mode CHECK (((provider_mode)::text = ANY ((ARRAY['test'::character varying, 'live'::character varying])::text[]))),
    CONSTRAINT fin_payout_attempt_pairing CHECK (((((currency)::text = 'DZD'::text) AND ((rail)::text = 'manual'::text)) OR (((currency)::text = 'EUR'::text) AND ((rail)::text = 'stripe_transfer'::text)))),
    CONSTRAINT fin_payout_attempt_positive CHECK ((amount_eur_cents > 0)),
    CONSTRAINT finance_payout_attempt_amount_eur_cents_check CHECK ((amount_eur_cents >= 0)),
    CONSTRAINT finance_payout_attempt_fencing_generation_check CHECK ((fencing_generation >= 0)),
    CONSTRAINT finance_payout_attempt_sequence_check CHECK ((sequence >= 0))
);


--
-- Name: finance_payout_attempt_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_payout_attempt ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_payout_attempt_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_payout_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_payout_event (
    id bigint NOT NULL,
    event_uuid uuid NOT NULL,
    sequence bigint NOT NULL,
    previous_state character varying(16) NOT NULL,
    new_state character varying(16) NOT NULL,
    reason_code character varying(64) NOT NULL,
    source character varying(32) NOT NULL,
    occurred_at timestamp with time zone NOT NULL,
    recorded_at timestamp with time zone NOT NULL,
    actor_id bigint,
    ledger_transaction_id bigint,
    payout_id bigint NOT NULL,
    evidence_id bigint,
    operation_id bigint,
    CONSTRAINT finance_payout_event_sequence_check CHECK ((sequence >= 0))
);


--
-- Name: finance_payout_event_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_payout_event ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_payout_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_payout_evidence; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_payout_evidence (
    id bigint NOT NULL,
    public_reference uuid NOT NULL,
    purpose character varying(24) NOT NULL,
    logical_store character varying(24) NOT NULL,
    object_key character varying(512) NOT NULL,
    encryption_key_id character varying(64) NOT NULL,
    digest character varying(64) NOT NULL,
    mime_type character varying(64) NOT NULL,
    size_bytes bigint,
    upload_state character varying(16) NOT NULL,
    retention_class character varying(32) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    owner_id bigint NOT NULL,
    CONSTRAINT fin_payout_evidence_store CHECK (((logical_store)::text = 'payout'::text)),
    CONSTRAINT finance_payout_evidence_size_bytes_check CHECK ((size_bytes >= 0))
);


--
-- Name: finance_payout_evidence_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_payout_evidence ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_payout_evidence_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_payout_funding_allocation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_payout_funding_allocation (
    id bigint NOT NULL,
    allocation_key character varying(160) NOT NULL,
    source_charge_id character varying(255) NOT NULL,
    provider character varying(16) NOT NULL,
    provider_mode character varying(16) NOT NULL,
    purpose character varying(24) NOT NULL,
    currency character varying(3) NOT NULL,
    amount_eur_cents bigint NOT NULL,
    unavailable_reason character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    attempt_id bigint,
    payout_id bigint NOT NULL,
    source_attempt_id bigint NOT NULL,
    CONSTRAINT fin_payout_allocation_positive CHECK ((amount_eur_cents > 0)),
    CONSTRAINT finance_payout_funding_allocation_amount_eur_cents_check CHECK ((amount_eur_cents >= 0))
);


--
-- Name: finance_payout_funding_allocation_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_payout_funding_allocation ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_payout_funding_allocation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_payout_funding_release; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_payout_funding_release (
    id bigint NOT NULL,
    reason_code character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    actor_id bigint,
    allocation_id bigint NOT NULL
);


--
-- Name: finance_payout_funding_release_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_payout_funding_release ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_payout_funding_release_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_payout_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_payout ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_payout_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_payout_identity_attestation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_payout_identity_attestation (
    id bigint NOT NULL,
    public_reference uuid NOT NULL,
    given_name_encrypted text NOT NULL,
    family_name_encrypted text NOT NULL,
    aliases_encrypted text NOT NULL,
    script_metadata character varying(64) NOT NULL,
    policy_version character varying(64) NOT NULL,
    attested_at timestamp with time zone NOT NULL,
    attested_by_id bigint NOT NULL,
    kyc_submission_id bigint NOT NULL,
    supersedes_id bigint,
    traveler_id bigint NOT NULL
);


--
-- Name: finance_payout_identity_attestation_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_payout_identity_attestation ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_payout_identity_attestation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_payout_identity_review_assignment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_payout_identity_review_assignment (
    id bigint NOT NULL,
    public_reference uuid NOT NULL,
    created_at timestamp with time zone NOT NULL,
    closed_at timestamp with time zone,
    assigned_by_id bigint NOT NULL,
    kyc_submission_id bigint NOT NULL,
    reviewer_id bigint NOT NULL,
    traveler_id bigint NOT NULL
);


--
-- Name: finance_payout_identity_review_assignment_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_payout_identity_review_assignment ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_payout_identity_review_assignment_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_payout_identity_revocation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_payout_identity_revocation (
    id bigint NOT NULL,
    reason_code character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    actor_id bigint NOT NULL,
    attestation_id bigint NOT NULL
);


--
-- Name: finance_payout_identity_revocation_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_payout_identity_revocation ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_payout_identity_revocation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_payout_instruction_amendment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_payout_instruction_amendment (
    id bigint NOT NULL,
    sequence integer NOT NULL,
    confirmed_at timestamp with time zone NOT NULL,
    reason_code character varying(64) NOT NULL,
    expected_state character varying(16) NOT NULL,
    expected_state_version bigint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    payout_id bigint NOT NULL,
    reviewed_by_id bigint NOT NULL,
    traveler_id bigint NOT NULL,
    new_version_id bigint NOT NULL,
    old_version_id bigint NOT NULL,
    CONSTRAINT finance_payout_instruction_amendme_expected_state_version_check CHECK ((expected_state_version >= 0)),
    CONSTRAINT finance_payout_instruction_amendment_sequence_check CHECK ((sequence >= 0))
);


--
-- Name: finance_payout_instruction_amendment_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_payout_instruction_amendment ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_payout_instruction_amendment_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_payout_instruction_confirmation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_payout_instruction_confirmation (
    id bigint NOT NULL,
    public_reference uuid NOT NULL,
    expected_state_version bigint NOT NULL,
    confirmed_at timestamp with time zone NOT NULL,
    new_version_id bigint NOT NULL,
    payout_id bigint NOT NULL,
    traveler_id bigint NOT NULL,
    CONSTRAINT finance_payout_instruction_confirm_expected_state_version_check CHECK ((expected_state_version >= 0))
);


--
-- Name: finance_payout_instruction_confirmation_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_payout_instruction_confirmation ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_payout_instruction_confirmation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_payout_method_version; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_payout_method_version (
    id bigint NOT NULL,
    public_reference uuid NOT NULL,
    sequence integer NOT NULL,
    rail character varying(20) NOT NULL,
    currency character varying(3) NOT NULL,
    country character varying(2) NOT NULL,
    policy_version character varying(64) NOT NULL,
    consent_at timestamp with time zone NOT NULL,
    source character varying(32) NOT NULL,
    content_hash character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    created_by_id bigint,
    dzd_profile_revision_id bigint,
    method_id bigint NOT NULL,
    stripe_account_id bigint,
    CONSTRAINT fin_method_version_pairing CHECK (((((currency)::text = 'DZD'::text) AND ((rail)::text = 'manual'::text) AND (stripe_account_id IS NULL)) OR (((currency)::text = 'EUR'::text) AND (dzd_profile_revision_id IS NULL) AND ((rail)::text = 'stripe_transfer'::text)))),
    CONSTRAINT finance_payout_method_version_sequence_check CHECK ((sequence >= 0))
);


--
-- Name: finance_payout_method_version_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_payout_method_version ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_payout_method_version_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_payout_profile_review; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_payout_profile_review (
    id bigint NOT NULL,
    status character varying(24) NOT NULL,
    reason_code character varying(64) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    identity_attestation_id bigint NOT NULL,
    profile_id bigint NOT NULL,
    reviewer_id bigint NOT NULL
);


--
-- Name: finance_payout_profile_review_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_payout_profile_review ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_payout_profile_review_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_payout_provider_operation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_payout_provider_operation (
    id bigint NOT NULL,
    public_reference uuid NOT NULL,
    kind character varying(24) NOT NULL,
    account_scope character varying(255) NOT NULL,
    provider_mode character varying(16) NOT NULL,
    sequence integer NOT NULL,
    idempotency_key character varying(160) NOT NULL,
    request_fingerprint character varying(64) NOT NULL,
    provider_object_id character varying(255) NOT NULL,
    provider_request_id character varying(255) NOT NULL,
    status character varying(16) NOT NULL,
    amount_minor bigint,
    currency character varying(3) NOT NULL,
    retry_after timestamp with time zone,
    first_request_at timestamp with time zone,
    last_request_at timestamp with time zone,
    response_code smallint,
    created_at timestamp with time zone NOT NULL,
    attempt_id bigint,
    method_id bigint,
    amount_reversed_minor bigint NOT NULL,
    balance_transaction_id character varying(255) NOT NULL,
    destination_payment_id character varying(255) NOT NULL,
    failure_code character varying(64) NOT NULL,
    funding_allocation_id bigint,
    last_observed_at timestamp with time zone,
    observation_generation bigint NOT NULL,
    provider_object_status character varying(32) NOT NULL,
    reconciled_at timestamp with time zone,
    disbursement_id bigint,
    CONSTRAINT fin_payout_operation_known_mode CHECK (((provider_mode)::text = ANY ((ARRAY['test'::character varying, 'live'::character varying])::text[]))),
    CONSTRAINT fin_payout_operation_owner CHECK ((((attempt_id IS NOT NULL) AND (method_id IS NULL)) OR ((attempt_id IS NULL) AND ((kind)::text = 'account_create'::text) AND (method_id IS NOT NULL)))),
    CONSTRAINT finance_payout_provider_operation_amount_minor_check CHECK ((amount_minor >= 0)),
    CONSTRAINT finance_payout_provider_operation_amount_reversed_minor_check CHECK ((amount_reversed_minor >= 0)),
    CONSTRAINT finance_payout_provider_operation_observation_generation_check CHECK ((observation_generation >= 0)),
    CONSTRAINT finance_payout_provider_operation_response_code_check CHECK ((response_code >= 0)),
    CONSTRAINT finance_payout_provider_operation_sequence_check CHECK ((sequence >= 0))
);


--
-- Name: finance_payout_provider_operation_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_payout_provider_operation ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_payout_provider_operation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_provider_dispute; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_provider_dispute (
    id bigint NOT NULL,
    provider character varying(16) NOT NULL,
    platform_id character varying(255) NOT NULL,
    provider_mode character varying(16) NOT NULL,
    provider_object_id character varying(255) NOT NULL,
    source_charge_id character varying(255) NOT NULL,
    amount_minor bigint NOT NULL,
    currency character varying(3) NOT NULL,
    canonical_amount_eur_cents bigint,
    status character varying(32) NOT NULL,
    funds_withdrawn_reference character varying(255) NOT NULL,
    funds_reinstated_reference character varying(255) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    source_attempt_id bigint,
    CONSTRAINT finance_provider_dispute_amount_minor_check CHECK ((amount_minor >= 0)),
    CONSTRAINT finance_provider_dispute_canonical_amount_eur_cents_check CHECK ((canonical_amount_eur_cents >= 0))
);


--
-- Name: finance_provider_dispute_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_provider_dispute ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_provider_dispute_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_provider_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_provider_event (
    id bigint NOT NULL,
    provider character varying(16) NOT NULL,
    provider_event_id character varying(255) NOT NULL,
    event_type character varying(128) NOT NULL,
    signature_verified boolean NOT NULL,
    payload jsonb NOT NULL,
    processing_result character varying(12) NOT NULL,
    processing_note character varying(255) NOT NULL,
    received_at timestamp with time zone NOT NULL,
    processed_at timestamp with time zone,
    attempt_id bigint,
    order_id bigint,
    last_error_code character varying(64) NOT NULL,
    last_error_message character varying(500) NOT NULL,
    next_retry_at timestamp with time zone,
    normalized_event jsonb NOT NULL,
    payload_fingerprint character varying(64) NOT NULL,
    processing_attempts smallint NOT NULL,
    processing_started_at timestamp with time zone,
    api_version character varying(64) NOT NULL,
    endpoint_scope character varying(24) NOT NULL,
    provider_account_id character varying(255) NOT NULL,
    provider_mode character varying(16) NOT NULL,
    object_id character varying(255) NOT NULL,
    object_type character varying(64) NOT NULL,
    CONSTRAINT finance_provider_event_processing_attempts_check CHECK ((processing_attempts >= 0))
);


--
-- Name: finance_provider_event_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_provider_event ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_provider_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_scheduled_job; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_scheduled_job (
    id bigint NOT NULL,
    key character varying(160) NOT NULL,
    kind character varying(32) NOT NULL,
    payload jsonb NOT NULL,
    run_at timestamp with time zone NOT NULL,
    status character varying(12) NOT NULL,
    attempts smallint NOT NULL,
    max_attempts smallint NOT NULL,
    locked_at timestamp with time zone,
    locked_by character varying(64) NOT NULL,
    last_error character varying(500) NOT NULL,
    last_result character varying(255) NOT NULL,
    completed_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    last_attempt_at timestamp with time zone,
    last_error_code character varying(64) NOT NULL,
    resolution character varying(16) NOT NULL,
    resolution_reason character varying(500) NOT NULL,
    resolved_at timestamp with time zone,
    resolved_by_id bigint,
    CONSTRAINT fin_job_resolution_complete CHECK (((((resolution)::text = ''::text) AND ((resolution_reason)::text = ''::text) AND (resolved_at IS NULL) AND (resolved_by_id IS NULL)) OR ((NOT ((resolution)::text = ''::text)) AND (resolved_at IS NOT NULL) AND (NOT ((resolution_reason)::text = ''::text)) AND ((status)::text = 'failed'::text)))),
    CONSTRAINT finance_scheduled_job_attempts_check CHECK ((attempts >= 0)),
    CONSTRAINT finance_scheduled_job_max_attempts_check CHECK ((max_attempts >= 0))
);


--
-- Name: finance_scheduled_job_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_scheduled_job ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_scheduled_job_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_stripe_disbursement; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_stripe_disbursement (
    id bigint NOT NULL,
    public_reference uuid NOT NULL,
    provider_mode character varying(16) NOT NULL,
    currency character varying(3) NOT NULL,
    amount_minor bigint NOT NULL,
    method character varying(16) NOT NULL,
    external_account_id character varying(255) NOT NULL,
    status character varying(16) NOT NULL,
    provider_payout_id character varying(255) NOT NULL,
    balance_transaction_id character varying(255) NOT NULL,
    failure_balance_transaction_id character varying(255) NOT NULL,
    failure_code character varying(64) NOT NULL,
    arrival_estimate timestamp with time zone,
    observation_generation bigint NOT NULL,
    last_observed_at timestamp with time zone,
    submitted_at timestamp with time zone,
    paid_at timestamp with time zone,
    failed_at timestamp with time zone,
    returned_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    account_id bigint NOT NULL,
    CONSTRAINT fin_disbursement_known_mode CHECK (((provider_mode)::text = ANY ((ARRAY['test'::character varying, 'live'::character varying])::text[]))),
    CONSTRAINT fin_disbursement_paid_requires_timestamp CHECK (((NOT ((status)::text = 'paid'::text)) OR (paid_at IS NOT NULL))),
    CONSTRAINT fin_disbursement_positive CHECK ((amount_minor > 0)),
    CONSTRAINT fin_disbursement_rail CHECK ((((currency)::text = 'EUR'::text) AND ((method)::text = 'standard'::text))),
    CONSTRAINT finance_stripe_disbursement_amount_minor_check CHECK ((amount_minor >= 0)),
    CONSTRAINT finance_stripe_disbursement_observation_generation_check CHECK ((observation_generation >= 0))
);


--
-- Name: finance_stripe_disbursement_allocation; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_stripe_disbursement_allocation (
    id bigint NOT NULL,
    amount_eur_cents bigint NOT NULL,
    active boolean NOT NULL,
    released_reason character varying(64) NOT NULL,
    released_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    attempt_id bigint,
    disbursement_id bigint NOT NULL,
    payout_id bigint NOT NULL,
    CONSTRAINT fin_disbursement_allocation_positive CHECK ((amount_eur_cents > 0)),
    CONSTRAINT fin_disbursement_allocation_release_complete CHECK (((active AND (released_at IS NULL) AND ((released_reason)::text = ''::text)) OR ((NOT active) AND (released_at IS NOT NULL)))),
    CONSTRAINT finance_stripe_disbursement_allocation_amount_eur_cents_check CHECK ((amount_eur_cents >= 0))
);


--
-- Name: finance_stripe_disbursement_allocation_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_stripe_disbursement_allocation ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_stripe_disbursement_allocation_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_stripe_disbursement_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_stripe_disbursement ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_stripe_disbursement_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_stripe_payout_account; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_stripe_payout_account (
    id bigint NOT NULL,
    public_reference uuid NOT NULL,
    platform_id character varying(255) NOT NULL,
    provider_account_id character varying(255) NOT NULL,
    provider_mode character varying(16) NOT NULL,
    declared_country character varying(2) NOT NULL,
    verified_country character varying(2) NOT NULL,
    creation_operation_key character varying(160) NOT NULL,
    status character varying(24) NOT NULL,
    active boolean NOT NULL,
    transfers_status character varying(24) NOT NULL,
    payouts_enabled boolean NOT NULL,
    details_submitted boolean NOT NULL,
    requirement_codes jsonb NOT NULL,
    disabled_reason character varying(64) NOT NULL,
    external_account_id character varying(255) NOT NULL,
    eur_bank_present boolean NOT NULL,
    readiness_checked_at timestamp with time zone,
    readiness_generation bigint NOT NULL,
    payout_schedule_interval character varying(16) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    traveler_id bigint NOT NULL,
    controller_summary jsonb NOT NULL,
    default_currency character varying(3) NOT NULL,
    past_due_codes jsonb NOT NULL,
    pending_verification_codes jsonb NOT NULL,
    requirements_deadline timestamp with time zone,
    status_reason character varying(64) NOT NULL,
    CONSTRAINT fin_stripe_account_known_mode CHECK (((provider_mode)::text = ANY ((ARRAY['test'::character varying, 'live'::character varying])::text[]))),
    CONSTRAINT finance_stripe_payout_account_readiness_generation_check CHECK ((readiness_generation >= 0))
);


--
-- Name: finance_stripe_payout_account_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_stripe_payout_account ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_stripe_payout_account_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: finance_traveler_payout_method; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_traveler_payout_method (
    id bigint NOT NULL,
    method character varying(20) NOT NULL,
    provider_account_id character varying(255) NOT NULL,
    country_code character varying(2) NOT NULL,
    payouts_enabled boolean NOT NULL,
    capabilities jsonb NOT NULL,
    capability_checked_at timestamp with time zone,
    is_default boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    traveler_id bigint NOT NULL,
    currency character varying(3) NOT NULL,
    enabled boolean NOT NULL,
    public_reference uuid NOT NULL,
    revision bigint NOT NULL,
    status character varying(24) NOT NULL,
    status_reason character varying(64) NOT NULL,
    current_version_id bigint,
    CONSTRAINT fin_payout_method_pairing CHECK (((((currency)::text = ''::text) AND (current_version_id IS NULL) AND (NOT enabled)) OR (((currency)::text = 'DZD'::text) AND ((method)::text = 'manual'::text)) OR (((currency)::text = 'EUR'::text) AND ((method)::text = 'stripe_connect'::text)))),
    CONSTRAINT finance_traveler_payout_method_revision_check CHECK ((revision >= 0))
);


--
-- Name: finance_traveler_payout_method_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.finance_traveler_payout_method ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.finance_traveler_payout_method_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: handover_attempt; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.handover_attempt (
    id bigint NOT NULL,
    kind character varying(16) NOT NULL,
    result character varying(20) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    actor_id bigint,
    code_id bigint,
    deal_id bigint NOT NULL
);


--
-- Name: handover_attempt_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.handover_attempt ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.handover_attempt_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: handover_code_access; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.handover_code_access (
    id bigint NOT NULL,
    purpose character varying(32) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    actor_id bigint,
    code_id bigint NOT NULL,
    deal_id bigint NOT NULL
);


--
-- Name: handover_code_access_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.handover_code_access ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.handover_code_access_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: handover_deal_code; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.handover_deal_code (
    id bigint NOT NULL,
    kind character varying(16) NOT NULL,
    status character varying(16) NOT NULL,
    code_hash character varying(64) NOT NULL,
    sealed_code text NOT NULL,
    code_length smallint NOT NULL,
    available_at timestamp with time zone,
    released_at timestamp with time zone,
    failed_attempts smallint NOT NULL,
    lockout_count smallint NOT NULL,
    locked_until timestamp with time zone,
    used_at timestamp with time zone,
    superseded_at timestamp with time zone,
    rotation smallint NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deal_id bigint NOT NULL,
    issued_to_id bigint NOT NULL,
    used_by_id bigint,
    CONSTRAINT handover_buffered_requires_available_at CHECK (((NOT ((status)::text = 'buffered'::text)) OR (available_at IS NOT NULL))),
    CONSTRAINT handover_code_material_present CHECK (((NOT ((code_hash)::text = ''::text)) AND (NOT (sealed_code = ''::text)))),
    CONSTRAINT handover_deal_code_code_length_check CHECK ((code_length >= 0)),
    CONSTRAINT handover_deal_code_failed_attempts_check CHECK ((failed_attempts >= 0)),
    CONSTRAINT handover_deal_code_lockout_count_check CHECK ((lockout_count >= 0)),
    CONSTRAINT handover_deal_code_rotation_check CHECK ((rotation >= 0)),
    CONSTRAINT handover_used_requires_actor CHECK (((NOT ((status)::text = 'used'::text)) OR ((used_at IS NOT NULL) AND (used_by_id IS NOT NULL))))
);


--
-- Name: handover_deal_code_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.handover_deal_code ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.handover_deal_code_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: kyc_submission; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.kyc_submission (
    id bigint NOT NULL,
    document_type character varying(24) NOT NULL,
    front_image_key character varying(512) NOT NULL,
    back_image_key character varying(512) NOT NULL,
    selfie_image_key character varying(512) NOT NULL,
    status character varying(16) NOT NULL,
    rejection_reason text NOT NULL,
    reviewed_by_id bigint,
    reviewed_at timestamp with time zone,
    expires_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    user_id bigint NOT NULL,
    idempotency_key character varying(32) NOT NULL
);


--
-- Name: kyc_submission_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.kyc_submission ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.kyc_submission_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: locations_airport_locality_mapping; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.locations_airport_locality_mapping (
    id bigint NOT NULL,
    relationship_type character varying(16) NOT NULL,
    is_primary boolean NOT NULL,
    source character varying(96) NOT NULL,
    source_id character varying(160) NOT NULL,
    source_version character varying(96) NOT NULL,
    active boolean NOT NULL,
    metadata jsonb NOT NULL,
    airport_id bigint NOT NULL,
    locality_id bigint NOT NULL
);


--
-- Name: locations_airport_locality_mapping_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.locations_airport_locality_mapping ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.locations_airport_locality_mapping_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: locations_country; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.locations_country (
    code character varying(2) NOT NULL,
    name character varying(120) NOT NULL,
    normalized_name character varying(120) NOT NULL,
    source character varying(96) NOT NULL,
    source_id character varying(128) NOT NULL,
    source_version character varying(96) NOT NULL,
    active boolean NOT NULL,
    metadata jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: locations_geography_catalogue_import; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.locations_geography_catalogue_import (
    id bigint NOT NULL,
    content_sha256 character varying(64) NOT NULL,
    counts jsonb NOT NULL,
    applied_by_release character varying(128) NOT NULL,
    applied_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL
);


--
-- Name: locations_geography_catalogue_import_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.locations_geography_catalogue_import ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.locations_geography_catalogue_import_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: locations_location; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.locations_location (
    id bigint NOT NULL,
    kind character varying(24) NOT NULL,
    normalized_label character varying(500) NOT NULL,
    public_label character varying(255) NOT NULL,
    private_label character varying(500) NOT NULL,
    city character varying(120) NOT NULL,
    region character varying(120) NOT NULL,
    country_code character varying(2) NOT NULL,
    latitude numeric(9,6) NOT NULL,
    longitude numeric(9,6) NOT NULL,
    coarse_latitude numeric(9,6),
    coarse_longitude numeric(9,6),
    provider character varying(64) NOT NULL,
    source character varying(64) NOT NULL,
    provider_place_id character varying(255) NOT NULL,
    provider_metadata jsonb NOT NULL,
    "precision" character varying(24) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    airport_id character varying(3),
    created_by_id bigint,
    owner_id bigint,
    coordinate_dataset_version character varying(64) NOT NULL,
    coordinates_trusted boolean NOT NULL,
    canonical_place_id bigint,
    CONSTRAINT locations_coarse_coords_pair CHECK ((((coarse_latitude IS NULL) AND (coarse_longitude IS NULL)) OR ((coarse_latitude IS NOT NULL) AND (coarse_longitude IS NOT NULL)))),
    CONSTRAINT locations_coarse_lat_range CHECK (((coarse_latitude IS NULL) OR ((coarse_latitude >= ('-90'::integer)::numeric) AND (coarse_latitude <= (90)::numeric)))),
    CONSTRAINT locations_coarse_lon_range CHECK (((coarse_longitude IS NULL) OR ((coarse_longitude >= ('-180'::integer)::numeric) AND (coarse_longitude <= (180)::numeric)))),
    CONSTRAINT locations_coordinate_trust_pair CHECK (((((coordinate_dataset_version)::text = ''::text) AND (NOT coordinates_trusted)) OR (coordinates_trusted AND (NOT ((coordinate_dataset_version)::text = ''::text))))),
    CONSTRAINT locations_latitude_range CHECK (((latitude >= ('-90'::integer)::numeric) AND (latitude <= (90)::numeric))),
    CONSTRAINT locations_longitude_range CHECK (((longitude >= ('-180'::integer)::numeric) AND (longitude <= (180)::numeric)))
);


--
-- Name: locations_location_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.locations_location ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.locations_location_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: locations_place; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.locations_place (
    id bigint NOT NULL,
    place_type character varying(24) NOT NULL,
    source character varying(96) NOT NULL,
    source_id character varying(160) NOT NULL,
    source_version character varying(96) NOT NULL,
    name character varying(255) NOT NULL,
    normalized_name character varying(255) NOT NULL,
    admin_level character varying(48) NOT NULL,
    latitude numeric(9,6),
    longitude numeric(9,6),
    iata_code character varying(3) NOT NULL,
    icao_code character varying(4) NOT NULL,
    airport_type character varying(40) NOT NULL,
    passenger_use boolean NOT NULL,
    active boolean NOT NULL,
    metadata jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    country_id character varying(2) NOT NULL,
    legacy_airport_id character varying(3),
    parent_id bigint,
    CONSTRAINT geo_place_airport_coords_required CHECK (((NOT ((place_type)::text = 'airport'::text)) OR ((latitude IS NOT NULL) AND (longitude IS NOT NULL)))),
    CONSTRAINT geo_place_coords_pair CHECK ((((latitude IS NULL) AND (longitude IS NULL)) OR ((latitude IS NOT NULL) AND (longitude IS NOT NULL)))),
    CONSTRAINT geo_place_iata_airport_only CHECK ((((iata_code)::text = ''::text) OR ((place_type)::text = 'airport'::text))),
    CONSTRAINT geo_place_icao_airport_only CHECK ((((icao_code)::text = ''::text) OR ((place_type)::text = 'airport'::text))),
    CONSTRAINT geo_place_latitude_range CHECK (((latitude IS NULL) OR ((latitude >= ('-90'::integer)::numeric) AND (latitude <= (90)::numeric)))),
    CONSTRAINT geo_place_longitude_range CHECK (((longitude IS NULL) OR ((longitude >= ('-180'::integer)::numeric) AND (longitude <= (180)::numeric)))),
    CONSTRAINT geo_place_passenger_airport_only CHECK (((NOT passenger_use) OR ((place_type)::text = 'airport'::text)))
);


--
-- Name: locations_place_alternate_name; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.locations_place_alternate_name (
    id bigint NOT NULL,
    name character varying(255) NOT NULL,
    normalized_name character varying(255) NOT NULL,
    language character varying(16) NOT NULL,
    source character varying(96) NOT NULL,
    source_id character varying(160) NOT NULL,
    source_version character varying(96) NOT NULL,
    active boolean NOT NULL,
    metadata jsonb NOT NULL,
    place_id bigint NOT NULL
);


--
-- Name: locations_place_alternate_name_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.locations_place_alternate_name ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.locations_place_alternate_name_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: locations_place_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.locations_place ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.locations_place_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: matching_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.matching_event (
    id bigint NOT NULL,
    kind character varying(24) NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    actor_id bigint,
    match_id bigint NOT NULL,
    offer_id bigint
);


--
-- Name: matching_event_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.matching_event ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.matching_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: matching_match; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.matching_match (
    id bigint NOT NULL,
    status character varying(16) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    parcel_id bigint NOT NULL,
    sender_id bigint NOT NULL,
    traveler_id bigint NOT NULL,
    trip_id bigint,
    end_leg_id bigint,
    journey_id bigint,
    start_leg_id bigint,
    compatibility_snapshot jsonb NOT NULL,
    matched_distance_meters bigint,
    matching_version character varying(32) NOT NULL,
    ranking_snapshot jsonb NOT NULL,
    CONSTRAINT match_legacy_or_v1_route CHECK ((((end_leg_id IS NULL) AND (journey_id IS NULL) AND (start_leg_id IS NULL) AND (trip_id IS NOT NULL)) OR ((end_leg_id IS NOT NULL) AND (journey_id IS NOT NULL) AND (start_leg_id IS NOT NULL) AND (trip_id IS NULL)))),
    CONSTRAINT matching_match_matched_distance_meters_check CHECK ((matched_distance_meters >= 0))
);


--
-- Name: matching_match_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.matching_match ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.matching_match_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: matching_offer; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.matching_offer (
    id bigint NOT NULL,
    proposed_by character varying(10) NOT NULL,
    base_amount_dzd integer NOT NULL,
    base_fee_dzd integer NOT NULL,
    commission_dzd integer NOT NULL,
    total_dzd integer NOT NULL,
    status character varying(12) NOT NULL,
    note text NOT NULL,
    expires_at timestamp with time zone,
    responded_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    match_id bigint NOT NULL,
    parent_offer_id bigint,
    proposer_id bigint NOT NULL,
    business_settings_version_id bigint,
    commission_rate_bps smallint,
    currency character varying(3) NOT NULL,
    economics_version character varying(16) NOT NULL,
    platform_fee_minor bigint,
    pricing_version character varying(32) NOT NULL,
    sender_total_minor bigint,
    terms_snapshot jsonb NOT NULL,
    traveler_reward_minor bigint,
    CONSTRAINT matching_offer_base_amount_dzd_check CHECK ((base_amount_dzd >= 0)),
    CONSTRAINT matching_offer_base_fee_dzd_check CHECK ((base_fee_dzd >= 0)),
    CONSTRAINT matching_offer_commission_dzd_check CHECK ((commission_dzd >= 0)),
    CONSTRAINT matching_offer_commission_rate_bps_check CHECK ((commission_rate_bps >= 0)),
    CONSTRAINT matching_offer_platform_fee_minor_check CHECK ((platform_fee_minor >= 0)),
    CONSTRAINT matching_offer_sender_total_minor_check CHECK ((sender_total_minor >= 0)),
    CONSTRAINT matching_offer_total_dzd_check CHECK ((total_dzd >= 0)),
    CONSTRAINT matching_offer_traveler_reward_minor_check CHECK ((traveler_reward_minor >= 0)),
    CONSTRAINT offer_economics_consistent CHECK (((((currency)::text = 'DZD'::text) AND ((economics_version)::text = 'legacy_dzd'::text)) OR ((base_amount_dzd = 0) AND (base_fee_dzd = 0) AND (business_settings_version_id IS NOT NULL) AND (commission_dzd = 0) AND (commission_rate_bps >= 0) AND (commission_rate_bps <= 10000) AND ((currency)::text = 'EUR'::text) AND ((economics_version)::text = 'v1_eur'::text) AND (platform_fee_minor >= 0) AND (sender_total_minor = (traveler_reward_minor + platform_fee_minor)) AND (total_dzd = 0) AND (traveler_reward_minor > 0))))
);


--
-- Name: matching_offer_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.matching_offer ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.matching_offer_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: notification; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification (
    id bigint NOT NULL,
    channel character varying(64) NOT NULL,
    event_id character varying(64) NOT NULL,
    payload jsonb NOT NULL,
    read_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    recipient_id bigint NOT NULL
);


--
-- Name: notification_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.notification ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.notification_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: notification_outbound_message; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification_outbound_message (
    id bigint NOT NULL,
    key character varying(160) NOT NULL,
    kind character varying(32) NOT NULL,
    channel character varying(16) NOT NULL,
    to_email character varying(254) NOT NULL,
    context jsonb NOT NULL,
    secret_ref character varying(64) NOT NULL,
    status character varying(12) NOT NULL,
    attempts smallint NOT NULL,
    max_attempts smallint NOT NULL,
    next_attempt_at timestamp with time zone,
    last_error character varying(500) NOT NULL,
    transport_event_id character varying(64) NOT NULL,
    dispatched_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deal_id bigint,
    recipient_user_id bigint,
    language character varying(2) NOT NULL,
    CONSTRAINT notification_outbound_message_attempts_check CHECK ((attempts >= 0)),
    CONSTRAINT notification_outbound_message_max_attempts_check CHECK ((max_attempts >= 0)),
    CONSTRAINT outbound_dispatched_requires_timestamp CHECK ((((status)::text = 'pending'::text) OR ((status)::text = 'cancelled'::text) OR (dispatched_at IS NOT NULL) OR ((status)::text = 'failed'::text)))
);


--
-- Name: notification_outbound_message_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.notification_outbound_message ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.notification_outbound_message_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: notification_outbound_secret; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification_outbound_secret (
    id uuid NOT NULL,
    key character varying(160) NOT NULL,
    purpose character varying(32) NOT NULL,
    sealed_value text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL
);


--
-- Name: notification_preference; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification_preference (
    id bigint NOT NULL,
    messages_enabled boolean NOT NULL,
    marketplace_enabled boolean NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    user_id bigint NOT NULL
);


--
-- Name: notification_preference_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.notification_preference ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.notification_preference_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: notification_push_device; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification_push_device (
    id bigint NOT NULL,
    provider character varying(8) NOT NULL,
    platform character varying(8) NOT NULL,
    installation_id uuid NOT NULL,
    token text NOT NULL,
    token_fingerprint character varying(64) NOT NULL,
    app_version character varying(32) NOT NULL,
    active boolean NOT NULL,
    last_seen_at timestamp with time zone NOT NULL,
    last_success_at timestamp with time zone,
    last_failure_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    user_id bigint NOT NULL
);


--
-- Name: notification_push_device_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.notification_push_device ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.notification_push_device_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: parcels_delivery; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parcels_delivery (
    parcelrequest_ptr_id bigint NOT NULL,
    base_amount_dzd integer,
    schema_version smallint NOT NULL,
    pickup_location_id bigint,
    delivery_location_id bigint,
    ready_window_start timestamp with time zone,
    ready_window_end timestamp with time zone,
    actual_weight_kg numeric(6,2),
    length_cm numeric(6,2),
    width_cm numeric(6,2),
    height_cm numeric(6,2),
    declared_value_eur_cents bigint,
    traveler_reward_eur_cents bigint,
    title character varying(160) NOT NULL,
    category character varying(32) NOT NULL,
    handling_notes text NOT NULL,
    fragile boolean NOT NULL,
    description_is_accurate boolean NOT NULL,
    item_is_legal boolean NOT NULL,
    no_prohibited_goods boolean NOT NULL,
    declared_value_is_accurate boolean NOT NULL,
    customs_responsibilities_understood boolean NOT NULL,
    ranking_boost_expires_at timestamp with time zone,
    ranking_boost_weight smallint NOT NULL,
    delivery_place_id bigint,
    pickup_place_id bigint,
    boost_eur_cents bigint NOT NULL,
    CONSTRAINT parcels_delivery_base_amount_dzd_check CHECK ((base_amount_dzd >= 0)),
    CONSTRAINT parcels_delivery_boost_eur_cents_check CHECK ((boost_eur_cents >= 0)),
    CONSTRAINT parcels_delivery_declared_value_eur_cents_check CHECK ((declared_value_eur_cents >= 0)),
    CONSTRAINT parcels_delivery_dimensions CHECK ((((length_cm IS NULL) AND (width_cm IS NULL) AND (height_cm IS NULL)) OR ((length_cm > (0)::numeric) AND (length_cm <= (500)::numeric) AND (width_cm > (0)::numeric) AND (width_cm <= (500)::numeric) AND (height_cm > (0)::numeric) AND (height_cm <= (500)::numeric)))),
    CONSTRAINT parcels_delivery_locations_differ CHECK (((pickup_location_id IS NULL) OR (delivery_location_id IS NULL) OR (NOT ((pickup_location_id = delivery_location_id) AND (pickup_location_id IS NOT NULL) AND (delivery_location_id IS NOT NULL))))),
    CONSTRAINT parcels_delivery_ranking_boost_weight_check CHECK ((ranking_boost_weight >= 0)),
    CONSTRAINT parcels_delivery_ready_window CHECK ((((ready_window_start IS NULL) AND (ready_window_end IS NULL)) OR ((ready_window_start IS NOT NULL) AND (ready_window_end IS NOT NULL) AND (ready_window_start < ready_window_end)))),
    CONSTRAINT parcels_delivery_schema_ver CHECK ((schema_version = ANY (ARRAY[1, 2, 3]))),
    CONSTRAINT parcels_delivery_schema_version_check CHECK ((schema_version >= 0)),
    CONSTRAINT parcels_delivery_traveler_reward_eur_cents_check CHECK ((traveler_reward_eur_cents >= 0)),
    CONSTRAINT parcels_delivery_v1_no_dzd CHECK (((schema_version = 1) OR (base_amount_dzd IS NULL))),
    CONSTRAINT parcels_delivery_v1_required CHECK (((schema_version = ANY (ARRAY[1, 2])) OR ((schema_version = 3) AND (pickup_place_id IS NOT NULL) AND (delivery_place_id IS NOT NULL) AND (ready_window_start IS NOT NULL) AND (ready_window_end IS NOT NULL) AND (actual_weight_kg IS NOT NULL) AND (declared_value_eur_cents IS NOT NULL) AND (traveler_reward_eur_cents IS NOT NULL)))),
    CONSTRAINT parcels_delivery_v1_safety CHECK (((schema_version = ANY (ARRAY[1, 2])) OR ((schema_version = 3) AND description_is_accurate AND item_is_legal AND no_prohibited_goods AND declared_value_is_accurate AND customs_responsibilities_understood))),
    CONSTRAINT parcels_delivery_weight_range CHECK (((actual_weight_kg IS NULL) OR ((actual_weight_kg > (0)::numeric) AND (actual_weight_kg <= (100)::numeric)))),
    CONSTRAINT parcels_ranking_boost_pair CHECK ((((ranking_boost_expires_at IS NULL) AND (ranking_boost_weight = 0)) OR ((ranking_boost_expires_at IS NOT NULL) AND (ranking_boost_weight > 0))))
);


--
-- Name: parcels_media; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parcels_media (
    id bigint NOT NULL,
    bucket character varying(64) NOT NULL,
    object_key character varying(255) NOT NULL,
    content_type character varying(64) NOT NULL,
    bytes integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    parcel_id bigint,
    idempotency_key character varying(64) NOT NULL,
    purpose character varying(16) NOT NULL,
    uploaded_by_id bigint,
    CONSTRAINT parcels_media_bytes_check CHECK ((bytes >= 0)),
    CONSTRAINT parcels_media_owned CHECK (((parcel_id IS NOT NULL) OR (uploaded_by_id IS NOT NULL)))
);


--
-- Name: parcels_media_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.parcels_media ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.parcels_media_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: parcels_product; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parcels_product (
    parcelrequest_ptr_id bigint NOT NULL,
    product_url character varying(500) NOT NULL,
    store_name character varying(120) NOT NULL,
    product_price_dzd integer NOT NULL,
    CONSTRAINT parcels_product_product_price_dzd_check CHECK ((product_price_dzd >= 0))
);


--
-- Name: parcels_request; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.parcels_request (
    id bigint NOT NULL,
    kind character varying(12) NOT NULL,
    pickup_city character varying(80) NOT NULL,
    delivery_city character varying(80) NOT NULL,
    weight_kg smallint,
    item_type character varying(16) NOT NULL,
    description text NOT NULL,
    deadline_at timestamp with time zone,
    status character varying(16) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    destination_id character varying(3),
    origin_id character varying(3),
    sender_id bigint NOT NULL,
    target_traveler_id bigint,
    CONSTRAINT parcels_origin_neq_destination CHECK ((NOT ((origin_id)::text = (destination_id)::text))),
    CONSTRAINT parcels_request_weight_kg_check CHECK ((weight_kg >= 0))
);


--
-- Name: parcels_request_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.parcels_request ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.parcels_request_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: payments_event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.payments_event (
    id bigint NOT NULL,
    provider character varying(12) NOT NULL,
    provider_event_id character varying(128) NOT NULL,
    kind character varying(24) NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    intent_id bigint NOT NULL
);


--
-- Name: payments_event_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.payments_event ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.payments_event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: payments_intent; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.payments_intent (
    id bigint NOT NULL,
    provider character varying(12) NOT NULL,
    provider_intent_id character varying(128) NOT NULL,
    amount_minor integer NOT NULL,
    currency character varying(3) NOT NULL,
    status character varying(24) NOT NULL,
    client_idempotency_key character varying(64) NOT NULL,
    failure_code character varying(64) NOT NULL,
    failure_message character varying(255) NOT NULL,
    succeeded_at timestamp with time zone,
    refunded_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    offer_id bigint NOT NULL,
    payer_id bigint NOT NULL,
    CONSTRAINT payments_intent_amount_minor_check CHECK ((amount_minor >= 0))
);


--
-- Name: payments_intent_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.payments_intent ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.payments_intent_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: payments_refund; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.payments_refund (
    id bigint NOT NULL,
    amount_minor integer NOT NULL,
    currency character varying(3) NOT NULL,
    provider character varying(12) NOT NULL,
    provider_refund_id character varying(128) NOT NULL,
    reason character varying(64) NOT NULL,
    status character varying(12) NOT NULL,
    succeeded_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    intent_id bigint NOT NULL,
    CONSTRAINT payments_refund_amount_minor_check CHECK ((amount_minor >= 0))
);


--
-- Name: payments_refund_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.payments_refund ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.payments_refund_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: ratings_rating; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ratings_rating (
    id bigint NOT NULL,
    rater_role character varying(10) NOT NULL,
    score smallint NOT NULL,
    tags jsonb NOT NULL,
    comment text NOT NULL,
    review_window_ends_at timestamp with time zone NOT NULL,
    revealed_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    deal_id bigint NOT NULL,
    ratee_id bigint NOT NULL,
    rater_id bigint NOT NULL,
    CONSTRAINT ratings_rater_neq_ratee CHECK ((NOT (rater_id = ratee_id))),
    CONSTRAINT ratings_rating_score_check CHECK ((score >= 0)),
    CONSTRAINT ratings_score_range CHECK (((score >= 1) AND (score <= 5)))
);


--
-- Name: ratings_rating_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.ratings_rating ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.ratings_rating_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: token_blacklist_blacklistedtoken; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.token_blacklist_blacklistedtoken (
    id bigint NOT NULL,
    blacklisted_at timestamp with time zone NOT NULL,
    token_id bigint NOT NULL
);


--
-- Name: token_blacklist_blacklistedtoken_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.token_blacklist_blacklistedtoken ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.token_blacklist_blacklistedtoken_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: token_blacklist_outstandingtoken; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.token_blacklist_outstandingtoken (
    id bigint NOT NULL,
    token text NOT NULL,
    created_at timestamp with time zone,
    expires_at timestamp with time zone NOT NULL,
    user_id bigint,
    jti character varying(255) NOT NULL
);


--
-- Name: token_blacklist_outstandingtoken_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.token_blacklist_outstandingtoken ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.token_blacklist_outstandingtoken_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: trips_airport; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trips_airport (
    iata character varying(3) NOT NULL,
    city character varying(80) NOT NULL,
    name character varying(120) NOT NULL,
    country character varying(2) NOT NULL
);


--
-- Name: trips_journey; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trips_journey (
    id bigint NOT NULL,
    status character varying(24) NOT NULL,
    published_at timestamp with time zone,
    notes text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    destination_location_id bigint,
    legacy_trip_id bigint,
    start_location_id bigint,
    traveler_id bigint NOT NULL,
    destination_place_id bigint,
    schema_version smallint NOT NULL,
    start_place_id bigint,
    CONSTRAINT journey_canonical_endpoints CHECK ((((destination_place_id IS NULL) AND (schema_version = 1) AND (start_place_id IS NULL)) OR ((destination_place_id IS NOT NULL) AND (schema_version = 2) AND (start_place_id IS NOT NULL)))),
    CONSTRAINT journey_distinct_endpoints CHECK ((((start_location_id IS NULL) OR (destination_location_id IS NULL) OR (NOT ((start_location_id = destination_location_id) AND (start_location_id IS NOT NULL) AND (destination_location_id IS NOT NULL)))) AND ((start_place_id IS NULL) OR (destination_place_id IS NULL) OR (NOT ((start_place_id = destination_place_id) AND (start_place_id IS NOT NULL) AND (destination_place_id IS NOT NULL)))))),
    CONSTRAINT trips_journey_schema_version_check CHECK ((schema_version >= 0))
);


--
-- Name: trips_journey_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.trips_journey ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.trips_journey_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: trips_journey_leg; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trips_journey_leg (
    id bigint NOT NULL,
    "position" smallint NOT NULL,
    mode character varying(8) NOT NULL,
    depart_at timestamp with time zone NOT NULL,
    arrive_at timestamp with time zone,
    capacity_kg numeric(8,2) NOT NULL,
    distance_meters bigint,
    route_polyline text NOT NULL,
    allowed_detour_meters integer,
    route_metadata jsonb NOT NULL,
    flight_number character varying(16) NOT NULL,
    departure_airport_metadata jsonb NOT NULL,
    arrival_airport_metadata jsonb NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    destination_id bigint,
    journey_id bigint NOT NULL,
    origin_id bigint,
    route_captured_at timestamp with time zone,
    route_duration_seconds integer,
    route_profile character varying(32) NOT NULL,
    route_provider character varying(64) NOT NULL,
    destination_place_id bigint,
    origin_place_id bigint,
    CONSTRAINT journey_leg_arrival_after_departure CHECK (((arrive_at IS NULL) OR (arrive_at > depart_at))),
    CONSTRAINT journey_leg_canonical_endpoints CHECK ((((destination_place_id IS NULL) AND (origin_place_id IS NULL)) OR ((destination_place_id IS NOT NULL) AND (origin_place_id IS NOT NULL)))),
    CONSTRAINT journey_leg_distinct_endpoints CHECK ((((origin_id IS NULL) OR (destination_id IS NULL) OR (NOT ((origin_id = destination_id) AND (origin_id IS NOT NULL) AND (destination_id IS NOT NULL)))) AND ((origin_place_id IS NULL) OR (destination_place_id IS NULL) OR (NOT ((origin_place_id = destination_place_id) AND (origin_place_id IS NOT NULL) AND (destination_place_id IS NOT NULL)))))),
    CONSTRAINT journey_leg_positive_capacity CHECK ((capacity_kg > (0)::numeric)),
    CONSTRAINT trips_journey_leg_allowed_detour_meters_check CHECK ((allowed_detour_meters >= 0)),
    CONSTRAINT trips_journey_leg_distance_meters_check CHECK ((distance_meters >= 0)),
    CONSTRAINT trips_journey_leg_position_check CHECK (("position" >= 0)),
    CONSTRAINT trips_journey_leg_route_duration_seconds_check CHECK ((route_duration_seconds >= 0))
);


--
-- Name: trips_journey_leg_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.trips_journey_leg ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.trips_journey_leg_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: trips_journey_leg_proof; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trips_journey_leg_proof (
    id bigint NOT NULL,
    bucket character varying(64) NOT NULL,
    object_key character varying(512) NOT NULL,
    content_type character varying(64) NOT NULL,
    bytes integer NOT NULL,
    kind character varying(24) NOT NULL,
    metadata jsonb NOT NULL,
    status character varying(16) NOT NULL,
    reviewed_at timestamp with time zone,
    rejection_reason text NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    leg_id bigint NOT NULL,
    reviewer_id bigint,
    idempotency_key character varying(64) NOT NULL,
    CONSTRAINT journey_proof_review_consistent CHECK ((((rejection_reason = ''::text) AND (reviewed_at IS NULL) AND (reviewer_id IS NULL) AND ((status)::text = 'pending'::text)) OR ((rejection_reason = ''::text) AND (reviewed_at IS NOT NULL) AND (reviewer_id IS NOT NULL) AND ((status)::text = 'approved'::text)) OR ((reviewed_at IS NOT NULL) AND (reviewer_id IS NOT NULL) AND ((status)::text = 'rejected'::text) AND (NOT (rejection_reason = ''::text))))),
    CONSTRAINT trips_journey_leg_proof_bytes_check CHECK ((bytes >= 0))
);


--
-- Name: trips_journey_leg_proof_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.trips_journey_leg_proof ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.trips_journey_leg_proof_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: trips_media; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trips_media (
    id bigint NOT NULL,
    bucket character varying(64) NOT NULL,
    object_key character varying(255) NOT NULL,
    content_type character varying(64) NOT NULL,
    bytes integer NOT NULL,
    kind character varying(24) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    trip_id bigint NOT NULL,
    CONSTRAINT trips_media_bytes_check CHECK ((bytes >= 0))
);


--
-- Name: trips_media_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.trips_media ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.trips_media_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: trips_stopover; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trips_stopover (
    id bigint NOT NULL,
    "position" smallint NOT NULL,
    arrives_at timestamp with time zone,
    departs_at timestamp with time zone,
    airport_id character varying(3) NOT NULL,
    trip_id bigint NOT NULL,
    CONSTRAINT trips_stopover_position_check CHECK (("position" >= 0))
);


--
-- Name: trips_stopover_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.trips_stopover ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.trips_stopover_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: trips_tracking_snapshot; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trips_tracking_snapshot (
    id bigint NOT NULL,
    captured_at timestamp with time zone NOT NULL,
    status character varying(24) NOT NULL,
    latitude double precision,
    longitude double precision,
    altitude_m integer,
    speed_kph integer,
    raw jsonb NOT NULL,
    trip_id bigint NOT NULL
);


--
-- Name: trips_tracking_snapshot_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.trips_tracking_snapshot ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.trips_tracking_snapshot_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: trips_trip; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trips_trip (
    id bigint NOT NULL,
    departure_at timestamp with time zone NOT NULL,
    capacity_kg smallint NOT NULL,
    notes text NOT NULL,
    status character varying(16) NOT NULL,
    flight_number character varying(12) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    destination_id character varying(3) NOT NULL,
    origin_id character varying(3) NOT NULL,
    traveler_id bigint NOT NULL,
    CONSTRAINT trips_origin_neq_destination CHECK ((NOT ((origin_id)::text = (destination_id)::text))),
    CONSTRAINT trips_trip_capacity_kg_check CHECK ((capacity_kg >= 0))
);


--
-- Name: trips_trip_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.trips_trip ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.trips_trip_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: verification_handover_code; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.verification_handover_code (
    id bigint NOT NULL,
    kind character varying(16) NOT NULL,
    code_hash character varying(255) NOT NULL,
    status character varying(16) NOT NULL,
    attempts smallint NOT NULL,
    used_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    issued_to_id bigint NOT NULL,
    match_id bigint NOT NULL,
    used_by_id bigint,
    CONSTRAINT verification_handover_code_attempts_check CHECK ((attempts >= 0))
);


--
-- Name: verification_handover_code_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.verification_handover_code ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.verification_handover_code_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: wallet_entry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wallet_entry (
    id bigint NOT NULL,
    kind character varying(12) NOT NULL,
    amount_minor bigint NOT NULL,
    currency character varying(3) NOT NULL,
    key character varying(128) NOT NULL,
    source character varying(24) NOT NULL,
    source_id bigint,
    note character varying(255) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    wallet_id bigint NOT NULL
);


--
-- Name: wallet_entry_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.wallet_entry ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.wallet_entry_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: wallet_hold; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wallet_hold (
    id bigint NOT NULL,
    amount_minor bigint NOT NULL,
    currency character varying(3) NOT NULL,
    source character varying(24) NOT NULL,
    source_id bigint NOT NULL,
    status character varying(10) NOT NULL,
    opened_at timestamp with time zone NOT NULL,
    closed_at timestamp with time zone,
    wallet_id bigint NOT NULL,
    CONSTRAINT wallet_hold_amount_minor_check CHECK ((amount_minor >= 0))
);


--
-- Name: wallet_hold_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.wallet_hold ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.wallet_hold_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: wallet_wallet; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wallet_wallet (
    id bigint NOT NULL,
    currency character varying(3) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    user_id bigint NOT NULL
);


--
-- Name: wallet_wallet_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.wallet_wallet ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.wallet_wallet_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: wallet_withdrawal; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.wallet_withdrawal (
    id bigint NOT NULL,
    amount_minor bigint NOT NULL,
    currency character varying(3) NOT NULL,
    destination character varying(12) NOT NULL,
    destination_ref character varying(128) NOT NULL,
    status character varying(12) NOT NULL,
    sent_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    user_id bigint NOT NULL,
    wallet_id bigint NOT NULL,
    CONSTRAINT wallet_withdrawal_amount_minor_check CHECK ((amount_minor >= 0))
);


--
-- Name: wallet_withdrawal_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.wallet_withdrawal ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.wallet_withdrawal_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: accounts_emailverificationcode accounts_emailverificationcode_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_emailverificationcode
    ADD CONSTRAINT accounts_emailverificationcode_pkey PRIMARY KEY (id);


--
-- Name: accounts_oauthidentity accounts_oauthidentity_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_oauthidentity
    ADD CONSTRAINT accounts_oauthidentity_pkey PRIMARY KEY (id);


--
-- Name: accounts_passwordresetcode accounts_passwordresetcode_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_passwordresetcode
    ADD CONSTRAINT accounts_passwordresetcode_pkey PRIMARY KEY (id);


--
-- Name: accounts_user accounts_user_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_user
    ADD CONSTRAINT accounts_user_email_key UNIQUE (email);


--
-- Name: accounts_user_groups accounts_user_groups_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_user_groups
    ADD CONSTRAINT accounts_user_groups_pkey PRIMARY KEY (id);


--
-- Name: accounts_user_groups accounts_user_groups_user_id_group_id_59c0b32f_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_user_groups
    ADD CONSTRAINT accounts_user_groups_user_id_group_id_59c0b32f_uniq UNIQUE (user_id, group_id);


--
-- Name: accounts_user accounts_user_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_user
    ADD CONSTRAINT accounts_user_pkey PRIMARY KEY (id);


--
-- Name: accounts_user_user_permissions accounts_user_user_permi_user_id_permission_id_2ab516c2_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_user_user_permissions
    ADD CONSTRAINT accounts_user_user_permi_user_id_permission_id_2ab516c2_uniq UNIQUE (user_id, permission_id);


--
-- Name: accounts_user_user_permissions accounts_user_user_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_user_user_permissions
    ADD CONSTRAINT accounts_user_user_permissions_pkey PRIMARY KEY (id);


--
-- Name: accounts_user accounts_user_username_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_user
    ADD CONSTRAINT accounts_user_username_key UNIQUE (username);


--
-- Name: admin_panel_audit_log admin_panel_audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_panel_audit_log
    ADD CONSTRAINT admin_panel_audit_log_pkey PRIMARY KEY (id);


--
-- Name: admin_panel_invitation admin_panel_invitation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_panel_invitation
    ADD CONSTRAINT admin_panel_invitation_pkey PRIMARY KEY (id);


--
-- Name: admin_panel_invitation admin_panel_invitation_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_panel_invitation
    ADD CONSTRAINT admin_panel_invitation_token_hash_key UNIQUE (token_hash);


--
-- Name: auth_group auth_group_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group
    ADD CONSTRAINT auth_group_name_key UNIQUE (name);


--
-- Name: auth_group_permissions auth_group_permissions_group_id_permission_id_0cd325b0_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_group_id_permission_id_0cd325b0_uniq UNIQUE (group_id, permission_id);


--
-- Name: auth_group_permissions auth_group_permissions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_pkey PRIMARY KEY (id);


--
-- Name: auth_group auth_group_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group
    ADD CONSTRAINT auth_group_pkey PRIMARY KEY (id);


--
-- Name: auth_permission auth_permission_content_type_id_codename_01ab375a_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_content_type_id_codename_01ab375a_uniq UNIQUE (content_type_id, codename);


--
-- Name: auth_permission auth_permission_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_pkey PRIMARY KEY (id);


--
-- Name: boosts_intent_event boosts_intent_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boosts_intent_event
    ADD CONSTRAINT boosts_intent_event_pkey PRIMARY KEY (id);


--
-- Name: boosts_purchase boosts_purchase_payment_order_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boosts_purchase
    ADD CONSTRAINT boosts_purchase_payment_order_id_key UNIQUE (payment_order_id);


--
-- Name: boosts_purchase boosts_purchase_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boosts_purchase
    ADD CONSTRAINT boosts_purchase_pkey PRIMARY KEY (id);


--
-- Name: boosts_purchase boosts_purchase_public_reference_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boosts_purchase
    ADD CONSTRAINT boosts_purchase_public_reference_key UNIQUE (public_reference);


--
-- Name: chat_message chat_message_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_message
    ADD CONSTRAINT chat_message_pkey PRIMARY KEY (id);


--
-- Name: chat_message chat_sender_client_message_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_message
    ADD CONSTRAINT chat_sender_client_message_uniq UNIQUE (match_id, sender_id, client_message_id);


--
-- Name: core_business_settings_version core_business_settings_version_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.core_business_settings_version
    ADD CONSTRAINT core_business_settings_version_pkey PRIMARY KEY (id);


--
-- Name: core_business_settings_version core_business_settings_version_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.core_business_settings_version
    ADD CONSTRAINT core_business_settings_version_version_key UNIQUE (version);


--
-- Name: core_published_event core_published_event_event_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.core_published_event
    ADD CONSTRAINT core_published_event_event_id_key UNIQUE (event_id);


--
-- Name: core_published_event core_published_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.core_published_event
    ADD CONSTRAINT core_published_event_pkey PRIMARY KEY (id);


--
-- Name: deals_leg_allocation deals_allocation_unique_leg; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_leg_allocation
    ADD CONSTRAINT deals_allocation_unique_leg UNIQUE (deal_id, journey_leg_id);


--
-- Name: deals_arrival_report deals_arrival_report_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_arrival_report
    ADD CONSTRAINT deals_arrival_report_pkey PRIMARY KEY (id);


--
-- Name: deals_deal deals_deal_accepted_offer_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_deal
    ADD CONSTRAINT deals_deal_accepted_offer_id_key UNIQUE (accepted_offer_id);


--
-- Name: deals_deal deals_deal_match_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_deal
    ADD CONSTRAINT deals_deal_match_id_key UNIQUE (match_id);


--
-- Name: deals_deal deals_deal_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_deal
    ADD CONSTRAINT deals_deal_pkey PRIMARY KEY (id);


--
-- Name: deals_event deals_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_event
    ADD CONSTRAINT deals_event_pkey PRIMARY KEY (id);


--
-- Name: deals_leg_allocation deals_leg_allocation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_leg_allocation
    ADD CONSTRAINT deals_leg_allocation_pkey PRIMARY KEY (id);


--
-- Name: deals_recipient deals_recipient_deal_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_recipient
    ADD CONSTRAINT deals_recipient_deal_id_key UNIQUE (deal_id);


--
-- Name: deals_recipient deals_recipient_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_recipient
    ADD CONSTRAINT deals_recipient_pkey PRIMARY KEY (id);


--
-- Name: deals_terms_snapshot deals_terms_snapshot_deal_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_terms_snapshot
    ADD CONSTRAINT deals_terms_snapshot_deal_id_key UNIQUE (deal_id);


--
-- Name: deals_terms_snapshot deals_terms_snapshot_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_terms_snapshot
    ADD CONSTRAINT deals_terms_snapshot_pkey PRIMARY KEY (id);


--
-- Name: disputes_dispute disputes_dispute_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disputes_dispute
    ADD CONSTRAINT disputes_dispute_pkey PRIMARY KEY (id);


--
-- Name: disputes_dispute disputes_dispute_public_reference_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disputes_dispute
    ADD CONSTRAINT disputes_dispute_public_reference_key UNIQUE (public_reference);


--
-- Name: disputes_event disputes_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disputes_event
    ADD CONSTRAINT disputes_event_pkey PRIMARY KEY (id);


--
-- Name: disputes_evidence disputes_evidence_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disputes_evidence
    ADD CONSTRAINT disputes_evidence_pkey PRIMARY KEY (id);


--
-- Name: django_admin_log django_admin_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_admin_log
    ADD CONSTRAINT django_admin_log_pkey PRIMARY KEY (id);


--
-- Name: django_content_type django_content_type_app_label_model_76bd3d3b_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_content_type
    ADD CONSTRAINT django_content_type_app_label_model_76bd3d3b_uniq UNIQUE (app_label, model);


--
-- Name: django_content_type django_content_type_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_content_type
    ADD CONSTRAINT django_content_type_pkey PRIMARY KEY (id);


--
-- Name: django_migrations django_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_migrations
    ADD CONSTRAINT django_migrations_pkey PRIMARY KEY (id);


--
-- Name: django_session django_session_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_session
    ADD CONSTRAINT django_session_pkey PRIMARY KEY (session_key);


--
-- Name: finance_payout_amount_revision fin_amount_revision_decision; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_amount_revision
    ADD CONSTRAINT fin_amount_revision_decision UNIQUE (payout_id, settlement_reference);


--
-- Name: finance_payout_amount_revision fin_amount_revision_sequence; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_amount_revision
    ADD CONSTRAINT fin_amount_revision_sequence UNIQUE (payout_id, revision);


--
-- Name: finance_payment_attempt fin_attempt_unique_idempotency; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payment_attempt
    ADD CONSTRAINT fin_attempt_unique_idempotency UNIQUE (provider, idempotency_key);


--
-- Name: finance_stripe_disbursement_allocation fin_disbursement_allocation_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_stripe_disbursement_allocation
    ADD CONSTRAINT fin_disbursement_allocation_unique UNIQUE (disbursement_id, payout_id);


--
-- Name: finance_dzd_profile_revision fin_dzd_profile_sequence; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_dzd_profile_revision
    ADD CONSTRAINT fin_dzd_profile_sequence UNIQUE (method_id, sequence);


--
-- Name: finance_provider_event fin_event_unique_provider_event; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_provider_event
    ADD CONSTRAINT fin_event_unique_provider_event UNIQUE (provider, provider_event_id);


--
-- Name: finance_payout_instruction_amendment fin_instruction_sequence; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_instruction_amendment
    ADD CONSTRAINT fin_instruction_sequence UNIQUE (payout_id, sequence);


--
-- Name: finance_manual_payout_receipt fin_manual_receipt_revision; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_manual_payout_receipt
    ADD CONSTRAINT fin_manual_receipt_revision UNIQUE (attempt_id, revision);


--
-- Name: finance_payout_method_version fin_method_version_sequence; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_method_version
    ADD CONSTRAINT fin_method_version_sequence UNIQUE (method_id, sequence);


--
-- Name: finance_payout_attempt fin_payout_attempt_sequence; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_attempt
    ADD CONSTRAINT fin_payout_attempt_sequence UNIQUE (payout_id, sequence);


--
-- Name: finance_payout_event fin_payout_event_sequence; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_event
    ADD CONSTRAINT fin_payout_event_sequence UNIQUE (payout_id, sequence);


--
-- Name: finance_traveler_payout_method fin_payout_method_unique_per_traveler; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_traveler_payout_method
    ADD CONSTRAINT fin_payout_method_unique_per_traveler UNIQUE (traveler_id, method);


--
-- Name: finance_provider_dispute fin_provider_dispute_identity; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_provider_dispute
    ADD CONSTRAINT fin_provider_dispute_identity UNIQUE (provider, platform_id, provider_mode, provider_object_id);


--
-- Name: finance_stripe_payout_account fin_stripe_account_identity; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_stripe_payout_account
    ADD CONSTRAINT fin_stripe_account_identity UNIQUE (platform_id, provider_mode, provider_account_id);


--
-- Name: finance_dzd_profile_revision finance_dzd_profile_revision_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_dzd_profile_revision
    ADD CONSTRAINT finance_dzd_profile_revision_pkey PRIMARY KEY (id);


--
-- Name: finance_dzd_profile_revision finance_dzd_profile_revision_public_reference_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_dzd_profile_revision
    ADD CONSTRAINT finance_dzd_profile_revision_public_reference_key UNIQUE (public_reference);


--
-- Name: finance_guest_payment_link finance_guest_payment_link_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_guest_payment_link
    ADD CONSTRAINT finance_guest_payment_link_pkey PRIMARY KEY (id);


--
-- Name: finance_guest_payment_link finance_guest_payment_link_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_guest_payment_link
    ADD CONSTRAINT finance_guest_payment_link_token_hash_key UNIQUE (token_hash);


--
-- Name: finance_hold finance_hold_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_hold
    ADD CONSTRAINT finance_hold_pkey PRIMARY KEY (id);


--
-- Name: finance_ledger_entry finance_ledger_entry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_ledger_entry
    ADD CONSTRAINT finance_ledger_entry_pkey PRIMARY KEY (id);


--
-- Name: finance_ledger_transaction finance_ledger_transaction_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_ledger_transaction
    ADD CONSTRAINT finance_ledger_transaction_key_key UNIQUE (key);


--
-- Name: finance_ledger_transaction finance_ledger_transaction_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_ledger_transaction
    ADD CONSTRAINT finance_ledger_transaction_pkey PRIMARY KEY (id);


--
-- Name: finance_manual_payout_receipt finance_manual_payout_receipt_evidence_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_manual_payout_receipt
    ADD CONSTRAINT finance_manual_payout_receipt_evidence_id_key UNIQUE (evidence_id);


--
-- Name: finance_manual_payout_receipt finance_manual_payout_receipt_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_manual_payout_receipt
    ADD CONSTRAINT finance_manual_payout_receipt_pkey PRIMARY KEY (id);


--
-- Name: finance_payment_attempt finance_payment_attempt_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payment_attempt
    ADD CONSTRAINT finance_payment_attempt_pkey PRIMARY KEY (id);


--
-- Name: finance_payment_order finance_payment_order_credit_source_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payment_order
    ADD CONSTRAINT finance_payment_order_credit_source_id_key UNIQUE (credit_source_id);


--
-- Name: finance_payment_order finance_payment_order_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payment_order
    ADD CONSTRAINT finance_payment_order_pkey PRIMARY KEY (id);


--
-- Name: finance_payment_order finance_payment_order_public_reference_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payment_order
    ADD CONSTRAINT finance_payment_order_public_reference_key UNIQUE (public_reference);


--
-- Name: finance_payment_refund finance_payment_refund_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payment_refund
    ADD CONSTRAINT finance_payment_refund_idempotency_key_key UNIQUE (idempotency_key);


--
-- Name: finance_payment_refund finance_payment_refund_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payment_refund
    ADD CONSTRAINT finance_payment_refund_pkey PRIMARY KEY (id);


--
-- Name: finance_payout_amount_revision finance_payout_amount_revision_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_amount_revision
    ADD CONSTRAINT finance_payout_amount_revision_pkey PRIMARY KEY (id);


--
-- Name: finance_payout_attempt finance_payout_attempt_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_attempt
    ADD CONSTRAINT finance_payout_attempt_idempotency_key_key UNIQUE (idempotency_key);


--
-- Name: finance_payout_attempt finance_payout_attempt_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_attempt
    ADD CONSTRAINT finance_payout_attempt_pkey PRIMARY KEY (id);


--
-- Name: finance_payout finance_payout_deal_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout
    ADD CONSTRAINT finance_payout_deal_id_key UNIQUE (deal_id);


--
-- Name: finance_payout_event finance_payout_event_event_uuid_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_event
    ADD CONSTRAINT finance_payout_event_event_uuid_key UNIQUE (event_uuid);


--
-- Name: finance_payout_event finance_payout_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_event
    ADD CONSTRAINT finance_payout_event_pkey PRIMARY KEY (id);


--
-- Name: finance_payout_evidence finance_payout_evidence_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_evidence
    ADD CONSTRAINT finance_payout_evidence_pkey PRIMARY KEY (id);


--
-- Name: finance_payout_evidence finance_payout_evidence_public_reference_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_evidence
    ADD CONSTRAINT finance_payout_evidence_public_reference_key UNIQUE (public_reference);


--
-- Name: finance_payout_funding_allocation finance_payout_funding_allocation_allocation_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_funding_allocation
    ADD CONSTRAINT finance_payout_funding_allocation_allocation_key_key UNIQUE (allocation_key);


--
-- Name: finance_payout_funding_allocation finance_payout_funding_allocation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_funding_allocation
    ADD CONSTRAINT finance_payout_funding_allocation_pkey PRIMARY KEY (id);


--
-- Name: finance_payout_funding_release finance_payout_funding_release_allocation_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_funding_release
    ADD CONSTRAINT finance_payout_funding_release_allocation_id_key UNIQUE (allocation_id);


--
-- Name: finance_payout_funding_release finance_payout_funding_release_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_funding_release
    ADD CONSTRAINT finance_payout_funding_release_pkey PRIMARY KEY (id);


--
-- Name: finance_payout_identity_attestation finance_payout_identity_attestation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_identity_attestation
    ADD CONSTRAINT finance_payout_identity_attestation_pkey PRIMARY KEY (id);


--
-- Name: finance_payout_identity_attestation finance_payout_identity_attestation_public_reference_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_identity_attestation
    ADD CONSTRAINT finance_payout_identity_attestation_public_reference_key UNIQUE (public_reference);


--
-- Name: finance_payout_identity_review_assignment finance_payout_identity_review_assignment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_identity_review_assignment
    ADD CONSTRAINT finance_payout_identity_review_assignment_pkey PRIMARY KEY (id);


--
-- Name: finance_payout_identity_review_assignment finance_payout_identity_review_assignment_public_reference_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_identity_review_assignment
    ADD CONSTRAINT finance_payout_identity_review_assignment_public_reference_key UNIQUE (public_reference);


--
-- Name: finance_payout_identity_revocation finance_payout_identity_revocation_attestation_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_identity_revocation
    ADD CONSTRAINT finance_payout_identity_revocation_attestation_id_key UNIQUE (attestation_id);


--
-- Name: finance_payout_identity_revocation finance_payout_identity_revocation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_identity_revocation
    ADD CONSTRAINT finance_payout_identity_revocation_pkey PRIMARY KEY (id);


--
-- Name: finance_payout_instruction_amendment finance_payout_instruction_amendment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_instruction_amendment
    ADD CONSTRAINT finance_payout_instruction_amendment_pkey PRIMARY KEY (id);


--
-- Name: finance_payout_instruction_confirmation finance_payout_instruction_confirmation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_instruction_confirmation
    ADD CONSTRAINT finance_payout_instruction_confirmation_pkey PRIMARY KEY (id);


--
-- Name: finance_payout_instruction_confirmation finance_payout_instruction_confirmation_public_reference_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_instruction_confirmation
    ADD CONSTRAINT finance_payout_instruction_confirmation_public_reference_key UNIQUE (public_reference);


--
-- Name: finance_payout_method_version finance_payout_method_version_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_method_version
    ADD CONSTRAINT finance_payout_method_version_pkey PRIMARY KEY (id);


--
-- Name: finance_payout_method_version finance_payout_method_version_public_reference_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_method_version
    ADD CONSTRAINT finance_payout_method_version_public_reference_key UNIQUE (public_reference);


--
-- Name: finance_payout finance_payout_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout
    ADD CONSTRAINT finance_payout_pkey PRIMARY KEY (id);


--
-- Name: finance_payout_profile_review finance_payout_profile_review_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_profile_review
    ADD CONSTRAINT finance_payout_profile_review_pkey PRIMARY KEY (id);


--
-- Name: finance_payout_provider_operation finance_payout_provider_operation_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_provider_operation
    ADD CONSTRAINT finance_payout_provider_operation_idempotency_key_key UNIQUE (idempotency_key);


--
-- Name: finance_payout_provider_operation finance_payout_provider_operation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_provider_operation
    ADD CONSTRAINT finance_payout_provider_operation_pkey PRIMARY KEY (id);


--
-- Name: finance_payout_provider_operation finance_payout_provider_operation_public_reference_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_provider_operation
    ADD CONSTRAINT finance_payout_provider_operation_public_reference_key UNIQUE (public_reference);


--
-- Name: finance_payout finance_payout_public_reference_f27f5dde_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout
    ADD CONSTRAINT finance_payout_public_reference_f27f5dde_uniq UNIQUE (public_reference);


--
-- Name: finance_provider_dispute finance_provider_dispute_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_provider_dispute
    ADD CONSTRAINT finance_provider_dispute_pkey PRIMARY KEY (id);


--
-- Name: finance_provider_event finance_provider_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_provider_event
    ADD CONSTRAINT finance_provider_event_pkey PRIMARY KEY (id);


--
-- Name: finance_scheduled_job finance_scheduled_job_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_scheduled_job
    ADD CONSTRAINT finance_scheduled_job_key_key UNIQUE (key);


--
-- Name: finance_scheduled_job finance_scheduled_job_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_scheduled_job
    ADD CONSTRAINT finance_scheduled_job_pkey PRIMARY KEY (id);


--
-- Name: finance_stripe_disbursement_allocation finance_stripe_disbursement_allocation_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_stripe_disbursement_allocation
    ADD CONSTRAINT finance_stripe_disbursement_allocation_pkey PRIMARY KEY (id);


--
-- Name: finance_stripe_disbursement finance_stripe_disbursement_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_stripe_disbursement
    ADD CONSTRAINT finance_stripe_disbursement_pkey PRIMARY KEY (id);


--
-- Name: finance_stripe_disbursement finance_stripe_disbursement_public_reference_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_stripe_disbursement
    ADD CONSTRAINT finance_stripe_disbursement_public_reference_key UNIQUE (public_reference);


--
-- Name: finance_stripe_payout_account finance_stripe_payout_account_creation_operation_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_stripe_payout_account
    ADD CONSTRAINT finance_stripe_payout_account_creation_operation_key_key UNIQUE (creation_operation_key);


--
-- Name: finance_stripe_payout_account finance_stripe_payout_account_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_stripe_payout_account
    ADD CONSTRAINT finance_stripe_payout_account_pkey PRIMARY KEY (id);


--
-- Name: finance_stripe_payout_account finance_stripe_payout_account_public_reference_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_stripe_payout_account
    ADD CONSTRAINT finance_stripe_payout_account_public_reference_key UNIQUE (public_reference);


--
-- Name: finance_traveler_payout_method finance_traveler_payout_method_current_version_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_traveler_payout_method
    ADD CONSTRAINT finance_traveler_payout_method_current_version_id_key UNIQUE (current_version_id);


--
-- Name: finance_traveler_payout_method finance_traveler_payout_method_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_traveler_payout_method
    ADD CONSTRAINT finance_traveler_payout_method_pkey PRIMARY KEY (id);


--
-- Name: finance_traveler_payout_method finance_traveler_payout_method_public_reference_dee0c057_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_traveler_payout_method
    ADD CONSTRAINT finance_traveler_payout_method_public_reference_dee0c057_uniq UNIQUE (public_reference);


--
-- Name: locations_place_alternate_name geo_alt_name_place_lang_norm_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_place_alternate_name
    ADD CONSTRAINT geo_alt_name_place_lang_norm_uniq UNIQUE (place_id, language, normalized_name);


--
-- Name: locations_place_alternate_name geo_alt_name_source_identity_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_place_alternate_name
    ADD CONSTRAINT geo_alt_name_source_identity_uniq UNIQUE (source, source_id);


--
-- Name: locations_country geo_country_source_identity_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_country
    ADD CONSTRAINT geo_country_source_identity_uniq UNIQUE (source, source_id);


--
-- Name: locations_airport_locality_mapping geo_map_airport_type_locality_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_airport_locality_mapping
    ADD CONSTRAINT geo_map_airport_type_locality_uniq UNIQUE (airport_id, relationship_type, locality_id);


--
-- Name: locations_airport_locality_mapping geo_map_source_identity_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_airport_locality_mapping
    ADD CONSTRAINT geo_map_source_identity_uniq UNIQUE (source, source_id);


--
-- Name: locations_place geo_place_source_identity_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_place
    ADD CONSTRAINT geo_place_source_identity_uniq UNIQUE (source, source_id);


--
-- Name: handover_attempt handover_attempt_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.handover_attempt
    ADD CONSTRAINT handover_attempt_pkey PRIMARY KEY (id);


--
-- Name: handover_code_access handover_code_access_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.handover_code_access
    ADD CONSTRAINT handover_code_access_pkey PRIMARY KEY (id);


--
-- Name: handover_deal_code handover_deal_code_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.handover_deal_code
    ADD CONSTRAINT handover_deal_code_pkey PRIMARY KEY (id);


--
-- Name: trips_journey_leg journey_leg_unique_position; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_journey_leg
    ADD CONSTRAINT journey_leg_unique_position UNIQUE (journey_id, "position");


--
-- Name: trips_journey_leg_proof journey_proof_unique_object; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_journey_leg_proof
    ADD CONSTRAINT journey_proof_unique_object UNIQUE (bucket, object_key);


--
-- Name: kyc_submission kyc_submission_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_submission
    ADD CONSTRAINT kyc_submission_idempotency_key_key UNIQUE (idempotency_key);


--
-- Name: kyc_submission kyc_submission_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_submission
    ADD CONSTRAINT kyc_submission_pkey PRIMARY KEY (id);


--
-- Name: locations_airport_locality_mapping locations_airport_locality_mapping_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_airport_locality_mapping
    ADD CONSTRAINT locations_airport_locality_mapping_pkey PRIMARY KEY (id);


--
-- Name: locations_country locations_country_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_country
    ADD CONSTRAINT locations_country_pkey PRIMARY KEY (code);


--
-- Name: locations_geography_catalogue_import locations_geography_catalogue_import_content_sha256_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_geography_catalogue_import
    ADD CONSTRAINT locations_geography_catalogue_import_content_sha256_key UNIQUE (content_sha256);


--
-- Name: locations_geography_catalogue_import locations_geography_catalogue_import_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_geography_catalogue_import
    ADD CONSTRAINT locations_geography_catalogue_import_pkey PRIMARY KEY (id);


--
-- Name: locations_location locations_location_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_location
    ADD CONSTRAINT locations_location_pkey PRIMARY KEY (id);


--
-- Name: locations_place_alternate_name locations_place_alternate_name_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_place_alternate_name
    ADD CONSTRAINT locations_place_alternate_name_pkey PRIMARY KEY (id);


--
-- Name: locations_place locations_place_legacy_airport_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_place
    ADD CONSTRAINT locations_place_legacy_airport_id_key UNIQUE (legacy_airport_id);


--
-- Name: locations_place locations_place_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_place
    ADD CONSTRAINT locations_place_pkey PRIMARY KEY (id);


--
-- Name: matching_event matching_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.matching_event
    ADD CONSTRAINT matching_event_pkey PRIMARY KEY (id);


--
-- Name: matching_match matching_match_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.matching_match
    ADD CONSTRAINT matching_match_pkey PRIMARY KEY (id);


--
-- Name: matching_offer matching_offer_parent_offer_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.matching_offer
    ADD CONSTRAINT matching_offer_parent_offer_id_key UNIQUE (parent_offer_id);


--
-- Name: matching_offer matching_offer_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.matching_offer
    ADD CONSTRAINT matching_offer_pkey PRIMARY KEY (id);


--
-- Name: notification notif_recipient_event_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notif_recipient_event_uniq UNIQUE (recipient_id, event_id);


--
-- Name: notification_outbound_message notification_outbound_message_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_outbound_message
    ADD CONSTRAINT notification_outbound_message_key_key UNIQUE (key);


--
-- Name: notification_outbound_message notification_outbound_message_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_outbound_message
    ADD CONSTRAINT notification_outbound_message_pkey PRIMARY KEY (id);


--
-- Name: notification_outbound_secret notification_outbound_secret_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_outbound_secret
    ADD CONSTRAINT notification_outbound_secret_key_key UNIQUE (key);


--
-- Name: notification_outbound_secret notification_outbound_secret_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_outbound_secret
    ADD CONSTRAINT notification_outbound_secret_pkey PRIMARY KEY (id);


--
-- Name: notification notification_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_pkey PRIMARY KEY (id);


--
-- Name: notification_preference notification_preference_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_preference
    ADD CONSTRAINT notification_preference_pkey PRIMARY KEY (id);


--
-- Name: notification_preference notification_preference_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_preference
    ADD CONSTRAINT notification_preference_user_id_key UNIQUE (user_id);


--
-- Name: notification_push_device notification_push_device_installation_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_push_device
    ADD CONSTRAINT notification_push_device_installation_id_key UNIQUE (installation_id);


--
-- Name: notification_push_device notification_push_device_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_push_device
    ADD CONSTRAINT notification_push_device_pkey PRIMARY KEY (id);


--
-- Name: notification_push_device notification_push_device_token_fingerprint_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_push_device
    ADD CONSTRAINT notification_push_device_token_fingerprint_key UNIQUE (token_fingerprint);


--
-- Name: accounts_oauthidentity oauthidentity_provider_subject_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_oauthidentity
    ADD CONSTRAINT oauthidentity_provider_subject_unique UNIQUE (provider, subject);


--
-- Name: parcels_delivery parcels_delivery_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcels_delivery
    ADD CONSTRAINT parcels_delivery_pkey PRIMARY KEY (parcelrequest_ptr_id);


--
-- Name: parcels_media parcels_media_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcels_media
    ADD CONSTRAINT parcels_media_pkey PRIMARY KEY (id);


--
-- Name: parcels_media parcels_media_unique_object; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcels_media
    ADD CONSTRAINT parcels_media_unique_object UNIQUE (bucket, object_key);


--
-- Name: parcels_product parcels_product_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcels_product
    ADD CONSTRAINT parcels_product_pkey PRIMARY KEY (parcelrequest_ptr_id);


--
-- Name: parcels_request parcels_request_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcels_request
    ADD CONSTRAINT parcels_request_pkey PRIMARY KEY (id);


--
-- Name: payments_event payments_event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments_event
    ADD CONSTRAINT payments_event_pkey PRIMARY KEY (id);


--
-- Name: payments_event payments_event_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments_event
    ADD CONSTRAINT payments_event_unique UNIQUE (provider, provider_event_id);


--
-- Name: payments_intent payments_intent_offer_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments_intent
    ADD CONSTRAINT payments_intent_offer_id_key UNIQUE (offer_id);


--
-- Name: payments_intent payments_intent_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments_intent
    ADD CONSTRAINT payments_intent_pkey PRIMARY KEY (id);


--
-- Name: payments_refund payments_refund_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments_refund
    ADD CONSTRAINT payments_refund_pkey PRIMARY KEY (id);


--
-- Name: ratings_rating ratings_one_per_side_per_deal; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ratings_rating
    ADD CONSTRAINT ratings_one_per_side_per_deal UNIQUE (deal_id, rater_role);


--
-- Name: ratings_rating ratings_rating_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ratings_rating
    ADD CONSTRAINT ratings_rating_pkey PRIMARY KEY (id);


--
-- Name: token_blacklist_blacklistedtoken token_blacklist_blacklistedtoken_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.token_blacklist_blacklistedtoken
    ADD CONSTRAINT token_blacklist_blacklistedtoken_pkey PRIMARY KEY (id);


--
-- Name: token_blacklist_blacklistedtoken token_blacklist_blacklistedtoken_token_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.token_blacklist_blacklistedtoken
    ADD CONSTRAINT token_blacklist_blacklistedtoken_token_id_key UNIQUE (token_id);


--
-- Name: token_blacklist_outstandingtoken token_blacklist_outstandingtoken_jti_hex_d9bdf6f7_uniq; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.token_blacklist_outstandingtoken
    ADD CONSTRAINT token_blacklist_outstandingtoken_jti_hex_d9bdf6f7_uniq UNIQUE (jti);


--
-- Name: token_blacklist_outstandingtoken token_blacklist_outstandingtoken_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.token_blacklist_outstandingtoken
    ADD CONSTRAINT token_blacklist_outstandingtoken_pkey PRIMARY KEY (id);


--
-- Name: trips_airport trips_airport_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_airport
    ADD CONSTRAINT trips_airport_pkey PRIMARY KEY (iata);


--
-- Name: trips_journey_leg trips_journey_leg_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_journey_leg
    ADD CONSTRAINT trips_journey_leg_pkey PRIMARY KEY (id);


--
-- Name: trips_journey_leg_proof trips_journey_leg_proof_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_journey_leg_proof
    ADD CONSTRAINT trips_journey_leg_proof_pkey PRIMARY KEY (id);


--
-- Name: trips_journey trips_journey_legacy_trip_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_journey
    ADD CONSTRAINT trips_journey_legacy_trip_id_key UNIQUE (legacy_trip_id);


--
-- Name: trips_journey trips_journey_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_journey
    ADD CONSTRAINT trips_journey_pkey PRIMARY KEY (id);


--
-- Name: trips_media trips_media_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_media
    ADD CONSTRAINT trips_media_pkey PRIMARY KEY (id);


--
-- Name: trips_media trips_media_unique_object; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_media
    ADD CONSTRAINT trips_media_unique_object UNIQUE (bucket, object_key);


--
-- Name: trips_stopover trips_stopover_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_stopover
    ADD CONSTRAINT trips_stopover_pkey PRIMARY KEY (id);


--
-- Name: trips_stopover trips_stopover_unique_position; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_stopover
    ADD CONSTRAINT trips_stopover_unique_position UNIQUE (trip_id, "position");


--
-- Name: trips_tracking_snapshot trips_tracking_snapshot_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_tracking_snapshot
    ADD CONSTRAINT trips_tracking_snapshot_pkey PRIMARY KEY (id);


--
-- Name: trips_trip trips_trip_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_trip
    ADD CONSTRAINT trips_trip_pkey PRIMARY KEY (id);


--
-- Name: verification_handover_code verification_handover_code_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.verification_handover_code
    ADD CONSTRAINT verification_handover_code_pkey PRIMARY KEY (id);


--
-- Name: wallet_entry wallet_entry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wallet_entry
    ADD CONSTRAINT wallet_entry_pkey PRIMARY KEY (id);


--
-- Name: wallet_entry wallet_entry_unique_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wallet_entry
    ADD CONSTRAINT wallet_entry_unique_key UNIQUE (wallet_id, key);


--
-- Name: wallet_hold wallet_hold_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wallet_hold
    ADD CONSTRAINT wallet_hold_pkey PRIMARY KEY (id);


--
-- Name: wallet_hold wallet_hold_unique_source; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wallet_hold
    ADD CONSTRAINT wallet_hold_unique_source UNIQUE (source, source_id);


--
-- Name: wallet_wallet wallet_unique_user_currency; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wallet_wallet
    ADD CONSTRAINT wallet_unique_user_currency UNIQUE (user_id, currency);


--
-- Name: wallet_wallet wallet_wallet_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wallet_wallet
    ADD CONSTRAINT wallet_wallet_pkey PRIMARY KEY (id);


--
-- Name: wallet_withdrawal wallet_withdrawal_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wallet_withdrawal
    ADD CONSTRAINT wallet_withdrawal_pkey PRIMARY KEY (id);


--
-- Name: accounts_em_user_id_be3451_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX accounts_em_user_id_be3451_idx ON public.accounts_emailverificationcode USING btree (user_id, used_at, expires_at);


--
-- Name: accounts_emailverificationcode_user_id_2d1d1145; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX accounts_emailverificationcode_user_id_2d1d1145 ON public.accounts_emailverificationcode USING btree (user_id);


--
-- Name: accounts_oa_user_id_170745_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX accounts_oa_user_id_170745_idx ON public.accounts_oauthidentity USING btree (user_id, provider);


--
-- Name: accounts_oauthidentity_user_id_906e1c75; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX accounts_oauthidentity_user_id_906e1c75 ON public.accounts_oauthidentity USING btree (user_id);


--
-- Name: accounts_pa_user_id_e7002a_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX accounts_pa_user_id_e7002a_idx ON public.accounts_passwordresetcode USING btree (user_id, used_at, expires_at);


--
-- Name: accounts_passwordresetcode_user_id_5331448e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX accounts_passwordresetcode_user_id_5331448e ON public.accounts_passwordresetcode USING btree (user_id);


--
-- Name: accounts_user_email_b2644a56_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX accounts_user_email_b2644a56_like ON public.accounts_user USING btree (email varchar_pattern_ops);


--
-- Name: accounts_user_groups_group_id_bd11a704; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX accounts_user_groups_group_id_bd11a704 ON public.accounts_user_groups USING btree (group_id);


--
-- Name: accounts_user_groups_user_id_52b62117; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX accounts_user_groups_user_id_52b62117 ON public.accounts_user_groups USING btree (user_id);


--
-- Name: accounts_user_is_banned_7056432d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX accounts_user_is_banned_7056432d ON public.accounts_user USING btree (is_banned);


--
-- Name: accounts_user_phone_c603acdd; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX accounts_user_phone_c603acdd ON public.accounts_user USING btree (phone);


--
-- Name: accounts_user_phone_c603acdd_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX accounts_user_phone_c603acdd_like ON public.accounts_user USING btree (phone varchar_pattern_ops);


--
-- Name: accounts_user_user_permissions_permission_id_113bb443; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX accounts_user_user_permissions_permission_id_113bb443 ON public.accounts_user_user_permissions USING btree (permission_id);


--
-- Name: accounts_user_user_permissions_user_id_e4f0a161; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX accounts_user_user_permissions_user_id_e4f0a161 ON public.accounts_user_user_permissions USING btree (user_id);


--
-- Name: accounts_user_username_6088629e_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX accounts_user_username_6088629e_like ON public.accounts_user USING btree (username varchar_pattern_ops);


--
-- Name: admin_audit_actor_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_audit_actor_time_idx ON public.admin_panel_audit_log USING btree (actor_id, created_at DESC);


--
-- Name: admin_audit_target_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_audit_target_time_idx ON public.admin_panel_audit_log USING btree (target_type, target_id, created_at DESC);


--
-- Name: admin_invite_active_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_invite_active_idx ON public.admin_panel_invitation USING btree (used_at, revoked_at, expires_at);


--
-- Name: admin_invite_email_exp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_invite_email_exp_idx ON public.admin_panel_invitation USING btree (email, expires_at);


--
-- Name: admin_panel_audit_log_action_31472744; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_panel_audit_log_action_31472744 ON public.admin_panel_audit_log USING btree (action);


--
-- Name: admin_panel_audit_log_action_31472744_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_panel_audit_log_action_31472744_like ON public.admin_panel_audit_log USING btree (action varchar_pattern_ops);


--
-- Name: admin_panel_audit_log_actor_id_437e6e37; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_panel_audit_log_actor_id_437e6e37 ON public.admin_panel_audit_log USING btree (actor_id);


--
-- Name: admin_panel_audit_log_created_at_8c29fbdb; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_panel_audit_log_created_at_8c29fbdb ON public.admin_panel_audit_log USING btree (created_at);


--
-- Name: admin_panel_audit_log_target_id_baf7237a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_panel_audit_log_target_id_baf7237a ON public.admin_panel_audit_log USING btree (target_id);


--
-- Name: admin_panel_audit_log_target_id_baf7237a_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_panel_audit_log_target_id_baf7237a_like ON public.admin_panel_audit_log USING btree (target_id varchar_pattern_ops);


--
-- Name: admin_panel_audit_log_target_type_45f6b773; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_panel_audit_log_target_type_45f6b773 ON public.admin_panel_audit_log USING btree (target_type);


--
-- Name: admin_panel_audit_log_target_type_45f6b773_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_panel_audit_log_target_type_45f6b773_like ON public.admin_panel_audit_log USING btree (target_type varchar_pattern_ops);


--
-- Name: admin_panel_invitation_accepted_by_id_d9ad5a3f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_panel_invitation_accepted_by_id_d9ad5a3f ON public.admin_panel_invitation USING btree (accepted_by_id);


--
-- Name: admin_panel_invitation_created_at_d3879ee5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_panel_invitation_created_at_d3879ee5 ON public.admin_panel_invitation USING btree (created_at);


--
-- Name: admin_panel_invitation_email_7497be3d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_panel_invitation_email_7497be3d ON public.admin_panel_invitation USING btree (email);


--
-- Name: admin_panel_invitation_email_7497be3d_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_panel_invitation_email_7497be3d_like ON public.admin_panel_invitation USING btree (email varchar_pattern_ops);


--
-- Name: admin_panel_invitation_expires_at_ece31482; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_panel_invitation_expires_at_ece31482 ON public.admin_panel_invitation USING btree (expires_at);


--
-- Name: admin_panel_invitation_invited_by_id_d5d65a71; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_panel_invitation_invited_by_id_d5d65a71 ON public.admin_panel_invitation USING btree (invited_by_id);


--
-- Name: admin_panel_invitation_revoked_at_17aab78a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_panel_invitation_revoked_at_17aab78a ON public.admin_panel_invitation USING btree (revoked_at);


--
-- Name: admin_panel_invitation_role_e5aa1380; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_panel_invitation_role_e5aa1380 ON public.admin_panel_invitation USING btree (role);


--
-- Name: admin_panel_invitation_role_e5aa1380_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_panel_invitation_role_e5aa1380_like ON public.admin_panel_invitation USING btree (role varchar_pattern_ops);


--
-- Name: admin_panel_invitation_token_hash_8f4891e1_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_panel_invitation_token_hash_8f4891e1_like ON public.admin_panel_invitation USING btree (token_hash varchar_pattern_ops);


--
-- Name: admin_panel_invitation_used_at_66d3c0a3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX admin_panel_invitation_used_at_66d3c0a3 ON public.admin_panel_invitation USING btree (used_at);


--
-- Name: auth_group_name_a6ea08ec_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_group_name_a6ea08ec_like ON public.auth_group USING btree (name varchar_pattern_ops);


--
-- Name: auth_group_permissions_group_id_b120cbf9; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_group_permissions_group_id_b120cbf9 ON public.auth_group_permissions USING btree (group_id);


--
-- Name: auth_group_permissions_permission_id_84c5c92e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_group_permissions_permission_id_84c5c92e ON public.auth_group_permissions USING btree (permission_id);


--
-- Name: auth_permission_content_type_id_2f476e4b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX auth_permission_content_type_id_2f476e4b ON public.auth_permission USING btree (content_type_id);


--
-- Name: boosts_buyer_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX boosts_buyer_idx ON public.boosts_purchase USING btree (buyer_id, created_at DESC);


--
-- Name: boosts_expiry_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX boosts_expiry_idx ON public.boosts_purchase USING btree (status, expires_at);


--
-- Name: boosts_intent_event_actor_id_91c534f0; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX boosts_intent_event_actor_id_91c534f0 ON public.boosts_intent_event USING btree (actor_id);


--
-- Name: boosts_intent_event_business_settings_version_id_40a78b91; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX boosts_intent_event_business_settings_version_id_40a78b91 ON public.boosts_intent_event USING btree (business_settings_version_id);


--
-- Name: boosts_intent_event_deal_id_9c8cb8b2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX boosts_intent_event_deal_id_9c8cb8b2 ON public.boosts_intent_event USING btree (deal_id);


--
-- Name: boosts_intent_event_delivery_request_id_1e7439b0; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX boosts_intent_event_delivery_request_id_1e7439b0 ON public.boosts_intent_event USING btree (delivery_request_id);


--
-- Name: boosts_intent_request_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX boosts_intent_request_idx ON public.boosts_intent_event USING btree (delivery_request_id, created_at DESC);


--
-- Name: boosts_purchase_business_settings_version_id_27c0d1e8; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX boosts_purchase_business_settings_version_id_27c0d1e8 ON public.boosts_purchase USING btree (business_settings_version_id);


--
-- Name: boosts_purchase_buyer_id_3911b29b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX boosts_purchase_buyer_id_3911b29b ON public.boosts_purchase USING btree (buyer_id);


--
-- Name: boosts_purchase_deal_id_3980c6fb; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX boosts_purchase_deal_id_3980c6fb ON public.boosts_purchase USING btree (deal_id);


--
-- Name: boosts_purchase_delivery_request_id_9e9304ad; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX boosts_purchase_delivery_request_id_9e9304ad ON public.boosts_purchase USING btree (delivery_request_id);


--
-- Name: boosts_purchase_package_code_cff6929a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX boosts_purchase_package_code_cff6929a ON public.boosts_purchase USING btree (package_code);


--
-- Name: boosts_purchase_package_code_cff6929a_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX boosts_purchase_package_code_cff6929a_like ON public.boosts_purchase USING btree (package_code varchar_pattern_ops);


--
-- Name: boosts_purchase_status_6cce2513; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX boosts_purchase_status_6cce2513 ON public.boosts_purchase USING btree (status);


--
-- Name: boosts_purchase_status_6cce2513_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX boosts_purchase_status_6cce2513_like ON public.boosts_purchase USING btree (status varchar_pattern_ops);


--
-- Name: boosts_request_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX boosts_request_idx ON public.boosts_purchase USING btree (delivery_request_id, created_at DESC);


--
-- Name: chat_match_created_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX chat_match_created_idx ON public.chat_message USING btree (match_id, created_at);


--
-- Name: chat_match_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX chat_match_id_idx ON public.chat_message USING btree (match_id, id);


--
-- Name: chat_message_created_at_618078f0; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX chat_message_created_at_618078f0 ON public.chat_message USING btree (created_at);


--
-- Name: chat_message_match_id_f9b82a81; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX chat_message_match_id_f9b82a81 ON public.chat_message USING btree (match_id);


--
-- Name: chat_message_read_at_789964e3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX chat_message_read_at_789964e3 ON public.chat_message USING btree (read_at);


--
-- Name: chat_message_sender_id_991c686c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX chat_message_sender_id_991c686c ON public.chat_message USING btree (sender_id);


--
-- Name: core_business_settings_version_created_by_id_16811bac; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX core_business_settings_version_created_by_id_16811bac ON public.core_business_settings_version USING btree (created_by_id);


--
-- Name: core_business_settings_version_status_3a081776; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX core_business_settings_version_status_3a081776 ON public.core_business_settings_version USING btree (status);


--
-- Name: core_business_settings_version_status_3a081776_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX core_business_settings_version_status_3a081776_like ON public.core_business_settings_version USING btree (status varchar_pattern_ops);


--
-- Name: core_pe_undelivered_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX core_pe_undelivered_idx ON public.core_published_event USING btree (delivered_at, published_at);


--
-- Name: core_published_event_channel_92dc2586; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX core_published_event_channel_92dc2586 ON public.core_published_event USING btree (channel);


--
-- Name: core_published_event_channel_92dc2586_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX core_published_event_channel_92dc2586_like ON public.core_published_event USING btree (channel varchar_pattern_ops);


--
-- Name: core_published_event_event_id_698b18a8_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX core_published_event_event_id_698b18a8_like ON public.core_published_event USING btree (event_id varchar_pattern_ops);


--
-- Name: core_published_event_published_at_66c16e00; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX core_published_event_published_at_66c16e00 ON public.core_published_event USING btree (published_at);


--
-- Name: core_settings_one_active; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX core_settings_one_active ON public.core_business_settings_version USING btree (status) WHERE ((status)::text = 'active'::text);


--
-- Name: core_settings_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX core_settings_status_idx ON public.core_business_settings_version USING btree (status, version DESC);


--
-- Name: deals_allocation_expiry_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_allocation_expiry_idx ON public.deals_leg_allocation USING btree (status, expires_at);


--
-- Name: deals_arrival_deal_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_arrival_deal_idx ON public.deals_arrival_report USING btree (deal_id, reported_at DESC);


--
-- Name: deals_arrival_one_confirmed_per_deal; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX deals_arrival_one_confirmed_per_deal ON public.deals_arrival_report USING btree (deal_id) WHERE ((status)::text = 'confirmed'::text);


--
-- Name: deals_arrival_one_open_per_deal; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX deals_arrival_one_open_per_deal ON public.deals_arrival_report USING btree (deal_id) WHERE ((status)::text = 'pending_confirmation'::text);


--
-- Name: deals_arrival_open_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_arrival_open_idx ON public.deals_arrival_report USING btree (status, reported_at DESC);


--
-- Name: deals_arrival_report_deal_id_96a41f3c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_arrival_report_deal_id_96a41f3c ON public.deals_arrival_report USING btree (deal_id);


--
-- Name: deals_arrival_report_decided_by_id_e2ba4401; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_arrival_report_decided_by_id_e2ba4401 ON public.deals_arrival_report USING btree (decided_by_id);


--
-- Name: deals_arrival_report_reported_by_id_9850a243; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_arrival_report_reported_by_id_9850a243 ON public.deals_arrival_report USING btree (reported_by_id);


--
-- Name: deals_arrival_report_status_d859ff0c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_arrival_report_status_d859ff0c ON public.deals_arrival_report USING btree (status);


--
-- Name: deals_arrival_report_status_d859ff0c_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_arrival_report_status_d859ff0c_like ON public.deals_arrival_report USING btree (status varchar_pattern_ops);


--
-- Name: deals_code_release_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_code_release_idx ON public.deals_deal USING btree (status, delivery_code_available_at);


--
-- Name: deals_deal_cancelled_by_id_0bdb3b24; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_deal_cancelled_by_id_0bdb3b24 ON public.deals_deal USING btree (cancelled_by_id);


--
-- Name: deals_deal_delivery_request_id_070220c8; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_deal_delivery_request_id_070220c8 ON public.deals_deal USING btree (delivery_request_id);


--
-- Name: deals_deal_is_legacy_37831aac; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_deal_is_legacy_37831aac ON public.deals_deal USING btree (is_legacy);


--
-- Name: deals_deal_journey_id_7d375dce; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_deal_journey_id_7d375dce ON public.deals_deal USING btree (journey_id);


--
-- Name: deals_deal_no_show_recorded_by_id_79f62367; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_deal_no_show_recorded_by_id_79f62367 ON public.deals_deal USING btree (no_show_recorded_by_id);


--
-- Name: deals_deal_sender_id_658c5ee7; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_deal_sender_id_658c5ee7 ON public.deals_deal USING btree (sender_id);


--
-- Name: deals_deal_status_3f482227; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_deal_status_3f482227 ON public.deals_deal USING btree (status);


--
-- Name: deals_deal_status_3f482227_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_deal_status_3f482227_like ON public.deals_deal USING btree (status varchar_pattern_ops);


--
-- Name: deals_deal_traveler_id_65c604f0; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_deal_traveler_id_65c604f0 ON public.deals_deal USING btree (traveler_id);


--
-- Name: deals_event_actor_id_316aa5de; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_event_actor_id_316aa5de ON public.deals_event USING btree (actor_id);


--
-- Name: deals_event_deal_id_bde49cc2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_event_deal_id_bde49cc2 ON public.deals_event USING btree (deal_id);


--
-- Name: deals_event_timeline_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_event_timeline_idx ON public.deals_event USING btree (deal_id, created_at);


--
-- Name: deals_journey_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_journey_status_idx ON public.deals_deal USING btree (journey_id, status);


--
-- Name: deals_leg_allocation_deal_id_c7b3d6c9; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_leg_allocation_deal_id_c7b3d6c9 ON public.deals_leg_allocation USING btree (deal_id);


--
-- Name: deals_leg_allocation_journey_leg_id_ce6c0525; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_leg_allocation_journey_leg_id_ce6c0525 ON public.deals_leg_allocation USING btree (journey_leg_id);


--
-- Name: deals_leg_allocation_status_a1e590a9; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_leg_allocation_status_a1e590a9 ON public.deals_leg_allocation USING btree (status);


--
-- Name: deals_leg_allocation_status_a1e590a9_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_leg_allocation_status_a1e590a9_like ON public.deals_leg_allocation USING btree (status varchar_pattern_ops);


--
-- Name: deals_leg_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_leg_status_idx ON public.deals_leg_allocation USING btree (journey_leg_id, status);


--
-- Name: deals_one_active_per_request; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX deals_one_active_per_request ON public.deals_deal USING btree (delivery_request_id) WHERE ((status)::text = ANY ((ARRAY['offer_accepted'::character varying, 'payment_required'::character varying, 'funded'::character varying, 'pickup_ready'::character varying, 'picked_up'::character varying, 'in_transit'::character varying, 'delivery_ready'::character varying, 'delivery_confirmed'::character varying, 'protection_window'::character varying, 'disputed'::character varying])::text[]));


--
-- Name: deals_protection_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_protection_idx ON public.deals_deal USING btree (status, protection_ends_at);


--
-- Name: deals_recipient_created_by_id_5c736da8; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_recipient_created_by_id_5c736da8 ON public.deals_recipient USING btree (created_by_id);


--
-- Name: deals_recipient_updated_by_id_8a2b2ab3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_recipient_updated_by_id_8a2b2ab3 ON public.deals_recipient USING btree (updated_by_id);


--
-- Name: deals_sender_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_sender_idx ON public.deals_deal USING btree (sender_id, created_at DESC);


--
-- Name: deals_terms_snapshot_business_settings_version_id_75afe5df; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_terms_snapshot_business_settings_version_id_75afe5df ON public.deals_terms_snapshot USING btree (business_settings_version_id);


--
-- Name: deals_traveler_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX deals_traveler_idx ON public.deals_deal USING btree (traveler_id, created_at DESC);


--
-- Name: disputes_deal_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX disputes_deal_idx ON public.disputes_dispute USING btree (deal_id, opened_at DESC);


--
-- Name: disputes_dispute_deal_id_5497f895; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX disputes_dispute_deal_id_5497f895 ON public.disputes_dispute USING btree (deal_id);


--
-- Name: disputes_dispute_opened_at_21c649b6; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX disputes_dispute_opened_at_21c649b6 ON public.disputes_dispute USING btree (opened_at);


--
-- Name: disputes_dispute_opened_by_id_677cad74; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX disputes_dispute_opened_by_id_677cad74 ON public.disputes_dispute USING btree (opened_by_id);


--
-- Name: disputes_dispute_resolved_by_id_100fd82f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX disputes_dispute_resolved_by_id_100fd82f ON public.disputes_dispute USING btree (resolved_by_id);


--
-- Name: disputes_dispute_status_a639ff00; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX disputes_dispute_status_a639ff00 ON public.disputes_dispute USING btree (status);


--
-- Name: disputes_dispute_status_a639ff00_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX disputes_dispute_status_a639ff00_like ON public.disputes_dispute USING btree (status varchar_pattern_ops);


--
-- Name: disputes_event_actor_id_f3f79611; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX disputes_event_actor_id_f3f79611 ON public.disputes_event USING btree (actor_id);


--
-- Name: disputes_event_dispute_id_5ab10d2c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX disputes_event_dispute_id_5ab10d2c ON public.disputes_event USING btree (dispute_id);


--
-- Name: disputes_event_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX disputes_event_idx ON public.disputes_event USING btree (dispute_id, created_at);


--
-- Name: disputes_evidence_dispute_id_7a038a46; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX disputes_evidence_dispute_id_7a038a46 ON public.disputes_evidence USING btree (dispute_id);


--
-- Name: disputes_evidence_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX disputes_evidence_idx ON public.disputes_evidence USING btree (dispute_id, created_at);


--
-- Name: disputes_evidence_submitted_by_id_7cff983e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX disputes_evidence_submitted_by_id_7cff983e ON public.disputes_evidence USING btree (submitted_by_id);


--
-- Name: disputes_one_active_per_deal; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX disputes_one_active_per_deal ON public.disputes_dispute USING btree (deal_id) WHERE ((status)::text = ANY ((ARRAY['open'::character varying, 'awaiting_evidence'::character varying, 'under_review'::character varying])::text[]));


--
-- Name: disputes_queue_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX disputes_queue_idx ON public.disputes_dispute USING btree (status, opened_at DESC);


--
-- Name: django_admin_log_content_type_id_c4bce8eb; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_admin_log_content_type_id_c4bce8eb ON public.django_admin_log USING btree (content_type_id);


--
-- Name: django_admin_log_user_id_c564eba6; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_admin_log_user_id_c564eba6 ON public.django_admin_log USING btree (user_id);


--
-- Name: django_session_expire_date_a5c62663; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_session_expire_date_a5c62663 ON public.django_session USING btree (expire_date);


--
-- Name: django_session_session_key_c0390e0f_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX django_session_session_key_c0390e0f_like ON public.django_session USING btree (session_key varchar_pattern_ops);


--
-- Name: fin_account_operation_sequence; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX fin_account_operation_sequence ON public.finance_payout_provider_operation USING btree (method_id, sequence) WHERE (method_id IS NOT NULL);


--
-- Name: fin_attempt_expiry_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_attempt_expiry_idx ON public.finance_payment_attempt USING btree (status, expires_at);


--
-- Name: fin_attempt_one_open_per_order; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX fin_attempt_one_open_per_order ON public.finance_payment_attempt USING btree (order_id) WHERE ((status)::text = ANY ((ARRAY['created'::character varying, 'checkout_pending'::character varying, 'processing'::character varying])::text[]));


--
-- Name: fin_attempt_order_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_attempt_order_idx ON public.finance_payment_attempt USING btree (order_id, created_at DESC);


--
-- Name: fin_attempt_provider_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_attempt_provider_idx ON public.finance_payment_attempt USING btree (provider, status);


--
-- Name: fin_attempt_unique_provider_payment; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX fin_attempt_unique_provider_payment ON public.finance_payment_attempt USING btree (provider, provider_payment_id) WHERE (NOT ((provider_payment_id)::text = ''::text));


--
-- Name: fin_attempt_unique_provider_session; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX fin_attempt_unique_provider_session ON public.finance_payment_attempt USING btree (provider, provider_session_id) WHERE (NOT ((provider_session_id)::text = ''::text));


--
-- Name: fin_disb_account_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_disb_account_idx ON public.finance_stripe_disbursement USING btree (account_id, created_at DESC);


--
-- Name: fin_disb_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_disb_status_idx ON public.finance_stripe_disbursement USING btree (status, created_at);


--
-- Name: fin_disbursement_provider_identity; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX fin_disbursement_provider_identity ON public.finance_stripe_disbursement USING btree (account_id, provider_mode, provider_payout_id) WHERE (NOT ((provider_payout_id)::text = ''::text));


--
-- Name: fin_event_att_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_event_att_idx ON public.finance_provider_event USING btree (attempt_id, received_at DESC);


--
-- Name: fin_event_provider_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_event_provider_idx ON public.finance_provider_event USING btree (provider, received_at DESC);


--
-- Name: fin_event_recovery_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_event_recovery_idx ON public.finance_provider_event USING btree (processing_result, next_retry_at);


--
-- Name: fin_event_scope_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_event_scope_idx ON public.finance_provider_event USING btree (endpoint_scope, provider_account_id, received_at DESC);


--
-- Name: fin_guest_one_live_link_per_order; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX fin_guest_one_live_link_per_order ON public.finance_guest_payment_link USING btree (order_id) WHERE ((revoked_at IS NULL) AND (consumed_at IS NULL));


--
-- Name: fin_guest_order_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_guest_order_idx ON public.finance_guest_payment_link USING btree (order_id, created_at DESC);


--
-- Name: fin_hold_active_payout; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_hold_active_payout ON public.finance_hold USING btree (payout_id, cleared_at);


--
-- Name: fin_job_due_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_job_due_idx ON public.finance_scheduled_job USING btree (status, run_at);


--
-- Name: fin_job_kind_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_job_kind_idx ON public.finance_scheduled_job USING btree (kind, status);


--
-- Name: fin_ledger_acct_user_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_ledger_acct_user_idx ON public.finance_ledger_entry USING btree (account, user_id);


--
-- Name: fin_ledger_deal_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_ledger_deal_idx ON public.finance_ledger_entry USING btree (deal_id, account);


--
-- Name: fin_ledger_order_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_ledger_order_idx ON public.finance_ledger_entry USING btree (order_id);


--
-- Name: fin_ltx_kind_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_ltx_kind_idx ON public.finance_ledger_transaction USING btree (kind, created_at DESC);


--
-- Name: fin_order_deal_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_order_deal_idx ON public.finance_payment_order USING btree (deal_id, purpose);


--
-- Name: fin_order_one_live_balance_per_deal; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX fin_order_one_live_balance_per_deal ON public.finance_payment_order USING btree (deal_id) WHERE (((purpose)::text = 'deal_balance'::text) AND (NOT ((status)::text = 'cancelled'::text)));


--
-- Name: fin_order_one_live_deposit_per_request; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX fin_order_one_live_deposit_per_request ON public.finance_payment_order USING btree (delivery_request_id) WHERE (((purpose)::text = 'posting_deposit'::text) AND (NOT ((status)::text = 'cancelled'::text)));


--
-- Name: fin_order_owner_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_order_owner_idx ON public.finance_payment_order USING btree (owner_id, created_at DESC);


--
-- Name: fin_order_request_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_order_request_idx ON public.finance_payment_order USING btree (delivery_request_id, purpose);


--
-- Name: fin_order_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_order_status_idx ON public.finance_payment_order USING btree (status, purpose);


--
-- Name: fin_payout_method_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_payout_method_idx ON public.finance_payout USING btree (method, status);


--
-- Name: fin_payout_method_one_default; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX fin_payout_method_one_default ON public.finance_traveler_payout_method USING btree (traveler_id) WHERE is_default;


--
-- Name: fin_payout_one_active_disbursement; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX fin_payout_one_active_disbursement ON public.finance_stripe_disbursement_allocation USING btree (payout_id) WHERE active;


--
-- Name: fin_payout_one_committed_attempt; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX fin_payout_one_committed_attempt ON public.finance_payout_attempt USING btree (payout_id) WHERE ((status)::text = ANY ((ARRAY['dispatch_committed'::character varying, 'unknown'::character varying, 'accepted'::character varying, 'sent'::character varying])::text[]));


--
-- Name: fin_payout_one_prepared_attempt; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX fin_payout_one_prepared_attempt ON public.finance_payout_attempt USING btree (payout_id) WHERE ((status)::text = 'prepared'::text);


--
-- Name: fin_payout_operation_identity; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX fin_payout_operation_identity ON public.finance_payout_provider_operation USING btree (kind, account_scope, provider_mode, provider_object_id) WHERE (NOT ((provider_object_id)::text = ''::text));


--
-- Name: fin_payout_operation_sequence; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX fin_payout_operation_sequence ON public.finance_payout_provider_operation USING btree (attempt_id, sequence) WHERE (attempt_id IS NOT NULL);


--
-- Name: fin_payout_queue_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_payout_queue_idx ON public.finance_payout USING btree (status, scheduled_for);


--
-- Name: fin_payout_trav_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_payout_trav_idx ON public.finance_payout USING btree (traveler_id, created_at DESC);


--
-- Name: fin_refund_order_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_refund_order_idx ON public.finance_payment_refund USING btree (order_id, created_at DESC);


--
-- Name: fin_refund_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fin_refund_status_idx ON public.finance_payment_refund USING btree (status);


--
-- Name: fin_refund_unique_provider_refund; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX fin_refund_unique_provider_refund ON public.finance_payment_refund USING btree (provider, provider_refund_id) WHERE (NOT ((provider_refund_id)::text = ''::text));


--
-- Name: fin_stripe_one_active_account; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX fin_stripe_one_active_account ON public.finance_stripe_payout_account USING btree (traveler_id, platform_id, provider_mode) WHERE active;


--
-- Name: finance_dzd_profile_revision_account_fingerprint_d6496213; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_dzd_profile_revision_account_fingerprint_d6496213 ON public.finance_dzd_profile_revision USING btree (account_fingerprint);


--
-- Name: finance_dzd_profile_revision_account_fingerprint_d6496213_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_dzd_profile_revision_account_fingerprint_d6496213_like ON public.finance_dzd_profile_revision USING btree (account_fingerprint varchar_pattern_ops);


--
-- Name: finance_dzd_profile_revision_evidence_id_f926fc32; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_dzd_profile_revision_evidence_id_f926fc32 ON public.finance_dzd_profile_revision USING btree (evidence_id);


--
-- Name: finance_dzd_profile_revision_identity_attestation_id_16c42fd4; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_dzd_profile_revision_identity_attestation_id_16c42fd4 ON public.finance_dzd_profile_revision USING btree (identity_attestation_id);


--
-- Name: finance_dzd_profile_revision_method_id_136d0c5f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_dzd_profile_revision_method_id_136d0c5f ON public.finance_dzd_profile_revision USING btree (method_id);


--
-- Name: finance_guest_payment_link_created_by_id_551a1ab1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_guest_payment_link_created_by_id_551a1ab1 ON public.finance_guest_payment_link USING btree (created_by_id);


--
-- Name: finance_guest_payment_link_expires_at_ecffd91b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_guest_payment_link_expires_at_ecffd91b ON public.finance_guest_payment_link USING btree (expires_at);


--
-- Name: finance_guest_payment_link_order_id_a42e1ebd; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_guest_payment_link_order_id_a42e1ebd ON public.finance_guest_payment_link USING btree (order_id);


--
-- Name: finance_guest_payment_link_token_hash_da4954f5_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_guest_payment_link_token_hash_da4954f5_like ON public.finance_guest_payment_link USING btree (token_hash varchar_pattern_ops);


--
-- Name: finance_hold_account_id_2d03ecf0; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_hold_account_id_2d03ecf0 ON public.finance_hold USING btree (account_id);


--
-- Name: finance_hold_cleared_by_id_ddcd1db0; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_hold_cleared_by_id_ddcd1db0 ON public.finance_hold USING btree (cleared_by_id);


--
-- Name: finance_hold_deal_id_b4f859f8; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_hold_deal_id_b4f859f8 ON public.finance_hold USING btree (deal_id);


--
-- Name: finance_hold_opened_by_id_61ed2329; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_hold_opened_by_id_61ed2329 ON public.finance_hold USING btree (opened_by_id);


--
-- Name: finance_hold_payout_id_ea48e192; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_hold_payout_id_ea48e192 ON public.finance_hold USING btree (payout_id);


--
-- Name: finance_hold_source_attempt_id_f547de2d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_hold_source_attempt_id_f547de2d ON public.finance_hold USING btree (source_attempt_id);


--
-- Name: finance_ledger_entry_attempt_id_26619ebd; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_ledger_entry_attempt_id_26619ebd ON public.finance_ledger_entry USING btree (attempt_id);


--
-- Name: finance_ledger_entry_deal_id_cf63abba; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_ledger_entry_deal_id_cf63abba ON public.finance_ledger_entry USING btree (deal_id);


--
-- Name: finance_ledger_entry_order_id_fc0792a1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_ledger_entry_order_id_fc0792a1 ON public.finance_ledger_entry USING btree (order_id);


--
-- Name: finance_ledger_entry_payout_id_1ff65405; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_ledger_entry_payout_id_1ff65405 ON public.finance_ledger_entry USING btree (payout_id);


--
-- Name: finance_ledger_entry_refund_id_2221dcec; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_ledger_entry_refund_id_2221dcec ON public.finance_ledger_entry USING btree (refund_id);


--
-- Name: finance_ledger_entry_transaction_id_ec94704b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_ledger_entry_transaction_id_ec94704b ON public.finance_ledger_entry USING btree (transaction_id);


--
-- Name: finance_ledger_entry_user_id_9c8392ab; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_ledger_entry_user_id_9c8392ab ON public.finance_ledger_entry USING btree (user_id);


--
-- Name: finance_ledger_transaction_key_fec16b8e_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_ledger_transaction_key_fec16b8e_like ON public.finance_ledger_transaction USING btree (key varchar_pattern_ops);


--
-- Name: finance_ledger_transaction_kind_532a363d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_ledger_transaction_kind_532a363d ON public.finance_ledger_transaction USING btree (kind);


--
-- Name: finance_ledger_transaction_kind_532a363d_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_ledger_transaction_kind_532a363d_like ON public.finance_ledger_transaction USING btree (kind varchar_pattern_ops);


--
-- Name: finance_ledger_transaction_reverses_id_d4017be9; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_ledger_transaction_reverses_id_d4017be9 ON public.finance_ledger_transaction USING btree (reverses_id);


--
-- Name: finance_manual_payout_receipt_attempt_id_1e342be4; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_manual_payout_receipt_attempt_id_1e342be4 ON public.finance_manual_payout_receipt USING btree (attempt_id);


--
-- Name: finance_manual_payout_receipt_operator_id_a7ef8ec5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_manual_payout_receipt_operator_id_a7ef8ec5 ON public.finance_manual_payout_receipt USING btree (operator_id);


--
-- Name: finance_payment_attempt_fx_settings_version_id_9099cde3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_attempt_fx_settings_version_id_9099cde3 ON public.finance_payment_attempt USING btree (fx_settings_version_id);


--
-- Name: finance_payment_attempt_guest_link_id_478fe6b2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_attempt_guest_link_id_478fe6b2 ON public.finance_payment_attempt USING btree (guest_link_id);


--
-- Name: finance_payment_attempt_operational_resolution_ed46f60e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_attempt_operational_resolution_ed46f60e ON public.finance_payment_attempt USING btree (operational_resolution);


--
-- Name: finance_payment_attempt_operational_resolution_ed46f60e_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_attempt_operational_resolution_ed46f60e_like ON public.finance_payment_attempt USING btree (operational_resolution varchar_pattern_ops);


--
-- Name: finance_payment_attempt_operational_resolved_by_id_40d78727; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_attempt_operational_resolved_by_id_40d78727 ON public.finance_payment_attempt USING btree (operational_resolved_by_id);


--
-- Name: finance_payment_attempt_order_id_e6c98179; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_attempt_order_id_e6c98179 ON public.finance_payment_attempt USING btree (order_id);


--
-- Name: finance_payment_attempt_payer_id_3bdcd913; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_attempt_payer_id_3bdcd913 ON public.finance_payment_attempt USING btree (payer_id);


--
-- Name: finance_payment_attempt_provider_d7c1118c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_attempt_provider_d7c1118c ON public.finance_payment_attempt USING btree (provider);


--
-- Name: finance_payment_attempt_provider_d7c1118c_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_attempt_provider_d7c1118c_like ON public.finance_payment_attempt USING btree (provider varchar_pattern_ops);


--
-- Name: finance_payment_attempt_status_68fe4b35; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_attempt_status_68fe4b35 ON public.finance_payment_attempt USING btree (status);


--
-- Name: finance_payment_attempt_status_68fe4b35_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_attempt_status_68fe4b35_like ON public.finance_payment_attempt USING btree (status varchar_pattern_ops);


--
-- Name: finance_payment_order_business_settings_version_id_c5e57eb4; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_order_business_settings_version_id_c5e57eb4 ON public.finance_payment_order USING btree (business_settings_version_id);


--
-- Name: finance_payment_order_deal_id_be89d1b6; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_order_deal_id_be89d1b6 ON public.finance_payment_order USING btree (deal_id);


--
-- Name: finance_payment_order_delivery_request_id_0a53ea23; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_order_delivery_request_id_0a53ea23 ON public.finance_payment_order USING btree (delivery_request_id);


--
-- Name: finance_payment_order_owner_id_306c0486; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_order_owner_id_306c0486 ON public.finance_payment_order USING btree (owner_id);


--
-- Name: finance_payment_order_purpose_aec3e788; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_order_purpose_aec3e788 ON public.finance_payment_order USING btree (purpose);


--
-- Name: finance_payment_order_purpose_aec3e788_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_order_purpose_aec3e788_like ON public.finance_payment_order USING btree (purpose varchar_pattern_ops);


--
-- Name: finance_payment_order_status_6943a362; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_order_status_6943a362 ON public.finance_payment_order USING btree (status);


--
-- Name: finance_payment_order_status_6943a362_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_order_status_6943a362_like ON public.finance_payment_order USING btree (status varchar_pattern_ops);


--
-- Name: finance_payment_refund_attempt_id_fa439711; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_refund_attempt_id_fa439711 ON public.finance_payment_refund USING btree (attempt_id);


--
-- Name: finance_payment_refund_idempotency_key_df8d6084_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_refund_idempotency_key_df8d6084_like ON public.finance_payment_refund USING btree (idempotency_key varchar_pattern_ops);


--
-- Name: finance_payment_refund_order_id_e85b6171; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_refund_order_id_e85b6171 ON public.finance_payment_refund USING btree (order_id);


--
-- Name: finance_payment_refund_requested_by_id_89dccbc7; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_refund_requested_by_id_89dccbc7 ON public.finance_payment_refund USING btree (requested_by_id);


--
-- Name: finance_payment_refund_requires_manual_action_271b45b0; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_refund_requires_manual_action_271b45b0 ON public.finance_payment_refund USING btree (requires_manual_action);


--
-- Name: finance_payment_refund_settled_by_id_f5e2d8ac; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_refund_settled_by_id_f5e2d8ac ON public.finance_payment_refund USING btree (settled_by_id);


--
-- Name: finance_payment_refund_status_51679129; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_refund_status_51679129 ON public.finance_payment_refund USING btree (status);


--
-- Name: finance_payment_refund_status_51679129_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payment_refund_status_51679129_like ON public.finance_payment_refund USING btree (status varchar_pattern_ops);


--
-- Name: finance_payout_active_instruction_version_id_3ce5d7a7; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_active_instruction_version_id_3ce5d7a7 ON public.finance_payout USING btree (active_instruction_version_id);


--
-- Name: finance_payout_admin_actor_id_a9ddc7f4; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_admin_actor_id_a9ddc7f4 ON public.finance_payout USING btree (admin_actor_id);


--
-- Name: finance_payout_amount_revision_actor_id_b0b41f39; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_amount_revision_actor_id_b0b41f39 ON public.finance_payout_amount_revision USING btree (actor_id);


--
-- Name: finance_payout_amount_revision_fx_settings_version_id_5f2066c7; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_amount_revision_fx_settings_version_id_5f2066c7 ON public.finance_payout_amount_revision USING btree (fx_settings_version_id);


--
-- Name: finance_payout_amount_revision_ledger_transaction_id_e08d7cb7; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_amount_revision_ledger_transaction_id_e08d7cb7 ON public.finance_payout_amount_revision USING btree (ledger_transaction_id);


--
-- Name: finance_payout_amount_revision_payout_id_ca8521da; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_amount_revision_payout_id_ca8521da ON public.finance_payout_amount_revision USING btree (payout_id);


--
-- Name: finance_payout_attempt_amount_revision_id_0d37b95e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_attempt_amount_revision_id_0d37b95e ON public.finance_payout_attempt USING btree (amount_revision_id);


--
-- Name: finance_payout_attempt_idempotency_key_b2f08040_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_attempt_idempotency_key_b2f08040_like ON public.finance_payout_attempt USING btree (idempotency_key varchar_pattern_ops);


--
-- Name: finance_payout_attempt_instruction_version_id_62243bca; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_attempt_instruction_version_id_62243bca ON public.finance_payout_attempt USING btree (instruction_version_id);


--
-- Name: finance_payout_attempt_operator_id_6ce3fbf2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_attempt_operator_id_6ce3fbf2 ON public.finance_payout_attempt USING btree (operator_id);


--
-- Name: finance_payout_attempt_payout_id_0e1e7692; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_attempt_payout_id_0e1e7692 ON public.finance_payout_attempt USING btree (payout_id);


--
-- Name: finance_payout_dzd_profile_revision_id_da138436; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_dzd_profile_revision_id_da138436 ON public.finance_payout USING btree (dzd_profile_revision_id);


--
-- Name: finance_payout_event_actor_id_a62d3ee7; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_event_actor_id_a62d3ee7 ON public.finance_payout_event USING btree (actor_id);


--
-- Name: finance_payout_event_evidence_id_997f5917; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_event_evidence_id_997f5917 ON public.finance_payout_event USING btree (evidence_id);


--
-- Name: finance_payout_event_ledger_transaction_id_a72df823; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_event_ledger_transaction_id_a72df823 ON public.finance_payout_event USING btree (ledger_transaction_id);


--
-- Name: finance_payout_event_operation_id_807b1409; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_event_operation_id_807b1409 ON public.finance_payout_event USING btree (operation_id);


--
-- Name: finance_payout_event_payout_id_89e98008; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_event_payout_id_89e98008 ON public.finance_payout_event USING btree (payout_id);


--
-- Name: finance_payout_evidence_owner_id_751cc2e0; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_evidence_owner_id_751cc2e0 ON public.finance_payout_evidence USING btree (owner_id);


--
-- Name: finance_payout_funding_allocation_allocation_key_1e7a6fa1_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_funding_allocation_allocation_key_1e7a6fa1_like ON public.finance_payout_funding_allocation USING btree (allocation_key varchar_pattern_ops);


--
-- Name: finance_payout_funding_allocation_attempt_id_da72ee55; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_funding_allocation_attempt_id_da72ee55 ON public.finance_payout_funding_allocation USING btree (attempt_id);


--
-- Name: finance_payout_funding_allocation_payout_id_872f06e0; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_funding_allocation_payout_id_872f06e0 ON public.finance_payout_funding_allocation USING btree (payout_id);


--
-- Name: finance_payout_funding_allocation_source_attempt_id_62488a9d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_funding_allocation_source_attempt_id_62488a9d ON public.finance_payout_funding_allocation USING btree (source_attempt_id);


--
-- Name: finance_payout_funding_attempt_id_b068abb2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_funding_attempt_id_b068abb2 ON public.finance_payout USING btree (funding_attempt_id);


--
-- Name: finance_payout_funding_release_actor_id_16999c47; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_funding_release_actor_id_16999c47 ON public.finance_payout_funding_release USING btree (actor_id);


--
-- Name: finance_payout_fx_settings_version_id_13a001ba; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_fx_settings_version_id_13a001ba ON public.finance_payout USING btree (fx_settings_version_id);


--
-- Name: finance_payout_fx_source_attempt_id_a9f6861d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_fx_source_attempt_id_a9f6861d ON public.finance_payout USING btree (fx_source_attempt_id);


--
-- Name: finance_payout_identity_attestation_attested_by_id_cbc2d8a6; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_identity_attestation_attested_by_id_cbc2d8a6 ON public.finance_payout_identity_attestation USING btree (attested_by_id);


--
-- Name: finance_payout_identity_attestation_kyc_submission_id_b5c6a3de; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_identity_attestation_kyc_submission_id_b5c6a3de ON public.finance_payout_identity_attestation USING btree (kyc_submission_id);


--
-- Name: finance_payout_identity_attestation_supersedes_id_f05f6ad1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_identity_attestation_supersedes_id_f05f6ad1 ON public.finance_payout_identity_attestation USING btree (supersedes_id);


--
-- Name: finance_payout_identity_attestation_traveler_id_521b64a4; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_identity_attestation_traveler_id_521b64a4 ON public.finance_payout_identity_attestation USING btree (traveler_id);


--
-- Name: finance_payout_identity_re_assigned_by_id_8bd7ea44; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_identity_re_assigned_by_id_8bd7ea44 ON public.finance_payout_identity_review_assignment USING btree (assigned_by_id);


--
-- Name: finance_payout_identity_re_kyc_submission_id_1a3e6ceb; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_identity_re_kyc_submission_id_1a3e6ceb ON public.finance_payout_identity_review_assignment USING btree (kyc_submission_id);


--
-- Name: finance_payout_identity_review_assignment_reviewer_id_849f357f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_identity_review_assignment_reviewer_id_849f357f ON public.finance_payout_identity_review_assignment USING btree (reviewer_id);


--
-- Name: finance_payout_identity_review_assignment_traveler_id_b6071b64; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_identity_review_assignment_traveler_id_b6071b64 ON public.finance_payout_identity_review_assignment USING btree (traveler_id);


--
-- Name: finance_payout_identity_revocation_actor_id_0d4669c1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_identity_revocation_actor_id_0d4669c1 ON public.finance_payout_identity_revocation USING btree (actor_id);


--
-- Name: finance_payout_instruction_amendment_new_version_id_6d591f63; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_instruction_amendment_new_version_id_6d591f63 ON public.finance_payout_instruction_amendment USING btree (new_version_id);


--
-- Name: finance_payout_instruction_amendment_old_version_id_56abaf12; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_instruction_amendment_old_version_id_56abaf12 ON public.finance_payout_instruction_amendment USING btree (old_version_id);


--
-- Name: finance_payout_instruction_amendment_payout_id_e1b50536; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_instruction_amendment_payout_id_e1b50536 ON public.finance_payout_instruction_amendment USING btree (payout_id);


--
-- Name: finance_payout_instruction_amendment_reviewed_by_id_75d0cfa3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_instruction_amendment_reviewed_by_id_75d0cfa3 ON public.finance_payout_instruction_amendment USING btree (reviewed_by_id);


--
-- Name: finance_payout_instruction_amendment_traveler_id_add22ee2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_instruction_amendment_traveler_id_add22ee2 ON public.finance_payout_instruction_amendment USING btree (traveler_id);


--
-- Name: finance_payout_instruction_confirmation_new_version_id_b22618a4; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_instruction_confirmation_new_version_id_b22618a4 ON public.finance_payout_instruction_confirmation USING btree (new_version_id);


--
-- Name: finance_payout_instruction_confirmation_payout_id_7512f0ca; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_instruction_confirmation_payout_id_7512f0ca ON public.finance_payout_instruction_confirmation USING btree (payout_id);


--
-- Name: finance_payout_instruction_confirmation_traveler_id_16f8a562; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_instruction_confirmation_traveler_id_16f8a562 ON public.finance_payout_instruction_confirmation USING btree (traveler_id);


--
-- Name: finance_payout_method_version_created_by_id_9540ff66; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_method_version_created_by_id_9540ff66 ON public.finance_payout_method_version USING btree (created_by_id);


--
-- Name: finance_payout_method_version_dzd_profile_revision_id_3f3cc202; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_method_version_dzd_profile_revision_id_3f3cc202 ON public.finance_payout_method_version USING btree (dzd_profile_revision_id);


--
-- Name: finance_payout_method_version_id_de3d06b7; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_method_version_id_de3d06b7 ON public.finance_payout USING btree (method_version_id);


--
-- Name: finance_payout_method_version_method_id_2f8935e7; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_method_version_method_id_2f8935e7 ON public.finance_payout_method_version USING btree (method_id);


--
-- Name: finance_payout_method_version_stripe_account_id_bd562a2f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_method_version_stripe_account_id_bd562a2f ON public.finance_payout_method_version USING btree (stripe_account_id);


--
-- Name: finance_payout_profile_review_identity_attestation_id_14d1410f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_profile_review_identity_attestation_id_14d1410f ON public.finance_payout_profile_review USING btree (identity_attestation_id);


--
-- Name: finance_payout_profile_review_profile_id_5fa4ff9b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_profile_review_profile_id_5fa4ff9b ON public.finance_payout_profile_review USING btree (profile_id);


--
-- Name: finance_payout_profile_review_reviewer_id_cf325963; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_profile_review_reviewer_id_cf325963 ON public.finance_payout_profile_review USING btree (reviewer_id);


--
-- Name: finance_payout_provider_op_funding_allocation_id_7f0f345e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_provider_op_funding_allocation_id_7f0f345e ON public.finance_payout_provider_operation USING btree (funding_allocation_id);


--
-- Name: finance_payout_provider_operation_attempt_id_6ca74607; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_provider_operation_attempt_id_6ca74607 ON public.finance_payout_provider_operation USING btree (attempt_id);


--
-- Name: finance_payout_provider_operation_disbursement_id_62d361b1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_provider_operation_disbursement_id_62d361b1 ON public.finance_payout_provider_operation USING btree (disbursement_id);


--
-- Name: finance_payout_provider_operation_idempotency_key_71abdc6f_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_provider_operation_idempotency_key_71abdc6f_like ON public.finance_payout_provider_operation USING btree (idempotency_key varchar_pattern_ops);


--
-- Name: finance_payout_provider_operation_method_id_822f098e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_provider_operation_method_id_822f098e ON public.finance_payout_provider_operation USING btree (method_id);


--
-- Name: finance_payout_status_652246a6; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_status_652246a6 ON public.finance_payout USING btree (status);


--
-- Name: finance_payout_status_652246a6_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_status_652246a6_like ON public.finance_payout USING btree (status varchar_pattern_ops);


--
-- Name: finance_payout_stripe_account_id_8c52326c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_stripe_account_id_8c52326c ON public.finance_payout USING btree (stripe_account_id);


--
-- Name: finance_payout_traveler_id_5ad36ce0; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_payout_traveler_id_5ad36ce0 ON public.finance_payout USING btree (traveler_id);


--
-- Name: finance_provider_dispute_source_attempt_id_82a7e9a7; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_provider_dispute_source_attempt_id_82a7e9a7 ON public.finance_provider_dispute USING btree (source_attempt_id);


--
-- Name: finance_provider_event_attempt_id_d8b89e74; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_provider_event_attempt_id_d8b89e74 ON public.finance_provider_event USING btree (attempt_id);


--
-- Name: finance_provider_event_order_id_973b1b4e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_provider_event_order_id_973b1b4e ON public.finance_provider_event USING btree (order_id);


--
-- Name: finance_scheduled_job_key_a3652fb9_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_scheduled_job_key_a3652fb9_like ON public.finance_scheduled_job USING btree (key varchar_pattern_ops);


--
-- Name: finance_scheduled_job_kind_e1cc9d62; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_scheduled_job_kind_e1cc9d62 ON public.finance_scheduled_job USING btree (kind);


--
-- Name: finance_scheduled_job_kind_e1cc9d62_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_scheduled_job_kind_e1cc9d62_like ON public.finance_scheduled_job USING btree (kind varchar_pattern_ops);


--
-- Name: finance_scheduled_job_resolution_80ea6776; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_scheduled_job_resolution_80ea6776 ON public.finance_scheduled_job USING btree (resolution);


--
-- Name: finance_scheduled_job_resolution_80ea6776_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_scheduled_job_resolution_80ea6776_like ON public.finance_scheduled_job USING btree (resolution varchar_pattern_ops);


--
-- Name: finance_scheduled_job_resolved_by_id_45521f75; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_scheduled_job_resolved_by_id_45521f75 ON public.finance_scheduled_job USING btree (resolved_by_id);


--
-- Name: finance_scheduled_job_run_at_1ef7d06f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_scheduled_job_run_at_1ef7d06f ON public.finance_scheduled_job USING btree (run_at);


--
-- Name: finance_scheduled_job_status_15b1c1fe; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_scheduled_job_status_15b1c1fe ON public.finance_scheduled_job USING btree (status);


--
-- Name: finance_scheduled_job_status_15b1c1fe_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_scheduled_job_status_15b1c1fe_like ON public.finance_scheduled_job USING btree (status varchar_pattern_ops);


--
-- Name: finance_stripe_disbursement_account_id_0addbb81; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_stripe_disbursement_account_id_0addbb81 ON public.finance_stripe_disbursement USING btree (account_id);


--
-- Name: finance_stripe_disbursement_allocation_attempt_id_366d8297; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_stripe_disbursement_allocation_attempt_id_366d8297 ON public.finance_stripe_disbursement_allocation USING btree (attempt_id);


--
-- Name: finance_stripe_disbursement_allocation_disbursement_id_37ad7df5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_stripe_disbursement_allocation_disbursement_id_37ad7df5 ON public.finance_stripe_disbursement_allocation USING btree (disbursement_id);


--
-- Name: finance_stripe_disbursement_allocation_payout_id_c051671a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_stripe_disbursement_allocation_payout_id_c051671a ON public.finance_stripe_disbursement_allocation USING btree (payout_id);


--
-- Name: finance_stripe_payout_ac_creation_operation_key_fadc9128_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_stripe_payout_ac_creation_operation_key_fadc9128_like ON public.finance_stripe_payout_account USING btree (creation_operation_key varchar_pattern_ops);


--
-- Name: finance_stripe_payout_account_traveler_id_d9df979a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_stripe_payout_account_traveler_id_d9df979a ON public.finance_stripe_payout_account USING btree (traveler_id);


--
-- Name: finance_traveler_payout_method_traveler_id_27aac0e7; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX finance_traveler_payout_method_traveler_id_27aac0e7 ON public.finance_traveler_payout_method USING btree (traveler_id);


--
-- Name: geo_alt_name_norm_active_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX geo_alt_name_norm_active_idx ON public.locations_place_alternate_name USING btree (normalized_name, active);


--
-- Name: geo_alt_name_pattern_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX geo_alt_name_pattern_idx ON public.locations_place_alternate_name USING btree (normalized_name varchar_pattern_ops) WHERE active;


--
-- Name: geo_alt_name_source_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX geo_alt_name_source_id_idx ON public.locations_place_alternate_name USING btree (source, source_id);


--
-- Name: geo_country_active_name_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX geo_country_active_name_idx ON public.locations_country USING btree (active, name);


--
-- Name: geo_country_norm_name_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX geo_country_norm_name_idx ON public.locations_country USING btree (normalized_name);


--
-- Name: geo_country_source_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX geo_country_source_id_idx ON public.locations_country USING btree (source, source_id);


--
-- Name: geo_map_airport_active_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX geo_map_airport_active_idx ON public.locations_airport_locality_mapping USING btree (airport_id, active);


--
-- Name: geo_map_locality_active_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX geo_map_locality_active_idx ON public.locations_airport_locality_mapping USING btree (locality_id, active);


--
-- Name: geo_map_one_primary_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX geo_map_one_primary_uniq ON public.locations_airport_locality_mapping USING btree (airport_id, relationship_type) WHERE (active AND is_primary);


--
-- Name: geo_map_source_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX geo_map_source_id_idx ON public.locations_airport_locality_mapping USING btree (source, source_id);


--
-- Name: geo_place_active_norm_name_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX geo_place_active_norm_name_idx ON public.locations_place USING btree (active, normalized_name);


--
-- Name: geo_place_ctry_act_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX geo_place_ctry_act_type_idx ON public.locations_place USING btree (country_id, active, place_type);


--
-- Name: geo_place_ctry_norm_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX geo_place_ctry_norm_idx ON public.locations_place USING btree (country_id, normalized_name);


--
-- Name: geo_place_iata_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX geo_place_iata_uniq ON public.locations_place USING btree (iata_code) WHERE ((iata_code)::text > ''::text);


--
-- Name: geo_place_norm_pattern_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX geo_place_norm_pattern_idx ON public.locations_place USING btree (normalized_name varchar_pattern_ops) WHERE active;


--
-- Name: geo_place_parent_active_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX geo_place_parent_active_idx ON public.locations_place USING btree (parent_id, active);


--
-- Name: geo_place_source_id_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX geo_place_source_id_idx ON public.locations_place USING btree (source, source_id);


--
-- Name: geo_place_type_active_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX geo_place_type_active_idx ON public.locations_place USING btree (place_type, active);


--
-- Name: handover_access_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_access_idx ON public.handover_code_access USING btree (deal_id, created_at DESC);


--
-- Name: handover_att_actor_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_att_actor_idx ON public.handover_attempt USING btree (actor_id, created_at DESC);


--
-- Name: handover_att_window_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_att_window_idx ON public.handover_attempt USING btree (deal_id, kind, created_at DESC);


--
-- Name: handover_attempt_actor_id_93069cb7; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_attempt_actor_id_93069cb7 ON public.handover_attempt USING btree (actor_id);


--
-- Name: handover_attempt_code_id_8f5c9f85; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_attempt_code_id_8f5c9f85 ON public.handover_attempt USING btree (code_id);


--
-- Name: handover_attempt_created_at_79f90837; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_attempt_created_at_79f90837 ON public.handover_attempt USING btree (created_at);


--
-- Name: handover_attempt_deal_id_de76fd8b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_attempt_deal_id_de76fd8b ON public.handover_attempt USING btree (deal_id);


--
-- Name: handover_attempt_result_aac4cac6; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_attempt_result_aac4cac6 ON public.handover_attempt USING btree (result);


--
-- Name: handover_attempt_result_aac4cac6_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_attempt_result_aac4cac6_like ON public.handover_attempt USING btree (result varchar_pattern_ops);


--
-- Name: handover_code_access_actor_id_bc611bf5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_code_access_actor_id_bc611bf5 ON public.handover_code_access USING btree (actor_id);


--
-- Name: handover_code_access_code_id_0393b58d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_code_access_code_id_0393b58d ON public.handover_code_access USING btree (code_id);


--
-- Name: handover_code_access_created_at_5292991d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_code_access_created_at_5292991d ON public.handover_code_access USING btree (created_at);


--
-- Name: handover_code_access_deal_id_0382ad0d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_code_access_deal_id_0382ad0d ON public.handover_code_access USING btree (deal_id);


--
-- Name: handover_deal_code_deal_id_2c4d715c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_deal_code_deal_id_2c4d715c ON public.handover_deal_code USING btree (deal_id);


--
-- Name: handover_deal_code_issued_to_id_2fba254c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_deal_code_issued_to_id_2fba254c ON public.handover_deal_code USING btree (issued_to_id);


--
-- Name: handover_deal_code_kind_580406ce; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_deal_code_kind_580406ce ON public.handover_deal_code USING btree (kind);


--
-- Name: handover_deal_code_kind_580406ce_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_deal_code_kind_580406ce_like ON public.handover_deal_code USING btree (kind varchar_pattern_ops);


--
-- Name: handover_deal_code_status_c40db3ce; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_deal_code_status_c40db3ce ON public.handover_deal_code USING btree (status);


--
-- Name: handover_deal_code_status_c40db3ce_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_deal_code_status_c40db3ce_like ON public.handover_deal_code USING btree (status varchar_pattern_ops);


--
-- Name: handover_deal_code_used_by_id_a52d8dc1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_deal_code_used_by_id_a52d8dc1 ON public.handover_deal_code USING btree (used_by_id);


--
-- Name: handover_lookup_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_lookup_idx ON public.handover_deal_code USING btree (deal_id, kind, status);


--
-- Name: handover_one_active_per_match_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX handover_one_active_per_match_kind ON public.verification_handover_code USING btree (match_id, kind) WHERE ((status)::text = 'active'::text);


--
-- Name: handover_one_live_code_per_kind; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX handover_one_live_code_per_kind ON public.handover_deal_code USING btree (deal_id, kind) WHERE ((status)::text = ANY ((ARRAY['buffered'::character varying, 'active'::character varying])::text[]));


--
-- Name: handover_release_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX handover_release_idx ON public.handover_deal_code USING btree (status, available_at);


--
-- Name: journey_endpoints_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX journey_endpoints_idx ON public.trips_journey USING btree (start_location_id, destination_location_id, status);


--
-- Name: journey_leg_mode_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX journey_leg_mode_time_idx ON public.trips_journey_leg USING btree (mode, depart_at);


--
-- Name: journey_leg_route_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX journey_leg_route_idx ON public.trips_journey_leg USING btree (origin_id, destination_id, depart_at);


--
-- Name: journey_leg_time_window_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX journey_leg_time_window_idx ON public.trips_journey_leg USING btree (journey_id, depart_at, arrive_at);


--
-- Name: journey_owner_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX journey_owner_status_idx ON public.trips_journey USING btree (traveler_id, status, created_at DESC);


--
-- Name: journey_place_endpoints_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX journey_place_endpoints_idx ON public.trips_journey USING btree (start_place_id, destination_place_id, status);


--
-- Name: journey_proof_review_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX journey_proof_review_idx ON public.trips_journey_leg_proof USING btree (leg_id, status, created_at DESC);


--
-- Name: journey_proof_unique_idempotency_key; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX journey_proof_unique_idempotency_key ON public.trips_journey_leg_proof USING btree (leg_id, idempotency_key) WHERE (NOT ((idempotency_key)::text = ''::text));


--
-- Name: journey_status_published_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX journey_status_published_idx ON public.trips_journey USING btree (status, published_at DESC);


--
-- Name: kyc_one_approved_per_user_doctype; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX kyc_one_approved_per_user_doctype ON public.kyc_submission USING btree (user_id, document_type) WHERE ((status)::text = 'approved'::text);


--
-- Name: kyc_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX kyc_status_idx ON public.kyc_submission USING btree (status);


--
-- Name: kyc_submission_idempotency_key_87ed0c3f_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX kyc_submission_idempotency_key_87ed0c3f_like ON public.kyc_submission USING btree (idempotency_key varchar_pattern_ops);


--
-- Name: kyc_submission_status_166456ca; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX kyc_submission_status_166456ca ON public.kyc_submission USING btree (status);


--
-- Name: kyc_submission_status_166456ca_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX kyc_submission_status_166456ca_like ON public.kyc_submission USING btree (status varchar_pattern_ops);


--
-- Name: kyc_submission_user_id_88472018; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX kyc_submission_user_id_88472018 ON public.kyc_submission USING btree (user_id);


--
-- Name: kyc_user_latest_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX kyc_user_latest_idx ON public.kyc_submission USING btree (user_id, created_at DESC);


--
-- Name: locations_airport_locality_mapping_active_58d4db6a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_airport_locality_mapping_active_58d4db6a ON public.locations_airport_locality_mapping USING btree (active);


--
-- Name: locations_airport_locality_mapping_airport_id_4068f206; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_airport_locality_mapping_airport_id_4068f206 ON public.locations_airport_locality_mapping USING btree (airport_id);


--
-- Name: locations_airport_locality_mapping_locality_id_d9dac550; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_airport_locality_mapping_locality_id_d9dac550 ON public.locations_airport_locality_mapping USING btree (locality_id);


--
-- Name: locations_country_active_d6c9ea76; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_country_active_d6c9ea76 ON public.locations_country USING btree (active);


--
-- Name: locations_country_city_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_country_city_idx ON public.locations_location USING btree (country_code, city);


--
-- Name: locations_country_code_bacab364_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_country_code_bacab364_like ON public.locations_country USING btree (code varchar_pattern_ops);


--
-- Name: locations_geography_cata_content_sha256_f6e177b3_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_geography_cata_content_sha256_f6e177b3_like ON public.locations_geography_catalogue_import USING btree (content_sha256 varchar_pattern_ops);


--
-- Name: locations_kind_country_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_kind_country_idx ON public.locations_location USING btree (kind, country_code);


--
-- Name: locations_location_airport_id_02040de1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_location_airport_id_02040de1 ON public.locations_location USING btree (airport_id);


--
-- Name: locations_location_airport_id_02040de1_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_location_airport_id_02040de1_like ON public.locations_location USING btree (airport_id varchar_pattern_ops);


--
-- Name: locations_location_canonical_place_id_0ec16219; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_location_canonical_place_id_0ec16219 ON public.locations_location USING btree (canonical_place_id);


--
-- Name: locations_location_coordinates_trusted_99041f7e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_location_coordinates_trusted_99041f7e ON public.locations_location USING btree (coordinates_trusted);


--
-- Name: locations_location_created_by_id_37e13144; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_location_created_by_id_37e13144 ON public.locations_location USING btree (created_by_id);


--
-- Name: locations_location_owner_id_dcf0d67f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_location_owner_id_dcf0d67f ON public.locations_location USING btree (owner_id);


--
-- Name: locations_owner_created_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_owner_created_idx ON public.locations_location USING btree (owner_id, created_at DESC);


--
-- Name: locations_owner_provider_place_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX locations_owner_provider_place_uniq ON public.locations_location USING btree (owner_id, provider, provider_place_id) WHERE ((owner_id IS NOT NULL) AND (NOT ((provider)::text = ''::text)) AND (NOT ((provider_place_id)::text = ''::text)));


--
-- Name: locations_place_active_b81dc6c8; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_place_active_b81dc6c8 ON public.locations_place USING btree (active);


--
-- Name: locations_place_alternate_name_active_ff041075; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_place_alternate_name_active_ff041075 ON public.locations_place_alternate_name USING btree (active);


--
-- Name: locations_place_alternate_name_place_id_9c6b0670; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_place_alternate_name_place_id_9c6b0670 ON public.locations_place_alternate_name USING btree (place_id);


--
-- Name: locations_place_country_id_1740f5cc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_place_country_id_1740f5cc ON public.locations_place USING btree (country_id);


--
-- Name: locations_place_country_id_1740f5cc_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_place_country_id_1740f5cc_like ON public.locations_place USING btree (country_id varchar_pattern_ops);


--
-- Name: locations_place_legacy_airport_id_d24c896a_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_place_legacy_airport_id_d24c896a_like ON public.locations_place USING btree (legacy_airport_id varchar_pattern_ops);


--
-- Name: locations_place_parent_id_13a98485; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX locations_place_parent_id_13a98485 ON public.locations_place USING btree (parent_id);


--
-- Name: locations_shared_provider_place_uniq; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX locations_shared_provider_place_uniq ON public.locations_location USING btree (provider, provider_place_id) WHERE ((owner_id IS NULL) AND (NOT ((provider)::text = ''::text)) AND (NOT ((provider_place_id)::text = ''::text)));


--
-- Name: match_event_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX match_event_idx ON public.matching_event USING btree (match_id, created_at DESC);


--
-- Name: match_journey_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX match_journey_status_idx ON public.matching_match USING btree (journey_id, status);


--
-- Name: match_journey_version_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX match_journey_version_idx ON public.matching_match USING btree (journey_id, matching_version, status);


--
-- Name: match_parcel_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX match_parcel_status_idx ON public.matching_match USING btree (parcel_id, status);


--
-- Name: match_sender_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX match_sender_idx ON public.matching_match USING btree (sender_id, created_at DESC);


--
-- Name: match_traveler_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX match_traveler_idx ON public.matching_match USING btree (traveler_id, created_at DESC);


--
-- Name: match_trip_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX match_trip_status_idx ON public.matching_match USING btree (trip_id, status);


--
-- Name: match_unique_pending_journey; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX match_unique_pending_journey ON public.matching_match USING btree (parcel_id, journey_id) WHERE ((journey_id IS NOT NULL) AND ((status)::text = 'pending'::text));


--
-- Name: match_unique_pending_pair; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX match_unique_pending_pair ON public.matching_match USING btree (parcel_id, trip_id) WHERE (((status)::text = 'pending'::text) AND (trip_id IS NOT NULL));


--
-- Name: matching_event_actor_id_4bbc578e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX matching_event_actor_id_4bbc578e ON public.matching_event USING btree (actor_id);


--
-- Name: matching_event_match_id_9a46daed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX matching_event_match_id_9a46daed ON public.matching_event USING btree (match_id);


--
-- Name: matching_event_offer_id_0c174aa5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX matching_event_offer_id_0c174aa5 ON public.matching_event USING btree (offer_id);


--
-- Name: matching_match_end_leg_id_85a27d52; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX matching_match_end_leg_id_85a27d52 ON public.matching_match USING btree (end_leg_id);


--
-- Name: matching_match_journey_id_c1c75fa5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX matching_match_journey_id_c1c75fa5 ON public.matching_match USING btree (journey_id);


--
-- Name: matching_match_parcel_id_37bffd80; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX matching_match_parcel_id_37bffd80 ON public.matching_match USING btree (parcel_id);


--
-- Name: matching_match_sender_id_d5f8efbd; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX matching_match_sender_id_d5f8efbd ON public.matching_match USING btree (sender_id);


--
-- Name: matching_match_start_leg_id_a274366e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX matching_match_start_leg_id_a274366e ON public.matching_match USING btree (start_leg_id);


--
-- Name: matching_match_status_ce0f5571; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX matching_match_status_ce0f5571 ON public.matching_match USING btree (status);


--
-- Name: matching_match_status_ce0f5571_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX matching_match_status_ce0f5571_like ON public.matching_match USING btree (status varchar_pattern_ops);


--
-- Name: matching_match_traveler_id_efec247a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX matching_match_traveler_id_efec247a ON public.matching_match USING btree (traveler_id);


--
-- Name: matching_match_trip_id_c9757271; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX matching_match_trip_id_c9757271 ON public.matching_match USING btree (trip_id);


--
-- Name: matching_offer_business_settings_version_id_57f2ce49; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX matching_offer_business_settings_version_id_57f2ce49 ON public.matching_offer USING btree (business_settings_version_id);


--
-- Name: matching_offer_economics_version_7d6b7ac8; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX matching_offer_economics_version_7d6b7ac8 ON public.matching_offer USING btree (economics_version);


--
-- Name: matching_offer_economics_version_7d6b7ac8_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX matching_offer_economics_version_7d6b7ac8_like ON public.matching_offer USING btree (economics_version varchar_pattern_ops);


--
-- Name: matching_offer_match_id_e31edde3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX matching_offer_match_id_e31edde3 ON public.matching_offer USING btree (match_id);


--
-- Name: matching_offer_proposer_id_00bc9a80; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX matching_offer_proposer_id_00bc9a80 ON public.matching_offer USING btree (proposer_id);


--
-- Name: matching_offer_status_50070c54; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX matching_offer_status_50070c54 ON public.matching_offer USING btree (status);


--
-- Name: matching_offer_status_50070c54_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX matching_offer_status_50070c54_like ON public.matching_offer USING btree (status varchar_pattern_ops);


--
-- Name: notif_recipient_recent_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notif_recipient_recent_idx ON public.notification USING btree (recipient_id, created_at DESC);


--
-- Name: notif_recipient_unread_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notif_recipient_unread_idx ON public.notification USING btree (recipient_id, read_at);


--
-- Name: notification_channel_23c2bac3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_channel_23c2bac3 ON public.notification USING btree (channel);


--
-- Name: notification_channel_23c2bac3_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_channel_23c2bac3_like ON public.notification USING btree (channel varchar_pattern_ops);


--
-- Name: notification_created_at_02eea978; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_created_at_02eea978 ON public.notification USING btree (created_at);


--
-- Name: notification_event_id_62517e32; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_event_id_62517e32 ON public.notification USING btree (event_id);


--
-- Name: notification_event_id_62517e32_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_event_id_62517e32_like ON public.notification USING btree (event_id varchar_pattern_ops);


--
-- Name: notification_outbound_message_deal_id_0990d7c4; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_outbound_message_deal_id_0990d7c4 ON public.notification_outbound_message USING btree (deal_id);


--
-- Name: notification_outbound_message_key_c6d41f48_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_outbound_message_key_c6d41f48_like ON public.notification_outbound_message USING btree (key varchar_pattern_ops);


--
-- Name: notification_outbound_message_kind_f18207d6; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_outbound_message_kind_f18207d6 ON public.notification_outbound_message USING btree (kind);


--
-- Name: notification_outbound_message_kind_f18207d6_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_outbound_message_kind_f18207d6_like ON public.notification_outbound_message USING btree (kind varchar_pattern_ops);


--
-- Name: notification_outbound_message_language_95ecda7b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_outbound_message_language_95ecda7b ON public.notification_outbound_message USING btree (language);


--
-- Name: notification_outbound_message_language_95ecda7b_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_outbound_message_language_95ecda7b_like ON public.notification_outbound_message USING btree (language varchar_pattern_ops);


--
-- Name: notification_outbound_message_next_attempt_at_e5b9fab7; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_outbound_message_next_attempt_at_e5b9fab7 ON public.notification_outbound_message USING btree (next_attempt_at);


--
-- Name: notification_outbound_message_recipient_user_id_4f1f66f1; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_outbound_message_recipient_user_id_4f1f66f1 ON public.notification_outbound_message USING btree (recipient_user_id);


--
-- Name: notification_outbound_message_status_bd65865e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_outbound_message_status_bd65865e ON public.notification_outbound_message USING btree (status);


--
-- Name: notification_outbound_message_status_bd65865e_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_outbound_message_status_bd65865e_like ON public.notification_outbound_message USING btree (status varchar_pattern_ops);


--
-- Name: notification_outbound_secret_consumed_at_21b8fa52; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_outbound_secret_consumed_at_21b8fa52 ON public.notification_outbound_secret USING btree (consumed_at);


--
-- Name: notification_outbound_secret_expires_at_3ce43b68; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_outbound_secret_expires_at_3ce43b68 ON public.notification_outbound_secret USING btree (expires_at);


--
-- Name: notification_outbound_secret_key_58db8ae5_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_outbound_secret_key_58db8ae5_like ON public.notification_outbound_secret USING btree (key varchar_pattern_ops);


--
-- Name: notification_push_device_active_d5e31dca; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_push_device_active_d5e31dca ON public.notification_push_device USING btree (active);


--
-- Name: notification_push_device_last_seen_at_39b3ce8a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_push_device_last_seen_at_39b3ce8a ON public.notification_push_device USING btree (last_seen_at);


--
-- Name: notification_push_device_token_fingerprint_0f5a13c5_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_push_device_token_fingerprint_0f5a13c5_like ON public.notification_push_device USING btree (token_fingerprint varchar_pattern_ops);


--
-- Name: notification_push_device_user_id_10b2bfcc; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_push_device_user_id_10b2bfcc ON public.notification_push_device USING btree (user_id);


--
-- Name: notification_read_at_c2b8c24d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_read_at_c2b8c24d ON public.notification USING btree (read_at);


--
-- Name: notification_recipient_id_305d14d6; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_recipient_id_305d14d6 ON public.notification USING btree (recipient_id);


--
-- Name: offer_match_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX offer_match_idx ON public.matching_offer USING btree (match_id, created_at DESC);


--
-- Name: offer_one_accepted_per_match; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX offer_one_accepted_per_match ON public.matching_offer USING btree (match_id) WHERE ((status)::text = 'accepted'::text);


--
-- Name: offer_one_pending_per_match; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX offer_one_pending_per_match ON public.matching_offer USING btree (match_id) WHERE ((status)::text = 'pending'::text);


--
-- Name: offer_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX offer_status_idx ON public.matching_offer USING btree (status);


--
-- Name: outbound_deal_kind_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX outbound_deal_kind_idx ON public.notification_outbound_message USING btree (deal_id, kind);


--
-- Name: outbound_due_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX outbound_due_idx ON public.notification_outbound_message USING btree (status, next_attempt_at);


--
-- Name: outbound_secret_exp_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX outbound_secret_exp_idx ON public.notification_outbound_secret USING btree (purpose, expires_at);


--
-- Name: parcels_boost_expiry_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_boost_expiry_idx ON public.parcels_delivery USING btree (ranking_boost_expires_at);


--
-- Name: parcels_corridor_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_corridor_idx ON public.parcels_request USING btree (origin_id, destination_id, status);


--
-- Name: parcels_delivery_delivery_location_id_b57c763f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_delivery_delivery_location_id_b57c763f ON public.parcels_delivery USING btree (delivery_location_id);


--
-- Name: parcels_delivery_delivery_place_id_406fd8d0; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_delivery_delivery_place_id_406fd8d0 ON public.parcels_delivery USING btree (delivery_place_id);


--
-- Name: parcels_delivery_pickup_location_id_7bf84e0c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_delivery_pickup_location_id_7bf84e0c ON public.parcels_delivery USING btree (pickup_location_id);


--
-- Name: parcels_delivery_pickup_place_id_91535a2e; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_delivery_pickup_place_id_91535a2e ON public.parcels_delivery USING btree (pickup_place_id);


--
-- Name: parcels_kind_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_kind_status_idx ON public.parcels_request USING btree (kind, status);


--
-- Name: parcels_media_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_media_idx ON public.parcels_media USING btree (parcel_id, created_at);


--
-- Name: parcels_media_parcel_id_4618cd58; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_media_parcel_id_4618cd58 ON public.parcels_media USING btree (parcel_id);


--
-- Name: parcels_media_purpose_404f54aa; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_media_purpose_404f54aa ON public.parcels_media USING btree (purpose);


--
-- Name: parcels_media_purpose_404f54aa_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_media_purpose_404f54aa_like ON public.parcels_media USING btree (purpose varchar_pattern_ops);


--
-- Name: parcels_media_staged_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_media_staged_idx ON public.parcels_media USING btree (uploaded_by_id, parcel_id);


--
-- Name: parcels_media_unique_idempotency; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX parcels_media_unique_idempotency ON public.parcels_media USING btree (uploaded_by_id, idempotency_key) WHERE (NOT ((idempotency_key)::text = ''::text));


--
-- Name: parcels_media_uploaded_by_id_213d0269; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_media_uploaded_by_id_213d0269 ON public.parcels_media USING btree (uploaded_by_id);


--
-- Name: parcels_request_destination_id_3759c9ba; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_request_destination_id_3759c9ba ON public.parcels_request USING btree (destination_id);


--
-- Name: parcels_request_destination_id_3759c9ba_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_request_destination_id_3759c9ba_like ON public.parcels_request USING btree (destination_id varchar_pattern_ops);


--
-- Name: parcels_request_kind_d2680e98; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_request_kind_d2680e98 ON public.parcels_request USING btree (kind);


--
-- Name: parcels_request_kind_d2680e98_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_request_kind_d2680e98_like ON public.parcels_request USING btree (kind varchar_pattern_ops);


--
-- Name: parcels_request_origin_id_ea79a227; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_request_origin_id_ea79a227 ON public.parcels_request USING btree (origin_id);


--
-- Name: parcels_request_origin_id_ea79a227_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_request_origin_id_ea79a227_like ON public.parcels_request USING btree (origin_id varchar_pattern_ops);


--
-- Name: parcels_request_sender_id_b6c24f22; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_request_sender_id_b6c24f22 ON public.parcels_request USING btree (sender_id);


--
-- Name: parcels_request_status_190c4686; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_request_status_190c4686 ON public.parcels_request USING btree (status);


--
-- Name: parcels_request_status_190c4686_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_request_status_190c4686_like ON public.parcels_request USING btree (status varchar_pattern_ops);


--
-- Name: parcels_request_target_traveler_id_f7c960d8; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_request_target_traveler_id_f7c960d8 ON public.parcels_request USING btree (target_traveler_id);


--
-- Name: parcels_sender_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_sender_idx ON public.parcels_request USING btree (sender_id, created_at DESC);


--
-- Name: parcels_v1_place_route_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_v1_place_route_idx ON public.parcels_delivery USING btree (schema_version, pickup_place_id, delivery_place_id);


--
-- Name: parcels_v1_ready_window_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_v1_ready_window_idx ON public.parcels_delivery USING btree (schema_version, ready_window_start, ready_window_end);


--
-- Name: parcels_v1_route_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX parcels_v1_route_idx ON public.parcels_delivery USING btree (schema_version, pickup_location_id, delivery_location_id);


--
-- Name: payments_event_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX payments_event_idx ON public.payments_event USING btree (intent_id, created_at DESC);


--
-- Name: payments_event_intent_id_ef557761; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX payments_event_intent_id_ef557761 ON public.payments_event USING btree (intent_id);


--
-- Name: payments_intent_payer_id_58eeda3b; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX payments_intent_payer_id_58eeda3b ON public.payments_intent USING btree (payer_id);


--
-- Name: payments_intent_status_5f2168be; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX payments_intent_status_5f2168be ON public.payments_intent USING btree (status);


--
-- Name: payments_intent_status_5f2168be_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX payments_intent_status_5f2168be_like ON public.payments_intent USING btree (status varchar_pattern_ops);


--
-- Name: payments_one_open_per_offer; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX payments_one_open_per_offer ON public.payments_intent USING btree (offer_id) WHERE ((status)::text = ANY ((ARRAY['requires_payment_method'::character varying, 'processing'::character varying])::text[]));


--
-- Name: payments_payer_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX payments_payer_idx ON public.payments_intent USING btree (payer_id, created_at DESC);


--
-- Name: payments_provider_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX payments_provider_status_idx ON public.payments_intent USING btree (provider, status);


--
-- Name: payments_refund_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX payments_refund_idx ON public.payments_refund USING btree (intent_id, created_at DESC);


--
-- Name: payments_refund_intent_id_0fcc71c9; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX payments_refund_intent_id_0fcc71c9 ON public.payments_refund USING btree (intent_id);


--
-- Name: payments_refund_unique_provider_id; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX payments_refund_unique_provider_id ON public.payments_refund USING btree (provider, provider_refund_id) WHERE (NOT ((provider_refund_id)::text = ''::text));


--
-- Name: payments_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX payments_status_idx ON public.payments_intent USING btree (status);


--
-- Name: payments_unique_client_key_per_payer; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX payments_unique_client_key_per_payer ON public.payments_intent USING btree (payer_id, client_idempotency_key) WHERE (NOT ((client_idempotency_key)::text = ''::text));


--
-- Name: payments_unique_provider_intent; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX payments_unique_provider_intent ON public.payments_intent USING btree (provider, provider_intent_id) WHERE (NOT ((provider_intent_id)::text = ''::text));


--
-- Name: push_device_user_active_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX push_device_user_active_idx ON public.notification_push_device USING btree (user_id, active);


--
-- Name: ratings_ratee_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ratings_ratee_idx ON public.ratings_rating USING btree (ratee_id, created_at DESC);


--
-- Name: ratings_rating_deal_id_4ca9de15; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ratings_rating_deal_id_4ca9de15 ON public.ratings_rating USING btree (deal_id);


--
-- Name: ratings_rating_ratee_id_68de5385; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ratings_rating_ratee_id_68de5385 ON public.ratings_rating USING btree (ratee_id);


--
-- Name: ratings_rating_rater_id_1093bd6d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ratings_rating_rater_id_1093bd6d ON public.ratings_rating USING btree (rater_id);


--
-- Name: ratings_reveal_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX ratings_reveal_idx ON public.ratings_rating USING btree (revealed_at, review_window_ends_at);


--
-- Name: token_blacklist_outstandingtoken_jti_hex_d9bdf6f7_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX token_blacklist_outstandingtoken_jti_hex_d9bdf6f7_like ON public.token_blacklist_outstandingtoken USING btree (jti varchar_pattern_ops);


--
-- Name: token_blacklist_outstandingtoken_user_id_83bc629a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX token_blacklist_outstandingtoken_user_id_83bc629a ON public.token_blacklist_outstandingtoken USING btree (user_id);


--
-- Name: trips_airport_country_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_airport_country_idx ON public.trips_airport USING btree (country);


--
-- Name: trips_airport_iata_e9932bf0_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_airport_iata_e9932bf0_like ON public.trips_airport USING btree (iata varchar_pattern_ops);


--
-- Name: trips_corridor_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_corridor_idx ON public.trips_trip USING btree (origin_id, destination_id, departure_at);


--
-- Name: trips_journey_destination_location_id_a4b8da30; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_journey_destination_location_id_a4b8da30 ON public.trips_journey USING btree (destination_location_id);


--
-- Name: trips_journey_destination_place_id_a9e2040d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_journey_destination_place_id_a9e2040d ON public.trips_journey USING btree (destination_place_id);


--
-- Name: trips_journey_leg_destination_id_bf982858; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_journey_leg_destination_id_bf982858 ON public.trips_journey_leg USING btree (destination_id);


--
-- Name: trips_journey_leg_destination_place_id_5098d4a5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_journey_leg_destination_place_id_5098d4a5 ON public.trips_journey_leg USING btree (destination_place_id);


--
-- Name: trips_journey_leg_journey_id_aaa36f4d; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_journey_leg_journey_id_aaa36f4d ON public.trips_journey_leg USING btree (journey_id);


--
-- Name: trips_journey_leg_origin_id_4f36a14c; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_journey_leg_origin_id_4f36a14c ON public.trips_journey_leg USING btree (origin_id);


--
-- Name: trips_journey_leg_origin_place_id_112b90e3; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_journey_leg_origin_place_id_112b90e3 ON public.trips_journey_leg USING btree (origin_place_id);


--
-- Name: trips_journey_leg_proof_leg_id_4f5caa94; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_journey_leg_proof_leg_id_4f5caa94 ON public.trips_journey_leg_proof USING btree (leg_id);


--
-- Name: trips_journey_leg_proof_reviewer_id_54c7deea; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_journey_leg_proof_reviewer_id_54c7deea ON public.trips_journey_leg_proof USING btree (reviewer_id);


--
-- Name: trips_journey_leg_proof_status_5829fefa; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_journey_leg_proof_status_5829fefa ON public.trips_journey_leg_proof USING btree (status);


--
-- Name: trips_journey_leg_proof_status_5829fefa_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_journey_leg_proof_status_5829fefa_like ON public.trips_journey_leg_proof USING btree (status varchar_pattern_ops);


--
-- Name: trips_journey_start_location_id_9e128623; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_journey_start_location_id_9e128623 ON public.trips_journey USING btree (start_location_id);


--
-- Name: trips_journey_start_place_id_5e983cd2; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_journey_start_place_id_5e983cd2 ON public.trips_journey USING btree (start_place_id);


--
-- Name: trips_journey_status_790ba2ce; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_journey_status_790ba2ce ON public.trips_journey USING btree (status);


--
-- Name: trips_journey_status_790ba2ce_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_journey_status_790ba2ce_like ON public.trips_journey USING btree (status varchar_pattern_ops);


--
-- Name: trips_journey_traveler_id_2f192771; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_journey_traveler_id_2f192771 ON public.trips_journey USING btree (traveler_id);


--
-- Name: trips_media_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_media_idx ON public.trips_media USING btree (trip_id, created_at);


--
-- Name: trips_media_trip_id_564fe19f; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_media_trip_id_564fe19f ON public.trips_media USING btree (trip_id);


--
-- Name: trips_stopover_airport_id_0767c665; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_stopover_airport_id_0767c665 ON public.trips_stopover USING btree (airport_id);


--
-- Name: trips_stopover_airport_id_0767c665_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_stopover_airport_id_0767c665_like ON public.trips_stopover USING btree (airport_id varchar_pattern_ops);


--
-- Name: trips_stopover_trip_id_ff310d00; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_stopover_trip_id_ff310d00 ON public.trips_stopover USING btree (trip_id);


--
-- Name: trips_track_trip_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_track_trip_idx ON public.trips_tracking_snapshot USING btree (trip_id, captured_at DESC);


--
-- Name: trips_tracking_snapshot_trip_id_605cb5d5; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_tracking_snapshot_trip_id_605cb5d5 ON public.trips_tracking_snapshot USING btree (trip_id);


--
-- Name: trips_trip_destination_id_a03da6f8; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_trip_destination_id_a03da6f8 ON public.trips_trip USING btree (destination_id);


--
-- Name: trips_trip_destination_id_a03da6f8_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_trip_destination_id_a03da6f8_like ON public.trips_trip USING btree (destination_id varchar_pattern_ops);


--
-- Name: trips_trip_origin_id_043ab555; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_trip_origin_id_043ab555 ON public.trips_trip USING btree (origin_id);


--
-- Name: trips_trip_origin_id_043ab555_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_trip_origin_id_043ab555_like ON public.trips_trip USING btree (origin_id varchar_pattern_ops);


--
-- Name: trips_trip_status_b4892f21; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_trip_status_b4892f21 ON public.trips_trip USING btree (status);


--
-- Name: trips_trip_status_b4892f21_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_trip_status_b4892f21_like ON public.trips_trip USING btree (status varchar_pattern_ops);


--
-- Name: trips_trip_traveler_id_78282829; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_trip_traveler_id_78282829 ON public.trips_trip USING btree (traveler_id);


--
-- Name: trips_user_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trips_user_idx ON public.trips_trip USING btree (traveler_id, departure_at DESC);


--
-- Name: verification_handover_code_issued_to_id_14f1a0fd; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX verification_handover_code_issued_to_id_14f1a0fd ON public.verification_handover_code USING btree (issued_to_id);


--
-- Name: verification_handover_code_kind_28a9cb35; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX verification_handover_code_kind_28a9cb35 ON public.verification_handover_code USING btree (kind);


--
-- Name: verification_handover_code_kind_28a9cb35_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX verification_handover_code_kind_28a9cb35_like ON public.verification_handover_code USING btree (kind varchar_pattern_ops);


--
-- Name: verification_handover_code_match_id_de694667; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX verification_handover_code_match_id_de694667 ON public.verification_handover_code USING btree (match_id);


--
-- Name: verification_handover_code_status_799e9e47; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX verification_handover_code_status_799e9e47 ON public.verification_handover_code USING btree (status);


--
-- Name: verification_handover_code_status_799e9e47_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX verification_handover_code_status_799e9e47_like ON public.verification_handover_code USING btree (status varchar_pattern_ops);


--
-- Name: verification_handover_code_used_by_id_3599beae; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX verification_handover_code_used_by_id_3599beae ON public.verification_handover_code USING btree (used_by_id);


--
-- Name: wallet_entry_source_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX wallet_entry_source_idx ON public.wallet_entry USING btree (source, source_id);


--
-- Name: wallet_entry_wallet_id_008ca9ae; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX wallet_entry_wallet_id_008ca9ae ON public.wallet_entry USING btree (wallet_id);


--
-- Name: wallet_entry_wallet_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX wallet_entry_wallet_idx ON public.wallet_entry USING btree (wallet_id, created_at DESC);


--
-- Name: wallet_hold_source_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX wallet_hold_source_idx ON public.wallet_hold USING btree (source, source_id);


--
-- Name: wallet_hold_status_58298504; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX wallet_hold_status_58298504 ON public.wallet_hold USING btree (status);


--
-- Name: wallet_hold_status_58298504_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX wallet_hold_status_58298504_like ON public.wallet_hold USING btree (status varchar_pattern_ops);


--
-- Name: wallet_hold_wallet_id_b20de9ff; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX wallet_hold_wallet_id_b20de9ff ON public.wallet_hold USING btree (wallet_id);


--
-- Name: wallet_hold_wallet_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX wallet_hold_wallet_idx ON public.wallet_hold USING btree (wallet_id, status);


--
-- Name: wallet_wallet_user_id_8c75caaa; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX wallet_wallet_user_id_8c75caaa ON public.wallet_wallet USING btree (user_id);


--
-- Name: wallet_wd_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX wallet_wd_status_idx ON public.wallet_withdrawal USING btree (status);


--
-- Name: wallet_wd_user_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX wallet_wd_user_idx ON public.wallet_withdrawal USING btree (user_id, created_at DESC);


--
-- Name: wallet_withdrawal_status_372e26a8; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX wallet_withdrawal_status_372e26a8 ON public.wallet_withdrawal USING btree (status);


--
-- Name: wallet_withdrawal_status_372e26a8_like; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX wallet_withdrawal_status_372e26a8_like ON public.wallet_withdrawal USING btree (status varchar_pattern_ops);


--
-- Name: wallet_withdrawal_user_id_4fd05cda; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX wallet_withdrawal_user_id_4fd05cda ON public.wallet_withdrawal USING btree (user_id);


--
-- Name: wallet_withdrawal_wallet_id_4825123a; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX wallet_withdrawal_wallet_id_4825123a ON public.wallet_withdrawal USING btree (wallet_id);


--
-- Name: finance_manual_payout_receipt manual_receipt_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER manual_receipt_guard BEFORE INSERT ON public.finance_manual_payout_receipt FOR EACH ROW EXECUTE FUNCTION public.finance_manual_receipt_guard();


--
-- Name: finance_payout manual_receipt_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER manual_receipt_guard BEFORE UPDATE ON public.finance_payout FOR EACH ROW EXECUTE FUNCTION public.finance_manual_receipt_guard();


--
-- Name: finance_payout_attempt manual_receipt_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER manual_receipt_guard BEFORE UPDATE ON public.finance_payout_attempt FOR EACH ROW EXECUTE FUNCTION public.finance_manual_receipt_guard();


--
-- Name: finance_payout_provider_operation payout_execution_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_execution_guard BEFORE INSERT OR UPDATE ON public.finance_payout_provider_operation FOR EACH ROW EXECUTE FUNCTION public.finance_payout_execution_guard();


--
-- Name: finance_stripe_disbursement payout_execution_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_execution_guard BEFORE INSERT OR UPDATE ON public.finance_stripe_disbursement FOR EACH ROW EXECUTE FUNCTION public.finance_payout_execution_guard();


--
-- Name: finance_stripe_disbursement_allocation payout_execution_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_execution_guard BEFORE INSERT OR UPDATE ON public.finance_stripe_disbursement_allocation FOR EACH ROW EXECUTE FUNCTION public.finance_payout_execution_guard();


--
-- Name: finance_dzd_profile_revision payout_history_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_history_immutable BEFORE DELETE OR UPDATE ON public.finance_dzd_profile_revision FOR EACH ROW EXECUTE FUNCTION public.finance_payout_immutable();


--
-- Name: finance_manual_payout_receipt payout_history_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_history_immutable BEFORE DELETE OR UPDATE ON public.finance_manual_payout_receipt FOR EACH ROW EXECUTE FUNCTION public.finance_payout_immutable();


--
-- Name: finance_payout_amount_revision payout_history_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_history_immutable BEFORE DELETE OR UPDATE ON public.finance_payout_amount_revision FOR EACH ROW EXECUTE FUNCTION public.finance_payout_immutable();


--
-- Name: finance_payout_event payout_history_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_history_immutable BEFORE DELETE OR UPDATE ON public.finance_payout_event FOR EACH ROW EXECUTE FUNCTION public.finance_payout_immutable();


--
-- Name: finance_payout_evidence payout_history_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_history_immutable BEFORE DELETE OR UPDATE ON public.finance_payout_evidence FOR EACH ROW EXECUTE FUNCTION public.finance_payout_immutable();


--
-- Name: finance_payout_funding_allocation payout_history_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_history_immutable BEFORE DELETE OR UPDATE ON public.finance_payout_funding_allocation FOR EACH ROW EXECUTE FUNCTION public.finance_payout_immutable();


--
-- Name: finance_payout_funding_release payout_history_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_history_immutable BEFORE DELETE OR UPDATE ON public.finance_payout_funding_release FOR EACH ROW EXECUTE FUNCTION public.finance_payout_immutable();


--
-- Name: finance_payout_identity_attestation payout_history_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_history_immutable BEFORE DELETE OR UPDATE ON public.finance_payout_identity_attestation FOR EACH ROW EXECUTE FUNCTION public.finance_payout_immutable();


--
-- Name: finance_payout_identity_revocation payout_history_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_history_immutable BEFORE DELETE OR UPDATE ON public.finance_payout_identity_revocation FOR EACH ROW EXECUTE FUNCTION public.finance_payout_immutable();


--
-- Name: finance_payout_instruction_amendment payout_history_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_history_immutable BEFORE DELETE OR UPDATE ON public.finance_payout_instruction_amendment FOR EACH ROW EXECUTE FUNCTION public.finance_payout_immutable();


--
-- Name: finance_payout_instruction_confirmation payout_history_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_history_immutable BEFORE DELETE OR UPDATE ON public.finance_payout_instruction_confirmation FOR EACH ROW EXECUTE FUNCTION public.finance_payout_immutable();


--
-- Name: finance_payout_method_version payout_history_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_history_immutable BEFORE DELETE OR UPDATE ON public.finance_payout_method_version FOR EACH ROW EXECUTE FUNCTION public.finance_payout_immutable();


--
-- Name: finance_payout_profile_review payout_history_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_history_immutable BEFORE DELETE OR UPDATE ON public.finance_payout_profile_review FOR EACH ROW EXECUTE FUNCTION public.finance_payout_immutable();


--
-- Name: finance_payout_attempt payout_relation_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_relation_guard BEFORE INSERT OR UPDATE ON public.finance_payout_attempt FOR EACH ROW EXECUTE FUNCTION public.finance_payout_relation_guard();


--
-- Name: finance_payout_funding_allocation payout_relation_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_relation_guard BEFORE INSERT OR UPDATE ON public.finance_payout_funding_allocation FOR EACH ROW EXECUTE FUNCTION public.finance_payout_relation_guard();


--
-- Name: finance_payout_method_version payout_relation_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_relation_guard BEFORE INSERT OR UPDATE ON public.finance_payout_method_version FOR EACH ROW EXECUTE FUNCTION public.finance_payout_relation_guard();


--
-- Name: finance_payout_provider_operation payout_relation_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_relation_guard BEFORE INSERT OR UPDATE ON public.finance_payout_provider_operation FOR EACH ROW EXECUTE FUNCTION public.finance_payout_relation_guard();


--
-- Name: finance_stripe_payout_account payout_relation_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_relation_guard BEFORE INSERT OR UPDATE ON public.finance_stripe_payout_account FOR EACH ROW EXECUTE FUNCTION public.finance_payout_relation_guard();


--
-- Name: finance_traveler_payout_method payout_relation_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_relation_guard BEFORE INSERT OR UPDATE ON public.finance_traveler_payout_method FOR EACH ROW EXECUTE FUNCTION public.finance_payout_relation_guard();


--
-- Name: finance_payout payout_snapshot_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER payout_snapshot_immutable BEFORE INSERT OR UPDATE ON public.finance_payout FOR EACH ROW EXECUTE FUNCTION public.finance_payout_snapshot_guard();


--
-- Name: accounts_emailverificationcode accounts_emailverifi_user_id_2d1d1145_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_emailverificationcode
    ADD CONSTRAINT accounts_emailverifi_user_id_2d1d1145_fk_accounts_ FOREIGN KEY (user_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: accounts_oauthidentity accounts_oauthidentity_user_id_906e1c75_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_oauthidentity
    ADD CONSTRAINT accounts_oauthidentity_user_id_906e1c75_fk_accounts_user_id FOREIGN KEY (user_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: accounts_passwordresetcode accounts_passwordresetcode_user_id_5331448e_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_passwordresetcode
    ADD CONSTRAINT accounts_passwordresetcode_user_id_5331448e_fk_accounts_user_id FOREIGN KEY (user_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: accounts_user_groups accounts_user_groups_group_id_bd11a704_fk_auth_group_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_user_groups
    ADD CONSTRAINT accounts_user_groups_group_id_bd11a704_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: accounts_user_groups accounts_user_groups_user_id_52b62117_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_user_groups
    ADD CONSTRAINT accounts_user_groups_user_id_52b62117_fk_accounts_user_id FOREIGN KEY (user_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: accounts_user_user_permissions accounts_user_user_p_permission_id_113bb443_fk_auth_perm; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_user_user_permissions
    ADD CONSTRAINT accounts_user_user_p_permission_id_113bb443_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: accounts_user_user_permissions accounts_user_user_p_user_id_e4f0a161_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts_user_user_permissions
    ADD CONSTRAINT accounts_user_user_p_user_id_e4f0a161_fk_accounts_ FOREIGN KEY (user_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: admin_panel_audit_log admin_panel_audit_log_actor_id_437e6e37_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_panel_audit_log
    ADD CONSTRAINT admin_panel_audit_log_actor_id_437e6e37_fk_accounts_user_id FOREIGN KEY (actor_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: admin_panel_invitation admin_panel_invitati_accepted_by_id_d9ad5a3f_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_panel_invitation
    ADD CONSTRAINT admin_panel_invitati_accepted_by_id_d9ad5a3f_fk_accounts_ FOREIGN KEY (accepted_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: admin_panel_invitation admin_panel_invitati_invited_by_id_d5d65a71_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.admin_panel_invitation
    ADD CONSTRAINT admin_panel_invitati_invited_by_id_d5d65a71_fk_accounts_ FOREIGN KEY (invited_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_group_permissions auth_group_permissio_permission_id_84c5c92e_fk_auth_perm; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissio_permission_id_84c5c92e_fk_auth_perm FOREIGN KEY (permission_id) REFERENCES public.auth_permission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_group_permissions auth_group_permissions_group_id_b120cbf9_fk_auth_group_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_group_permissions
    ADD CONSTRAINT auth_group_permissions_group_id_b120cbf9_fk_auth_group_id FOREIGN KEY (group_id) REFERENCES public.auth_group(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: auth_permission auth_permission_content_type_id_2f476e4b_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.auth_permission
    ADD CONSTRAINT auth_permission_content_type_id_2f476e4b_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: boosts_intent_event boosts_intent_event_actor_id_91c534f0_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boosts_intent_event
    ADD CONSTRAINT boosts_intent_event_actor_id_91c534f0_fk_accounts_user_id FOREIGN KEY (actor_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: boosts_intent_event boosts_intent_event_business_settings_ve_40a78b91_fk_core_busi; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boosts_intent_event
    ADD CONSTRAINT boosts_intent_event_business_settings_ve_40a78b91_fk_core_busi FOREIGN KEY (business_settings_version_id) REFERENCES public.core_business_settings_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: boosts_intent_event boosts_intent_event_deal_id_9c8cb8b2_fk_deals_deal_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boosts_intent_event
    ADD CONSTRAINT boosts_intent_event_deal_id_9c8cb8b2_fk_deals_deal_id FOREIGN KEY (deal_id) REFERENCES public.deals_deal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: boosts_intent_event boosts_intent_event_delivery_request_id_1e7439b0_fk_parcels_d; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boosts_intent_event
    ADD CONSTRAINT boosts_intent_event_delivery_request_id_1e7439b0_fk_parcels_d FOREIGN KEY (delivery_request_id) REFERENCES public.parcels_delivery(parcelrequest_ptr_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: boosts_purchase boosts_purchase_business_settings_ve_27c0d1e8_fk_core_busi; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boosts_purchase
    ADD CONSTRAINT boosts_purchase_business_settings_ve_27c0d1e8_fk_core_busi FOREIGN KEY (business_settings_version_id) REFERENCES public.core_business_settings_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: boosts_purchase boosts_purchase_buyer_id_3911b29b_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boosts_purchase
    ADD CONSTRAINT boosts_purchase_buyer_id_3911b29b_fk_accounts_user_id FOREIGN KEY (buyer_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: boosts_purchase boosts_purchase_deal_id_3980c6fb_fk_deals_deal_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boosts_purchase
    ADD CONSTRAINT boosts_purchase_deal_id_3980c6fb_fk_deals_deal_id FOREIGN KEY (deal_id) REFERENCES public.deals_deal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: boosts_purchase boosts_purchase_delivery_request_id_9e9304ad_fk_parcels_d; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boosts_purchase
    ADD CONSTRAINT boosts_purchase_delivery_request_id_9e9304ad_fk_parcels_d FOREIGN KEY (delivery_request_id) REFERENCES public.parcels_delivery(parcelrequest_ptr_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: boosts_purchase boosts_purchase_payment_order_id_e7de4324_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.boosts_purchase
    ADD CONSTRAINT boosts_purchase_payment_order_id_e7de4324_fk_finance_p FOREIGN KEY (payment_order_id) REFERENCES public.finance_payment_order(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: chat_message chat_message_match_id_f9b82a81_fk_matching_match_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_message
    ADD CONSTRAINT chat_message_match_id_f9b82a81_fk_matching_match_id FOREIGN KEY (match_id) REFERENCES public.matching_match(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: chat_message chat_message_sender_id_991c686c_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.chat_message
    ADD CONSTRAINT chat_message_sender_id_991c686c_fk_accounts_user_id FOREIGN KEY (sender_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: core_business_settings_version core_business_settin_created_by_id_16811bac_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.core_business_settings_version
    ADD CONSTRAINT core_business_settin_created_by_id_16811bac_fk_accounts_ FOREIGN KEY (created_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: deals_arrival_report deals_arrival_report_deal_id_96a41f3c_fk_deals_deal_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_arrival_report
    ADD CONSTRAINT deals_arrival_report_deal_id_96a41f3c_fk_deals_deal_id FOREIGN KEY (deal_id) REFERENCES public.deals_deal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: deals_arrival_report deals_arrival_report_decided_by_id_e2ba4401_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_arrival_report
    ADD CONSTRAINT deals_arrival_report_decided_by_id_e2ba4401_fk_accounts_user_id FOREIGN KEY (decided_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: deals_arrival_report deals_arrival_report_reported_by_id_9850a243_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_arrival_report
    ADD CONSTRAINT deals_arrival_report_reported_by_id_9850a243_fk_accounts_ FOREIGN KEY (reported_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: deals_deal deals_deal_accepted_offer_id_b0886468_fk_matching_offer_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_deal
    ADD CONSTRAINT deals_deal_accepted_offer_id_b0886468_fk_matching_offer_id FOREIGN KEY (accepted_offer_id) REFERENCES public.matching_offer(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: deals_deal deals_deal_cancelled_by_id_0bdb3b24_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_deal
    ADD CONSTRAINT deals_deal_cancelled_by_id_0bdb3b24_fk_accounts_user_id FOREIGN KEY (cancelled_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: deals_deal deals_deal_delivery_request_id_070220c8_fk_parcels_d; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_deal
    ADD CONSTRAINT deals_deal_delivery_request_id_070220c8_fk_parcels_d FOREIGN KEY (delivery_request_id) REFERENCES public.parcels_delivery(parcelrequest_ptr_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: deals_deal deals_deal_journey_id_7d375dce_fk_trips_journey_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_deal
    ADD CONSTRAINT deals_deal_journey_id_7d375dce_fk_trips_journey_id FOREIGN KEY (journey_id) REFERENCES public.trips_journey(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: deals_deal deals_deal_match_id_46931f3b_fk_matching_match_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_deal
    ADD CONSTRAINT deals_deal_match_id_46931f3b_fk_matching_match_id FOREIGN KEY (match_id) REFERENCES public.matching_match(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: deals_deal deals_deal_no_show_recorded_by_id_79f62367_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_deal
    ADD CONSTRAINT deals_deal_no_show_recorded_by_id_79f62367_fk_accounts_user_id FOREIGN KEY (no_show_recorded_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: deals_deal deals_deal_sender_id_658c5ee7_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_deal
    ADD CONSTRAINT deals_deal_sender_id_658c5ee7_fk_accounts_user_id FOREIGN KEY (sender_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: deals_deal deals_deal_traveler_id_65c604f0_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_deal
    ADD CONSTRAINT deals_deal_traveler_id_65c604f0_fk_accounts_user_id FOREIGN KEY (traveler_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: deals_event deals_event_actor_id_316aa5de_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_event
    ADD CONSTRAINT deals_event_actor_id_316aa5de_fk_accounts_user_id FOREIGN KEY (actor_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: deals_event deals_event_deal_id_bde49cc2_fk_deals_deal_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_event
    ADD CONSTRAINT deals_event_deal_id_bde49cc2_fk_deals_deal_id FOREIGN KEY (deal_id) REFERENCES public.deals_deal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: deals_leg_allocation deals_leg_allocation_deal_id_c7b3d6c9_fk_deals_deal_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_leg_allocation
    ADD CONSTRAINT deals_leg_allocation_deal_id_c7b3d6c9_fk_deals_deal_id FOREIGN KEY (deal_id) REFERENCES public.deals_deal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: deals_leg_allocation deals_leg_allocation_journey_leg_id_ce6c0525_fk_trips_jou; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_leg_allocation
    ADD CONSTRAINT deals_leg_allocation_journey_leg_id_ce6c0525_fk_trips_jou FOREIGN KEY (journey_leg_id) REFERENCES public.trips_journey_leg(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: deals_recipient deals_recipient_created_by_id_5c736da8_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_recipient
    ADD CONSTRAINT deals_recipient_created_by_id_5c736da8_fk_accounts_user_id FOREIGN KEY (created_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: deals_recipient deals_recipient_deal_id_dff3e87b_fk_deals_deal_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_recipient
    ADD CONSTRAINT deals_recipient_deal_id_dff3e87b_fk_deals_deal_id FOREIGN KEY (deal_id) REFERENCES public.deals_deal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: deals_recipient deals_recipient_updated_by_id_8a2b2ab3_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_recipient
    ADD CONSTRAINT deals_recipient_updated_by_id_8a2b2ab3_fk_accounts_user_id FOREIGN KEY (updated_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: deals_terms_snapshot deals_terms_snapshot_business_settings_ve_75afe5df_fk_core_busi; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_terms_snapshot
    ADD CONSTRAINT deals_terms_snapshot_business_settings_ve_75afe5df_fk_core_busi FOREIGN KEY (business_settings_version_id) REFERENCES public.core_business_settings_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: deals_terms_snapshot deals_terms_snapshot_deal_id_a48ba978_fk_deals_deal_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.deals_terms_snapshot
    ADD CONSTRAINT deals_terms_snapshot_deal_id_a48ba978_fk_deals_deal_id FOREIGN KEY (deal_id) REFERENCES public.deals_deal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: disputes_dispute disputes_dispute_deal_id_5497f895_fk_deals_deal_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disputes_dispute
    ADD CONSTRAINT disputes_dispute_deal_id_5497f895_fk_deals_deal_id FOREIGN KEY (deal_id) REFERENCES public.deals_deal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: disputes_dispute disputes_dispute_opened_by_id_677cad74_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disputes_dispute
    ADD CONSTRAINT disputes_dispute_opened_by_id_677cad74_fk_accounts_user_id FOREIGN KEY (opened_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: disputes_dispute disputes_dispute_resolved_by_id_100fd82f_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disputes_dispute
    ADD CONSTRAINT disputes_dispute_resolved_by_id_100fd82f_fk_accounts_user_id FOREIGN KEY (resolved_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: disputes_event disputes_event_actor_id_f3f79611_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disputes_event
    ADD CONSTRAINT disputes_event_actor_id_f3f79611_fk_accounts_user_id FOREIGN KEY (actor_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: disputes_event disputes_event_dispute_id_5ab10d2c_fk_disputes_dispute_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disputes_event
    ADD CONSTRAINT disputes_event_dispute_id_5ab10d2c_fk_disputes_dispute_id FOREIGN KEY (dispute_id) REFERENCES public.disputes_dispute(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: disputes_evidence disputes_evidence_dispute_id_7a038a46_fk_disputes_dispute_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disputes_evidence
    ADD CONSTRAINT disputes_evidence_dispute_id_7a038a46_fk_disputes_dispute_id FOREIGN KEY (dispute_id) REFERENCES public.disputes_dispute(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: disputes_evidence disputes_evidence_submitted_by_id_7cff983e_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.disputes_evidence
    ADD CONSTRAINT disputes_evidence_submitted_by_id_7cff983e_fk_accounts_user_id FOREIGN KEY (submitted_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: django_admin_log django_admin_log_content_type_id_c4bce8eb_fk_django_co; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_admin_log
    ADD CONSTRAINT django_admin_log_content_type_id_c4bce8eb_fk_django_co FOREIGN KEY (content_type_id) REFERENCES public.django_content_type(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: django_admin_log django_admin_log_user_id_c564eba6_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.django_admin_log
    ADD CONSTRAINT django_admin_log_user_id_c564eba6_fk_accounts_user_id FOREIGN KEY (user_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_dzd_profile_revision finance_dzd_profile__evidence_id_f926fc32_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_dzd_profile_revision
    ADD CONSTRAINT finance_dzd_profile__evidence_id_f926fc32_fk_finance_p FOREIGN KEY (evidence_id) REFERENCES public.finance_payout_evidence(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_dzd_profile_revision finance_dzd_profile__identity_attestation_16c42fd4_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_dzd_profile_revision
    ADD CONSTRAINT finance_dzd_profile__identity_attestation_16c42fd4_fk_finance_p FOREIGN KEY (identity_attestation_id) REFERENCES public.finance_payout_identity_attestation(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_dzd_profile_revision finance_dzd_profile__method_id_136d0c5f_fk_finance_t; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_dzd_profile_revision
    ADD CONSTRAINT finance_dzd_profile__method_id_136d0c5f_fk_finance_t FOREIGN KEY (method_id) REFERENCES public.finance_traveler_payout_method(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_guest_payment_link finance_guest_paymen_created_by_id_551a1ab1_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_guest_payment_link
    ADD CONSTRAINT finance_guest_paymen_created_by_id_551a1ab1_fk_accounts_ FOREIGN KEY (created_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_guest_payment_link finance_guest_paymen_order_id_a42e1ebd_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_guest_payment_link
    ADD CONSTRAINT finance_guest_paymen_order_id_a42e1ebd_fk_finance_p FOREIGN KEY (order_id) REFERENCES public.finance_payment_order(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_hold finance_hold_account_id_2d03ecf0_fk_finance_s; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_hold
    ADD CONSTRAINT finance_hold_account_id_2d03ecf0_fk_finance_s FOREIGN KEY (account_id) REFERENCES public.finance_stripe_payout_account(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_hold finance_hold_cleared_by_id_ddcd1db0_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_hold
    ADD CONSTRAINT finance_hold_cleared_by_id_ddcd1db0_fk_accounts_user_id FOREIGN KEY (cleared_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_hold finance_hold_deal_id_b4f859f8_fk_deals_deal_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_hold
    ADD CONSTRAINT finance_hold_deal_id_b4f859f8_fk_deals_deal_id FOREIGN KEY (deal_id) REFERENCES public.deals_deal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_hold finance_hold_opened_by_id_61ed2329_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_hold
    ADD CONSTRAINT finance_hold_opened_by_id_61ed2329_fk_accounts_user_id FOREIGN KEY (opened_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_hold finance_hold_payout_id_ea48e192_fk_finance_payout_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_hold
    ADD CONSTRAINT finance_hold_payout_id_ea48e192_fk_finance_payout_id FOREIGN KEY (payout_id) REFERENCES public.finance_payout(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_hold finance_hold_source_attempt_id_f547de2d_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_hold
    ADD CONSTRAINT finance_hold_source_attempt_id_f547de2d_fk_finance_p FOREIGN KEY (source_attempt_id) REFERENCES public.finance_payment_attempt(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_ledger_entry finance_ledger_entry_attempt_id_26619ebd_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_ledger_entry
    ADD CONSTRAINT finance_ledger_entry_attempt_id_26619ebd_fk_finance_p FOREIGN KEY (attempt_id) REFERENCES public.finance_payment_attempt(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_ledger_entry finance_ledger_entry_deal_id_cf63abba_fk_deals_deal_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_ledger_entry
    ADD CONSTRAINT finance_ledger_entry_deal_id_cf63abba_fk_deals_deal_id FOREIGN KEY (deal_id) REFERENCES public.deals_deal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_ledger_entry finance_ledger_entry_order_id_fc0792a1_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_ledger_entry
    ADD CONSTRAINT finance_ledger_entry_order_id_fc0792a1_fk_finance_p FOREIGN KEY (order_id) REFERENCES public.finance_payment_order(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_ledger_entry finance_ledger_entry_payout_id_1ff65405_fk_finance_payout_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_ledger_entry
    ADD CONSTRAINT finance_ledger_entry_payout_id_1ff65405_fk_finance_payout_id FOREIGN KEY (payout_id) REFERENCES public.finance_payout(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_ledger_entry finance_ledger_entry_refund_id_2221dcec_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_ledger_entry
    ADD CONSTRAINT finance_ledger_entry_refund_id_2221dcec_fk_finance_p FOREIGN KEY (refund_id) REFERENCES public.finance_payment_refund(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_ledger_entry finance_ledger_entry_transaction_id_ec94704b_fk_finance_l; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_ledger_entry
    ADD CONSTRAINT finance_ledger_entry_transaction_id_ec94704b_fk_finance_l FOREIGN KEY (transaction_id) REFERENCES public.finance_ledger_transaction(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_ledger_entry finance_ledger_entry_user_id_9c8392ab_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_ledger_entry
    ADD CONSTRAINT finance_ledger_entry_user_id_9c8392ab_fk_accounts_user_id FOREIGN KEY (user_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_ledger_transaction finance_ledger_trans_reverses_id_d4017be9_fk_finance_l; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_ledger_transaction
    ADD CONSTRAINT finance_ledger_trans_reverses_id_d4017be9_fk_finance_l FOREIGN KEY (reverses_id) REFERENCES public.finance_ledger_transaction(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_manual_payout_receipt finance_manual_payou_attempt_id_1e342be4_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_manual_payout_receipt
    ADD CONSTRAINT finance_manual_payou_attempt_id_1e342be4_fk_finance_p FOREIGN KEY (attempt_id) REFERENCES public.finance_payout_attempt(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_manual_payout_receipt finance_manual_payou_evidence_id_b31b6be2_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_manual_payout_receipt
    ADD CONSTRAINT finance_manual_payou_evidence_id_b31b6be2_fk_finance_p FOREIGN KEY (evidence_id) REFERENCES public.finance_payout_evidence(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_manual_payout_receipt finance_manual_payou_operator_id_a7ef8ec5_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_manual_payout_receipt
    ADD CONSTRAINT finance_manual_payou_operator_id_a7ef8ec5_fk_accounts_ FOREIGN KEY (operator_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payment_attempt finance_payment_atte_fx_settings_version__9099cde3_fk_core_busi; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payment_attempt
    ADD CONSTRAINT finance_payment_atte_fx_settings_version__9099cde3_fk_core_busi FOREIGN KEY (fx_settings_version_id) REFERENCES public.core_business_settings_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payment_attempt finance_payment_atte_guest_link_id_478fe6b2_fk_finance_g; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payment_attempt
    ADD CONSTRAINT finance_payment_atte_guest_link_id_478fe6b2_fk_finance_g FOREIGN KEY (guest_link_id) REFERENCES public.finance_guest_payment_link(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payment_attempt finance_payment_atte_operational_resolved_40d78727_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payment_attempt
    ADD CONSTRAINT finance_payment_atte_operational_resolved_40d78727_fk_accounts_ FOREIGN KEY (operational_resolved_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payment_attempt finance_payment_atte_order_id_e6c98179_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payment_attempt
    ADD CONSTRAINT finance_payment_atte_order_id_e6c98179_fk_finance_p FOREIGN KEY (order_id) REFERENCES public.finance_payment_order(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payment_attempt finance_payment_attempt_payer_id_3bdcd913_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payment_attempt
    ADD CONSTRAINT finance_payment_attempt_payer_id_3bdcd913_fk_accounts_user_id FOREIGN KEY (payer_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payment_order finance_payment_orde_business_settings_ve_c5e57eb4_fk_core_busi; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payment_order
    ADD CONSTRAINT finance_payment_orde_business_settings_ve_c5e57eb4_fk_core_busi FOREIGN KEY (business_settings_version_id) REFERENCES public.core_business_settings_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payment_order finance_payment_orde_credit_source_id_4f440218_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payment_order
    ADD CONSTRAINT finance_payment_orde_credit_source_id_4f440218_fk_finance_p FOREIGN KEY (credit_source_id) REFERENCES public.finance_payment_order(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payment_order finance_payment_orde_delivery_request_id_0a53ea23_fk_parcels_d; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payment_order
    ADD CONSTRAINT finance_payment_orde_delivery_request_id_0a53ea23_fk_parcels_d FOREIGN KEY (delivery_request_id) REFERENCES public.parcels_delivery(parcelrequest_ptr_id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payment_order finance_payment_order_deal_id_be89d1b6_fk_deals_deal_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payment_order
    ADD CONSTRAINT finance_payment_order_deal_id_be89d1b6_fk_deals_deal_id FOREIGN KEY (deal_id) REFERENCES public.deals_deal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payment_order finance_payment_order_owner_id_306c0486_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payment_order
    ADD CONSTRAINT finance_payment_order_owner_id_306c0486_fk_accounts_user_id FOREIGN KEY (owner_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payment_refund finance_payment_refu_attempt_id_fa439711_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payment_refund
    ADD CONSTRAINT finance_payment_refu_attempt_id_fa439711_fk_finance_p FOREIGN KEY (attempt_id) REFERENCES public.finance_payment_attempt(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payment_refund finance_payment_refu_order_id_e85b6171_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payment_refund
    ADD CONSTRAINT finance_payment_refu_order_id_e85b6171_fk_finance_p FOREIGN KEY (order_id) REFERENCES public.finance_payment_order(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payment_refund finance_payment_refu_requested_by_id_89dccbc7_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payment_refund
    ADD CONSTRAINT finance_payment_refu_requested_by_id_89dccbc7_fk_accounts_ FOREIGN KEY (requested_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payment_refund finance_payment_refu_settled_by_id_f5e2d8ac_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payment_refund
    ADD CONSTRAINT finance_payment_refu_settled_by_id_f5e2d8ac_fk_accounts_ FOREIGN KEY (settled_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout finance_payout_active_instruction_v_3ce5d7a7_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout
    ADD CONSTRAINT finance_payout_active_instruction_v_3ce5d7a7_fk_finance_p FOREIGN KEY (active_instruction_version_id) REFERENCES public.finance_payout_method_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout finance_payout_admin_actor_id_a9ddc7f4_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout
    ADD CONSTRAINT finance_payout_admin_actor_id_a9ddc7f4_fk_accounts_user_id FOREIGN KEY (admin_actor_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_amount_revision finance_payout_amoun_actor_id_b0b41f39_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_amount_revision
    ADD CONSTRAINT finance_payout_amoun_actor_id_b0b41f39_fk_accounts_ FOREIGN KEY (actor_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_amount_revision finance_payout_amoun_fx_settings_version__5f2066c7_fk_core_busi; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_amount_revision
    ADD CONSTRAINT finance_payout_amoun_fx_settings_version__5f2066c7_fk_core_busi FOREIGN KEY (fx_settings_version_id) REFERENCES public.core_business_settings_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_amount_revision finance_payout_amoun_ledger_transaction_i_e08d7cb7_fk_finance_l; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_amount_revision
    ADD CONSTRAINT finance_payout_amoun_ledger_transaction_i_e08d7cb7_fk_finance_l FOREIGN KEY (ledger_transaction_id) REFERENCES public.finance_ledger_transaction(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_amount_revision finance_payout_amoun_payout_id_ca8521da_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_amount_revision
    ADD CONSTRAINT finance_payout_amoun_payout_id_ca8521da_fk_finance_p FOREIGN KEY (payout_id) REFERENCES public.finance_payout(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_attempt finance_payout_attem_amount_revision_id_0d37b95e_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_attempt
    ADD CONSTRAINT finance_payout_attem_amount_revision_id_0d37b95e_fk_finance_p FOREIGN KEY (amount_revision_id) REFERENCES public.finance_payout_amount_revision(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_attempt finance_payout_attem_instruction_version__62243bca_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_attempt
    ADD CONSTRAINT finance_payout_attem_instruction_version__62243bca_fk_finance_p FOREIGN KEY (instruction_version_id) REFERENCES public.finance_payout_method_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_attempt finance_payout_attempt_operator_id_6ce3fbf2_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_attempt
    ADD CONSTRAINT finance_payout_attempt_operator_id_6ce3fbf2_fk_accounts_user_id FOREIGN KEY (operator_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_attempt finance_payout_attempt_payout_id_0e1e7692_fk_finance_payout_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_attempt
    ADD CONSTRAINT finance_payout_attempt_payout_id_0e1e7692_fk_finance_payout_id FOREIGN KEY (payout_id) REFERENCES public.finance_payout(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout finance_payout_deal_id_547e0923_fk_deals_deal_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout
    ADD CONSTRAINT finance_payout_deal_id_547e0923_fk_deals_deal_id FOREIGN KEY (deal_id) REFERENCES public.deals_deal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout finance_payout_dzd_profile_revision_da138436_fk_finance_d; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout
    ADD CONSTRAINT finance_payout_dzd_profile_revision_da138436_fk_finance_d FOREIGN KEY (dzd_profile_revision_id) REFERENCES public.finance_dzd_profile_revision(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_event finance_payout_event_actor_id_a62d3ee7_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_event
    ADD CONSTRAINT finance_payout_event_actor_id_a62d3ee7_fk_accounts_user_id FOREIGN KEY (actor_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_event finance_payout_event_evidence_id_997f5917_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_event
    ADD CONSTRAINT finance_payout_event_evidence_id_997f5917_fk_finance_p FOREIGN KEY (evidence_id) REFERENCES public.finance_payout_evidence(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_event finance_payout_event_ledger_transaction_i_a72df823_fk_finance_l; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_event
    ADD CONSTRAINT finance_payout_event_ledger_transaction_i_a72df823_fk_finance_l FOREIGN KEY (ledger_transaction_id) REFERENCES public.finance_ledger_transaction(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_event finance_payout_event_operation_id_807b1409_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_event
    ADD CONSTRAINT finance_payout_event_operation_id_807b1409_fk_finance_p FOREIGN KEY (operation_id) REFERENCES public.finance_payout_provider_operation(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_event finance_payout_event_payout_id_89e98008_fk_finance_payout_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_event
    ADD CONSTRAINT finance_payout_event_payout_id_89e98008_fk_finance_payout_id FOREIGN KEY (payout_id) REFERENCES public.finance_payout(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_evidence finance_payout_evidence_owner_id_751cc2e0_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_evidence
    ADD CONSTRAINT finance_payout_evidence_owner_id_751cc2e0_fk_accounts_user_id FOREIGN KEY (owner_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_funding_release finance_payout_fundi_actor_id_16999c47_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_funding_release
    ADD CONSTRAINT finance_payout_fundi_actor_id_16999c47_fk_accounts_ FOREIGN KEY (actor_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_funding_release finance_payout_fundi_allocation_id_d62de96c_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_funding_release
    ADD CONSTRAINT finance_payout_fundi_allocation_id_d62de96c_fk_finance_p FOREIGN KEY (allocation_id) REFERENCES public.finance_payout_funding_allocation(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_funding_allocation finance_payout_fundi_attempt_id_da72ee55_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_funding_allocation
    ADD CONSTRAINT finance_payout_fundi_attempt_id_da72ee55_fk_finance_p FOREIGN KEY (attempt_id) REFERENCES public.finance_payout_attempt(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_funding_allocation finance_payout_fundi_payout_id_872f06e0_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_funding_allocation
    ADD CONSTRAINT finance_payout_fundi_payout_id_872f06e0_fk_finance_p FOREIGN KEY (payout_id) REFERENCES public.finance_payout(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_funding_allocation finance_payout_fundi_source_attempt_id_62488a9d_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_funding_allocation
    ADD CONSTRAINT finance_payout_fundi_source_attempt_id_62488a9d_fk_finance_p FOREIGN KEY (source_attempt_id) REFERENCES public.finance_payment_attempt(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout finance_payout_funding_attempt_id_b068abb2_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout
    ADD CONSTRAINT finance_payout_funding_attempt_id_b068abb2_fk_finance_p FOREIGN KEY (funding_attempt_id) REFERENCES public.finance_payment_attempt(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout finance_payout_fx_settings_version__13a001ba_fk_core_busi; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout
    ADD CONSTRAINT finance_payout_fx_settings_version__13a001ba_fk_core_busi FOREIGN KEY (fx_settings_version_id) REFERENCES public.core_business_settings_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout finance_payout_fx_source_attempt_id_a9f6861d_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout
    ADD CONSTRAINT finance_payout_fx_source_attempt_id_a9f6861d_fk_finance_p FOREIGN KEY (fx_source_attempt_id) REFERENCES public.finance_payment_attempt(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_identity_revocation finance_payout_ident_actor_id_0d4669c1_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_identity_revocation
    ADD CONSTRAINT finance_payout_ident_actor_id_0d4669c1_fk_accounts_ FOREIGN KEY (actor_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_identity_review_assignment finance_payout_ident_assigned_by_id_8bd7ea44_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_identity_review_assignment
    ADD CONSTRAINT finance_payout_ident_assigned_by_id_8bd7ea44_fk_accounts_ FOREIGN KEY (assigned_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_identity_revocation finance_payout_ident_attestation_id_6f29f57b_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_identity_revocation
    ADD CONSTRAINT finance_payout_ident_attestation_id_6f29f57b_fk_finance_p FOREIGN KEY (attestation_id) REFERENCES public.finance_payout_identity_attestation(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_identity_attestation finance_payout_ident_attested_by_id_cbc2d8a6_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_identity_attestation
    ADD CONSTRAINT finance_payout_ident_attested_by_id_cbc2d8a6_fk_accounts_ FOREIGN KEY (attested_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_identity_review_assignment finance_payout_ident_kyc_submission_id_1a3e6ceb_fk_kyc_submi; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_identity_review_assignment
    ADD CONSTRAINT finance_payout_ident_kyc_submission_id_1a3e6ceb_fk_kyc_submi FOREIGN KEY (kyc_submission_id) REFERENCES public.kyc_submission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_identity_attestation finance_payout_ident_kyc_submission_id_b5c6a3de_fk_kyc_submi; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_identity_attestation
    ADD CONSTRAINT finance_payout_ident_kyc_submission_id_b5c6a3de_fk_kyc_submi FOREIGN KEY (kyc_submission_id) REFERENCES public.kyc_submission(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_identity_review_assignment finance_payout_ident_reviewer_id_849f357f_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_identity_review_assignment
    ADD CONSTRAINT finance_payout_ident_reviewer_id_849f357f_fk_accounts_ FOREIGN KEY (reviewer_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_identity_attestation finance_payout_ident_supersedes_id_f05f6ad1_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_identity_attestation
    ADD CONSTRAINT finance_payout_ident_supersedes_id_f05f6ad1_fk_finance_p FOREIGN KEY (supersedes_id) REFERENCES public.finance_payout_identity_attestation(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_identity_attestation finance_payout_ident_traveler_id_521b64a4_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_identity_attestation
    ADD CONSTRAINT finance_payout_ident_traveler_id_521b64a4_fk_accounts_ FOREIGN KEY (traveler_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_identity_review_assignment finance_payout_ident_traveler_id_b6071b64_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_identity_review_assignment
    ADD CONSTRAINT finance_payout_ident_traveler_id_b6071b64_fk_accounts_ FOREIGN KEY (traveler_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_instruction_amendment finance_payout_instr_new_version_id_6d591f63_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_instruction_amendment
    ADD CONSTRAINT finance_payout_instr_new_version_id_6d591f63_fk_finance_p FOREIGN KEY (new_version_id) REFERENCES public.finance_payout_method_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_instruction_confirmation finance_payout_instr_new_version_id_b22618a4_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_instruction_confirmation
    ADD CONSTRAINT finance_payout_instr_new_version_id_b22618a4_fk_finance_p FOREIGN KEY (new_version_id) REFERENCES public.finance_payout_method_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_instruction_amendment finance_payout_instr_old_version_id_56abaf12_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_instruction_amendment
    ADD CONSTRAINT finance_payout_instr_old_version_id_56abaf12_fk_finance_p FOREIGN KEY (old_version_id) REFERENCES public.finance_payout_method_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_instruction_confirmation finance_payout_instr_payout_id_7512f0ca_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_instruction_confirmation
    ADD CONSTRAINT finance_payout_instr_payout_id_7512f0ca_fk_finance_p FOREIGN KEY (payout_id) REFERENCES public.finance_payout(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_instruction_amendment finance_payout_instr_payout_id_e1b50536_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_instruction_amendment
    ADD CONSTRAINT finance_payout_instr_payout_id_e1b50536_fk_finance_p FOREIGN KEY (payout_id) REFERENCES public.finance_payout(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_instruction_amendment finance_payout_instr_reviewed_by_id_75d0cfa3_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_instruction_amendment
    ADD CONSTRAINT finance_payout_instr_reviewed_by_id_75d0cfa3_fk_accounts_ FOREIGN KEY (reviewed_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_instruction_confirmation finance_payout_instr_traveler_id_16f8a562_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_instruction_confirmation
    ADD CONSTRAINT finance_payout_instr_traveler_id_16f8a562_fk_accounts_ FOREIGN KEY (traveler_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_instruction_amendment finance_payout_instr_traveler_id_add22ee2_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_instruction_amendment
    ADD CONSTRAINT finance_payout_instr_traveler_id_add22ee2_fk_accounts_ FOREIGN KEY (traveler_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_method_version finance_payout_metho_created_by_id_9540ff66_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_method_version
    ADD CONSTRAINT finance_payout_metho_created_by_id_9540ff66_fk_accounts_ FOREIGN KEY (created_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_method_version finance_payout_metho_dzd_profile_revision_3f3cc202_fk_finance_d; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_method_version
    ADD CONSTRAINT finance_payout_metho_dzd_profile_revision_3f3cc202_fk_finance_d FOREIGN KEY (dzd_profile_revision_id) REFERENCES public.finance_dzd_profile_revision(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_method_version finance_payout_metho_method_id_2f8935e7_fk_finance_t; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_method_version
    ADD CONSTRAINT finance_payout_metho_method_id_2f8935e7_fk_finance_t FOREIGN KEY (method_id) REFERENCES public.finance_traveler_payout_method(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_method_version finance_payout_metho_stripe_account_id_bd562a2f_fk_finance_s; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_method_version
    ADD CONSTRAINT finance_payout_metho_stripe_account_id_bd562a2f_fk_finance_s FOREIGN KEY (stripe_account_id) REFERENCES public.finance_stripe_payout_account(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout finance_payout_method_version_id_de3d06b7_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout
    ADD CONSTRAINT finance_payout_method_version_id_de3d06b7_fk_finance_p FOREIGN KEY (method_version_id) REFERENCES public.finance_payout_method_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_profile_review finance_payout_profi_identity_attestation_14d1410f_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_profile_review
    ADD CONSTRAINT finance_payout_profi_identity_attestation_14d1410f_fk_finance_p FOREIGN KEY (identity_attestation_id) REFERENCES public.finance_payout_identity_attestation(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_profile_review finance_payout_profi_profile_id_5fa4ff9b_fk_finance_d; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_profile_review
    ADD CONSTRAINT finance_payout_profi_profile_id_5fa4ff9b_fk_finance_d FOREIGN KEY (profile_id) REFERENCES public.finance_dzd_profile_revision(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_profile_review finance_payout_profi_reviewer_id_cf325963_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_profile_review
    ADD CONSTRAINT finance_payout_profi_reviewer_id_cf325963_fk_accounts_ FOREIGN KEY (reviewer_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_provider_operation finance_payout_provi_attempt_id_6ca74607_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_provider_operation
    ADD CONSTRAINT finance_payout_provi_attempt_id_6ca74607_fk_finance_p FOREIGN KEY (attempt_id) REFERENCES public.finance_payout_attempt(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_provider_operation finance_payout_provi_disbursement_id_62d361b1_fk_finance_s; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_provider_operation
    ADD CONSTRAINT finance_payout_provi_disbursement_id_62d361b1_fk_finance_s FOREIGN KEY (disbursement_id) REFERENCES public.finance_stripe_disbursement(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_provider_operation finance_payout_provi_funding_allocation_i_7f0f345e_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_provider_operation
    ADD CONSTRAINT finance_payout_provi_funding_allocation_i_7f0f345e_fk_finance_p FOREIGN KEY (funding_allocation_id) REFERENCES public.finance_payout_funding_allocation(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout_provider_operation finance_payout_provi_method_id_822f098e_fk_finance_t; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout_provider_operation
    ADD CONSTRAINT finance_payout_provi_method_id_822f098e_fk_finance_t FOREIGN KEY (method_id) REFERENCES public.finance_traveler_payout_method(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout finance_payout_stripe_account_id_8c52326c_fk_finance_s; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout
    ADD CONSTRAINT finance_payout_stripe_account_id_8c52326c_fk_finance_s FOREIGN KEY (stripe_account_id) REFERENCES public.finance_stripe_payout_account(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_payout finance_payout_traveler_id_5ad36ce0_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_payout
    ADD CONSTRAINT finance_payout_traveler_id_5ad36ce0_fk_accounts_user_id FOREIGN KEY (traveler_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_provider_dispute finance_provider_dis_source_attempt_id_82a7e9a7_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_provider_dispute
    ADD CONSTRAINT finance_provider_dis_source_attempt_id_82a7e9a7_fk_finance_p FOREIGN KEY (source_attempt_id) REFERENCES public.finance_payment_attempt(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_provider_event finance_provider_eve_attempt_id_d8b89e74_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_provider_event
    ADD CONSTRAINT finance_provider_eve_attempt_id_d8b89e74_fk_finance_p FOREIGN KEY (attempt_id) REFERENCES public.finance_payment_attempt(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_provider_event finance_provider_eve_order_id_973b1b4e_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_provider_event
    ADD CONSTRAINT finance_provider_eve_order_id_973b1b4e_fk_finance_p FOREIGN KEY (order_id) REFERENCES public.finance_payment_order(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_scheduled_job finance_scheduled_jo_resolved_by_id_45521f75_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_scheduled_job
    ADD CONSTRAINT finance_scheduled_jo_resolved_by_id_45521f75_fk_accounts_ FOREIGN KEY (resolved_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_stripe_disbursement finance_stripe_disbu_account_id_0addbb81_fk_finance_s; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_stripe_disbursement
    ADD CONSTRAINT finance_stripe_disbu_account_id_0addbb81_fk_finance_s FOREIGN KEY (account_id) REFERENCES public.finance_stripe_payout_account(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_stripe_disbursement_allocation finance_stripe_disbu_attempt_id_366d8297_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_stripe_disbursement_allocation
    ADD CONSTRAINT finance_stripe_disbu_attempt_id_366d8297_fk_finance_p FOREIGN KEY (attempt_id) REFERENCES public.finance_payout_attempt(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_stripe_disbursement_allocation finance_stripe_disbu_disbursement_id_37ad7df5_fk_finance_s; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_stripe_disbursement_allocation
    ADD CONSTRAINT finance_stripe_disbu_disbursement_id_37ad7df5_fk_finance_s FOREIGN KEY (disbursement_id) REFERENCES public.finance_stripe_disbursement(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_stripe_disbursement_allocation finance_stripe_disbu_payout_id_c051671a_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_stripe_disbursement_allocation
    ADD CONSTRAINT finance_stripe_disbu_payout_id_c051671a_fk_finance_p FOREIGN KEY (payout_id) REFERENCES public.finance_payout(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_stripe_payout_account finance_stripe_payou_traveler_id_d9df979a_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_stripe_payout_account
    ADD CONSTRAINT finance_stripe_payou_traveler_id_d9df979a_fk_accounts_ FOREIGN KEY (traveler_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_traveler_payout_method finance_traveler_pay_current_version_id_ea63db31_fk_finance_p; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_traveler_payout_method
    ADD CONSTRAINT finance_traveler_pay_current_version_id_ea63db31_fk_finance_p FOREIGN KEY (current_version_id) REFERENCES public.finance_payout_method_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: finance_traveler_payout_method finance_traveler_pay_traveler_id_27aac0e7_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_traveler_payout_method
    ADD CONSTRAINT finance_traveler_pay_traveler_id_27aac0e7_fk_accounts_ FOREIGN KEY (traveler_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: handover_attempt handover_attempt_actor_id_93069cb7_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.handover_attempt
    ADD CONSTRAINT handover_attempt_actor_id_93069cb7_fk_accounts_user_id FOREIGN KEY (actor_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: handover_attempt handover_attempt_code_id_8f5c9f85_fk_handover_deal_code_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.handover_attempt
    ADD CONSTRAINT handover_attempt_code_id_8f5c9f85_fk_handover_deal_code_id FOREIGN KEY (code_id) REFERENCES public.handover_deal_code(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: handover_attempt handover_attempt_deal_id_de76fd8b_fk_deals_deal_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.handover_attempt
    ADD CONSTRAINT handover_attempt_deal_id_de76fd8b_fk_deals_deal_id FOREIGN KEY (deal_id) REFERENCES public.deals_deal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: handover_code_access handover_code_access_actor_id_bc611bf5_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.handover_code_access
    ADD CONSTRAINT handover_code_access_actor_id_bc611bf5_fk_accounts_user_id FOREIGN KEY (actor_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: handover_code_access handover_code_access_code_id_0393b58d_fk_handover_deal_code_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.handover_code_access
    ADD CONSTRAINT handover_code_access_code_id_0393b58d_fk_handover_deal_code_id FOREIGN KEY (code_id) REFERENCES public.handover_deal_code(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: handover_code_access handover_code_access_deal_id_0382ad0d_fk_deals_deal_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.handover_code_access
    ADD CONSTRAINT handover_code_access_deal_id_0382ad0d_fk_deals_deal_id FOREIGN KEY (deal_id) REFERENCES public.deals_deal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: handover_deal_code handover_deal_code_deal_id_2c4d715c_fk_deals_deal_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.handover_deal_code
    ADD CONSTRAINT handover_deal_code_deal_id_2c4d715c_fk_deals_deal_id FOREIGN KEY (deal_id) REFERENCES public.deals_deal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: handover_deal_code handover_deal_code_issued_to_id_2fba254c_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.handover_deal_code
    ADD CONSTRAINT handover_deal_code_issued_to_id_2fba254c_fk_accounts_user_id FOREIGN KEY (issued_to_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: handover_deal_code handover_deal_code_used_by_id_a52d8dc1_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.handover_deal_code
    ADD CONSTRAINT handover_deal_code_used_by_id_a52d8dc1_fk_accounts_user_id FOREIGN KEY (used_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: kyc_submission kyc_submission_user_id_88472018_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.kyc_submission
    ADD CONSTRAINT kyc_submission_user_id_88472018_fk_accounts_user_id FOREIGN KEY (user_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: locations_airport_locality_mapping locations_airport_lo_airport_id_4068f206_fk_locations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_airport_locality_mapping
    ADD CONSTRAINT locations_airport_lo_airport_id_4068f206_fk_locations FOREIGN KEY (airport_id) REFERENCES public.locations_place(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: locations_airport_locality_mapping locations_airport_lo_locality_id_d9dac550_fk_locations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_airport_locality_mapping
    ADD CONSTRAINT locations_airport_lo_locality_id_d9dac550_fk_locations FOREIGN KEY (locality_id) REFERENCES public.locations_place(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: locations_location locations_location_airport_id_02040de1_fk_trips_airport_iata; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_location
    ADD CONSTRAINT locations_location_airport_id_02040de1_fk_trips_airport_iata FOREIGN KEY (airport_id) REFERENCES public.trips_airport(iata) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: locations_location locations_location_canonical_place_id_0ec16219_fk_locations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_location
    ADD CONSTRAINT locations_location_canonical_place_id_0ec16219_fk_locations FOREIGN KEY (canonical_place_id) REFERENCES public.locations_place(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: locations_location locations_location_created_by_id_37e13144_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_location
    ADD CONSTRAINT locations_location_created_by_id_37e13144_fk_accounts_user_id FOREIGN KEY (created_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: locations_location locations_location_owner_id_dcf0d67f_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_location
    ADD CONSTRAINT locations_location_owner_id_dcf0d67f_fk_accounts_user_id FOREIGN KEY (owner_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: locations_place_alternate_name locations_place_alte_place_id_9c6b0670_fk_locations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_place_alternate_name
    ADD CONSTRAINT locations_place_alte_place_id_9c6b0670_fk_locations FOREIGN KEY (place_id) REFERENCES public.locations_place(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: locations_place locations_place_country_id_1740f5cc_fk_locations_country_code; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_place
    ADD CONSTRAINT locations_place_country_id_1740f5cc_fk_locations_country_code FOREIGN KEY (country_id) REFERENCES public.locations_country(code) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: locations_place locations_place_legacy_airport_id_d24c896a_fk_trips_air; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_place
    ADD CONSTRAINT locations_place_legacy_airport_id_d24c896a_fk_trips_air FOREIGN KEY (legacy_airport_id) REFERENCES public.trips_airport(iata) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: locations_place locations_place_parent_id_13a98485_fk_locations_place_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.locations_place
    ADD CONSTRAINT locations_place_parent_id_13a98485_fk_locations_place_id FOREIGN KEY (parent_id) REFERENCES public.locations_place(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: matching_event matching_event_actor_id_4bbc578e_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.matching_event
    ADD CONSTRAINT matching_event_actor_id_4bbc578e_fk_accounts_user_id FOREIGN KEY (actor_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: matching_event matching_event_match_id_9a46daed_fk_matching_match_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.matching_event
    ADD CONSTRAINT matching_event_match_id_9a46daed_fk_matching_match_id FOREIGN KEY (match_id) REFERENCES public.matching_match(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: matching_event matching_event_offer_id_0c174aa5_fk_matching_offer_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.matching_event
    ADD CONSTRAINT matching_event_offer_id_0c174aa5_fk_matching_offer_id FOREIGN KEY (offer_id) REFERENCES public.matching_offer(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: matching_match matching_match_end_leg_id_85a27d52_fk_trips_journey_leg_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.matching_match
    ADD CONSTRAINT matching_match_end_leg_id_85a27d52_fk_trips_journey_leg_id FOREIGN KEY (end_leg_id) REFERENCES public.trips_journey_leg(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: matching_match matching_match_journey_id_c1c75fa5_fk_trips_journey_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.matching_match
    ADD CONSTRAINT matching_match_journey_id_c1c75fa5_fk_trips_journey_id FOREIGN KEY (journey_id) REFERENCES public.trips_journey(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: matching_match matching_match_parcel_id_37bffd80_fk_parcels_request_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.matching_match
    ADD CONSTRAINT matching_match_parcel_id_37bffd80_fk_parcels_request_id FOREIGN KEY (parcel_id) REFERENCES public.parcels_request(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: matching_match matching_match_sender_id_d5f8efbd_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.matching_match
    ADD CONSTRAINT matching_match_sender_id_d5f8efbd_fk_accounts_user_id FOREIGN KEY (sender_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: matching_match matching_match_start_leg_id_a274366e_fk_trips_journey_leg_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.matching_match
    ADD CONSTRAINT matching_match_start_leg_id_a274366e_fk_trips_journey_leg_id FOREIGN KEY (start_leg_id) REFERENCES public.trips_journey_leg(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: matching_match matching_match_traveler_id_efec247a_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.matching_match
    ADD CONSTRAINT matching_match_traveler_id_efec247a_fk_accounts_user_id FOREIGN KEY (traveler_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: matching_match matching_match_trip_id_c9757271_fk_trips_trip_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.matching_match
    ADD CONSTRAINT matching_match_trip_id_c9757271_fk_trips_trip_id FOREIGN KEY (trip_id) REFERENCES public.trips_trip(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: matching_offer matching_offer_business_settings_ve_57f2ce49_fk_core_busi; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.matching_offer
    ADD CONSTRAINT matching_offer_business_settings_ve_57f2ce49_fk_core_busi FOREIGN KEY (business_settings_version_id) REFERENCES public.core_business_settings_version(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: matching_offer matching_offer_match_id_e31edde3_fk_matching_match_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.matching_offer
    ADD CONSTRAINT matching_offer_match_id_e31edde3_fk_matching_match_id FOREIGN KEY (match_id) REFERENCES public.matching_match(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: matching_offer matching_offer_parent_offer_id_8439dc32_fk_matching_offer_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.matching_offer
    ADD CONSTRAINT matching_offer_parent_offer_id_8439dc32_fk_matching_offer_id FOREIGN KEY (parent_offer_id) REFERENCES public.matching_offer(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: matching_offer matching_offer_proposer_id_00bc9a80_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.matching_offer
    ADD CONSTRAINT matching_offer_proposer_id_00bc9a80_fk_accounts_user_id FOREIGN KEY (proposer_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: notification_outbound_message notification_outboun_recipient_user_id_4f1f66f1_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_outbound_message
    ADD CONSTRAINT notification_outboun_recipient_user_id_4f1f66f1_fk_accounts_ FOREIGN KEY (recipient_user_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: notification_outbound_message notification_outbound_message_deal_id_0990d7c4_fk_deals_deal_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_outbound_message
    ADD CONSTRAINT notification_outbound_message_deal_id_0990d7c4_fk_deals_deal_id FOREIGN KEY (deal_id) REFERENCES public.deals_deal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: notification_preference notification_preference_user_id_de890342_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_preference
    ADD CONSTRAINT notification_preference_user_id_de890342_fk_accounts_user_id FOREIGN KEY (user_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: notification_push_device notification_push_device_user_id_10b2bfcc_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_push_device
    ADD CONSTRAINT notification_push_device_user_id_10b2bfcc_fk_accounts_user_id FOREIGN KEY (user_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: notification notification_recipient_id_305d14d6_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification
    ADD CONSTRAINT notification_recipient_id_305d14d6_fk_accounts_user_id FOREIGN KEY (recipient_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: parcels_delivery parcels_delivery_delivery_location_id_b57c763f_fk_locations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcels_delivery
    ADD CONSTRAINT parcels_delivery_delivery_location_id_b57c763f_fk_locations FOREIGN KEY (delivery_location_id) REFERENCES public.locations_location(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: parcels_delivery parcels_delivery_delivery_place_id_406fd8d0_fk_locations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcels_delivery
    ADD CONSTRAINT parcels_delivery_delivery_place_id_406fd8d0_fk_locations FOREIGN KEY (delivery_place_id) REFERENCES public.locations_place(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: parcels_delivery parcels_delivery_parcelrequest_ptr_id_fd65b55b_fk_parcels_r; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcels_delivery
    ADD CONSTRAINT parcels_delivery_parcelrequest_ptr_id_fd65b55b_fk_parcels_r FOREIGN KEY (parcelrequest_ptr_id) REFERENCES public.parcels_request(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: parcels_delivery parcels_delivery_pickup_location_id_7bf84e0c_fk_locations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcels_delivery
    ADD CONSTRAINT parcels_delivery_pickup_location_id_7bf84e0c_fk_locations FOREIGN KEY (pickup_location_id) REFERENCES public.locations_location(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: parcels_delivery parcels_delivery_pickup_place_id_91535a2e_fk_locations_place_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcels_delivery
    ADD CONSTRAINT parcels_delivery_pickup_place_id_91535a2e_fk_locations_place_id FOREIGN KEY (pickup_place_id) REFERENCES public.locations_place(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: parcels_media parcels_media_parcel_id_4618cd58_fk_parcels_request_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcels_media
    ADD CONSTRAINT parcels_media_parcel_id_4618cd58_fk_parcels_request_id FOREIGN KEY (parcel_id) REFERENCES public.parcels_request(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: parcels_media parcels_media_uploaded_by_id_213d0269_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcels_media
    ADD CONSTRAINT parcels_media_uploaded_by_id_213d0269_fk_accounts_user_id FOREIGN KEY (uploaded_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: parcels_product parcels_product_parcelrequest_ptr_id_cd16db97_fk_parcels_r; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcels_product
    ADD CONSTRAINT parcels_product_parcelrequest_ptr_id_cd16db97_fk_parcels_r FOREIGN KEY (parcelrequest_ptr_id) REFERENCES public.parcels_request(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: parcels_request parcels_request_destination_id_3759c9ba_fk_trips_airport_iata; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcels_request
    ADD CONSTRAINT parcels_request_destination_id_3759c9ba_fk_trips_airport_iata FOREIGN KEY (destination_id) REFERENCES public.trips_airport(iata) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: parcels_request parcels_request_origin_id_ea79a227_fk_trips_airport_iata; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcels_request
    ADD CONSTRAINT parcels_request_origin_id_ea79a227_fk_trips_airport_iata FOREIGN KEY (origin_id) REFERENCES public.trips_airport(iata) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: parcels_request parcels_request_sender_id_b6c24f22_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcels_request
    ADD CONSTRAINT parcels_request_sender_id_b6c24f22_fk_accounts_user_id FOREIGN KEY (sender_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: parcels_request parcels_request_target_traveler_id_f7c960d8_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.parcels_request
    ADD CONSTRAINT parcels_request_target_traveler_id_f7c960d8_fk_accounts_user_id FOREIGN KEY (target_traveler_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: payments_event payments_event_intent_id_ef557761_fk_payments_intent_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments_event
    ADD CONSTRAINT payments_event_intent_id_ef557761_fk_payments_intent_id FOREIGN KEY (intent_id) REFERENCES public.payments_intent(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: payments_intent payments_intent_offer_id_3ebd08f9_fk_matching_offer_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments_intent
    ADD CONSTRAINT payments_intent_offer_id_3ebd08f9_fk_matching_offer_id FOREIGN KEY (offer_id) REFERENCES public.matching_offer(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: payments_intent payments_intent_payer_id_58eeda3b_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments_intent
    ADD CONSTRAINT payments_intent_payer_id_58eeda3b_fk_accounts_user_id FOREIGN KEY (payer_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: payments_refund payments_refund_intent_id_0fcc71c9_fk_payments_intent_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.payments_refund
    ADD CONSTRAINT payments_refund_intent_id_0fcc71c9_fk_payments_intent_id FOREIGN KEY (intent_id) REFERENCES public.payments_intent(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: ratings_rating ratings_rating_deal_id_4ca9de15_fk_deals_deal_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ratings_rating
    ADD CONSTRAINT ratings_rating_deal_id_4ca9de15_fk_deals_deal_id FOREIGN KEY (deal_id) REFERENCES public.deals_deal(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: ratings_rating ratings_rating_ratee_id_68de5385_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ratings_rating
    ADD CONSTRAINT ratings_rating_ratee_id_68de5385_fk_accounts_user_id FOREIGN KEY (ratee_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: ratings_rating ratings_rating_rater_id_1093bd6d_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ratings_rating
    ADD CONSTRAINT ratings_rating_rater_id_1093bd6d_fk_accounts_user_id FOREIGN KEY (rater_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: token_blacklist_blacklistedtoken token_blacklist_blacklistedtoken_token_id_3cc7fe56_fk; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.token_blacklist_blacklistedtoken
    ADD CONSTRAINT token_blacklist_blacklistedtoken_token_id_3cc7fe56_fk FOREIGN KEY (token_id) REFERENCES public.token_blacklist_outstandingtoken(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: token_blacklist_outstandingtoken token_blacklist_outs_user_id_83bc629a_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.token_blacklist_outstandingtoken
    ADD CONSTRAINT token_blacklist_outs_user_id_83bc629a_fk_accounts_ FOREIGN KEY (user_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: trips_journey trips_journey_destination_location_a4b8da30_fk_locations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_journey
    ADD CONSTRAINT trips_journey_destination_location_a4b8da30_fk_locations FOREIGN KEY (destination_location_id) REFERENCES public.locations_location(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: trips_journey trips_journey_destination_place_id_a9e2040d_fk_locations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_journey
    ADD CONSTRAINT trips_journey_destination_place_id_a9e2040d_fk_locations FOREIGN KEY (destination_place_id) REFERENCES public.locations_place(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: trips_journey_leg trips_journey_leg_destination_id_bf982858_fk_locations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_journey_leg
    ADD CONSTRAINT trips_journey_leg_destination_id_bf982858_fk_locations FOREIGN KEY (destination_id) REFERENCES public.locations_location(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: trips_journey_leg trips_journey_leg_destination_place_id_5098d4a5_fk_locations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_journey_leg
    ADD CONSTRAINT trips_journey_leg_destination_place_id_5098d4a5_fk_locations FOREIGN KEY (destination_place_id) REFERENCES public.locations_place(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: trips_journey_leg trips_journey_leg_journey_id_aaa36f4d_fk_trips_journey_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_journey_leg
    ADD CONSTRAINT trips_journey_leg_journey_id_aaa36f4d_fk_trips_journey_id FOREIGN KEY (journey_id) REFERENCES public.trips_journey(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: trips_journey_leg trips_journey_leg_origin_id_4f36a14c_fk_locations_location_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_journey_leg
    ADD CONSTRAINT trips_journey_leg_origin_id_4f36a14c_fk_locations_location_id FOREIGN KEY (origin_id) REFERENCES public.locations_location(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: trips_journey_leg trips_journey_leg_origin_place_id_112b90e3_fk_locations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_journey_leg
    ADD CONSTRAINT trips_journey_leg_origin_place_id_112b90e3_fk_locations FOREIGN KEY (origin_place_id) REFERENCES public.locations_place(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: trips_journey_leg_proof trips_journey_leg_pr_reviewer_id_54c7deea_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_journey_leg_proof
    ADD CONSTRAINT trips_journey_leg_pr_reviewer_id_54c7deea_fk_accounts_ FOREIGN KEY (reviewer_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: trips_journey_leg_proof trips_journey_leg_proof_leg_id_4f5caa94_fk_trips_journey_leg_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_journey_leg_proof
    ADD CONSTRAINT trips_journey_leg_proof_leg_id_4f5caa94_fk_trips_journey_leg_id FOREIGN KEY (leg_id) REFERENCES public.trips_journey_leg(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: trips_journey trips_journey_legacy_trip_id_3baf7d80_fk_trips_trip_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_journey
    ADD CONSTRAINT trips_journey_legacy_trip_id_3baf7d80_fk_trips_trip_id FOREIGN KEY (legacy_trip_id) REFERENCES public.trips_trip(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: trips_journey trips_journey_start_location_id_9e128623_fk_locations; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_journey
    ADD CONSTRAINT trips_journey_start_location_id_9e128623_fk_locations FOREIGN KEY (start_location_id) REFERENCES public.locations_location(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: trips_journey trips_journey_start_place_id_5e983cd2_fk_locations_place_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_journey
    ADD CONSTRAINT trips_journey_start_place_id_5e983cd2_fk_locations_place_id FOREIGN KEY (start_place_id) REFERENCES public.locations_place(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: trips_journey trips_journey_traveler_id_2f192771_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_journey
    ADD CONSTRAINT trips_journey_traveler_id_2f192771_fk_accounts_user_id FOREIGN KEY (traveler_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: trips_media trips_media_trip_id_564fe19f_fk_trips_trip_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_media
    ADD CONSTRAINT trips_media_trip_id_564fe19f_fk_trips_trip_id FOREIGN KEY (trip_id) REFERENCES public.trips_trip(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: trips_stopover trips_stopover_airport_id_0767c665_fk_trips_airport_iata; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_stopover
    ADD CONSTRAINT trips_stopover_airport_id_0767c665_fk_trips_airport_iata FOREIGN KEY (airport_id) REFERENCES public.trips_airport(iata) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: trips_stopover trips_stopover_trip_id_ff310d00_fk_trips_trip_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_stopover
    ADD CONSTRAINT trips_stopover_trip_id_ff310d00_fk_trips_trip_id FOREIGN KEY (trip_id) REFERENCES public.trips_trip(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: trips_tracking_snapshot trips_tracking_snapshot_trip_id_605cb5d5_fk_trips_trip_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_tracking_snapshot
    ADD CONSTRAINT trips_tracking_snapshot_trip_id_605cb5d5_fk_trips_trip_id FOREIGN KEY (trip_id) REFERENCES public.trips_trip(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: trips_trip trips_trip_destination_id_a03da6f8_fk_trips_airport_iata; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_trip
    ADD CONSTRAINT trips_trip_destination_id_a03da6f8_fk_trips_airport_iata FOREIGN KEY (destination_id) REFERENCES public.trips_airport(iata) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: trips_trip trips_trip_origin_id_043ab555_fk_trips_airport_iata; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_trip
    ADD CONSTRAINT trips_trip_origin_id_043ab555_fk_trips_airport_iata FOREIGN KEY (origin_id) REFERENCES public.trips_airport(iata) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: trips_trip trips_trip_traveler_id_78282829_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trips_trip
    ADD CONSTRAINT trips_trip_traveler_id_78282829_fk_accounts_user_id FOREIGN KEY (traveler_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: verification_handover_code verification_handove_issued_to_id_14f1a0fd_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.verification_handover_code
    ADD CONSTRAINT verification_handove_issued_to_id_14f1a0fd_fk_accounts_ FOREIGN KEY (issued_to_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: verification_handover_code verification_handove_match_id_de694667_fk_matching_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.verification_handover_code
    ADD CONSTRAINT verification_handove_match_id_de694667_fk_matching_ FOREIGN KEY (match_id) REFERENCES public.matching_match(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: verification_handover_code verification_handove_used_by_id_3599beae_fk_accounts_; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.verification_handover_code
    ADD CONSTRAINT verification_handove_used_by_id_3599beae_fk_accounts_ FOREIGN KEY (used_by_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: wallet_entry wallet_entry_wallet_id_008ca9ae_fk_wallet_wallet_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wallet_entry
    ADD CONSTRAINT wallet_entry_wallet_id_008ca9ae_fk_wallet_wallet_id FOREIGN KEY (wallet_id) REFERENCES public.wallet_wallet(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: wallet_hold wallet_hold_wallet_id_b20de9ff_fk_wallet_wallet_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wallet_hold
    ADD CONSTRAINT wallet_hold_wallet_id_b20de9ff_fk_wallet_wallet_id FOREIGN KEY (wallet_id) REFERENCES public.wallet_wallet(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: wallet_wallet wallet_wallet_user_id_8c75caaa_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wallet_wallet
    ADD CONSTRAINT wallet_wallet_user_id_8c75caaa_fk_accounts_user_id FOREIGN KEY (user_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: wallet_withdrawal wallet_withdrawal_user_id_4fd05cda_fk_accounts_user_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wallet_withdrawal
    ADD CONSTRAINT wallet_withdrawal_user_id_4fd05cda_fk_accounts_user_id FOREIGN KEY (user_id) REFERENCES public.accounts_user(id) DEFERRABLE INITIALLY DEFERRED;


--
-- Name: wallet_withdrawal wallet_withdrawal_wallet_id_4825123a_fk_wallet_wallet_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.wallet_withdrawal
    ADD CONSTRAINT wallet_withdrawal_wallet_id_4825123a_fk_wallet_wallet_id FOREIGN KEY (wallet_id) REFERENCES public.wallet_wallet(id) DEFERRABLE INITIALLY DEFERRED;


--
-- PostgreSQL database dump complete
--

\unrestrict 1QaaFWYDRe9UoFz85mvL9WZWCdBzkQMXDvsnOGw4NevVp16ZViey90zPQdo36lk

