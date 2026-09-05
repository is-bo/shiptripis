/// The card that represents one delivery, everywhere it appears.
///
/// Home, Deliveries and search results all show the same object, so they show
/// the same card. That is not laziness — a user who learns to read this card
/// once should not have to relearn it a screen later.
///
/// The card answers four questions, in this order, because that is the order
/// people ask them:
///
/// 1. **Where?** The route, on one line, with the arrow that mirrors in
///    Arabic.
/// 2. **What state?** A pill with a word, an icon and a tone — never a bare
///    colour.
/// 3. **Who with, and for how much?** The counterparty and the agreed money,
///    labelled from *this* viewer's side: a sender sees what they pay, a
///    traveller sees what they earn. Same deal, two true sentences.
/// 4. **Does it need me?** An accent edge and an explicit line, only when the
///    server says the next move is this user's.
///
/// It is drawn as a boarding pass — notched sides, a dashed perforation
/// separating the route from the money — because that is the ShipTrip
/// vocabulary for "one journey, one document". The notch sits exactly on the
/// perforation, so the two read as the same tear line rather than as two
/// unrelated decorations.
library;

import 'package:flutter/material.dart';

import '../../core/money/money.dart';
import '../../design/components/money.dart';
import '../../design/components/route.dart';
import '../../design/components/status.dart';
import '../../design/identity.dart';
import '../../design/tokens.dart';
import '../../domain/deal.dart';
import '../../domain/money_perspective.dart';
import '../../l10n/app_localizations.dart';
import '../../design/typography.dart';
import 'formatters.dart';
import 'status_copy.dart';

/// Where the notch bites into the card's sides.
///
/// Tuned to land on the dashed perforation for a card of typical height. It
/// is a fraction rather than a pixel offset so it tracks the card as the
/// system font scale grows the rows above and below it.
const _notchAt = 0.58;

class DeliveryCard extends StatelessWidget {
  const DeliveryCard({
    required this.deal,
    required this.viewerId,
    required this.onTap,
    this.fromLabel,
    this.toLabel,
    this.counterpartyName,
    this.needsYou = false,
    this.needsYouLabel,
    super.key,
  });

  final Deal deal;
  final int viewerId;
  final VoidCallback onTap;

  /// Coarse place labels. Passed in rather than read off the deal because the
  /// deal projection does not carry the parcel's locations — the caller has
  /// them from the request or the match.
  final String? fromLabel;
  final String? toLabel;

  /// The other party's name. The Deal projection carries ids only, so a caller
  /// that has the Match passes it and a caller that does not omits the line
  /// rather than printing an id at a human.
  final String? counterpartyName;

  /// Server-derived. Never a guess made in this widget.
  final bool needsYou;
  final String? needsYouLabel;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    final perspective = deal.moneyPerspectiveFor(viewerId);
    final isSender = perspective == MoneyPerspective.sender;
    final status = dealStatusCopy(
      context,
      deal.status,
      viewerIsSender: isSender,
    );

    // Same deal, two true sentences. A sender's number is what leaves their
    // account; a traveller's is what arrives in theirs. Showing either party
    // the other's figure is a small lie that compounds.
    final Money? amount = perspective == null
        ? null
        : deal.terms?.totalFor(perspective);
    final amountLabel = isSender ? l.moneyYouPay : l.moneyYouReceive;

    return BoardingCard(
      onTap: onTap,
      accent: needsYou ? c.attention : null,
      notchAt: _notchAt,
      padding: const EdgeInsetsDirectional.all(AppSpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  (isSender ? l.deliveryCardSending : l.deliveryCardCarrying)
                      .toUpperCase(),
                  style: AppTypography.eyebrow(context, color: c.textTertiary),
                ),
              ),
              StatusPill(
                label: status.label,
                tone: status.tone,
                icon: status.icon,
                compact: true,
              ),
            ],
          ),
          const SizedBox(height: AppSpace.md),

          if (fromLabel != null && toLabel != null)
            RouteSummary(from: fromLabel!, to: toLabel!)
          else
            Text(
              l.deliveriesTitle,
              style: text.titleSmall,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
            ),

          const SizedBox(height: AppSpace.lg),
          // The tear line. Everything above it is the journey; everything
          // below is the agreement.
          const DashedDivider(),
          const SizedBox(height: AppSpace.lg),

          Row(
            children: [
              if (counterpartyName != null)
                Expanded(
                  child: Text(
                    l.deliveryCardWith(counterpartyName!),
                    style: text.bodySmall?.copyWith(color: c.textSecondary),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                )
              else
                const Spacer(),
              if (amount != null) ...[
                const SizedBox(width: AppSpace.md),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      amountLabel,
                      style: text.bodySmall?.copyWith(color: c.textSecondary),
                    ),
                    const SizedBox(height: AppSpace.xxs),
                    MoneyText(amount, semanticPrefix: amountLabel, size: 16),
                  ],
                ),
              ],
            ],
          ),

          if (needsYou && needsYouLabel != null) ...[
            const SizedBox(height: AppSpace.md),
            Row(
              children: [
                Icon(Icons.arrow_forward_rounded, size: 15, color: c.attention),
                const SizedBox(width: AppSpace.sm),
                Expanded(
                  child: Text(
                    needsYouLabel!,
                    style: text.labelMedium?.copyWith(color: c.attention),
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

/// A compact row for a journey, used on the traveller's home and in
/// Deliveries.
class JourneyCard extends StatelessWidget {
  const JourneyCard({
    required this.fromLabel,
    required this.toLabel,
    required this.status,
    required this.legCount,
    required this.onTap,
    this.departureLabel,
    this.capacityKg,
    this.legsNeedingProof = 0,
    super.key,
  });

  final String fromLabel;
  final String toLabel;
  final StatusCopy status;
  final int legCount;
  final VoidCallback onTap;
  final String? departureLabel;
  final double? capacityKg;

  /// Flight legs whose proof the server has not approved. A journey with any
  /// of these cannot go live, so it is the single most useful thing to say.
  final int legsNeedingProof;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return BoardingCard(
      onTap: onTap,
      accent: legsNeedingProof > 0 ? c.attention : null,
      notchAt: _notchAt,
      padding: const EdgeInsetsDirectional.all(AppSpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  l.journeyLegCount(legCount).toUpperCase(),
                  style: AppTypography.eyebrow(context, color: c.textTertiary),
                ),
              ),
              StatusPill(
                label: status.label,
                tone: status.tone,
                icon: status.icon,
                compact: true,
              ),
            ],
          ),
          const SizedBox(height: AppSpace.md),
          RouteSummary(from: fromLabel, to: toLabel),
          const SizedBox(height: AppSpace.lg),
          const DashedDivider(),
          const SizedBox(height: AppSpace.lg),
          Row(
            children: [
              if (departureLabel != null)
                Expanded(
                  child: Text(
                    departureLabel!,
                    style: text.bodySmall?.copyWith(color: c.textSecondary),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                )
              else
                const Spacer(),
              if (capacityKg != null)
                Text(
                  formatCapacity(context, capacityKg),
                  style: text.bodySmall?.copyWith(color: c.textSecondary),
                ),
            ],
          ),
          if (legsNeedingProof > 0) ...[
            const SizedBox(height: AppSpace.md),
            Row(
              children: [
                Icon(Icons.upload_file_rounded, size: 15, color: c.attention),
                const SizedBox(width: AppSpace.sm),
                Expanded(
                  child: Text(
                    l.journeyProofNeeded(legsNeedingProof),
                    style: text.labelMedium?.copyWith(color: c.attention),
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}
