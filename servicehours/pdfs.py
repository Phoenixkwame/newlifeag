"""
Renders a volunteer's service-hour certificate as an actual PDF file - same
"a real downloadable file, not just a browser printout" approach as
giving/pdfs.py's build_giving_statement_pdf and members/pdfs.py's
build_membership_certificate_pdf, and built with the same library
(reportlab) for the same reason: it installs cleanly on Windows with no
extra system libraries (no GTK/Cairo), which matters since this app is
developed and run there.

A volunteer often needs this for something outside the church - school
community-service credit, a scholarship or job application recognizing
volunteer work - so it's phrased as a formal letter confirming the hours
served, with the underlying log itemized beneath it.
"""

import io

from django.utils.dateformat import format as django_date_format
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def build_service_hour_certificate_pdf(member, year, logs, total_hours):
    """Returns the rendered PDF as bytes."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()

    # :.2f throughout, same "always show 2 decimal places" convention as
    # service_hour_report.html's {{ total_hours|floatformat:2 }} and
    # giving/pdfs.py's GHS amounts - hours are a DecimalField, so this stays
    # consistent whether total_hours arrives as a Decimal or a plain number.
    body = (
        f"This is to certify that <b>{member}</b> volunteered a total of "
        f"<b>{total_hours:.2f} hour(s)</b> in service to Newlife AG (Assemblies of God), Tema, Ghana, "
        f"during {year}. This letter is issued at the volunteer's request and may be presented "
        f"to any organization requiring proof of volunteer service."
    )

    elements = [
        Paragraph("Newlife AG (Assemblies of God)", styles["Title"]),
        Paragraph("Tema, Ghana", styles["Normal"]),
        Spacer(1, 0.35 * inch),
        Paragraph("Certificate of Volunteer Service", styles["Heading1"]),
        Spacer(1, 0.25 * inch),
        Paragraph(body, styles["Normal"]),
        Spacer(1, 0.3 * inch),
    ]

    if logs:
        rows = [["Date", "Role", "Hours"]]
        for log in logs:
            rows.append(
                [
                    django_date_format(log.date, "M j, Y"),
                    log.role,
                    f"{log.hours:.2f}",
                ]
            )
        rows.append(["", "Total", f"{total_hours:.2f}"])

        table = Table(rows, colWidths=[1.8 * inch, 3.7 * inch, 1 * inch])
        table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("LINEBELOW", (0, 0), (-1, 0), 1, colors.grey),
                    ("LINEABOVE", (0, -1), (-1, -1), 1, colors.grey),
                    ("ALIGN", (2, 0), (2, -1), "RIGHT"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        elements.append(table)
    else:
        elements.append(Paragraph(f"No hours were logged for {year}.", styles["Normal"]))

    elements.append(Spacer(1, 0.5 * inch))
    elements.append(Paragraph("Sincerely,", styles["Normal"]))
    elements.append(Spacer(1, 0.4 * inch))
    elements.append(Paragraph("Church Office", styles["Normal"]))
    elements.append(Paragraph("Newlife AG (Assemblies of God), Tema", styles["Normal"]))

    doc.build(elements)
    return buffer.getvalue()
