/// The one place the app asks what time it is for a countdown.
///
/// A provider rather than a bare `DateTime.now()` so a screen that counts
/// down can be tested at a chosen moment. Nothing decides anything from it:
/// the server owns every deadline, and a countdown only says how long is left
/// of the time the server already published.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';

final clockProvider = Provider<DateTime Function()>((ref) => DateTime.now);
