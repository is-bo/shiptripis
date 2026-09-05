/// The economic side from which an authenticated party views marketplace money.
///
/// This is deliberately resolved from server-owned party ids, never from the
/// currently selected dashboard context. One account may be both a Sender and
/// a Traveler, while one Match or Deal gives that account exactly one side.
library;

enum MoneyPerspective {
  sender,
  traveler;

  static MoneyPerspective? resolve({
    required int viewerId,
    required int senderId,
    required int travelerId,
  }) {
    if (viewerId == senderId) return MoneyPerspective.sender;
    if (viewerId == travelerId) return MoneyPerspective.traveler;
    return null;
  }

  bool get isSender => this == MoneyPerspective.sender;
  bool get isTraveler => this == MoneyPerspective.traveler;
}
