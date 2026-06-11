import 'package:flutter/material.dart';

import '../../core/theme/tokens.dart';
import '../../core/theme/typography.dart';
import '../../shared/util/safe_back.dart';

/// Placeholder screen reached via `/chat/<matchId>` while the in-app chat
/// service is being built out (Django chat_message schema + Go publisher
/// + WS stream are scoped for next milestone). Shows the user the feature
/// is coming and gives a fallback so they can still coordinate.
class ChatStubScreen extends StatelessWidget {
  const ChatStubScreen({super.key, required this.matchId});
  final int matchId;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.parchment,
      appBar: AppBar(
        backgroundColor: AppColors.parchment,
        elevation: 0,
        leading: IconButton(
          icon: const Icon(Icons.arrow_back_rounded),
          onPressed: () => safeBack(context),
        ),
        title: const Text('Chat'),
      ),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(28, 24, 28, 32),
          child: Column(
            children: [
              const SizedBox(height: 32),
              Container(
                width: 96,
                height: 96,
                decoration: BoxDecoration(
                  color: AppColors.sun.withValues(alpha: 0.18),
                  shape: BoxShape.circle,
                  border: Border.all(
                    color: AppColors.sun.withValues(alpha: 0.6),
                    width: 1.4,
                  ),
                ),
                child: const Icon(
                  Icons.chat_bubble_outline_rounded,
                  size: 44,
                  color: AppColors.ink,
                ),
              ),
              const SizedBox(height: 22),
              Text(
                'Direct chat is coming soon',
                textAlign: TextAlign.center,
                style: AppType.display(22, w: FontWeight.w500, height: 1.2),
              ),
              const SizedBox(height: 10),
              Text(
                'We\'re rolling out in-app messaging between senders and travelers. '
                'For now, you can still reach out via the options below.',
                textAlign: TextAlign.center,
                style: AppType.body(13.5,
                    color: AppColors.inkSoft, height: 1.5),
              ),
              const SizedBox(height: 28),
              _StubAction(
                icon: Icons.support_agent_rounded,
                label: 'Contact support',
                subtitle: 'We\'ll relay your message to the traveler',
                onTap: () {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(
                      content: Text('Support contact coming with chat rollout.'),
                      duration: Duration(seconds: 2),
                    ),
                  );
                },
              ),
              const SizedBox(height: 12),
              _StubAction(
                icon: Icons.help_outline_rounded,
                label: 'Read FAQ',
                subtitle: 'Common questions about pickup & delivery',
                onTap: () {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('FAQ coming soon.')),
                  );
                },
              ),
              const Spacer(),
              Text(
                'Match #$matchId',
                style: AppType.body(11, color: AppColors.inkMute, height: 1),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _StubAction extends StatelessWidget {
  const _StubAction({
    required this.icon,
    required this.label,
    required this.subtitle,
    required this.onTap,
  });
  final IconData icon;
  final String label;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white,
      borderRadius: BorderRadius.circular(AppRadius.lg),
      child: InkWell(
        borderRadius: BorderRadius.circular(AppRadius.lg),
        onTap: onTap,
        child: Container(
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(AppRadius.lg),
            border: Border.all(color: AppColors.hairline),
          ),
          child: Row(
            children: [
              Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(
                  color: AppColors.parchmentSoft,
                  borderRadius: BorderRadius.circular(AppRadius.md),
                ),
                child: Icon(icon, size: 20, color: AppColors.ink),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(label,
                        style: AppType.body(14.5, w: FontWeight.w700)),
                    const SizedBox(height: 2),
                    Text(subtitle,
                        style: AppType.body(12, color: AppColors.inkSoft)),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right_rounded,
                  color: AppColors.inkMute),
            ],
          ),
        ),
      ),
    );
  }
}
