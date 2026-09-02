# ShipTrip geography catalogue and V1 integration (Phases 8B–8C)

Phase 8B established the catalogue; Phase 8C integrates it into the active V1
Sender and Traveler flows. The locked selection flow is country → canonical
place → optional preferred exact meeting point. A preferred address/map pin is
user-owned private operational detail and never creates or changes a city
identity.

## Model

- `locations.Country` is an active ISO-3166 alpha-2 country with canonical and
  normalized name, source/source ID, source version and metadata.
- `locations.Place` is a stable selectable administrative region, locality /
  commune, or airport. Its database primary key is immutable; `(source,
  source_id)` is the importer natural key. It stores country, parent, canonical
  name, normalized name, optional reliable coordinates, active state, source
  version and airport identifiers (IATA/ICAO/type/passenger-use) when relevant.
- `locations.PlaceAlternateName` stores source-backed language variants only;
  the importer does not fabricate translations.
- `locations.AirportLocalityMapping` explicitly links an airport to a useful
  served locality. An airport's physical administrative context is represented
  by its parent/metadata. No mapping is inferred from a matching display name.
- `locations.Location` remains the optional preferred exact point. New V1
  points carry a protected `canonical_place` reference and are accepted only
  when the existing reverse-geocoding abstraction can confirm compatible
  country/locality context. Provider data is server-derived, not trusted from
  the client.

New `DeliveryRequest` rows reference canonical pickup/delivery `Place` records;
new `Journey` and ordered `JourneyLeg` rows reference the same catalogue. The
matching locality is derived authoritatively from those selected places rather
than duplicated: a locality resolves to itself, while an airport resolves
through its one active primary `SERVED` mapping. Stable indexed foreign keys and
prefetching keep this derivation cheap while avoiding a snapshot that could
drift from reviewed catalogue policy.

Legacy schema-2 delivery requests and schema-1 journeys retain their historic
`Location` references for bounded read/test compatibility. They are not
silently geocoded or inferred into municipalities. The active request and
Journey write APIs reject location-only payloads, and Location POST requires
`canonical_place`; every new record uses canonical Places, with `Location`
accepted only as optional scoped operational detail.

## Authoritative sources and observed 2026 coverage

The normalizer records these URLs and versions in the generated manifest:

- Algeria: the official [ONS Code géographique national 2021](https://www.ons.dz/IMG/pdf/code_geo_2021.pdf)
  supplies all 1,541 stable W/C commune identities. The normalizer then parses
  [JORADP Law 26-06, Journal Officiel 2026 F2026025](https://www.joradp.dz/FTP/jo-francais/2026/F2026025.pdf)
  and applies its current 69-wilaya hierarchy, including the ten amended
  mother-wilaya lists and new wilayas 59–69. Every ONS identity must reconcile
  exactly once and every affected legal list must match exactly. A current
  third-party JSON file contributes only coordinates, Arabic names, daïra
  hints and reviewed spelling reconciliations. Its five-digit `post_code` is
  retained as supplemental metadata, not claimed as an ONS CGN identifier.
- France: [INSEE COG 2026](https://www.insee.fr/fr/information/8740222),
  importing all 34,875 `TYPECOM=COM` communes plus region/department parents
  and preserving official commune codes.
- Spain: [INE municipality register (1 January 2026)](https://www.ine.es/dyngs/INEbase/es/operacion.htm?c=Estadistica_C&cid=1254736177031&idp=1254735976614&menu=ultiDatos),
  importing 8,132 municipalities, 52 provinces and 19
  autonomous-community parents. The five-digit province+municipality code and
  check digit are retained.
- Germany: [Destatis GV-ISys](https://www.destatis.de/DE/Themen/Laender-Regionen/Regionales/Gemeindeverzeichnis/_inhalt.html),
  30 June 2026 extract, importing 10,749 politically independent/statistically
  equivalent municipalities, 16 states and 401 district parents. The parser
  excludes 194 uninhabited municipality-free `Textkennzeichen=66` rows and
  retains the two inhabited `Textkennzeichen=65` rows. Eight-digit AGS is
  retained.
- Airports: [OurAirports data](https://ourairports.com/data/) filtered to
  large/medium/small airport records explicitly marked scheduled service. The
  observed extract yields 161 records: DZ 31, FR 49, ES 42 and DE 39. Closed
  airfields, heliports, seaplane/balloon/glider sites, unsupported types, and
  unscheduled military/private/general-aviation fields are excluded.

The verified manifest contains 56,134 places: 55,973 locality/admin rows plus
the 161 airports, and 3,833 source-backed alternate names. In exact terms it
contains DZ 69/1,541, FR 119/34,875, ES 71/8,132 and DE 417/10,749
admin/locality records. Every airport has a canonical admin parent established
through reviewed ISO-region crosswalks. Phase 8C produces 165 inspectable
mappings: exactly 161 active primary `SERVED` mappings (one for every selectable
airport) and four additional physical-locality mappings. The reviewed mapping
file seeds seven high-impact served-city policies (ALG, CDG, ORY, BCN, MAD, FRA
and MUC) plus the four physical contexts. Of the remaining 154 airports, 81 use
the maintained stable-OurAirports-ID source-context override table for
commercial semantics or ambiguous municipality nomenclature, and 73 resolve
uniquely from authoritative source municipality context. Airport display-name
parsing is never used as a fallback.

## Repeatable update process

`tools/geography/normalize_sources.py` performs an operator-triggered download
from a fixed host allow-list (or consumes locally reviewed source files) and
builds one normalized JSON manifest. The Django command
`manage.py import_geography --manifest <path>` imports it transactionally and
idempotently. Existing rows are updated by source identity, so renames preserve
internal IDs; additions are inserted; obsolete rows can be marked inactive
with `--deactivate-missing` and an explicit source list. Every row records the
source version. Bulk geography is not hard-coded in migrations. A reviewed
airport mapping file can be supplied as `airport_mappings` when available.
The source PDF parser dependency is isolated in
`tools/geography/requirements.txt`; source files and generated bulk manifests
are release artefacts, not migration payloads. Each input SHA-256 is written to
the manifest and volatile supplement digests are included in row versions.

The API is intentionally bounded:

- `GET /api/geography/countries` returns active countries.
- `GET /api/geography/places` returns 25 by default (caller maximum 100) with
  `country`, `q`, `place_type`, `parent`, `active`, `page` and `page_size`
  filters. Results include parent context, stable/source IDs, airport labels,
  the backend-owned matching locality and availability for matching. Unmapped
  airports are excluded from selectable airport searches.
- Parent context carries the parent's own tier as `parent_admin_level`
  alongside `parent_name` (and inside `matching_locality` / `served_locality`),
  taken verbatim from the reviewed source — `wilaya`, `region`, `department`,
  `autonomous_community`, `province`, `state`, `district`. It exists so a
  client can render "Jijel Wilaya" rather than stacking a commune under an
  identically named parent. A source that records no tier serves an empty
  string and a row with no parent serves `null`; a client must fall back to the
  bare parent name rather than inferring a tier from the country.

Search normalizes Unicode case and combining marks, treats hyphens/apostrophes
as separators, retains Arabic/French/Spanish/German letters, and searches both
canonical and source-backed alternate names. Indexed source identity,
country/type/parent/active and normalized-name columns support catalogue
filters. PostgreSQL adds partial `varchar_pattern_ops` indexes for active
canonical/alternate-name prefix search; a one-character query uses exact
indexed matching, while punctuation-only queries are rejected. Pagination
caps results at 100 and `select_related`/`prefetch_related` avoids N+1
serialization. This intentionally avoids a mandatory search extension.

## V1 matching and privacy

- Compatibility is equality of derived canonical matching-locality IDs. It
  never compares free-text city labels, preferred-point coordinates, radius,
  nearby municipalities or detour distance to establish basic compatibility.
- Different preferred pins inside the same canonical locality remain the same
  match. Different canonical locality IDs remain incompatible even when their
  coordinates are close.
- Airport/city interoperability exists only through an explicit active primary
  served mapping. CDG and ORY both resolve to canonical Paris under reviewed
  product policy; an airport does not become equivalent to every locality in
  its administrative region.
- Before funding, APIs expose only the safe canonical place/airport context.
  Exact labels, provider metadata and coordinates remain backend-protected and
  unlock only through existing Deal-state authorization.

## Limitations and review points

- OurAirports municipality and ISO-region fields are retained as hints; they
  are never used directly as matching identity. The normalizer resolves them
  against official catalogue records and rejects ambiguity. Its coverage gate
  requires the exact per-country selectable-airport counts and exactly one
  primary served mapping per airport; an unresolved airport must be made
  unavailable rather than guessed.
- Coordinates are source centroids/airport points and may be absent for some
  administrative rows. Exact user meeting points remain in `Location`.
- The published ONS CGN baseline predates Law 26-06. Phase 8B deliberately
  keeps its stable official W/C commune identities while storing the 2026
  JORADP parent assignment separately; a future ONS post-law CGN publication
  should be reviewed before replacing these source IDs. The importer rejects
  any missing/duplicate ONS identity or Law 26-06 membership mismatch.
- Source schemas and administrative changes are versioned yearly/quarterly;
  run the normalizer and focused data-quality tests before activating a new
  version. Any source change that breaks deterministic airport resolution must
  be reviewed before that airport can remain selectable.
