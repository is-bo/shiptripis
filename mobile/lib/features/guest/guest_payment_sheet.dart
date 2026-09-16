/// Guest payment sheet.
///
/// Allows a sender to share an unauthenticated payment link so a friend,
/// family member, or client can settle the obligation.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:share_plus/share_plus.dart';

import '../../core/api/api_exception.dart';
import '../../core/format/locale_formats.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/primitives.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/tokens.dart';
import '../../domain/payment.dart';
import '../../l10n/app_localizations.dart';

class GuestPaymentSheet extends ConsumerStatefulWidget {
  const GuestPaymentSheet({
    required this.order,
    this.onSettled,
    super.key,
  });

  final PaymentOrder order;
  final VoidCallback? onSettled;

  static Future<void> show(
    BuildContext context, {
    required PaymentOrder order,
    VoidCallback? onSettled,
  }) {
    return showAppSheet<void>(
      context,
      builder: (sheetContext) => GuestPaymentSheet(
        order: order,
        onSettled: onSettled,
      ),
    );
  }

  @override
  ConsumerState<GuestPaymentSheet> createState() => _GuestPaymentSheetState();
}

class _GuestPaymentSheetState extends ConsumerState<GuestPaymentSheet> {
  GuestPaymentLink? _link;
  bool _loading = true;
  bool _revoking = false;
  String? _error;
  Timer? _pollTimer;
  PaymentOrder? _liveOrder;

  @override
  void initState() {
    super.initState();
    _liveOrder = widget.order;
    _loadOrIssueLink();
    _startPolling();
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    super.dispose();
  }

  void _startPolling() {
    _pollTimer = Timer.periodic(const Duration(seconds: 3), (_) async {
      try {
        final updated = await ref
            .read(paymentRepositoryProvider)
            .order(widget.order.publicReference);
        if (!mounted) return;
        setState(() => _liveOrder = updated);
        if (updated.status.isSettled) {
          _pollTimer?.cancel();
          widget.onSettled?.call();
        }
      } catch (_) {}
    });
  }

  Future<void> _loadOrIssueLink() async {
    setState(() {
      _loading = true;
      _error = null;
    });

    try {
      final link = await ref
          .read(paymentRepositoryProvider)
          .createGuestLink(reference: widget.order.publicReference);
      if (!mounted) return;
      setState(() {
        _link = link;
        _loading = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.serverDetail ?? 'Failed to generate guest link';
        _loading = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = 'Failed to generate guest link';
        _loading = false;
      });
    }
  }

  Future<void> _revokeLink() async {
    final l = L.of(context);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(l.guestPaymentRevokeConfirmTitle),
        content: Text(l.guestPaymentRevokeConfirmBody),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: Text(l.actionCancel),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: Text(l.guestPaymentRevokeAction),
          ),
        ],
      ),
    );

    if (confirmed != true || !mounted) return;

    setState(() => _revoking = true);
    try {
      await ref
          .read(paymentRepositoryProvider)
          .revokeGuestLink(widget.order.publicReference);
      if (!mounted) return;
      Navigator.of(context).pop();
      AppSnack.info(context, l.actionDone);
    } on ApiException catch (e) {
      if (!mounted) return;
      AppSnack.failure(context, e);
    } finally {
      if (mounted) setState(() => _revoking = false);
    }
  }

  void _shareUrl(String url) {
    SharePlus.instance.share(ShareParams(uri: Uri.tryParse(url)));
  }

  void _copyUrl(String url) {
    Clipboard.setData(ClipboardData(text: url));
    AppSnack.success(context, L.of(context).guestPaymentCopied);
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final locale = Localizations.localeOf(context);
    final liveOrder = _liveOrder ?? widget.order;

    if (liveOrder.status.isSettled) {
      return AppSheet(
        title: l.guestPaymentTitle,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            InfoNotice(
              title: l.paymentSuccessTitle,
              message: l.guestPaymentPaidNotice,
              tone: StatusTone.good,
              icon: Icons.check_circle_rounded,
            ),
            const SizedBox(height: AppSpace.xl),
            AppButton(
              label: l.actionDone,
              onPressed: () => Navigator.of(context).pop(),
            ),
          ],
        ),
      );
    }

    return AppSheet(
      title: l.guestPaymentTitle,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            l.guestPaymentDescription,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: c.textSecondary,
            ),
          ),
          const SizedBox(height: AppSpace.md),

          if (_loading) ...[
            const Center(
              child: Padding(
                padding: EdgeInsets.symmetric(vertical: AppSpace.xl),
                child: CircularProgressIndicator(),
              ),
            ),
          ] else if (_error != null) ...[
            InfoNotice(
              message: _error!,
              tone: StatusTone.bad,
              icon: Icons.error_outline_rounded,
              actionLabel: l.actionRetry,
              onAction: _loadOrIssueLink,
            ),
          ] else if (_link != null) ...[
            AppCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  DetailRow(
                    label: l.paymentStatusPaid,
                    value: Text(
                      widget.order.amount?.format(locale) ?? '',
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                        fontWeight: FontWeight.bold,
                        color: c.brand,
                      ),
                    ),
                  ),
                  if (_link!.expiresAt != null) ...[
                    const SizedBox(height: AppSpace.xs),
                    Text(
                      l.guestPaymentExpires(
                        LocaleFormats.dateTime(locale, _link!.expiresAt!),
                      ),
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: c.textTertiary,
                      ),
                    ),
                  ],
                  const SizedBox(height: AppSpace.md),
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: AppSpace.sm,
                      vertical: AppSpace.xs,
                    ),
                    decoration: BoxDecoration(
                      color: c.surfaceSunken,
                      borderRadius: AppRadius.rSm,
                      border: Border.all(color: c.hairline),
                    ),
                    child: Row(
                      children: [
                        Expanded(
                          child: Text(
                            _link!.paymentLink ?? _link!.token,
                            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              fontFamily: 'monospace',
                              color: c.textSecondary,
                            ),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                        IconButton(
                          icon: const Icon(Icons.copy_rounded, size: 18),
                          tooltip: l.guestPaymentCopyButton,
                          onPressed: () => _copyUrl(_link!.paymentLink ?? _link!.token),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            const SizedBox(height: AppSpace.md),

            Row(
              children: [
                Expanded(
                  child: AppButton(
                    label: l.guestPaymentShareButton,
                    icon: Icons.share_rounded,
                    onPressed: () => _shareUrl(_link!.paymentLink ?? _link!.token),
                  ),
                ),
                const SizedBox(width: AppSpace.sm),
                AppButton(
                  label: l.guestPaymentCopyButton,
                  icon: Icons.copy_rounded,
                  variant: AppButtonVariant.secondary,
                  expand: false,
                  onPressed: () => _copyUrl(_link!.paymentLink ?? _link!.token),
                ),
              ],
            ),
            const SizedBox(height: AppSpace.sm),

            Center(
              child: AppButton(
                label: l.guestPaymentRevokeAction,
                variant: AppButtonVariant.tertiary,
                isLoading: _revoking,
                onPressed: _revokeLink,
              ),
            ),
          ],
        ],
      ),
    );
  }
}
