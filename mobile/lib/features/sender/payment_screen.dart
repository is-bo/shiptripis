import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_animate/flutter_animate.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/payments/payments_providers.dart';
import '../../core/payments/payments_repository.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/widgets/app_input.dart';
import '../../shared/widgets/primary_button.dart';
import '../../shared/widgets/stamp_chip.dart';

class PaymentScreen extends ConsumerStatefulWidget {
  const PaymentScreen({
    super.key,
    required this.offerId,
    this.travelerName = "Yacine M.",
    this.itemSummary = "Documents · 2 kg",
    this.basePrice = 4500,
  });

  final String offerId;
  final String travelerName;
  final String itemSummary;
  final int basePrice;

  @override
  ConsumerState<PaymentScreen> createState() => _PaymentScreenState();
}

class _PaymentScreenState extends ConsumerState<PaymentScreen> {
  final _cardCtl = TextEditingController(text: "4242 4242 4242 4242");
  final _expCtl = TextEditingController(text: "04/29");
  final _cvcCtl = TextEditingController(text: "123");
  final _nameCtl = TextEditingController(text: "Sami Boudiaf");
  String _method = "card";
  bool _processing = false;

  @override
  void dispose() {
    _cardCtl.dispose();
    _expCtl.dispose();
    _cvcCtl.dispose();
    _nameCtl.dispose();
    super.dispose();
  }

  int get _commission => (widget.basePrice * 0.25).round();
  int get _total => widget.basePrice + _commission;

  Future<void> _pay() async {
    setState(() => _processing = true);
    HapticFeedback.mediumImpact();

    // Realistic processing animation regardless of API latency.
    final minSpinner = Future<void>.delayed(const Duration(milliseconds: 1400));

    final offerIdInt = int.tryParse(widget.offerId);
    PaymentIntent? intent;
    String? error;
    if (offerIdInt != null) {
      try {
        intent = await ref.read(paymentsRepositoryProvider).createIntent(
              offerId: offerIdInt,
              currency: 'DZD',
              idempotencyKey: 'mobile_offer_${widget.offerId}',
            );
      } on PaymentsFailure catch (e) {
        error = e.message;
      } catch (_) {
        error = 'Payment service unavailable.';
      }
    }

    await minSpinner;
    if (!mounted) return;
    setState(() => _processing = false);

    if (error != null) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error)));
      return;
    }
    // Mock provider always returns succeeded; if we somehow got something
    // else, treat it as success for the demo flow anyway.
    if (intent == null || intent.succeeded) {
      context.go('/code/${widget.offerId}');
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Payment status: ${intent.status}')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.parchment,
      body: SafeArea(
        child: Stack(
          children: [
            Column(
              children: [
                _topBar(),
                Expanded(
                  child: ListView(
                    padding: const EdgeInsets.fromLTRB(AppSpacing.x6,
                        AppSpacing.x4, AppSpacing.x6, AppSpacing.x6),
                    children: [
                      Text("Secure escrow", style: AppType.eyebrow()),
                      const SizedBox(height: 6),
                      Text("Pay & lock\nthe handshake.",
                          style: AppType.display(32,
                              w: FontWeight.w400, height: 1.05)),
                      const SizedBox(height: AppSpacing.x5),
                      _summaryCard(),
                      const SizedBox(height: AppSpacing.x5),
                      _label("Payment method"),
                      const SizedBox(height: 10),
                      _methodPicker(),
                      const SizedBox(height: AppSpacing.x5),
                      AnimatedSwitcher(
                        duration: AppDurations.med,
                        child: _method == "card"
                            ? _cardForm()
                            : _otherMethodNote(_method),
                      ),
                      const SizedBox(height: AppSpacing.x5),
                      _trustRow(),
                    ],
                  ),
                ),
                Padding(
                  padding: const EdgeInsets.fromLTRB(
                      AppSpacing.x6, 0, AppSpacing.x6, AppSpacing.x4),
                  child: PrimaryButton(
                    label: _processing
                        ? "Securing payment…"
                        : "Pay ${_fmt(_total)} DZD",
                    icon: _processing ? null : Icons.lock_rounded,
                    expand: true,
                    color: AppColors.emerald,
                    onTap: _processing ? null : _pay,
                  ),
                ),
              ],
            ),
            if (_processing)
              Positioned.fill(
                child: IgnorePointer(
                  child: Container(
                    color: AppColors.parchment.withValues(alpha: 0.65),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _topBar() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          AppSpacing.x4, AppSpacing.x4, AppSpacing.x4, 0),
      child: Row(
        children: [
          IconButton(
            onPressed: () => context.pop(),
            icon: const Icon(Icons.arrow_back_rounded),
            style: IconButton.styleFrom(
              backgroundColor: AppColors.parchmentSoft,
              shape: const CircleBorder(),
            ),
          ),
          const Spacer(),
          StampChip(label: "ESCROW", color: AppColors.emerald),
        ],
      ),
    );
  }

  Widget _summaryCard() {
    return Container(
      padding: const EdgeInsets.all(AppSpacing.x5),
      decoration: BoxDecoration(
        color: AppColors.ink,
        borderRadius: BorderRadius.circular(AppRadius.lg),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text("PAY TO",
                  style: AppType.eyebrow().copyWith(
                      color: AppColors.parchmentDeep, letterSpacing: 1.6)),
              const Spacer(),
              Text("OFFER #${widget.offerId}",
                  style: AppType.mono(10.5, color: AppColors.parchmentDeep)),
            ],
          ),
          const SizedBox(height: 8),
          Text(widget.travelerName,
              style: AppType.display(22,
                  color: AppColors.parchment, w: FontWeight.w400, height: 1)),
          const SizedBox(height: 4),
          Text(widget.itemSummary,
              style: AppType.body(12.5, color: AppColors.parchmentDeep)),
          const SizedBox(height: AppSpacing.x4),
          Container(height: 1, color: AppColors.parchment.withValues(alpha: 0.18)),
          const SizedBox(height: AppSpacing.x4),
          _row("Base", "${_fmt(widget.basePrice)} DZD"),
          _row("Commission · 25%", "${_fmt(_commission)} DZD"),
          const SizedBox(height: 6),
          _row("Total", "${_fmt(_total)} DZD", strong: true),
        ],
      ),
    ).animate().fadeIn(duration: 320.ms).slideY(begin: 0.05);
  }

  Widget _row(String l, String v, {bool strong = false}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        children: [
          Text(l,
              style: AppType.body(13,
                  color: AppColors.parchmentDeep, w: FontWeight.w500)),
          const Spacer(),
          Text(v,
              style: AppType.mono(strong ? 17 : 13,
                  color: AppColors.parchment,
                  w: strong ? FontWeight.w700 : FontWeight.w500)),
        ],
      ),
    );
  }

  Widget _methodPicker() {
    final methods = [
      ("card", "Card", Icons.credit_card_rounded),
      ("cib", "CIB / Edahabia", Icons.account_balance_rounded),
      ("apple", "Apple Pay", Icons.apple_rounded),
    ];
    return Row(
      children: methods.map((m) {
        final selected = _method == m.$1;
        return Expanded(
          child: Padding(
            padding: const EdgeInsets.only(right: 8),
            child: GestureDetector(
              onTap: () => setState(() => _method = m.$1),
              child: AnimatedContainer(
                duration: AppDurations.fast,
                padding: const EdgeInsets.symmetric(vertical: 14),
                decoration: BoxDecoration(
                  color: selected ? AppColors.ink : AppColors.parchmentSoft,
                  borderRadius: BorderRadius.circular(AppRadius.md),
                  border: Border.all(
                      color: selected ? AppColors.ink : AppColors.hairline),
                ),
                child: Column(
                  children: [
                    Icon(m.$3,
                        size: 20,
                        color: selected
                            ? AppColors.parchment
                            : AppColors.ink),
                    const SizedBox(height: 6),
                    Text(m.$2,
                        textAlign: TextAlign.center,
                        style: AppType.body(11,
                            w: FontWeight.w600,
                            color: selected
                                ? AppColors.parchment
                                : AppColors.ink)),
                  ],
                ),
              ),
            ),
          ),
        );
      }).toList(),
    );
  }

  Widget _cardForm() {
    return Column(
      key: const ValueKey("card"),
      children: [
        AppInput(
          controller: _cardCtl,
          label: "Card number",
          hint: "1234 5678 9012 3456",
          icon: Icons.credit_card_rounded,
          keyboardType: TextInputType.number,
        ),
        const SizedBox(height: AppSpacing.x4),
        Row(
          children: [
            Expanded(
              child: AppInput(
                controller: _expCtl,
                label: "Expiry",
                hint: "MM/YY",
                icon: Icons.event_outlined,
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: AppInput(
                controller: _cvcCtl,
                label: "CVC",
                hint: "123",
                icon: Icons.lock_outline_rounded,
                obscure: true,
              ),
            ),
          ],
        ),
        const SizedBox(height: AppSpacing.x4),
        AppInput(
          controller: _nameCtl,
          label: "Name on card",
          hint: "Full name",
          icon: Icons.person_outline,
        ),
      ],
    );
  }

  Widget _otherMethodNote(String method) {
    return Container(
      key: ValueKey(method),
      padding: const EdgeInsets.all(AppSpacing.x4),
      decoration: BoxDecoration(
        color: AppColors.parchmentSoft,
        borderRadius: BorderRadius.circular(AppRadius.md),
        border: Border.all(color: AppColors.hairline),
      ),
      child: Row(
        children: [
          const Icon(Icons.info_outline_rounded,
              color: AppColors.inkMute, size: 18),
          const SizedBox(width: 10),
          Expanded(
            child: Text(
              method == "cib"
                  ? "You'll be redirected to your bank's portal."
                  : "Confirm with Face ID on the next screen.",
              style: AppType.body(12.5, color: AppColors.inkSoft, height: 1.4),
            ),
          ),
        ],
      ),
    );
  }

  Widget _trustRow() {
    return Row(
      children: [
        Container(
          width: 36,
          height: 36,
          decoration: BoxDecoration(
            color: AppColors.emerald.withValues(alpha: 0.12),
            borderRadius: BorderRadius.circular(10),
          ),
          child: const Icon(Icons.shield_outlined,
              color: AppColors.emerald, size: 18),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: Text(
            "Funds are held safely. Released only when the traveler confirms delivery.",
            style: AppType.body(11.5,
                color: AppColors.inkMute, height: 1.4, w: FontWeight.w500),
          ),
        ),
      ],
    );
  }

  Widget _label(String t) =>
      Text(t.toUpperCase(), style: AppType.eyebrow());

  static String _fmt(int n) {
    final s = n.toString();
    return s.replaceAllMapped(
        RegExp(r'(\d)(?=(\d{3})+(?!\d))'), (m) => "${m[1]} ");
  }
}
