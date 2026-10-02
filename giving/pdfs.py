"""
Renders a member's giving statement as an actual PDF file, for a real
download rather than relying on the browser's own "print to PDF" (see
giving/views.py's giving_statement, which still offers that print button
too - this is an additional, explicit "Download PDF" option). Built with
reportlab rather than an HTML-to-PDF converter (WeasyPrint, xhtml2pdf) -
reportlab installs cleanly on Windows with no extra system libraries
(no GTK/Cairo), which matters since this app is developed and run there.
"""

import io

from django.utils.dateformat import format as django_date_format
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def build_giving_statement_pdf(member, donations, start, end, total):
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
    elements = [
        Paragraph("Newlife AG (Assemblies of God)", styles["Title"]),
        Paragraph("Tema, Ghana", styles["Normal"]),
        Spacer(1, 0.25 * inch),
        Paragraph(f"Giving Statement for {member}", styles["Heading2"]),
    ]
    if member.email:
        elements.append(Paragraph(member.email, styles["Normal"]))
    # Uses Django's own dateformat.format (the same "F j, Y" format code
    # templates use, e.g. statement.html's {{ start|date:"M j, Y" }}) rather
    # than strftime's "%-d" no-leading-zero trick, which isn't portable to
    # Windows (this app is developed and run there).
    period = f"Statement period: {django_date_format(start, 'F j, Y')} - {django_date_format(end, 'F j, Y')}"
    elements.append(Paragraph(period, styles["Normal"]))
    elements.append(Spacer(1, 0.25 * inch))

    if donations:
        rows = [["Date", "Type", "Amount"]]
        for donation in donations:
            rows.append(
                [
                    django_date_format(donation.date, "M j, Y"),
                    donation.get_donation_type_display(),
                    f"GH₵{donation.amount:,.2f}",
                ]
            )
        rows.append(["", "Total", f"GH₵{total:,.2f}"])

        table = Table(rows, colWidths=[1.8 * inch, 3 * inch, 1.7 * inch])
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
        elements.append(Paragraph("No completed gifts recorded for this period.", styles["Normal"]))

    elements.append(Spacer(1, 0.35 * inch))
    elements.append(
        Paragraph(
            "This statement includes only gifts marked completed and confirmed by the church. "
            "Keep it for your own records.",
            styles["Normal"],
        )
    )

    doc.build(elements)
    return buffer.getvalue()
