import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/matching/matching_providers.dart';
import '../../core/matching/matching_repository.dart';
import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../core/ws/live_event_router.dart';
import '../../shared/util/safe_back.dart';
import '../../shared/widgets/stamp_chip.dart';

/// Follow-package — 3 loading circles bound to live Match.status.
///
/// Stages map to backend Match.status:
///   accepted    → waitingHandover
///   in_transit  → transmitting
///   delivered/completed → arrived
class FollowPackageScreen extends ConsumerStatefulWidget {
  const FollowPackageScreen({super.key, required this.matchId});

  final String matchId;

  @override
  ConsumerState<FollowPackageScreen> createState() =>
      _FollowPackageScreenState();
}

enum _Stage { waitingHandover, transmitting, arrived }

class _FollowPackageScreenState extends ConsumerState<FollowPackageScreen> {
  Timer? _poll;
  int get _id => int.parse(widget.matchId);

  @override
  void initState() {
    super.initState();
    // Light polling — Match status changes are infrequent so 12s is plenty.
    _poll = Timer.periodic(const Duration(seconds: 12), (_) {
      if (!mounted) return;
      ref.invalidate(matchDetailProvider(_id));
    });
  }

  @override
  void dispose() {
    _poll?.cancel();
    super.dispose();
  }

  _Stage _stageFor(MatchStatus s) {
    switch (s) {
      case MatchStatus.accepted:
        return _Stage.waitingHandover;
      case MatchStatus.inTransit:
        return _Stage.transmitting;
      case MatchStatus.delivered:
      case MatchStatus.completed:
        return _Stage.arrived;
      case MatchStatus.pending:
      case MatchStatus.cancelled:
      case MatchStatus.expired:
        return _Stage.waitingHandover;
    }
  }

  @override
  Widget build(BuildContext context) {
    final async = ref.watch(matchDetailProvider(_id));
    return Scaffold(
      backgroundColor: AppColors.parchment,
      body: SafeArea(
        child: async.when(
          loading: () =>
              const Center(child: CircularProgressIndicator()),
          error: (e, _) => Center(
            child: Padding(
              padding: const EdgeInsets.all(AppSpacing.x6),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.cloud_off_rounded,
                      color: AppColors.terracotta, size: 32),
                  const SizedBox(height: 12),
                  Text("Couldn't load match.",
                      style: AppType.body(13, w: FontWeight.w600)),
                  const SizedBox(height: 8),
                  TextButton(
                    onPressed: () =>
                        ref.invalidate(matchDetailProvider(_id)),
                    child: const Text('Retry'),
                  ),
                ],
              ),
            ),
          ),
          data: (match) {
            final stage = _stageFor(match.status);
            final live = liveCodeFor(ref, _id);
            final showCode = live != null &&
                live.kind == 'pickup' &&
                (match.status == MatchStatus.accepted ||
                    match.status == MatchStatus.inTransit);
            return RefreshIndicator(
              onRefresh: () async =>
                  ref.invalidate(matchDetailProvider(_id)),
              child: ListView(
                physics: const AlwaysScrollableScrollPhysics(),
                padding: EdgeInsets.zero,
                children: [
                  _topBar(match.status),
                  const SizedBox(height: AppSpacing.x4),
                  _headerCard(match),
                  if (showCode) ...[
                    const SizedBox(height: AppSpacing.x5),
                    _PickupCodeBanner(code: live.code),
                  ],
                  const SizedBox(height: AppSpacing.x6),
                  _stagesColumn(stage),
                  const SizedBox(height: AppSpacing.x6),
                ],
              ),
            );
          },
        ),
      ),
    );
  }

  Widget _topBar(MatchStatus status) {
    final stamp = switch (status) {
      MatchStatus.completed => ('PAID OUT', AppColors.emerald),
      MatchStatus.delivered => ('DELIVERED', AppColors.emerald),
      MatchStatus.inTransit => ('IN TRANSIT', AppColors.gold),
      MatchStatus.cancelled => ('CANCELLED', AppColors.terracotta),
      _ => ('IN ESCROW', AppColors.emerald),
    };
    return Padding(
      padding: const EdgeInsets.fromLTRB(
          AppSpacing.x4, AppSpacing.x4, AppSpacing.x4, 0),
      child: Row(
        children: [
          IconButton(
            onPressed: () => safeBack(context, fallback: '/sender/requests'),
            icon: const Icon(Icons.arrow_back_rounded),
            style: IconButton.styleFrom(
              backgroundColor: AppColors.parchmentSoft,
              shape: const CircleBorder(),
            ),
          ),
          const Spacer(),
          StampChip(label: stamp.$1, color: stamp.$2),
        ],
      ),
    );
  }

  Widget _headerCard(MatchSummary match) {
    final parcel = match.parcel;
    final route = parcel != null
        ? "${parcel.originIata} → ${parcel.destinationIata}"
        : "Match #${match.id}";
    final summary = parcel != null
        ? "${parcel.weightKg} kg · ${parcel.kind == 'product' ? 'product' : 'delivery'}"
        : "Parcel #${match.parcelId}";
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
      child: Container(
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
                Text('CARRIED BY',
                    style: AppType.eyebrow().copyWith(
                        color: AppColors.parchmentDeep, letterSpacing: 1.6)),
                const Spacer(),
                Text('MATCH #${match.id}',
                    style:
                        AppType.mono(10.5, color: AppColors.parchmentDeep)),
              ],
            ),
            const SizedBox(height: 8),
            Text(match.travelerLabel(),
                style: AppType.display(22,
                    color: AppColors.parchment,
                    w: FontWeight.w400,
                    height: 1)),
            const SizedBox(height: 4),
            Text(route,
                style: AppType.body(13,
                    color: AppColors.parchmentDeep, w: FontWeight.w500)),
            Text(summary,
                style: AppType.body(12.5, color: AppColors.parchmentDeep)),
          ],
        ),
      ),
    );
  }

  Widget _stagesColumn(_Stage stage) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
      child: Column(
        children: [
          _StageRow(
            label: 'Waiting to handover',
            sub: 'Sender will hand the package to the traveler.',
            status: _statusFor(stage, 0),
          ),
          _Connector(active: stage.index >= 1),
          _StageRow(
            label: 'Transmitting',
            sub: 'In transit with the traveler.',
            status: _statusFor(stage, 1),
          ),
          _Connector(active: stage.index >= 2),
          _StageRow(
            label: 'Package arrived',
            sub: 'Delivered. Escrow released to the traveler.',
            status: _statusFor(stage, 2),
          ),
        ],
      ),
    );
  }

  _StageStatus _statusFor(_Stage stage, int index) {
    if (stage.index > index) return _StageStatus.done;
    if (stage.index == index) return _StageStatus.active;
    return _StageStatus.idle;
  }
}

enum _StageStatus { idle, active, done }

class _StageRow extends StatelessWidget {
  const _StageRow({
    required this.label,
    required this.sub,
    required this.status,
  });

  final String label;
  final String sub;
  final _StageStatus status;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          _Circle(status: status),
          const SizedBox(width: AppSpacing.x4),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: AppType.display(
                    16,
                    color: status == _StageStatus.idle
                        ? AppColors.inkSoft
                        : AppColors.ink,
                    w: FontWeight.w400,
                    height: 1.1,
                  ),
                ),
                const SizedBox(height: 2),
                Text(sub, style: AppType.body(12, color: AppColors.inkSoft)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _Circle extends StatelessWidget {
  const _Circle({required this.status});
  final _StageStatus status;

  @override
  Widget build(BuildContext context) {
    const size = 44.0;
    switch (status) {
      case _StageStatus.idle:
        return Container(
          width: size,
          height: size,
          decoration: BoxDecoration(
            color: AppColors.parchmentSoft,
            shape: BoxShape.circle,
            border: Border.all(
              color: AppColors.inkSoft.withValues(alpha: 0.25),
              width: 1.5,
            ),
          ),
        );
      case _StageStatus.active:
        return SizedBox(
          width: size,
          height: size,
          child: Stack(
            alignment: Alignment.center,
            children: [
              SizedBox(
                width: size,
                height: size,
                child: CircularProgressIndicator(
                  strokeWidth: 3.5,
                  valueColor: AlwaysStoppedAnimation(AppColors.emerald),
                  backgroundColor: AppColors.parchmentSoft,
                ),
              ),
              Container(
                width: 14,
                height: 14,
                decoration: BoxDecoration(
                  color: AppColors.emerald,
                  shape: BoxShape.circle,
                ),
              ),
            ],
          ),
        );
      case _StageStatus.done:
        return Container(
          width: size,
          height: size,
          decoration: BoxDecoration(
            color: AppColors.emerald,
            shape: BoxShape.circle,
          ),
          child: const Icon(Icons.check_rounded,
              color: Colors.white, size: 26),
        );
    }
  }
}

class _PickupCodeBanner extends StatelessWidget {
  const _PickupCodeBanner({required this.code});
  final String code;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
      child: Container(
        padding: const EdgeInsets.fromLTRB(
            AppSpacing.x5, AppSpacing.x4, AppSpacing.x4, AppSpacing.x4),
        decoration: BoxDecoration(
          color: AppColors.sun,
          borderRadius: BorderRadius.circular(AppRadius.lg),
          border: Border.all(color: AppColors.ink, width: 1.5),
        ),
        child: Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('PICKUP CODE',
                      style: AppType.eyebrow()
                          .copyWith(color: AppColors.ink, letterSpacing: 1.6)),
                  const SizedBox(height: 6),
                  Text(
                    code,
                    style: AppType.display(28, w: FontWeight.w600).copyWith(
                      letterSpacing: 4,
                      fontFeatures: const [FontFeature.tabularFigures()],
                      color: AppColors.ink,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text('Share this with the traveler at handover.',
                      style: AppType.body(12, color: AppColors.ink)),
                ],
              ),
            ),
            IconButton(
              tooltip: 'Copy',
              onPressed: () {
                Clipboard.setData(ClipboardData(text: code));
                ScaffoldMessenger.of(context).showSnackBar(
                  const SnackBar(
                      content: Text('Pickup code copied'),
                      duration: Duration(seconds: 2)),
                );
              },
              icon: const Icon(Icons.copy_rounded, color: AppColors.ink),
            ),
          ],
        ),
      ),
    );
  }
}

class _Connector extends StatelessWidget {
  const _Connector({required this.active});
  final bool active;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: 21),
      child: Container(
        width: 3,
        height: 28,
        decoration: BoxDecoration(
          color: active
              ? AppColors.emerald
              : AppColors.inkSoft.withValues(alpha: 0.2),
          borderRadius: BorderRadius.circular(2),
        ),
      ),
    );
  }
}
