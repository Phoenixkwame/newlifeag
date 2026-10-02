"""
Renders a membership certificate/letter as an actual PDF file - the same
"a real downloadable file, not just a browser printout" approach as
giving/pdfs.py's build_giving_statement_pdf, and built with the same
library (reportlab) for the same reason: it installs cleanly on Windows
with no extra system libraries (no GTK/Cairo), which matters since this
app is developed and run there.

A member often needs this for something outside the church entirely - a
visa or school application, a loan, a new job - so it's phrased as a
formal letter from the church confirming membership, not just a data dump.
"""

import io

from django.utils.dateformat import format as django_date_format
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer


def build_membership_certificate_pdf(member, issue_date):
    """Returns the rendered PDF as bytes."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
    )
    styles = getSampleStyleSheet()

    member_since = django_date_format(member.date_joined, "F j, Y")
    issued_on = django_date_format(issue_date, "F j, Y")
    campus_line = f" at our {member.campus} campus" if member.campus_id else ""

    body = (
        f"This is to certify that <b>{member}</b> is a member in good standing of Newlife AG "
        f"(Assemblies of God), Tema, Ghana, having joined the church on {member_since}"
        f"{campus_line}. This letter is issued at the member's request and may be presented "
        f"to any organization requiring proof of church membership."
    )

    elements = [
        Paragraph("Newlife AG (Assemblies of God)", styles["Title"]),
        Paragraph("Tema, Ghana", styles["Normal"]),
        Spacer(1, 0.5 * inch),
        Paragraph("Certificate of Membership", styles["Heading1"]),
        Spacer(1, 0.3 * inch),
        Paragraph(f"Date: {issued_on}", styles["Normal"]),
        Spacer(1, 0.3 * inch),
        Paragraph(body, styles["Normal"]),
        Spacer(1, 0.6 * inch),
        Paragraph("Sincerely,", styles["Normal"]),
        Spacer(1, 0.5 * inch),
        Paragraph("Church Office", styles["Normal"]),
        Paragraph("Newlife AG (Assemblies of God), Tema", styles["Normal"]),
    ]

    doc.build(elements)
    return buffer.getvalue()
