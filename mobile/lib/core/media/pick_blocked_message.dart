import '../../l10n/app_localizations.dart';
import 'pick_guard.dart';

extension PickBlockedMessage on L {
  /// What the member is told when a pick was not allowed to go on: the picker
  /// could not be opened safely, or its answer could not be proven to be the
  /// photo they chose and was thrown away.
  String pickBlocked(PickBlockedException error) =>
      error.uncertain ? profilePhotoUncertain : photoPickBlocked;
}
