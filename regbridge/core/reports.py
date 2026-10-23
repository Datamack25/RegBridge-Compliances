"""Moteur de rapports unique : un même contexte produit un PDF, un Word, une image PNG ou JPEG.

Contexte attendu (dict) :
{
  "title": "Bulletin de veille",           # obligatoire
  "subtitle": "Période du ... au ...",
  "kpis": [("12", "textes"), ("3", "critiques")],
  "sections": [
      {"heading": "Synthèse", "paragraphs": ["..."], "bullets": ["..."],
       "table": {"columns": [...], "rows": [[...], ...]}},
  ],
  "sources": ["EUR-Lex ...", "..."],
  "free": False,                          # True = filigrane « Version gratuite »
  "author": "Nom de l'utilisateur",
}
Chaque livrable porte la date, une empreinte SHA-256 du contenu et un avertissement.
"""
import hashlib
import io
import json
from datetime import datetime

DISCLAIMER = ("Outil d'aide à la décision. Les informations doivent être vérifiées sur les sources officielles "
              "avant toute décision. Ce document n'est ni un avis juridique ni un avis fiscal.")
NAVY = "#0B2545"
TEAL = "#0E7C86"
LIGHT = "#EEF3F8"


def fingerprint(ctx: dict) -> str:
    payload = json.dumps({k: v for k, v in ctx.items() if k != "free"}, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def _stamp(ctx: dict) -> str:
    return f"Généré le {datetime.now().strftime('%d/%m/%Y %H:%M')} · empreinte {fingerprint(ctx)[:16]}"


def filename(ctx: dict, ext: str) -> str:
    base = "".join(ch if ch.isalnum() else "_" for ch in ctx["title"].lower())[:50].strip("_")
    return f"{base}_{datetime.now().strftime('%Y%m%d_%H%M')}.{ext}"


# ------------------------------------------------------------------ PDF
def to_pdf(ctx: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    wide = any(len(s.get("table", {}).get("columns", [])) > 6 for s in ctx.get("sections", []))
    size = landscape(A4) if wide else A4
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=size, leftMargin=40, rightMargin=40, topMargin=40, bottomMargin=50,
                            title=ctx["title"], author=ctx.get("author", ""))
    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=18, leading=22, textColor=colors.HexColor(NAVY))
    sub = ParagraphStyle("sub", fontName="Helvetica", fontSize=9.5, leading=13, textColor=colors.HexColor("#5B6770"))
    h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12, leading=16, textColor=colors.HexColor(TEAL),
                        spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("b", fontName="Helvetica", fontSize=9.5, leading=13.5, spaceAfter=4)
    cell = ParagraphStyle("c", fontName="Helvetica", fontSize=7.8, leading=9.5)
    head = ParagraphStyle("hd", parent=cell, fontName="Helvetica-Bold", textColor=colors.white)

    def esc(t):
        return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    story = [Paragraph(esc(ctx["title"]), h1)]
    if ctx.get("subtitle"):
        story += [Spacer(1, 4), Paragraph(esc(ctx["subtitle"]), sub)]
    if ctx.get("kpis"):
        data = [[Paragraph(f"<font size=15><b>{esc(v)}</b></font><br/><font size=7.5 color='#5B6770'>{esc(l)}</font>", body)
                 for v, l in ctx["kpis"]]]
        t = Table(data, colWidths=[(size[0] - 80) / len(data[0])] * len(data[0]))
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(LIGHT)),
                               ("LINEBEFORE", (0, 0), (-1, -1), 2.5, colors.HexColor(TEAL)),
                               ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        story += [Spacer(1, 10), t]
    for s in ctx.get("sections", []):
        if s.get("heading"):
            story.append(Paragraph(esc(s["heading"]), h2))
        for p in s.get("paragraphs", []):
            story.append(Paragraph(esc(p), body))
        for b in s.get("bullets", []):
            story.append(Paragraph(esc(b), body, bulletText="•"))
        for label, url in s.get("links", []):
            if url:
                story.append(Paragraph(f'<link href="{esc(url)}" color="{TEAL}"><u>{esc(label)}</u></link>'
                                       f' <font size=7.5 color="#5B6770">{esc(url)}</font>', body))
        tb = s.get("table")
        if tb and tb.get("rows"):
            cols = tb["columns"]
            data = [[Paragraph(esc(c), head) for c in cols]]
            for r in tb["rows"]:
                data.append([Paragraph(esc(v if v is not None else ""), cell) for v in r])
            t = Table(data, repeatRows=1, colWidths=[(size[0] - 80) / len(cols)] * len(cols))
            st = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NAVY)), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                  ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#D5DCE4"))]
            st += [("BACKGROUND", (0, i), (-1, i), colors.HexColor(LIGHT)) for i in range(2, len(data), 2)]
            t.setStyle(TableStyle(st))
            story += [Spacer(1, 4), t]
    if ctx.get("sources"):
        story.append(Paragraph("Sources", h2))
        for src in ctx["sources"]:
            story.append(Paragraph(esc(src), body, bulletText="•"))

    stamp, free = _stamp(ctx), ctx.get("free")

    def deco(c, d):
        c.saveState()
        c.setFont("Helvetica", 7)
        c.setFillColor(colors.HexColor("#5B6770"))
        c.drawString(40, 30, DISCLAIMER[:150])
        c.drawString(40, 20, stamp + (" · VERSION GRATUITE" if free else ""))
        c.drawRightString(size[0] - 40, 20, f"Page {d.page}")
        if free:
            c.setFont("Helvetica-Bold", 46)
            c.setFillColor(colors.Color(0.85, 0.2, 0.2, alpha=0.12))
            c.translate(size[0] / 2, size[1] / 2)
            c.rotate(35)
            c.drawCentredString(0, 0, "VERSION GRATUITE")
        c.restoreState()

    doc.build(story, onFirstPage=deco, onLaterPages=deco)
    return buf.getvalue()


# ------------------------------------------------------------------ Word
def _hyperlink(paragraph, url: str, text: str) -> None:
    """Lien cliquable dans un document Word (python-docx n'a pas de fonction dédiée)."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    r_id = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
    link = OxmlElement("w:hyperlink"); link.set(qn("r:id"), r_id)
    run = OxmlElement("w:r"); rpr = OxmlElement("w:rPr")
    color = OxmlElement("w:color"); color.set(qn("w:val"), "0E7C86")
    under = OxmlElement("w:u"); under.set(qn("w:val"), "single")
    rpr.append(color); rpr.append(under); run.append(rpr)
    t = OxmlElement("w:t"); t.text = text; run.append(t)
    link.append(run); paragraph._p.append(link)


def to_docx(ctx: dict) -> bytes:
    from docx import Document
    from docx.shared import Pt, RGBColor

    d = Document()
    st = d.styles["Normal"]
    st.font.name, st.font.size = "Calibri", Pt(10)
    d.add_heading(ctx["title"], level=0)
    if ctx.get("subtitle"):
        d.add_paragraph(ctx["subtitle"]).runs[0].font.color.rgb = RGBColor(0x5B, 0x67, 0x70)
    if ctx.get("free"):
        p = d.add_paragraph("VERSION GRATUITE")
        p.runs[0].bold = True
        p.runs[0].font.color.rgb = RGBColor(0xC0, 0x39, 0x2B)
    if ctx.get("kpis"):
        t = d.add_table(rows=2, cols=len(ctx["kpis"]))
        t.style = "Light Grid Accent 1"
        for i, (v, l) in enumerate(ctx["kpis"]):
            t.cell(0, i).text, t.cell(1, i).text = str(v), str(l)
    for s in ctx.get("sections", []):
        if s.get("heading"):
            d.add_heading(s["heading"], level=1)
        for p in s.get("paragraphs", []):
            d.add_paragraph(str(p))
        for b in s.get("bullets", []):
            d.add_paragraph(str(b), style="List Bullet")
        for label, url in s.get("links", []):
            if url:
                _hyperlink(d.add_paragraph(), url, f"{label} ↗")
        tb = s.get("table")
        if tb and tb.get("rows"):
            t = d.add_table(rows=1, cols=len(tb["columns"]))
            t.style = "Light Grid Accent 1"
            for i, c in enumerate(tb["columns"]):
                t.rows[0].cells[i].text = str(c)
            for r in tb["rows"]:
                cells = t.add_row().cells
                for i, v in enumerate(r):
                    cells[i].text = "" if v is None else str(v)
    if ctx.get("sources"):
        d.add_heading("Sources", level=1)
        for src in ctx["sources"]:
            d.add_paragraph(str(src), style="List Bullet")
    foot = d.sections[0].footer.paragraphs[0]
    foot.text = f"{DISCLAIMER} {_stamp(ctx)}"
    foot.runs[0].font.size = Pt(7)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ Image
def to_image(ctx: dict, fmt: str = "png") -> bytes:
    """Infographie partageable : titre, indicateurs, extrait du premier tableau."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig = plt.figure(figsize=(12, 6.75), dpi=110)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes([0, 0, 1, 1]); ax.axis("off")
    ax.add_patch(plt.Rectangle((0, 0.86), 1, 0.14, color=NAVY, transform=ax.transAxes))
    ax.text(0.03, 0.935, ctx["title"][:80], color="white", fontsize=20, weight="bold", va="center", transform=ax.transAxes)
    if ctx.get("subtitle"):
        ax.text(0.03, 0.885, ctx["subtitle"][:120], color="#CFE3E5", fontsize=10.5, va="center", transform=ax.transAxes)
    kpis = ctx.get("kpis", [])[:5]
    for i, (v, l) in enumerate(kpis):
        x = 0.03 + i * 0.19
        ax.add_patch(plt.Rectangle((x, 0.68), 0.175, 0.14, color=LIGHT, transform=ax.transAxes))
        ax.add_patch(plt.Rectangle((x, 0.68), 0.005, 0.14, color=TEAL, transform=ax.transAxes))
        ax.text(x + 0.015, 0.77, str(v), fontsize=19, weight="bold", color=NAVY, transform=ax.transAxes)
        ax.text(x + 0.015, 0.705, str(l)[:32], fontsize=9, color="#5B6770", transform=ax.transAxes)
    table = next((s["table"] for s in ctx.get("sections", []) if s.get("table", {}).get("rows")), None)
    if table:
        cols = table["columns"][:5]
        def cut(v, n=48):
            v = str(v if v is not None else "")
            return v if len(v) <= n else v[:n - 1] + "…"
        rows = [[cut(v) for v in r[:5]] for r in table["rows"][:9]]
        lens = [max([len(str(c))] + [len(r[i]) for r in rows]) for i, c in enumerate(cols)]
        widths = [max(6, l) / sum(max(6, x) for x in lens) for l in lens]
        tb = ax.table(cellText=rows, colLabels=cols, loc="center", cellLoc="left", colWidths=widths,
                      bbox=[0.03, 0.1, 0.94, 0.53] if kpis else [0.03, 0.1, 0.94, 0.72])
        tb.auto_set_font_size(False); tb.set_fontsize(8.5)
        for (r, c), cl in tb.get_celld().items():
            cl.set_edgecolor("#D5DCE4")
            if r == 0:
                cl.set_facecolor(NAVY); cl.get_text().set_color("white"); cl.get_text().set_weight("bold")
            elif r % 2 == 0:
                cl.set_facecolor(LIGHT)
    ax.text(0.03, 0.04, f"{_stamp(ctx)} · Aide à la décision, à vérifier sur les sources officielles",
            fontsize=8, color="#5B6770", transform=ax.transAxes)
    if ctx.get("free"):
        ax.text(0.5, 0.45, "VERSION GRATUITE", fontsize=60, color="#C0392B", alpha=0.13, rotation=25,
                ha="center", va="center", weight="bold", transform=ax.transAxes)
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    if fmt.lower() in ("jpg", "jpeg"):
        from PIL import Image
        im = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
        out = io.BytesIO(); im.save(out, format="JPEG", quality=88)
        return out.getvalue()
    return buf.getvalue()


def to_csv(ctx: dict) -> bytes:
    """Tableaux du contexte en CSV (UTF-8 avec BOM, point-virgule, lisible dans Excel)."""
    import csv
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    for s in ctx.get("sections", []):
        tb = s.get("table")
        if tb and tb.get("rows"):
            w.writerow(tb["columns"]); w.writerows(tb["rows"]); w.writerow([])
    return ("﻿" + out.getvalue()).encode("utf-8")


FORMATS = {
    "PDF": (to_pdf, "pdf", "application/pdf"),
    "Word": (to_docx, "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "Image PNG": (lambda c: to_image(c, "png"), "png", "image/png"),
    "Image JPEG": (lambda c: to_image(c, "jpeg"), "jpg", "image/jpeg"),
    "CSV": (to_csv, "csv", "text/csv"),
}
