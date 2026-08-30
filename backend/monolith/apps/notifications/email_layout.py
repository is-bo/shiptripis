"""The one place a transactional message becomes something a person reads.

Until now every outbound message was a list of lines. That was the right shape
while the outbox was being proven, and the wrong shape to send: a plain block of
text arriving from an unfamiliar address, carrying a six-character code and a
request to hand a parcel to a stranger, is indistinguishable from the phishing
mail this product's users get every week. Recognisable branding is not decoration
on a message like that — it is the only signal the recipient has.

So a message is now a small **document**: an eyebrow, one heading, some
paragraphs, at most one highlighted value, at most one callout, and a reference
line. `to_text` renders it as the plain-text body the transport has always
carried; `to_html` renders the same document as the HTML alternative. Both come
from the same object, so the two parts of a multipart message can never disagree
about what the message says.

Constraints this file works inside:

* **Email HTML, not web HTML.** Tables for layout, attributes for structure,
  inline styles for everything that matters. No flexbox, no grid, no external
  stylesheet, no web font, no image — including no logo image, because a
  blocked remote image is the normal case and a wordmark that disappears is
  worse than one set in type.
* **Narrow clients first.** One 600px column that collapses to full width, a
  16px floor on body text, and generous tap targets; the progressive-enhancement
  `<style>` block is allowed to be ignored entirely.
* **The delivery code changes nothing about secrecy.** This module renders a
  string it is handed. It is called from the same trusted renderer that opens
  the seal, it holds no reference to the sealed value, and it never logs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape

from django.utils.translation import gettext as _

# The app's light palette. Email clients cannot resolve custom properties, so
# the values are literals here — the one place in the codebase where that is
# true, and the reason they are named.
INK = "#0E1F2C"
INK_SOFT = "#2A3B49"
INK_MUTE = "#616C79"
PARCHMENT = "#F4EFE6"
PAPER = "#FAF6EE"
PAPER_LIFT = "#FFFCF5"
HAIRLINE = "#DCD4C6"
TERRACOTTA = "#C75E26"
TERRACOTTA_VIVID = "#E8763A"
TERRACOTTA_PRINT = "#9B4318"
TERRACOTTA_SOFT = "#FCEBE0"
SUN = "#FBBC04"
GOLD = "#C9A961"


@dataclass(frozen=True)
class EmailDocument:
    """One transactional message, independent of how it is rendered."""

    subject: str
    heading: str
    preheader: str = ""
    paragraphs: tuple[str, ...] = ()
    #: Small caps line above the heading. Says which part of the product this
    #: message is about, which is the first thing a reader triages on.
    eyebrow: str = ""
    #: The single value the message exists to deliver — a verification code, a
    #: delivery code, a payment reference. At most one per message: a mail with
    #: two "the important bit" boxes has none.
    highlight: tuple[str, str] | None = None
    #: The sentence the reader must not skip. Rendered as a bordered note.
    callout: str = ""
    #: (label, url) for the one thing the reader may need to open.
    action: tuple[str, str] | None = None
    #: Reference rows: delivery reference, payment reference, role, status.
    facts: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    #: Quiet closing line above the signature.
    footnote: str = ""


def _footer_lines(support_email: str = "") -> tuple[str, ...]:
    """The three closing lines, shared by both parts of the message.

    They are not decoration. The middle one is the anti-phishing rule this
    product's users are attacked with every week, and the last one is what
    identifies the message as transactional rather than marketing. The HTML
    part has always carried them; the plain-text part had neither, which made
    the part a text-only reader receives the one that said less.
    """

    return (
        (
            _("Questions? Reply to this email or write to %(support_email)s.")
            % {"support_email": support_email}
            if support_email
            else _("Questions? Reply to this email.")
        ),
        _(
            "ShipTrip will never ask you for a pickup or delivery code, and will "
            "never ask you to share one before the parcel is in your hands."
        ),
        _(
            "You are receiving this because of a delivery or account action on "
            "ShipTrip. This is a transactional message, not marketing."
        ),
    )


def _plain_machine_value(value: str, *, rtl: bool) -> str:
    """Keep references, numbers and URLs readable inside an RTL text part."""

    if not rtl or not value or (value.startswith("\u2066") and value.endswith("\u2069")):
        return value
    return f"\u2066{value}\u2069"


def to_text(
    doc: EmailDocument, *, support_email: str = "", language: str = "en"
) -> str:
    """Render the plain-text body. This is what the transport has always sent."""

    rtl = language == "ar"
    blocks: list[str] = [doc.heading]
    blocks.extend(p for p in doc.paragraphs if p)
    if doc.highlight:
        label, value = doc.highlight
        blocks.append(f"{label}: {_plain_machine_value(value, rtl=rtl)}")
    if doc.callout:
        blocks.append(doc.callout)
    if doc.action:
        label, url = doc.action
        blocks.append(
            f"{label}: {_plain_machine_value(url, rtl=rtl)}" if url else label
        )
    for label, value in doc.facts:
        if value:
            blocks.append(f"{label}: {_plain_machine_value(value, rtl=rtl)}")
    if doc.footnote:
        blocks.append(doc.footnote)
    blocks.append("--")
    blocks.extend(_footer_lines(_plain_machine_value(support_email, rtl=rtl)))
    return "\n\n".join(blocks) + "\n"


def _p(text: str, *, color: str = INK_SOFT, size: str = "16px", top: str = "0") -> str:
    return (
        f'<p style="margin:{top} 0 16px;padding:0;color:{color};font-size:{size};'
        f'line-height:26px;">{escape(text)}</p>'
    )


def _highlight_block(label: str, value: str, *, rtl: bool) -> str:
    """The one value the message carries, set so it can be read aloud.

    Monospaced, widely letter-spaced and large, because the realistic use of a
    handover code is one person reading it to another across a doorway.
    """

    label_style = (
        "letter-spacing:0;text-transform:none;"
        if rtl
        else "letter-spacing:2px;text-transform:uppercase;"
    )
    return f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
             style="margin:0 0 24px;border-collapse:separate;">
        <tr>
          <td align="center" bgcolor="{PAPER_LIFT}"
              style="padding:22px 16px;background-color:{PAPER_LIFT};
                     border:1px solid {HAIRLINE};border-radius:10px;">
            <p style="margin:0 0 10px;color:{INK_MUTE};font-size:12px;
                      {label_style}">{escape(label)}</p>
            <p class="st-code" dir="ltr" style="margin:0;color:{INK};font-size:30px;line-height:38px;
                      direction:ltr;unicode-bidi:embed;text-align:center;
                      letter-spacing:6px;font-weight:700;
                      font-family:'Courier New',Courier,monospace;">{escape(value)}</p>
          </td>
        </tr>
      </table>
    """


def _callout_block(text: str, *, rtl: bool) -> str:
    border = "border-right" if rtl else "border-left"
    return f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
             style="margin:0 0 24px;border-collapse:separate;">
        <tr>
          <td bgcolor="{TERRACOTTA_SOFT}"
              style="padding:16px 18px;background-color:{TERRACOTTA_SOFT};
                     {border}:4px solid {TERRACOTTA};border-radius:6px;
                     color:{TERRACOTTA_PRINT};font-size:15px;line-height:24px;">
            {escape(text)}
          </td>
        </tr>
      </table>
    """


def _action_block(label: str, url: str) -> str:
    """A bulletproof-ish button. Falls back to a plain link when it has to."""

    safe_url = escape(url, quote=True)
    return f"""
      <table role="presentation" cellpadding="0" cellspacing="0" border="0"
             style="margin:0 0 24px;border-collapse:separate;">
        <tr>
          <td bgcolor="{SUN}" style="background-color:{SUN};border-radius:26px;">
            <a href="{safe_url}"
               style="display:inline-block;padding:14px 28px;color:{INK};
                      font-size:16px;font-weight:700;text-decoration:none;
                      border-radius:26px;">{escape(label)}</a>
          </td>
        </tr>
      </table>
      <p dir="ltr" style="margin:-8px 0 24px;padding:0;color:{INK_MUTE};
                direction:ltr;unicode-bidi:embed;text-align:left;font-size:13px;
                line-height:20px;word-break:break-all;">{safe_url}</p>
    """


def _facts_block(facts: tuple[tuple[str, str], ...], *, rtl: bool) -> str:
    alignment = "right" if rtl else "left"
    label_padding = "6px 0 6px 16px" if rtl else "6px 16px 6px 0"
    rows = "".join(
        f"""
        <tr>
          <td align="{alignment}" width="1" style="width:1%;padding:{label_padding};color:{INK_MUTE};
                     font-size:13px;line-height:20px;white-space:nowrap;">{escape(label)}</td>
          <td align="{alignment}" dir="auto" style="padding:6px 0;color:{INK_SOFT};font-size:13px;line-height:20px;">
            {escape(value)}
          </td>
        </tr>
        """
        for label, value in facts
        if value
    )
    if not rows:
        return ""
    return f"""
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
             style="margin:0 0 8px;border-top:1px solid {HAIRLINE};padding-top:8px;">
        {rows}
      </table>
    """


def to_html(
    doc: EmailDocument,
    *,
    support_email: str = "",
    site_url: str = "",
    language: str = "en",
) -> str:
    """Render the HTML alternative of the same document."""

    rtl = language == "ar"
    direction = "rtl" if rtl else "ltr"
    alignment = "right" if rtl else "left"
    label_style = (
        "letter-spacing:0;text-transform:none;"
        if rtl
        else "letter-spacing:2px;text-transform:uppercase;"
    )
    preheader = doc.preheader or (doc.paragraphs[0] if doc.paragraphs else doc.heading)
    eyebrow = ""
    if doc.eyebrow:
        eyebrow = (
            f'<p style="margin:0 0 10px;padding:0;color:{TERRACOTTA_PRINT};font-size:12px;'
            f'font-weight:700;{label_style}">'
            f"{escape(doc.eyebrow)}</p>"
        )

    body_parts = [eyebrow]
    body_parts.append(
        f'<h1 class="st-h1" style="margin:0 0 18px;padding:0;color:{INK};font-size:26px;'
        f'line-height:33px;font-weight:700;'
        f"font-family:Georgia,'Times New Roman',Times,serif;\">{escape(doc.heading)}</h1>"
    )
    body_parts.extend(_p(text) for text in doc.paragraphs if text)
    if doc.highlight:
        body_parts.append(_highlight_block(*doc.highlight, rtl=rtl))
    if doc.callout:
        body_parts.append(_callout_block(doc.callout, rtl=rtl))
    if doc.action and doc.action[1]:
        body_parts.append(_action_block(*doc.action))
    elif doc.action:
        body_parts.append(_p(doc.action[0]))
    body_parts.append(_facts_block(doc.facts, rtl=rtl))
    if doc.footnote:
        body_parts.append(_p(doc.footnote, color=INK_MUTE, size="14px"))

    support_line = (
        _("Questions? Reply to this email or write to %(support_link)s.")
        % {"support_link": (
        f'<a href="mailto:{escape(support_email, quote=True)}" dir="ltr" '
        f'style="color:{TERRACOTTA_PRINT};direction:ltr;unicode-bidi:embed;">'
        f'{escape(support_email)}</a>'
        )}
        if support_email
        else _("Questions? Reply to this email.")
    )
    home_link = (
        f'<a href="{escape(site_url, quote=True)}" dir="ltr" style="color:{INK_MUTE};'
        f'text-decoration:underline;direction:ltr;unicode-bidi:embed;">ShipTrip</a>'
        if site_url
        else "ShipTrip"
    )

    transactional_line = _(
        "You are receiving this because of a delivery or account action on "
        "%(shiptrip)s. This is a transactional message, not marketing."
    ) % {"shiptrip": home_link}
    safety_line = _(
        "ShipTrip will never ask you for a pickup or delivery code, and will "
        "never ask you to share one before the parcel is in your hands."
    )

    return f"""<!doctype html>
<html lang="{escape(language, quote=True)}" dir="{direction}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{escape(doc.subject)}</title>
<style>
  /* Progressive enhancement only. Every rule below has a working default in
     the inline styles, so a client that strips this block loses nothing. */
  @media only screen and (max-width:620px) {{
    .st-shell {{ width:100% !important; }}
    .st-pad {{ padding-left:20px !important; padding-right:20px !important; }}
    .st-h1 {{ font-size:23px !important; line-height:30px !important; }}
    .st-code {{ font-size:26px !important; letter-spacing:4px !important; }}
  }}
</style>
</head>
<body dir="{direction}" style="margin:0;padding:0;background-color:{PARCHMENT};
             -webkit-text-size-adjust:100%;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;
            mso-hide:all;">{escape(preheader)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"
       bgcolor="{PARCHMENT}" style="background-color:{PARCHMENT};">
  <tr>
    <td align="center" style="padding:28px 12px;">
      <table role="presentation" class="st-shell" width="600" cellpadding="0"
             cellspacing="0" border="0"
             style="width:600px;max-width:600px;border-collapse:separate;">

        <!-- Masthead: a wordmark set in type, plus the airmail rule. No image,
             because a blocked image is the normal case. -->
        <tr>
          <td class="st-pad" align="{alignment}" style="padding:0 32px 14px;text-align:{alignment};">
            <span style="color:{INK};font-size:20px;font-weight:700;
                         letter-spacing:-0.3px;
                         font-family:Georgia,'Times New Roman',Times,serif;">ShipTrip</span>
            <span dir="auto" style="color:{INK_MUTE};font-size:12px;{label_style}">
              &nbsp;&nbsp;{escape(_("EU ↔ Algeria"))}</span>
          </td>
        </tr>
        <tr>
          <td style="padding:0;font-size:0;line-height:0;">
            <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
              <tr>
                <td height="4" bgcolor="{TERRACOTTA_VIVID}"
                    style="height:4px;background-color:{TERRACOTTA_VIVID};font-size:0;
                           line-height:0;">&nbsp;</td>
                <td height="4" bgcolor="{INK}"
                    style="height:4px;background-color:{INK};font-size:0;
                           line-height:0;">&nbsp;</td>
                <td height="4" bgcolor="{GOLD}"
                    style="height:4px;background-color:{GOLD};font-size:0;
                           line-height:0;">&nbsp;</td>
              </tr>
            </table>
          </td>
        </tr>

        <!-- The message itself -->
        <tr>
          <td class="st-pad" bgcolor="{PAPER}" align="{alignment}" dir="{direction}"
              style="padding:32px;background-color:{PAPER};
                     text-align:{alignment};direction:{direction};
                     border:1px solid {HAIRLINE};border-top:0;
                     border-radius:0 0 12px 12px;
                     font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
            {''.join(body_parts)}
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td class="st-pad" align="{alignment}" dir="{direction}" style="padding:22px 32px 8px;
                     text-align:{alignment};direction:{direction};
                     font-family:-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
            <p style="margin:0 0 8px;color:{INK_MUTE};font-size:13px;line-height:21px;">
              {support_line}
            </p>
            <p style="margin:0 0 8px;color:{INK_MUTE};font-size:13px;line-height:21px;">
              {escape(safety_line)}
            </p>
            <p style="margin:0;color:{INK_MUTE};font-size:12px;line-height:20px;">
              {transactional_line}
            </p>
          </td>
        </tr>

      </table>
    </td>
  </tr>
</table>
</body>
</html>
"""
