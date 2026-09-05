"""Generate the bundled synthetic regulation PDFs for sample scenarios."""
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parents[1] / "sample-environment" / "scenarios"

SCENARIOS = {
    "merger-acquisition": {
        "primary": ("Merger Control Regulation 2025", "MCR 2025", [
            ("1. Purpose", "This Regulation establishes notification, diligence, and recordkeeping controls for acquisitions and combinations."),
            ("3. Notification threshold", "Transactions valued above SGD 50 million require pre-closing notification to the Authority."),
            ("5. Competition assessment", "Acquirers must complete competition due diligence before signing a binding transaction agreement."),
            ("8. Records", "Integration decision records must be retained for 7 years after completion."),
        ]),
        "amendment": ("Merger Control Amendment 2026", "MCR Amendment 2026", [
            ("1. Amendment", "Section 3 of the Merger Control Regulation 2025 is amended."),
            ("2. Revised threshold", "Transactions valued above SGD 25 million require pre-closing notification to the Authority."),
            ("3. Commencement", "This amendment applies to transactions signed on or after 1 January 2027."),
        ]),
    },
    "capital-markets": {
        "primary": ("Capital Markets Disclosure Rules 2025", "CMDR 2025", [
            ("1. Purpose", "These Rules promote timely and accurate disclosure by issuers and offering participants."),
            ("Rule 4.2 Material transactions", "Transactions above SGD 10 million must be disclosed to the market."),
            ("Rule 6.1 Prospectus verification", "Every prospectus statement must be supported by verification evidence."),
            ("Rule 9.3 Inside information", "Inside information must be restricted until public disclosure."),
        ]),
        "amendment": ("Capital Markets Disclosure Amendment 2026", "CMDR Amendment 2026", [
            ("1. Amendment", "Rule 4.2 of the Capital Markets Disclosure Rules 2025 is replaced."),
            ("2. Revised threshold", "Transactions above SGD 5 million must be disclosed to the market."),
            ("3. Commencement", "This amendment takes effect on 1 March 2027."),
        ]),
    },
    "energy-market": {
        "primary": ("Energy Market Reliability Code 2025", "EMRC 2025", [
            ("1. Purpose", "This Code sets reliability and operational duties for licensed energy market participants."),
            ("Clause 4.1 Operating reserve", "Licensed generators must maintain an operating reserve margin of 15 percent."),
            ("Clause 6.2 Dispatch", "Dispatch instructions must be acknowledged and logged immediately."),
            ("Clause 8.5 Incidents", "Material market incidents must be reported within 2 hours."),
        ]),
        "amendment": ("Energy Market Reliability Amendment 2026", "EMRC Amendment 2026", [
            ("1. Amendment", "Clause 4.1 of the Energy Market Reliability Code 2025 is replaced."),
            ("2. Revised reserve", "Licensed generators must maintain an operating reserve margin of 20 percent."),
            ("3. Commencement", "This amendment takes effect on 1 June 2027."),
        ]),
    },
    "carbon-credit": {
        "primary": ("Carbon Credit Integrity Standard 2025", "CCIS 2025", [
            ("1. Purpose", "This Standard protects the integrity, traceability, and retirement of carbon credits."),
            ("Standard 3.4 Retirement", "Credits used for a claim must be retired within 12 months of the claim date."),
            ("Standard 5.1 Verification", "Every credited project must pass independent verification."),
            ("Standard 7.2 Reconciliation", "Registry holdings must be reconciled monthly."),
        ]),
        "amendment": ("Carbon Credit Integrity Amendment 2026", "CCIS Amendment 2026", [
            ("1. Amendment", "Standard 3.4 of the Carbon Credit Integrity Standard 2025 is replaced."),
            ("2. Revised deadline", "Credits used for a claim must be retired within 6 months of the claim date."),
            ("3. Commencement", "This amendment takes effect on 1 July 2027."),
        ]),
    },
}


def footer(canvas, document):
    canvas.saveState()
    canvas.setStrokeColor(HexColor("#D7DBE0"))
    canvas.line(22 * mm, 17 * mm, 188 * mm, 17 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(HexColor("#667085"))
    canvas.drawString(22 * mm, 11 * mm, "Synthetic sample source - Ripple demonstration environment")
    canvas.drawRightString(188 * mm, 11 * mm, f"Page {document.page}")
    canvas.restoreState()


def create_pdf(path: Path, title: str, reference: str, sections: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("DocumentTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=22, leading=27, textColor=HexColor("#172B4D"), spaceAfter=8)
    ref_style = ParagraphStyle("Reference", parent=styles["Normal"], fontName="Helvetica", fontSize=10, textColor=HexColor("#667085"), spaceAfter=22)
    heading_style = ParagraphStyle("Section", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=16, textColor=HexColor("#172B4D"), spaceBefore=10, spaceAfter=6)
    body_style = ParagraphStyle("Body", parent=styles["BodyText"], fontName="Helvetica", fontSize=10.5, leading=17, textColor=HexColor("#344054"), spaceAfter=10)
    document = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=22 * mm, leftMargin=22 * mm, topMargin=25 * mm, bottomMargin=24 * mm, title=title, author="Ripple Sample Environment")
    story = [Paragraph(title, title_style), Paragraph(reference, ref_style), Spacer(1, 4 * mm)]
    for heading, body in sections:
        story.extend([Paragraph(heading, heading_style), Paragraph(body, body_style)])
    story.extend([Spacer(1, 12 * mm), Paragraph("Issued for demonstration and product evaluation only.", ref_style)])
    document.build(story, onFirstPage=footer, onLaterPages=footer)


for scenario_id, documents in SCENARIOS.items():
    for kind, (title, reference, sections) in documents.items():
        suffix = "Amendment 2026" if kind == "amendment" else "2025"
        base = title.removesuffix(f" {suffix}")
        create_pdf(ROOT / scenario_id / "regulations" / f"{base} {suffix}.pdf", title, reference, sections)
