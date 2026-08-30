# Rendering the admin and the transactional email for review

Three scripts that put the operations admin and every transactional message in
front of a person. They exist because neither surface can be judged from source:
an admin queue is only legible against rows that are actually in the states it
is meant to surface, and an email is only legible rendered.

Everything here is **local review tooling**. Nothing imports it, CI does not run
it, and it writes only into `backend/monolith/build/`, which is git-ignored.

## Setup

From `backend/monolith/`, with a throwaway file-backed SQLite database:

```bash
python manage.py migrate --settings=config.settings.local_preview
```

`config/settings/local_preview.py` is `test_local` plus a file database and
unhashed static files, so `runserver` can serve the admin's CSS.

## Seed representative operational states

```bash
python manage.py shell --settings=config.settings.local_preview -c "exec(open('../../tools/preview/seed_admin_preview.py', encoding='utf-8').read())"
```

Every deal is driven through the real services rather than assembled by hand, so
what the admin renders is what the services actually produce. The finance models'
constraints refuse fabricated rows, and that is the point: a fixture that had to
bypass them would be showing a state the system cannot reach.

It produces a delivered deal past protection, a delivered deal with an open
dispute and frozen payout, a resolved dispute, an unfunded deal carrying a
failed attempt and an unapplied payment, a refund needing manual action, an
unverified provider event, three scheduled jobs in three states, pending and
rejected KYC, three flight proofs and a failed outbound email.

Set `REDIS_URL` to a closed port first — the outbox publishes after commit and
will otherwise wait on connection timeouts:

```bash
REDIS_URL=redis://127.0.0.1:6399/0 python manage.py shell --settings=config.settings.local_preview -c "..."
```

## Render the admin

```bash
python manage.py runserver 127.0.0.1:8199 --noreload --insecure --settings=config.settings.local_preview
python manage.py shell --settings=config.settings.local_preview -c "exec(open('../../tools/preview/dump_admin.py', encoding='utf-8').read())"
python -m http.server 4174 --directory build/adminshots
```

`dump_admin.py` authenticates with `force_login` rather than by posting the
login form — no credential is typed anywhere — and rewrites `/static/` to the
running dev server so the dumps carry the real stylesheet. It writes a charset
into each document, because the throwaway file server does not send one and
Django's admin relies on the response header.

## Render the email

```bash
python manage.py shell --settings=config.settings.local_preview -c "exec(open('../../tools/preview/render_emails.py', encoding='utf-8').read())"
python -m http.server 4175 --directory build/emailshots
```

One document per kind, HTML and plain text, plus an index. `resolve_secret` is
stubbed with a fixed sample string, so this script never touches real secret
material — including the delivery code, whose plaintext is opened only by the
outbox at send time. What is reviewed here is presentation; the secrecy
guarantee is held by the tests in `apps/notifications/tests/`.

## Screenshots

`tools/web/shot.sh <url> <out.png> [width] [height]` renders with headless Edge,
which on Windows will not lay out below ~492 CSS px. Phone widths have to be
reviewed in a browser that emulates the viewport properly.
