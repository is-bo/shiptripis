import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Knows whether a screen is still sliding in or out.
///
/// The router reports its new top route the moment a route is popped, while the
/// screen that was popped is still on the display for the length of its exit
/// animation. Anything that must wait for the person to be looking at the
/// *next* screen (the notification prompt, which would otherwise open over a
/// sign-in screen that is still leaving) waits for [settled] instead of
/// counting frames.
class RouteTransitionTracker extends NavigatorObserver {
  final Set<Route<dynamic>> _moving = {};
  Completer<void>? _idle;

  /// True when no route is animating in or out.
  bool get idle => _moving.isEmpty;

  /// Completes once every transition that is running has finished. Already
  /// complete when nothing is moving.
  Future<void> get settled =>
      idle ? Future<void>.value() : _idleCompleter.future;

  Completer<void> get _idleCompleter => _idle ??= Completer<void>();

  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) =>
      _track(route);

  @override
  void didPop(Route<dynamic> route, Route<dynamic>? previousRoute) =>
      _track(route);

  @override
  void didReplace({Route<dynamic>? newRoute, Route<dynamic>? oldRoute}) {
    if (oldRoute != null) _finish(oldRoute);
    if (newRoute != null) _track(newRoute);
  }

  @override
  void didRemove(Route<dynamic> route, Route<dynamic>? previousRoute) =>
      _finish(route);

  void _track(Route<dynamic> route) {
    final animation = route is TransitionRoute<dynamic>
        ? route.animation
        : null;
    if (animation == null || !_running(animation.status)) return;
    _moving.add(route);
    void onStatus(AnimationStatus status) {
      if (_running(status)) return;
      animation.removeStatusListener(onStatus);
      _finish(route);
    }

    animation.addStatusListener(onStatus);
  }

  static bool _running(AnimationStatus status) =>
      status == AnimationStatus.forward || status == AnimationStatus.reverse;

  void _finish(Route<dynamic> route) {
    if (!_moving.remove(route) || _moving.isNotEmpty) return;
    final idle = _idle;
    _idle = null;
    idle?.complete();
  }
}

final routeTransitionTrackerProvider = Provider<RouteTransitionTracker>(
  (ref) => RouteTransitionTracker(),
);
