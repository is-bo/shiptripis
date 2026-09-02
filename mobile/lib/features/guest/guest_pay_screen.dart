/// Paying somebody else's delivery, from a link.
///
/// This is the only anonymous screen in the app, and it exists for a specific
/// person: a relative in Algiers who has no account, opened a link from a
/// message, and needs to pay for a parcel somebody in Europe is sending. It
/// therefore runs entirely outside the session — no auth header, no account,
/// no shell.
///
/// ## What it deliberately does not show
///
/// Nothing about the counterparty. The API's anonymous payload carries an
/// amount, a currency, a generic description, an expiry and the usable rails —
/// no names, no addresses, no parcel, no deal id. That is a privacy decision,
/// and this screen does not go looking for more.
///
/// ## The token
///
/// An opaque bearer string. It is never parsed, never logged, never persisted,
/// and never put in an analytics event. It reaches this screen as a route
/// parameter and goes straight back out in the two calls that need it.
///
/// ## Known gap, stated honestly
///
/// There is no anonymous *status* endpoint. After the provider redirect a
/// guest has no way to ask the server "did it work" — the quote endpoint stops
/// resolving once the link is consumed. So the screen sets expectations before
/// the redirect rather than promising a confirmation it cannot deliver, and
/// tells the payer that the sender will see the result. Reported as a backend
/// finding.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../core/api/api_exception.dart';
import '../../core/format/locale_formats.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/money.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/payment.dart';
import '../../l10n/app_localizations.dart';

final _guestViewProvider = FutureProvider.autoDispose
    .family<GuestPaymentView, String>((ref, token) async {
      final repo = ref.watch(paymentRepositoryProvider);
      return repo.guestView(token);
    });

class GuestPayScreen extends ConsumerStatefulWidget {
  const GuestPayScreen({required this.token, super.key});

  /// Opaque. Never rendered, never stored.
  final String token;

  @override
  ConsumerState<GuestPayScreen> createState() => _GuestPayScreenState();
}

class _GuestPayScreenState extends ConsumerState<GuestPayScreen> {
  final _formKey = GlobalKey<FormState>();
  final _email = TextEditingController();
  PaymentProviderId? _selected;
  bool _busy = false;
  bool _handedOff = false;

  @override
  void dispose() {
    _email.dispose();
    super.dispose();
  }

  Future<void> _pay() async {
    final provider = _selected;
    if (provider == null) return;
    if (!(_formKey.currentState?.validate() ?? false)) return;

    setState(() => _busy = true);
    final l = L.of(context);

    try {
      final checkout = await ref
          .read(paymentRepositoryProvider)
          .guestCheckout(
            token: widget.token,
            provider: provider,
            email: _email.text.trim(),
          );

      final uri = Uri.tryParse(checkout.checkoutUrl);
      if (uri == null) throw StateError('unusable checkout url');

      final opened = await launchUrl(
        uri,
        // External, never an in-app webview: a card form inside somebody
        // else's app is the exact thing a payer should be suspicious of.
        mode: LaunchMode.externalApplication,
      );
      if (!mounted) return;
      if (!opened) {
        AppSnack.info(context, l.paymentProviderUnavailable);
        return;
      }
      setState(() => _handedOff = true);
    } on ApiException catch (error) {
      if (!mounted) return;
      AppSnack.failure(context, error);
    } on StateError {
      if (!mounted) return;
      AppSnack.info(context, l.paymentProviderUnavailable);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final view = ref.watch(_guestViewProvider(widget.token));

    return AppScaffold(
      topBar: AppTopBar(title: l.guestPayTitle),
      body: AsyncView<GuestPaymentView>(
        value: view,
        onRetry: () => ref.invalidate(_guestViewProvider(widget.token)),
        loading: () => const Padding(
          padding: EdgeInsets.all(AppSpace.gutter),
          child: SkeletonDetail(),
        ),
        // Every invalid reason — unknown, expired, revoked, already paid —
        // collapses to one response on the server so a prober learns nothing.
        // The screen mirrors that: one honest message, no speculation.
        error: (error) => ListView(
          padding: AppScrollPadding.page(context),
          children: [
            AppEmptyState(
              title: l.guestPayInvalidTitle,
              body: l.guestPayInvalidBody,
              icon: Icons.link_off_rounded,
            ),
          ],
        ),
        data: (data) {
          if (_handedOff) return _AfterHandoff(view: data);
          return _PayForm(
            formKey: _formKey,
            email: _email,
            view: data,
            selected: _selected,
            onSelect: (provider) => setState(() => _selected = provider),
          );
        },
      ),
      footer: view.hasValue && !_handedOff
          ? AppButton(
              label: l.paymentPayAction(
                view.value?.amount?.format(Localizations.localeOf(context)) ??
                    '',
              ),
              isLoading: _busy,
              onPressed: _selected == null ? null : _pay,
            )
          : null,
    );
  }
}

class _PayForm extends StatelessWidget {
  const _PayForm({
    required this.formKey,
    required this.email,
    required this.view,
    required this.selected,
    required this.onSelect,
  });

  final GlobalKey<FormState> formKey;
  final TextEditingController email;
  final GuestPaymentView view;
  final PaymentProviderId? selected;
  final ValueChanged<PaymentProviderId> onSelect;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final locale = Localizations.localeOf(context);
    final amount = view.amount;

    // Already filtered server-side to rails usable right now, so an empty list
    // means there is genuinely no way to pay at this moment.
    if (view.providers.isEmpty) {
      return ListView(
        padding: AppScrollPadding.page(context),
        children: [
          AppEmptyState(
            title: l.paymentNoProvidersTitle,
            body: l.paymentNoProvidersBody,
            icon: Icons.credit_card_off_rounded,
          ),
        ],
      );
    }

    return Form(
      key: formKey,
      child: ListView(
        padding: AppScrollPadding.pageWithFooter(context),
        children: [
          InfoNotice(
            message: l.guestPayExplainer,
            tone: StatusTone.progress,
            icon: Icons.volunteer_activism_outlined,
          ),
          const SizedBox(height: AppSpace.xl),

          AppTextField(
            label: l.guestPayPayerEmail,
            controller: email,
            helper: l.guestPayPayerEmailHelp,
            isRequired: true,
            keyboardType: TextInputType.emailAddress,
            textInputAction: TextInputAction.next,
            autofillHints: const [AutofillHints.email],
            validator: Validators.of(context).email,
            prefixIcon: Icons.alternate_email_rounded,
          ),

          if (amount != null)
            AppCard(
              child: MoneyHero(
                amount: amount,
                label: l.guestPayAmountDue,
                caption: view.description.isEmpty ? null : view.description,
              ),
            ),

          if (view.expiresAt != null) ...[
            const SizedBox(height: AppSpace.md),
            Text(
              l.guestPayExpiresAt(
                LocaleFormats.dateTime(locale, view.expiresAt!),
              ),
              style: Theme.of(
                context,
              ).textTheme.bodySmall?.copyWith(color: c.textTertiary),
            ),
          ],

          const SizedBox(height: AppSpace.xl),
          SectionHeader(title: l.paymentChooseProvider),
          for (final option in view.providers) ...[
            _ProviderTile(
              option: option,
              selected: option.provider == selected,
              onTap: () => onSelect(option.provider),
            ),
            const SizedBox(height: AppSpace.md),
          ],

          const SizedBox(height: AppSpace.lg),
          Text(
            l.guestPayWarning,
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: c.textSecondary),
          ),
          const SizedBox(height: AppSpace.sm),
          Text(
            l.guestPayPoweredBy,
            style: Theme.of(
              context,
            ).textTheme.labelSmall?.copyWith(color: c.textTertiary),
          ),
        ],
      ),
    );
  }
}

class _ProviderTile extends StatelessWidget {
  const _ProviderTile({
    required this.option,
    required this.selected,
    required this.onTap,
  });

  final ProviderOption option;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;

    final (label, subtitle, icon) = switch (option.provider) {
      PaymentProviderId.chargily => (
        l.paymentProviderChargily,
        l.paymentProviderChargilySubtitle,
        Icons.account_balance_rounded,
      ),
      _ => (
        l.paymentProviderStripe,
        l.paymentProviderStripeSubtitle,
        Icons.credit_card_rounded,
      ),
    };

    return Semantics(
      button: true,
      selected: selected,
      label: label,
      hint: selected ? l.a11ySelected : l.a11yNotSelected,
      onTap: onTap,
      child: ExcludeSemantics(
        child: AppCard(
          onTap: onTap,
          accent: selected ? StatusTone.progress : null,
          child: Row(
            children: [
              Icon(icon, size: 22, color: c.textSecondary),
              const SizedBox(width: AppSpace.lg),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(label, style: Theme.of(context).textTheme.titleSmall),
                    const SizedBox(height: AppSpace.xxs),
                    Text(
                      subtitle,
                      style: Theme.of(
                        context,
                      ).textTheme.bodySmall?.copyWith(color: c.textSecondary),
                    ),
                  ],
                ),
              ),
              Icon(
                selected
                    ? Icons.radio_button_checked_rounded
                    : Icons.radio_button_unchecked_rounded,
                size: 20,
                color: selected ? c.brand : c.hairlineStrong,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// After the payer has been sent to the provider.
///
/// It says what is true — the payment is with the provider and the sender will
/// see the outcome — and does **not** claim success, because the redirect
/// proves nothing and this surface has no way to check.
class _AfterHandoff extends StatelessWidget {
  const _AfterHandoff({required this.view});

  final GuestPaymentView view;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    return ListView(
      padding: AppScrollPadding.page(context),
      children: [
        AppEmptyState(
          title: l.paymentConfirmingTitle,
          body: '${l.paymentRedirectNotProof}\n\n${l.guestPayThanksBody}',
          icon: Icons.hourglass_top_rounded,
        ),
      ],
    );
  }
}
