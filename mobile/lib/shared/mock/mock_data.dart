class MockTraveler {
  final String name;
  final String avatar; // initials
  final String origin;
  final String dest;
  final String originCode; // DZ / FR
  final String destCode;
  final String date;
  final String flightNo;
  final int rating; // out of 50 (4.8 -> 48)
  final int trips;
  final int kgFree;
  final int pricePerKg; // DZD
  final bool kyc;

  const MockTraveler({
    required this.name,
    required this.avatar,
    required this.origin,
    required this.dest,
    required this.originCode,
    required this.destCode,
    required this.date,
    required this.flightNo,
    required this.rating,
    required this.trips,
    required this.kgFree,
    required this.pricePerKg,
    this.kyc = true,
  });
}

const mockTravelers = <MockTraveler>[
  MockTraveler(
    name: "Yacine M.",
    avatar: "YM",
    origin: "Algiers",
    dest: "Paris",
    originCode: "DZ",
    destCode: "FR",
    date: "May 04",
    flightNo: "AH 1004",
    rating: 49,
    trips: 23,
    kgFree: 8,
    pricePerKg: 1800,
  ),
  MockTraveler(
    name: "Lamia B.",
    avatar: "LB",
    origin: "Oran",
    dest: "Marseille",
    originCode: "DZ",
    destCode: "FR",
    date: "May 06",
    flightNo: "AF 1379",
    rating: 47,
    trips: 11,
    kgFree: 5,
    pricePerKg: 2100,
  ),
  MockTraveler(
    name: "Karim D.",
    avatar: "KD",
    origin: "Paris",
    dest: "Algiers",
    originCode: "FR",
    destCode: "DZ",
    date: "May 09",
    flightNo: "TU 712",
    rating: 50,
    trips: 41,
    kgFree: 12,
    pricePerKg: 1600,
  ),
  MockTraveler(
    name: "Soraya A.",
    avatar: "SA",
    origin: "Lyon",
    dest: "Constantine",
    originCode: "FR",
    destCode: "DZ",
    date: "May 12",
    flightNo: "AH 2056",
    rating: 48,
    trips: 7,
    kgFree: 6,
    pricePerKg: 1950,
  ),
];

class MockOffer {
  final String senderName;
  final String item;
  final int weightKg;
  final int proposedPrice;
  final String pickupCity;
  final String deliveryCity;
  final String when;
  final String status;

  const MockOffer({
    required this.senderName,
    required this.item,
    required this.weightKg,
    required this.proposedPrice,
    required this.pickupCity,
    required this.deliveryCity,
    required this.when,
    required this.status,
  });
}

const mockOffers = <MockOffer>[
  MockOffer(
    senderName: "Nadia H.",
    item: "Documents + small box",
    weightKg: 2,
    proposedPrice: 4500,
    pickupCity: "Algiers · Bab Ezzouar",
    deliveryCity: "Paris · 13e",
    when: "Before May 04",
    status: "New",
  ),
  MockOffer(
    senderName: "Mehdi T.",
    item: "Argan oil x4",
    weightKg: 3,
    proposedPrice: 6200,
    pickupCity: "Oran · Bir El Djir",
    deliveryCity: "Marseille",
    when: "Before May 06",
    status: "Counter",
  ),
  MockOffer(
    senderName: "Ines K.",
    item: "Wedding dress",
    weightKg: 4,
    proposedPrice: 9000,
    pickupCity: "Algiers · Hydra",
    deliveryCity: "Lyon",
    when: "May 09 – May 12",
    status: "New",
  ),
];

class MockTrip {
  final String origin;
  final String dest;
  final String originCode;
  final String destCode;
  final String date;
  final int booked;
  final int total;
  final String status;

  const MockTrip({
    required this.origin,
    required this.dest,
    required this.originCode,
    required this.destCode,
    required this.date,
    required this.booked,
    required this.total,
    required this.status,
  });
}

const mockMyTrips = <MockTrip>[
  MockTrip(
    origin: "Algiers",
    dest: "Paris",
    originCode: "DZ",
    destCode: "FR",
    date: "May 04, 2026",
    booked: 5,
    total: 10,
    status: "Approved",
  ),
];
