import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/widgets/stamp_chip.dart';

/// Follow-package — 3 loading circles for the journey stages.
///
/// No map. Per user instruction: "those loading circles is enough
/// (waiting to handover, transmitting, package arrived)".
///
/// Stages map to backend Match.status:
///   accepted    → waitingHandover (circle 1 spinning, 2&3 idle)
///   in_transit  → transmitting    (circle 1 done, 2 spinning, 3 idle)
///   completed   → arrived         (all 3 done)
class FollowPackageScreen extends StatefulWidget {
  const FollowPackageScreen({
    super.key,
    required this.matchId,
    this.stage = FollowStage.waitingHandover,
    this.travelerName = 'Yacine M.',
    this.itemSummary = 'Documents · 2 kg',
  });

  final String matchId;
  final FollowStage stage;
  final String travelerName;
  final String itemSummary;

  @override
  State<FollowPackageScreen> createState() => _FollowPackageScreenState();
}

enum FollowStage { waitingHandover, transmitting, arrived }

class _FollowPackageScreenState extends State<FollowPackageScreen> {
  late FollowStage _stage = widget.stage;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.parchment,
      body: SafeArea(
        child: Column(
          children: [
            _topBar(),
            const SizedBox(height: AppSpacing.x4),
            _headerCard(),
            const SizedBox(height: AppSpacing.x6),
            Expanded(child: _stagesColumn()),
            _devToggle(),
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
          StampChip(label: 'IN ESCROW', color: AppColors.emerald),
        ],
      ),
    );
  }

  Widget _headerCard() {
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
                Text('MATCH #${widget.matchId}',
                    style:
                        AppType.mono(10.5, color: AppColors.parchmentDeep)),
              ],
            ),
            const SizedBox(height: 8),
            Text(widget.travelerName,
                style: AppType.display(22,
                    color: AppColors.parchment,
                    w: FontWeight.w400,
                    height: 1)),
            const SizedBox(height: 4),
            Text(widget.itemSummary,
                style: AppType.body(12.5, color: AppColors.parchmentDeep)),
          ],
        ),
      ),
    );
  }

  Widget _stagesColumn() {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.x6),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          _StageRow(
            label: 'Waiting to handover',
            sub: 'Sender will hand the package to the traveler.',
            status: _statusFor(0),
          ),
          _Connector(active: _stage.index >= 1),
          _StageRow(
            label: 'Transmitting',
            sub: 'In transit with the traveler.',
            status: _statusFor(1),
          ),
          _Connector(active: _stage.index >= 2),
          _StageRow(
            label: 'Package arrived',
            sub: 'Delivered. Escrow released to the traveler.',
            status: _statusFor(2),
          ),
        ],
      ),
    );
  }

  _StageStatus _statusFor(int index) {
    if (_stage.index > index) return _StageStatus.done;
    if (_stage.index == index) return _StageStatus.active;
    return _StageStatus.idle;
  }

  // Hidden until backed by a real Match.status stream. Keeps demo usable.
  Widget _devToggle() {
    return Padding(
      padding: const EdgeInsets.all(AppSpacing.x4),
      child: SegmentedButton<FollowStage>(
        segments: const [
          ButtonSegment(value: FollowStage.waitingHandover, label: Text('1')),
          ButtonSegment(value: FollowStage.transmitting, label: Text('2')),
          ButtonSegment(value: FollowStage.arrived, label: Text('3')),
        ],
        selected: {_stage},
        onSelectionChanged: (s) => setState(() => _stage = s.first),
      ),
    );
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
                Text(
                  sub,
                  style: AppType.body(
                    12,
                    color: AppColors.inkSoft,
                  ),
                ),
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
