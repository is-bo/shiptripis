import os
from datetime import date
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle,
    PageBreak,
)
from reportlab.graphics.shapes import Drawing, Rect, String, Line, Polygon

OUT = r"C:\Users\islam\shiptrip\ShipTrip_Progress_Report.pdf"
PIC_DIR = r"C:\Users\islam\OneDrive\Pictures\ss"

INK = colors.HexColor("#2B2118")
INK_SOFT = colors.HexColor("#5A4A3C")
INK_MUTE = colors.HexColor("#8A7A6A")
EMERALD = colors.HexColor("#1F6E55")
TERRA = colors.HexColor("#B8593A")
GOLD = colors.HexColor("#C9962B")
PAPER = colors.HexColor("#FFFCF5")

styles = getSampleStyleSheet()

H1 = ParagraphStyle("H1", parent=styles["Heading1"],
    fontName="Times-Bold", fontSize=22, leading=26,
    textColor=INK, spaceAfter=4, spaceBefore=0)

H2 = ParagraphStyle("H2", parent=styles["Heading2"],
    fontName="Times-Bold", fontSize=13, leading=17,
    textColor=INK, spaceAfter=6, spaceBefore=10)

BODY = ParagraphStyle("Body", parent=styles["Normal"],
    fontName="Times-Roman", fontSize=10.5, leading=15,
    textColor=INK_SOFT, alignment=TA_JUSTIFY, spaceAfter=6)

CAP = ParagraphStyle("Cap", parent=styles["Normal"],
    fontName="Helvetica-Oblique", fontSize=8, leading=10,
    textColor=INK_MUTE, alignment=TA_CENTER, spaceAfter=0, spaceBefore=2)


def blank_page(c, doc):
    c.saveState()
    c.setFillColor(PAPER)
    c.rect(0, 0, A4[0], A4[1], stroke=0, fill=1)
    c.setFont("Helvetica", 8)
    c.setFillColor(INK_MUTE)
    c.drawCentredString(A4[0] / 2, 1.2*cm, "%d" % doc.page)
    c.restoreState()


def make_arch_diagram():
    d = Drawing(17*cm, 9*cm)
    d.add(Rect(0, 0, 17*cm, 9*cm, strokeColor=None, fillColor=PAPER))

    def block(x, y, w, h, label, sub, fill, stroke):
        d.add(Rect(x, y, w, h, strokeColor=stroke, fillColor=fill, strokeWidth=1.2))
        d.add(String(x + w/2, y + h - 14, label,
            fontName="Helvetica-Bold", fontSize=10, textAnchor="middle",
            fillColor=colors.white if fill in (EMERALD, TERRA) else INK))
        for i, line in enumerate(sub):
            d.add(String(x + w/2, y + h - 30 - i*11, line,
                fontName="Helvetica", fontSize=8, textAnchor="middle",
                fillColor=colors.white if fill in (EMERALD, TERRA) else INK_SOFT))

    def arrow(x1, y1, x2, y2):
        d.add(Line(x1, y1, x2, y2, strokeColor=INK_MUTE, strokeWidth=1))
        import math
        ang = math.atan2(y2 - y1, x2 - x1)
        ah = 5
        p1 = (x2, y2)
        p2 = (x2 - ah*math.cos(ang - 0.4), y2 - ah*math.sin(ang - 0.4))
        p3 = (x2 - ah*math.cos(ang + 0.4), y2 - ah*math.sin(ang + 0.4))
        d.add(Polygon([p1[0], p1[1], p2[0], p2[1], p3[0], p3[1]],
            strokeColor=INK_MUTE, fillColor=INK_MUTE))

    # Mobile - top center
    block(6.2*cm, 7*cm, 4.5*cm, 1.6*cm, "Mobile app",
          ["iOS + Android"],
          colors.HexColor("#F4EBD8"), GOLD)

    # Gateway - just below mobile
    block(6.2*cm, 4.5*cm, 4.5*cm, 1.6*cm, "Gateway",
          ["HTTPS + routing"],
          colors.HexColor("#F4EBD8"), GOLD)

    # Core service - left middle
    block(0.5*cm, 2*cm, 4.5*cm, 1.8*cm, "Core service",
          ["accounts, trips, parcels", "matching, payments",
           "wallet, handover codes"],
          EMERALD, EMERALD)

    # Live services - right middle
    block(11.9*cm, 2*cm, 4.5*cm, 1.8*cm, "Live services",
          ["notifications, chat", "identity, media"],
          TERRA, TERRA)

    # Database - bottom left
    block(0.5*cm, 0*cm, 4.5*cm, 1.3*cm, "Database",
          [],
          colors.HexColor("#EFE3CC"), INK_MUTE)

    # Realtime bus - bottom right
    block(11.9*cm, 0*cm, 4.5*cm, 1.3*cm, "Realtime bus",
          [],
          colors.HexColor("#EFE3CC"), INK_MUTE)

    # arrows
    # mobile <-> gateway
    arrow(8.45*cm, 7*cm, 8.45*cm, 6.1*cm)
    # gateway -> core (down-left)
    arrow(6.8*cm, 4.5*cm, 4.2*cm, 3.8*cm)
    # gateway -> live (down-right)
    arrow(10.1*cm, 4.5*cm, 12.7*cm, 3.8*cm)
    # core -> database
    arrow(2.75*cm, 2*cm, 2.75*cm, 1.3*cm)
    # live -> bus
    arrow(14.15*cm, 2*cm, 14.15*cm, 1.3*cm)
    # core -> bus (curved-ish via straight)
    arrow(5*cm, 2.6*cm, 11.9*cm, 0.65*cm)
    # live reads database (right -> left at bottom)
    arrow(11.9*cm, 2.3*cm, 5*cm, 0.65*cm)

    return d


def cover_block():
    flow = []
    flow.append(Spacer(1, 5*cm))
    flow.append(Paragraph("ShipTrip", H1))
    flow.append(Spacer(1, 4))
    sub = ParagraphStyle("sub", parent=BODY, fontSize=12, leading=15,
        fontName="Times-Italic", textColor=INK_SOFT, alignment=TA_LEFT)
    flow.append(Paragraph(
        "Peer-to-peer parcel delivery for travellers and senders in Algeria.",
        sub))
    flow.append(Spacer(1, 0.4*cm))
    flow.append(Paragraph(date.today().strftime("%B %Y"),
        ParagraphStyle("d", parent=BODY, fontSize=10, alignment=TA_LEFT,
            textColor=INK)))
    flow.append(PageBreak())
    return flow


def section_app():
    flow = []
    flow.append(Paragraph("The app", H2))
    flow.append(Paragraph(
        "ShipTrip puts two kinds of people in the same place: travellers "
        "who have spare room in their luggage on an upcoming trip, and "
        "senders who need a parcel carried along that same route. The "
        "sender posts what they need carried, the traveller posts the "
        "trip, and the two are matched. They agree on a price, the sender "
        "pays into a held wallet, and the money only reaches the traveller "
        "after the recipient confirms delivery with a short code.",
        BODY))
    flow.append(Paragraph(
        "Cheaper than a courier for the sender, a small income for the "
        "traveller, and the platform keeps the money in the middle until "
        "everyone is satisfied.",
        BODY))
    return flow


def section_architecture():
    flow = []
    flow.append(Paragraph("Architecture", H2))
    flow.append(Paragraph(
        "The mobile app reaches everything through a single gateway that "
        "handles HTTPS and routes each request to the right backend. Two "
        "backends sit behind it: a core service that owns accounts, money "
        "and the database, and a set of live services that handle "
        "long-lived things - chat, notifications, identity uploads and "
        "media. The two backends do not call each other directly; they "
        "share information through the database and a realtime bus, which "
        "means either can be restarted or scaled up without disturbing the "
        "other.",
        BODY))
    flow.append(Spacer(1, 6))
    flow.append(make_arch_diagram())
    return flow


def img(path, max_w, max_h):
    from PIL import Image as PILImage
    pi = PILImage.open(path)
    iw, ih = pi.size
    ratio = min(max_w / iw, max_h / ih)
    return Image(path, width=iw * ratio, height=ih * ratio)


def screenshot_pair(left_path, left_cap, right_path, right_cap):
    cell_w = 8.0*cm
    img_h = 10.5*cm
    li = img(os.path.join(PIC_DIR, left_path), cell_w - 1*cm, img_h)
    ri = img(os.path.join(PIC_DIR, right_path), cell_w - 1*cm, img_h)
    t = Table([
        [li, ri],
        [Paragraph(left_cap, CAP), Paragraph(right_cap, CAP)],
    ], colWidths=[cell_w, cell_w])
    t.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, 0), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def section_mobile():
    flow = []
    flow.append(Paragraph("The mobile app", H2))
    flow.append(Paragraph(
        "Built for iOS and Android, talking to a real backend. A few of "
        "the screens, captured from the live build:",
        BODY))
    flow.append(Spacer(1, 4))
    flow.append(screenshot_pair(
        "getstarted1.jpg", "Onboarding.",
        "getstarted2.jpg", "Onboarding."))
    flow.append(PageBreak())
    flow.append(screenshot_pair(
        "signup.jpg", "Sign-up.",
        "role.jpg", "Role selection."))
    flow.append(Spacer(1, 8))
    flow.append(screenshot_pair(
        "home_sender.jpg", "Sender home.",
        "findtraveler.jpg", "Find a traveller."))
    return flow


def section_done():
    flow = []
    flow.append(Paragraph("Done", H2))
    items = [
        "Accounts, sign-up and sign-in, with role selection (sender, traveller, or both).",
        "Trips: a traveller can publish a route with airports, dates and capacity.",
        "Parcels: a sender can describe a parcel or a product to be bought and delivered.",
        "Matching: trips and parcels find each other; offers are exchanged and accepted.",
        "Payments into a held wallet, with frozen pricing on each accepted offer.",
        "Handover codes: short numeric codes for pickup and delivery, hashed and rate-limited.",
        "Wallet release: the traveller is paid only when the delivery code is verified.",
        "Refunds that reverse the held amount cleanly.",
        "Mobile flows for all of the above, on iOS and Android.",
        "Notifications between the parties over a live connection.",
        "Identity submission on the mobile side.",
    ]
    for s in items:
        flow.append(Paragraph("&#8226; " + s, BODY))
    return flow


def section_missing():
    flow = []
    flow.append(Paragraph("Missing", H2))
    items = [
        ("Chat",
         "Sender and traveller can already coordinate by phone, but in-app "
         "chat is on the way."),
        ("Identity verification end-to-end",
         "The mobile capture and upload are done; the link between the "
         "upload service and the core record is the remaining piece."),
        ("Admin dashboard",
         "A back-office surface for moderation, identity review and "
         "general oversight."),
        ("Stripe",
         "A sandbox payment provider is in place today behind a single "
         "switch. Stripe slots into the same place."),
        ("Secure channel between backends",
         "The two backend layers authenticate with a shared token in "
         "development; production will use mutual certificates."),
    ]
    for h, b in items:
        flow.append(Paragraph("<b>" + h + ".</b> " + b, BODY))
    return flow


def section_strong_points():
    flow = []
    flow.append(Paragraph("Worth pointing out", H2))
    items = [
        ("Money is held, not paid.",
         "When a sender pays, the amount enters a wallet held against "
         "that specific deal. The traveller only receives it after the "
         "delivery code is verified. The same hold is reversed cleanly "
         "on a refund; the system cannot double-credit."),
        ("Private data stays private.",
         "Personal details and identity documents live in their own "
         "storage, encrypted at rest, and only the strict minimum ever "
         "comes back to the device. Identity images go straight to "
         "private storage; nothing transits a public URL."),
        ("Codes that age out quickly.",
         "The six-digit pickup and delivery codes are never stored in "
         "readable form. Five wrong attempts lock the code and a new "
         "one is issued."),
        ("Room to grow.",
         "The long-lived parts of the system - chat, notifications, "
         "identity uploads - run on a separate layer from the part that "
         "handles money, and can be scaled up on their own when traffic "
         "grows."),
    ]
    for h, b in items:
        flow.append(Paragraph("<b>" + h + "</b> " + b, BODY))
    return flow


def build():
    doc = SimpleDocTemplate(
        OUT, pagesize=A4,
        leftMargin=2.2*cm, rightMargin=2.2*cm,
        topMargin=2*cm, bottomMargin=2*cm,
        title="ShipTrip", author="ShipTrip")

    story = []
    story.extend(cover_block())
    story.extend(section_app())
    story.append(Spacer(1, 6))
    story.extend(section_architecture())
    story.append(PageBreak())
    story.extend(section_mobile())
    story.append(PageBreak())
    story.extend(section_done())
    story.append(Spacer(1, 10))
    story.extend(section_missing())
    story.append(PageBreak())
    story.extend(section_strong_points())

    doc.build(story, onFirstPage=blank_page, onLaterPages=blank_page)
    print("wrote " + OUT)


if __name__ == "__main__":
    build()
