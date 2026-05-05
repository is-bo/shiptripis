class Airport {
  final String iata; // 3-letter
  final String city;
  final String name;
  final String country; // 'DZ' or 'FR'
  const Airport(this.iata, this.city, this.name, this.country);
}

const dzAirports = <Airport>[
  Airport('ALG', 'Algiers', 'Houari Boumediene', 'DZ'),
  Airport('ORN', 'Oran', 'Ahmed Ben Bella', 'DZ'),
  Airport('CZL', 'Constantine', 'Mohamed Boudiaf', 'DZ'),
  Airport('AAE', 'Annaba', 'Rabah Bitat', 'DZ'),
  Airport('TLM', 'Tlemcen', 'Zenata – Messali El Hadj', 'DZ'),
  Airport('BJA', 'Béjaïa', 'Soummam – Abane Ramdane', 'DZ'),
  Airport('TMR', 'Tamanrasset', 'Aguenar – Hadj Bey Akhamok', 'DZ'),
  Airport('HME', 'Hassi Messaoud', 'Oued Irara – Krim Belkacem', 'DZ'),
];

const frAirports = <Airport>[
  Airport('CDG', 'Paris', 'Charles de Gaulle', 'FR'),
  Airport('ORY', 'Paris', 'Orly', 'FR'),
  Airport('MRS', 'Marseille', 'Provence', 'FR'),
  Airport('LYS', 'Lyon', 'Saint-Exupéry', 'FR'),
  Airport('NCE', 'Nice', 'Côte d\'Azur', 'FR'),
  Airport('TLS', 'Toulouse', 'Blagnac', 'FR'),
  Airport('BOD', 'Bordeaux', 'Mérignac', 'FR'),
  Airport('NTE', 'Nantes', 'Atlantique', 'FR'),
  Airport('LIL', 'Lille', 'Lesquin', 'FR'),
  Airport('SXB', 'Strasbourg', 'Entzheim', 'FR'),
];

List<Airport> airportsByCountry(String code) =>
    code == 'DZ' ? dzAirports : frAirports;
