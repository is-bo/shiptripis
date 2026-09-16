/// The optional preferred meeting point, stated as the optional thing it is.
///
/// This field exists because the product has two location questions that look
/// identical on a form and are not remotely the same:
///
/// * The **canonical place** decides whether a sender and a traveller can deal
///   with each other at all. It is required, and it is the only one matching
///   ever sees.
/// * The **preferred point** is a private operational preference — "the café by
///   the station rather than anywhere in town". It changes nothing about who
///   can be matched, and a sender who never sets one loses nothing.
///
/// A picker with a map behind it reads as mandatory unless the screen says
/// otherwise, so the field says otherwise three times over: it shows a
/// complete, valid answer ("Flexible within Jijel") before the user has done
/// anything, its label carries "Optional", and its footnote states outright
/// that matching runs on the place and not on the point.
///
/// It also owns the *undo*. A chosen point that can only be replaced and never
/// removed is a one-way door in a step that was advertised as optional.
library;

import 'package:flutter/material.dart';

import '../../design/components/primitives.dart';
import '../../design/tokens.dart';
import '../../design/typography.dart';
import '../../domain/canonical_place.dart';
import '../../domain/location.dart';
import '../../l10n/app_localizations.dart';

class PreferredPointField extends StatelessWidget {
  const PreferredPointField({
    required this.place,
    required this.point,
    required this.onChoose,
    required this.onRemove,
    this.enabled = true,
    super.key,
  });

  /// The canonical place the point must sit inside. Always known: this field
  /// is only rendered once a place has been chosen.
  final CanonicalPlace place;

  /// The point, if the user has set one. Null is a complete answer.
  final AppLocation? point;

  final VoidCallback onChoose;
  final VoidCallback onRemove;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final chosen = point;

    // The flexible state is a real value in primary ink, not grey placeholder
    // text. Placeholder styling would tell the eye "unanswered".
    final primary = chosen == null
        ? l.locationFlexibleWithin(place.name)
        : chosen.displayLabel;
    final secondary = chosen == null
        ? l.locationPreferredFlexibleHint
        : l.locationPrivacyBeforeFunding;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Flexible(
              child: Text(
                l.locationPreferredMeetingPoint,
                style: text.labelLarge,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            const SizedBox(width: AppSpace.sm),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
              decoration: BoxDecoration(
                color: c.surfaceSunken,
                borderRadius: AppRadius.rXs,
                border: Border.all(color: c.hairline),
              ),
              child: Text(
                l.locationPreferredOptional,
                style: AppTypography.eyebrow(context, color: c.textTertiary),
              ),
            ),
          ],
        ),
        const SizedBox(height: AppSpace.sm),
        AppCard(
          onTap: enabled ? onChoose : null,
          padding: const EdgeInsets.all(AppSpace.md),
          semanticLabel: '$primary. $secondary',
          child: Row(
            children: [
              Icon(
                chosen == null ? Icons.explore_outlined : Icons.place_outlined,
                size: 19,
                color: chosen == null ? c.textTertiary : c.brand,
              ),
              const SizedBox(width: AppSpace.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      primary,
                      style: text.bodyLarge,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: AppSpace.xxs),
                    Text(
                      secondary,
                      style: text.bodySmall?.copyWith(color: c.textSecondary),
                      maxLines: 2,
                    ),
                  ],
                ),
              ),
              const SizedBox(width: AppSpace.sm),
              if (chosen != null)
                AppIconButton(
                  icon: Icons.close_rounded,
                  label: l.locationRemovePreferredPoint,
                  onPressed: enabled ? onRemove : null,
                )
              else
                Icon(
                  Icons.chevron_right_rounded,
                  size: 20,
                  color: c.textTertiary,
                ),
            ],
          ),
        ),
        const SizedBox(height: AppSpace.sm),
        // The whole point of the field, in one sentence, under the field.
        Text(
          l.locationPreferredExplainer(place.name),
          style: text.bodySmall?.copyWith(color: c.textTertiary),
        ),
        const SizedBox(height: AppSpace.sm),
        Align(
          alignment: AlignmentDirectional.centerStart,
          child: AppButton(
            label: chosen == null
                ? l.locationAddPreferredPoint
                : l.locationChangePreferredPoint,
            icon: Icons.map_outlined,
            variant: AppButtonVariant.tertiary,
            expand: false,
            onPressed: enabled ? onChoose : null,
          ),
        ),
        const SizedBox(height: AppSpace.lg),
      ],
    );
  }
}
