/// L2B: every discovery screen, on every device the bottom-overlap suite
/// guards, in English and Arabic.
///
/// Two properties, both geometric. Nothing overflows (an overflow fails the
/// test on its own), and once a screen is scrolled to its end the last piece
/// of content sits above whatever occupies the bottom: the docked navigation
/// bar for the two tabs, the system gesture inset for a pushed screen.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/design/components/navigation.dart';
import 'package:shiptrip/design/layout/app_scaffold.dart';
import 'package:shiptrip/features/discovery/alerts_screen.dart';
import 'package:shiptrip/features/discovery/browse_screens.dart';
import 'package:shiptrip/features/discovery/person_screen.dart';
import 'package:shiptrip/features/discovery/public_profile_screen.dart';
import 'package:shiptrip/features/home/home_screen.dart';
import 'package:shiptrip/features/profile/profile_screen.dart';

import 'support/discovery_harness.dart';
import 'support/fake_api.dart';
import 'support/harness.dart';

/// The shell's docked bar around a tab, as the real shell lays it out.
class _Shell extends StatelessWidget {
  const _Shell({required this.child});

  final Widget child;

  @override
  Widget build(BuildContext context) => NavigationInsetScope(
    inset: AppNavigationBar.occupiedHeight(context),
    barIsVisible: true,
    child: Scaffold(
      body: child,
      bottomNavigationBar: AppNavigationBar(
        destinations: const [
          NavDestination(
            icon: Icons.home_outlined,
            selectedIcon: Icons.home_rounded,
            label: 'Home',
          ),
          NavDestination(
            icon: Icons.inventory_2_outlined,
            selectedIcon: Icons.inventory_2_rounded,
            label: 'Deliveries',
          ),
          NavDestination(
            icon: Icons.forum_outlined,
            selectedIcon: Icons.forum_rounded,
            label: 'Chat',
          ),
          NavDestination(
            icon: Icons.person_outline_rounded,
            selectedIcon: Icons.person_rounded,
            label: 'Profile',
          ),
        ],
        currentIndex: 0,
        onSelect: (_) {},
      ),
    ),
  );
}

/// A server with enough of everything that every screen scrolls.
FakeBackend _full() {
  final routes = [
    usualRouteFixture(),
    usualRouteFixture(from: 'Lyon', to: 'Oran'),
    usualRouteFixture(from: 'Lille', to: 'Setif'),
  ];
  return discoveryBackend()
    ..on(
      'GET',
      '/api/discovery/trips',
      discoveryPage([
        for (var i = 1; i <= 6; i++) tripCardFixture(i, name: 'Traveler $i'),
      ]),
    )
    ..on(
      'GET',
      '/api/discovery/requests',
      discoveryPage([
        for (var i = 1; i <= 6; i++)
          requestCardFixture(i, title: 'Parcel $i', sender: 'Sender $i'),
      ]),
    )
    ..on(
      'GET',
      '/api/discovery/people',
      discoveryPage([
        for (var i = 1; i <= 6; i++)
          profileCardFixture(id: 'p-$i', name: 'Person $i', routes: routes),
      ]),
    )
    ..on(
      'GET',
      '/api/discovery/matches',
      senderMatches([
        senderMatchGroup(5, [
          travelerCandidateFixture(101, name: 'Karim'),
          travelerCandidateFixture(102, name: 'Nadia'),
        ]),
        senderMatchGroup(6, [travelerCandidateFixture(103, name: 'Omar')]),
      ]),
    )
    ..on(
      'GET',
      '/api/discovery/profile/me',
      FakeResponse(200, ownProfileFixture(showPrompt: true, routes: routes)),
    )
    ..on(
      'GET',
      '/api/discovery/alerts',
      FakeResponse(200, {
        'results': [
          for (var i = 1; i <= 8; i++)
            alertFixture(i, watches: i.isEven ? 'requests' : 'trips'),
        ],
      }),
    )
    ..on(
      'GET',
      '/api/discovery/people/p-1',
      FakeResponse(200, {
        'state': 'results',
        'profile': profileCardFixture(name: 'Samira', routes: routes),
        'trips': [for (var i = 1; i <= 4; i++) tripCardFixture(i)],
        'requests': [for (var i = 1; i <= 4; i++) requestCardFixture(i)],
      }),
    );
}

typedef _Screen = ({String name, Widget Function() build, bool shell});

_Screen _screen(String name, Widget Function() build, {bool shell = false}) =>
    (name: name, build: build, shell: shell);

final _screens = <_Screen>[
  _screen('Home', () => const HomeScreen(), shell: true),
  _screen('Profile', () => const ProfileScreen(), shell: true),
  _screen('Browse trips', () => const BrowseTripsScreen()),
  _screen('Browse requests', () => const BrowseRequestsScreen()),
  _screen('People', () => const BrowsePeopleScreen()),
  _screen('Person', () => const PersonScreen(profileId: 'p-1')),
  _screen('Public profile', () => const PublicProfileScreen()),
  _screen('Route alerts', () => const AlertsScreen()),
];

/// The page's own scroll view: the outermost vertical one. A chip row or a
/// card carousel above it scrolls sideways and is not the page.
ScrollableState _page(WidgetTester tester) => tester
    .stateList<ScrollableState>(find.byType(Scrollable))
    .firstWhere((s) => s.position.axis == Axis.vertical);

/// Scrolls the page's own scroll view to its end in screen-sized steps, so
/// every lazy child is built on the way and the true length is known; a paged
/// list asks for more whenever the end comes near. Gives up after a bounded
/// number of steps, which a page this short never needs.
Future<void> _scrollToEnd(WidgetTester tester) async {
  final position = _page(tester).position;
  final step = position.viewportDimension * 0.8;
  var stable = 0;
  for (var i = 0; i < 80 && stable < 3; i++) {
    final before = position.pixels;
    position.jumpTo(
      (before + step).clamp(0, position.maxScrollExtent).toDouble(),
    );
    await tester.pumpAndSettle();
    stable = position.pixels == before ? stable + 1 : 0;
  }
}

/// The lowest edge of any text the scrolling content has built.
double _lowestText(WidgetTester tester) {
  var lowest = 0.0;
  final scrollable = find.byType(Scrollable).first;
  for (final element
      in find
          .descendant(of: scrollable, matching: find.byType(Text))
          .evaluate()) {
    final box = element.renderObject! as RenderBox;
    if (!box.attached || !box.hasSize) continue;
    final bottom = box.localToGlobal(Offset(0, box.size.height)).dy;
    if (bottom > lowest) lowest = bottom;
  }
  return lowest;
}

void main() {
  for (final locale in const [Locale('en'), Locale('ar')]) {
    group('layout in ${locale.languageCode}', () {
      for (final screen in _screens) {
        for (final device in DeviceProfile.all) {
          testWidgets('${screen.name} on ${device.name}', (tester) async {
            final widget = screen.shell
                ? _Shell(child: screen.build())
                : screen.build();
            await pumpDiscovery(
              tester,
              widget,
              _full(),
              locale: locale,
              device: device,
              role: RoleContext.sender,
            );

            await _scrollToEnd(tester);

            final floor = screen.shell
                ? tester.getTopLeft(find.byType(AppNavigationBar)).dy
                : device.size.height - device.viewPadding.bottom;
            expect(
              _lowestText(tester),
              lessThanOrEqualTo(floor + 0.5),
              reason: 'the last row must clear the bottom',
            );
          });
        }
      }
    });
  }
}
