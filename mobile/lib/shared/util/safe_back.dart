import 'package:flutter/widgets.dart';
import 'package:go_router/go_router.dart';

// Use on every screen reachable via deep-link (notification tap, push from
// cold start, share link). When the router stack is empty, plain pop()
// quits the app because there's nothing under the current route — this
// routes back to the shell instead.
void safeBack(BuildContext context, {String fallback = '/app'}) {
  if (context.canPop()) {
    context.pop();
  } else {
    context.go(fallback);
  }
}
