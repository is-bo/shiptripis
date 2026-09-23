# Superseded K6 package L runs

These are the first package L runs (base `b5e1118`). Their traffic mix modelled
`GET /api/journeys/search` (browse and corridor) and `GET /api/parcels/open` as
app traffic. No Flutter screen calls either endpoint, and together they were
about 40 % of web server time, so every figure here overstates the cost of real
app traffic. `-ps20` runs sent 20-row pages to those two endpoints.

They are kept for reference only. The current runs, taken with the
screen-shaped mix, are one level up and are summarised in
[`../../capacity.md`](../../capacity.md).
