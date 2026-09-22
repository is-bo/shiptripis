/// Decode sizing for photos drawn smaller than they were taken.
///
/// A decoded image costs width × height × 4 bytes whatever size it is painted
/// at, so a 2048 px upload shown in a 200 dp strip holds ~12 MB of pixels.
/// Passing the result to `cacheWidth` makes the codec decode at the drawn
/// width instead; the aspect ratio is kept, and nothing is ever upscaled.
///
/// Only the in-memory decode changes. No disk cache is involved, so private
/// images stay exactly as private as they were.
library;

import 'package:flutter/widgets.dart';

/// Physical pixels needed to draw [logicalWidth] sharply on this screen, or
/// null when the width is unbounded and the full image is the only answer.
int? decodeWidthFor(BuildContext context, double logicalWidth) =>
    decodeWidthForRatio(
      logicalWidth,
      MediaQuery.maybeDevicePixelRatioOf(context) ?? 1.0,
    );

/// [decodeWidthFor] with the pixel ratio given rather than looked up.
int? decodeWidthForRatio(double logicalWidth, double devicePixelRatio) {
  if (!logicalWidth.isFinite || logicalWidth <= 0) return null;
  return (logicalWidth * devicePixelRatio).ceil();
}
