"""Build the Polish LPTM grant attachment from repository evidence.

Run: python docs/raport_grantowy/build_report.py
No audio devices, network access or cloud services are used by this script.
"""
from __future__ import annotations

import ast
import csv
from collections import Counter
from hashlib import sha256
from html import escape
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from reportlab.lib import colors
from reportlab.graphics import renderSVG
from reportlab.graphics.shapes import Drawing, Rect, String, Line, PolyLine, Polygon
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, Paragraph,
    Spacer, Table, TableStyle, Image, PageBreak, KeepTogether)
from reportlab.platypus.tableofcontents import TableOfContents

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ASSETS = HERE / "assets"
ASSETS.mkdir(exist_ok=True)
REPORT_DATE = "17.11.2026"
TITLE = "LPTM — Laser Polarisation Modulation Transciever"
PDF = HERE / "LPTM_dokumentacja_do_raportu_grantowego.pdf"
WIDTH = A4[0] - 94
NAVY = colors.HexColor("#102B46")
TEAL = colors.HexColor("#007F87")
INK = colors.HexColor("#243649")
MUTED = colors.HexColor("#617285")
LIGHT = colors.HexColor("#EFF5F8")
ORANGE = colors.HexColor("#BD6A16")
MD: list[str] = []


def register_fonts():
    windows = Path("C:/Windows/Fonts")
    linux = Path("/usr/share/fonts/truetype/dejavu")
    for name, win, fallback in (("Body", "calibri.ttf", "DejaVuSans.ttf"),
                                 ("BodyBold", "calibrib.ttf", "DejaVuSans-Bold.ttf"),
                                 ("Heading", "segoeuib.ttf", "DejaVuSans-Bold.ttf"),
                                 ("Mono", "consola.ttf", "DejaVuSansMono.ttf")):
        path = windows / win if (windows / win).exists() else linux / fallback
        if not path.exists():
            raise FileNotFoundError(f"Brak fontu z polskimi znakami: {path}")
        pdfmetrics.registerFont(TTFont(name, str(path)))
    pdfmetrics.registerFontFamily("Body", normal="Body", bold="BodyBold", italic="Body", boldItalic="BodyBold")


register_fonts()
ST = getSampleStyleSheet()
ST.add(ParagraphStyle("Text", fontName="Body", fontSize=10.4, leading=14.4,
                     textColor=INK, spaceAfter=8))
ST.add(ParagraphStyle("Section", fontName="Heading", fontSize=20, leading=24,
                     textColor=NAVY, spaceAfter=15, keepWithNext=True))
ST.add(ParagraphStyle("Sub", fontName="BodyBold", fontSize=11.3, leading=15,
                     textColor=NAVY, spaceBefore=10, spaceAfter=6, keepWithNext=True))
ST.add(ParagraphStyle("Kicker", fontName="BodyBold", fontSize=8.7, leading=12,
                     textColor=TEAL, spaceAfter=6, tracking=.8, keepWithNext=True))
ST.add(ParagraphStyle("Fine", fontName="Body", fontSize=8.1, leading=10.8,
                     textColor=MUTED, spaceAfter=6, splitLongWords=True))
ST.add(ParagraphStyle("Cell", fontName="Body", fontSize=9, leading=11.7, textColor=INK))
ST.add(ParagraphStyle("CellHead", parent=ST["Cell"], fontName="BodyBold", textColor=colors.white))
ST.add(ParagraphStyle("CodeLine", fontName="Mono", fontSize=8.5, leading=12,
                     textColor=INK, backColor=LIGHT, borderPadding=9, spaceBefore=5, spaceAfter=12))
ST.add(ParagraphStyle("CoverTitle", fontName="Heading", fontSize=58, leading=66,
                     textColor=colors.white, spaceAfter=16))
ST.add(ParagraphStyle("CoverSub", fontName="Body", fontSize=20, leading=27,
                     textColor=colors.white, spaceAfter=20))
ST.add(ParagraphStyle("CoverFine", fontName="Body", fontSize=11, leading=16,
                     textColor=colors.HexColor("#C7E4EC"), spaceAfter=12))


def plain(text):
    return re.sub(r"<[^>]+>", "", text).replace("&lt;", "<").replace("&gt;", ">")


def p(text, style="Text"):
    MD.append(plain(text) + "\n")
    return Paragraph(text, ST[style])


def sub(text):
    MD.append("### " + text + "\n")
    return Paragraph(text, ST["Sub"])


def note(title, text):
    MD.append(f"> **{title}** {plain(text)}\n")
    box = Table([[Paragraph(f"<b>{title}</b><br/>{text}", ST["Text"])]], colWidths=[WIDTH])
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("LINEBEFORE", (0, 0), (0, -1), 3, TEAL),
        ("LEFTPADDING", (0, 0), (-1, -1), 13), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    return KeepTogether([box, Spacer(1, 10)])


def table(headers, rows, widths=None, small=False):
    MD.append("| " + " | ".join(map(str, headers)) + " |")
    MD.append("| " + " | ".join(["---"] * len(headers)) + " |")
    MD.extend("| " + " | ".join(plain(str(x)) for x in row) + " |" for row in rows)
    MD.append("")
    cell = ST["Fine"] if small else ST["Cell"]
    data = [[Paragraph(escape(str(x)), ST["CellHead"]) for x in headers]]
    data += [[Paragraph(str(x), cell) for x in row] for row in rows]
    widths = widths or [WIDTH / len(headers)] * len(headers)
    result = Table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    result.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LINEBELOW", (0, -1), (-1, -1), .5, colors.HexColor("#D2DFE7"))]))
    return result


def code(text):
    MD.append("```text\n" + text + "\n```\n")
    return Paragraph(escape(text).replace("\n", "<br/>"), ST["CodeLine"])


def source(text):
    return p("Źródło: " + text, "Fine")


def section(number, title, kicker):
    MD.append(f"\n## {number}. {title}\n")
    return [PageBreak(), Paragraph(kicker.upper(), ST["Kicker"]),
            Paragraph(f"{number:02d} / {title}", ST["Section"])]


def box(drawing, x, y, w, h, title, lines=(), fill=LIGHT, border=TEAL):
    drawing.add(Rect(x, y, w, h, rx=7, ry=7, fillColor=fill, strokeColor=border, strokeWidth=.8))
    drawing.add(String(x + 10, y + h - 20, title, fontName="BodyBold", fontSize=10, fillColor=NAVY))
    current = y + h - 37
    for line in lines:
        for segment in textwrap.wrap(line, max(14, int((w - 20) / 4.8))):
            drawing.add(String(x + 10, current, segment, fontName="Body", fontSize=8.8, fillColor=INK))
            current -= 12


def arrow(drawing, x1, y1, x2, y2, color=TEAL, dashed=False):
    drawing.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=1.6, strokeDashArray=[4, 3] if dashed else None))
    drawing.add(Polygon([x2, y2, x2 - 6, y2 + 3, x2 - 6, y2 - 3], fillColor=color, strokeColor=color))


def diagram(name, drawing, caption):
    renderSVG.drawToFile(drawing, str(ASSETS / f"{name}.svg"))
    MD.append(f"![{caption}](assets/{name}.svg)\n")
    return [drawing, p(caption, "Fine")]


def architecture():
    d = Drawing(WIDTH, 216)
    box(d, 0, 115, 108, 88, "PC: nadajnik", ["Tekst / plik", "Ramkowanie, modulacja"])
    box(d, 131, 115, 103, 88, "Wyjście PCM", ["float32, mono", "Karta audio / DAC"])
    box(d, 258, 115, 107, 88, "Tor zewnętrzny", ["Kanał fizyczny", "Ocena zależna od stanowiska"])
    box(d, 389, 115, WIDTH - 389, 88, "PC: odbiornik", ["ADC / PCM", "Dekodowanie i zapis"])
    for x1, x2 in [(108, 131), (234, 258), (365, 389)]:
        arrow(d, x1, 157, x2, 157)
    arrow(d, 55, 78, WIDTH - 55, 78, color=ORANGE, dashed=True)
    d.add(String(65, 57, "Oddzielny kanał lokalny: wzorzec BER i sterowanie pomiarem", fontName="Body", fontSize=9, fillColor=INK))
    d.add(String(65, 40, "127.0.0.1 — dotyczy aplikacji na tym samym komputerze", fontName="Body", fontSize=8.5, fillColor=MUTED))
    return d


def interface():
    d = Drawing(WIDTH, 276)
    box(d, 0, 235, WIDTH, 38, "Wspólny pasek: wejście, wyjście, start / stop, automatyczne ustawienia")
    box(d, 0, 102, 244, 123, "CZAT", ["Historia obu kierunków", "Odbiór znaków w trakcie transmisji", "Pole odpowiedzi; Ctrl+Enter", "Poziom sygnału; przerwanie nadawania"])
    box(d, 0, 10, 244, 82, "PLIKI", ["Wybór JPG / dowolnego pliku", "Postęp, czas, folder docelowy", "Automatyczny zapis, otwarcie folderu"])
    box(d, 255, 112, WIDTH - 255, 113, "OSCYLOSKOP", ["Stała skala ±1 V (założenie)", "Okno 5–100 ms; siatka czasu", "Wzmocnienie wyświetlania"])
    box(d, 255, 10, WIDTH - 255, 92, "USTAWIENIA I NARZĘDZIA", ["2FSK / 4FSK / 16QAM", "Bitrate, częstotliwości, ASCII / UTF-8", "WAV, generator, pomiary CSV"])
    return d


def frame_diagram():
    d = Drawing(WIDTH, 89)
    labels = [("Preambuła", "32 b", 64), ("SYNC", "32 b", 55), ("Próba BER", "128 b", 80),
              ("ID", "64 b", 53), ("Długość", "16 b", 61), ("Dane", "8N b", 121), ("CRC", "16 b", WIDTH - 434)]
    x = 0
    for index, (label, bits, width) in enumerate(labels):
        fill = TEAL if index == 5 else NAVY
        d.add(Rect(x, 25, width - 2, 48, fillColor=fill, strokeColor=None))
        d.add(String(x + 6, 54, label, fontName="BodyBold", fontSize=8.3, fillColor=colors.white))
        d.add(String(x + 6, 37, bits, fontName="Body", fontSize=9, fillColor=colors.white))
        x += width
    d.add(String(0, 8, "Pola pokazano schematycznie; ich szerokość na rysunku nie jest proporcjonalna do liczby bitów.",
                 fontName="Body", fontSize=8, fillColor=MUTED))
    return d


def transfer_diagram():
    d = Drawing(WIDTH, 217)
    box(d, 0, 123, 139, 83, "1. Nagłówek H", ["Nazwa, rozmiar", "SHA-256, blok = 1024 B"])
    box(d, 169, 123, 146, 83, "2. Bloki D", ["Numer i oryginalne bajty", "1–3 kopie; kontrola CRC"])
    box(d, 345, 123, WIDTH - 345, 83, "3. Zapis .part", ["Pozycja wynika z numeru", "Duplikaty pomijane"])
    arrow(d, 139, 163, 169, 163)
    arrow(d, 315, 163, 345, 163)
    box(d, 0, 12, 234, 85, "Brakujące bloki", ["Późniejsza kopia może uzupełnić lukę.", "Marker E nie wymusza zamknięcia pliku."], border=ORANGE)
    box(d, 264, 12, WIDTH - 264, 85, "Komplet i zgodny SHA-256", ["Zamknięcie .part i docelowa nazwa", "Zapis automatyczny; marker E zbędny"])
    arrow(d, 234, 53, 264, 53)
    return d


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def evidence():
    stems = ["ber_1x", "ber_128B_1x"] + [f"ber_128B_pomiar_{i}_80procent" for i in range(1, 7)]
    result = {}
    for stem in stems:
        rows = read_csv(ROOT / "measurements" / f"{stem}_raw.csv")
        comparable = [r for r in rows if r["compared_bits"] and int(r["compared_bits"]) > 0]
        bits = sum(int(r["compared_bits"]) for r in comparable)
        errors = sum(int(r["bit_errors"]) for r in comparable)
        result[stem] = {"rows": rows, "count": len(rows), "status": dict(Counter(r["status"] for r in rows)),
            "recognized": sum(r["status"] != "no_frame" for r in rows),
            "crc_ok": sum(r["crc_ok"] == "1" for r in rows),
            "zero_ber": sum(float(r["ber_percent"]) == 0 for r in comparable),
            "errors": errors, "bits": bits, "pooled_ber": 100 * errors / bits if bits else None,
            "score_mean": sum(100 if r["status"] == "no_frame" else float(r["ber_percent"]) for r in rows) / len(rows),
            "metadata": json.loads((ROOT / "measurements" / f"{stem}_metadata.json").read_text(encoding="utf-8"))}
    tests = json.loads((HERE / "testy_weryfikacja.json").read_text(encoding="utf-8"))
    counts = {}
    for path in sorted((ROOT / "tests").glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        counts[path.name] = sum(isinstance(node, ast.FunctionDef) and node.name.startswith("test_") for node in ast.walk(tree))
    selected = list(ROOT.glob("*.py")) + list((ROOT / "tests").glob("test_*.py"))
    selected += [ROOT / "README.md", ROOT / "requirements.txt", ROOT / "build_windows.bat", ROOT / "build_macos.sh"]
    for stem in stems:
        selected += [ROOT / "measurements" / f"{stem}_raw.csv", ROOT / "measurements" / f"{stem}_metadata.json"]
    update = json.loads((HERE / "wyniki_przedwzmacniacz.json").read_text(encoding="utf-8"))
    selected += [HERE / "wyniki_przedwzmacniacz.json"]
    transmission = []
    from PIL import Image as PILImage
    for path in sorted((ROOT / "TRANSMISJA").iterdir()):
        if not path.is_file():
            continue
        selected.append(path)
        if path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        original = ROOT / path.name
        with PILImage.open(path) as photo:
            width, height = photo.size
        digest = sha256(path.read_bytes()).hexdigest()
        source_hash = sha256(original.read_bytes()).hexdigest() if original.is_file() else None
        if original.is_file():
            selected.append(original)
        destination = ASSETS / ("transmisja_karmelini.jpg" if path.stem == "karmelini" else "transmisja_bez_tytulu.jpg")
        shutil.copy2(path, destination)
        transmission.append({"plik": path.name, "bajty": path.stat().st_size, "szerokosc": width,
            "wysokosc": height, "sha256_odebranego": digest, "sha256_zrodlowego": source_hash,
            "identyczne_bajty": source_hash == digest if source_hash is not None else None,
            "reprodukcja": str(destination.relative_to(HERE)).replace("\\", "/")})
    attachments = HERE / "zalaczniki"
    attachments.mkdir(exist_ok=True)
    log = ROOT / "TRANSMISJA" / "zapisTransmisji16_11.txt"
    if log.is_file():
        shutil.copy2(log, attachments / log.name)
    update["weryfikacja_odebranych_obrazow"] = transmission
    (HERE / "weryfikacja_TRANSMISJA.json").write_text(json.dumps(update, ensure_ascii=False, indent=2), encoding="utf-8")
    inventory = [{"plik": str(path.relative_to(ROOT)).replace("\\", "/"), "bajty": path.stat().st_size,
                  "sha256": sha256(path.read_bytes()).hexdigest()} for path in sorted(selected)]
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    summary = {"data_dokumentu": REPORT_DATE, "commit": commit, "python": platform.python_version(),
               "testy": tests, "liczebnosc_testow_w_plikach": counts,
               "serie": {key: {k: v for k, v in value.items() if k != "rows"} for key, value in result.items()},
               "uzupelnienie_stanowiskowe": update, "zrodla": inventory}
    (HERE / "dane_i_proweniencja.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (HERE / "zestawienie_serii.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["seria", "nadania", "rozpoznane", "crc_ok", "brak_ramki", "BER_wazony_odebranych_pct", "umowna_srednia_ocena_pct"])
        for key, value in result.items():
            writer.writerow([key, value["count"], value["recognized"], value["crc_ok"], value["status"].get("no_frame", 0),
                             value["pooled_ber"], value["score_mean"]])
    return result, tests, counts, commit


def plots(data):
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
        "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#BAC8D2",
        "axes.labelcolor": "#243649", "xtick.color": "#43566A", "ytick.color": "#43566A",
        "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white"})
    palette = {"ok": "#008D8C", "bad_crc": "#E9AF50", "id_mismatch": "#AA6470", "no_frame": "#D5DEE5"}
    fig, ax = plt.subplots(figsize=(8.1, 3.0), layout="constrained")
    for y, stem in enumerate(["ber_1x", "ber_128B_1x"]):
        left = 0
        for status in palette:
            count = data[stem]["status"].get(status, 0)
            ax.barh(y, count, left=left, color=palette[status], height=.52)
            if count:
                ax.text(left + count / 2, y, str(count), ha="center", va="center",
                        color="white" if status in ("ok", "id_mismatch") else "#243649", fontweight="bold")
            left += count
    ax.set_yticks([0, 1], ["41 B / 50 nadań", "128 B / 50 nadań"])
    ax.invert_yaxis()
    ax.set_xlim(0, 50)
    ax.set_xlabel("Liczba transmisji w archiwalnej serii")
    fig.suptitle("Kanał słabej jakości — dane archiwalne", fontsize=11, color="#9A5716", fontweight="bold")
    ax.legend(handles=[Patch(color=palette[s], label=s) for s in palette], ncol=4, loc="upper center", bbox_to_anchor=(.5, 1.18), frameon=False)
    fig.savefig(ASSETS / "statusy_serii.png", dpi=220)
    fig.savefig(ASSETS / "statusy_serii.pdf")
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.1, 4.2), layout="constrained")
    ax.set_title("Kanał słabej jakości — serie historyczne", fontsize=11, color="#9A5716", fontweight="bold", pad=14)
    for y, stem in enumerate([f"ber_128B_pomiar_{i}_80procent" for i in range(1, 7)]):
        for x, row in enumerate(data[stem]["rows"]):
            ax.add_patch(plt.Rectangle((x, y), 1, 1, facecolor=palette[row["status"]], edgecolor="white", linewidth=2))
            text = "brak" if row["status"] == "no_frame" else f"{float(row['ber_percent']):.3f}".rstrip("0").rstrip(".")
            ax.text(x + .5, y + .5, text, ha="center", va="center", fontsize=9,
                    color="white" if row["status"] in ("ok", "id_mismatch") else "#243649")
    rows = data["ber_128B_pomiar_1_80procent"]["rows"]
    ax.set_xticks([i + .5 for i in range(9)], [f"{r['bit_0_hz']}/{r['bit_1_hz']}\n{r['speed_bps']} b/s" for r in rows], fontsize=7.2)
    ax.set_yticks([i + .5 for i in range(6)], [f"Seria {i}" for i in range(1, 7)])
    ax.set_xlim(0, 9)
    ax.set_ylim(6, 0)
    ax.tick_params(length=0)
    ax.set_xlabel("Częstotliwości 0/1 [Hz] i bitrate; liczby w polach: BER danych [%]", labelpad=12)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.savefig(ASSETS / "serie_80procent.png", dpi=220)
    fig.savefig(ASSETS / "serie_80procent.pdf")
    plt.close(fig)


class Report(BaseDocTemplate):
    def __init__(self, path):
        super().__init__(str(path), pagesize=A4, leftMargin=47, rightMargin=47,
                         topMargin=54, bottomMargin=43, title=TITLE,
                         author="Dokumentacja projektu LPTM", subject="Załącznik techniczny do raportu końcowego grantu rektora")
        frame = Frame(self.leftMargin, self.bottomMargin, self.width, self.height, leftPadding=0,
                      rightPadding=0, topPadding=0, bottomPadding=0)
        self.addPageTemplates([PageTemplate(id="report", frames=[frame], onPage=self.decorate)])
        self.section_index = 0

    def beforeDocument(self):
        self.section_index = 0

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name == "Section":
            self.section_index += 1
            key = f"section-{self.section_index}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(flowable.getPlainText(), key, 0, closed=False)
            self.notify("TOCEntry", (0, flowable.getPlainText(), self.page, key))

    def decorate(self, canvas, doc):
        canvas.saveState()
        if doc.page == 1:
            canvas.setFillColor(NAVY)
            canvas.rect(0, 0, *A4, fill=1, stroke=0)
            canvas.setStrokeColor(colors.HexColor("#275873"))
            for offset in range(4):
                import math
                points = [(x, 120 + offset * 19 + 32 * math.sin(x / 38 + offset * .6)) for x in range(0, 596, 3)]
                path = canvas.beginPath()
                path.moveTo(*points[0])
                for point in points[1:]:
                    path.lineTo(*point)
                canvas.drawPath(path)
            canvas.setFillColor(colors.HexColor("#43CED0"))
            canvas.rect(47, 735, 45, 4, fill=1, stroke=0)
        else:
            canvas.setFillColor(TEAL)
            canvas.rect(47, A4[1] - 30, 22, 3, fill=1, stroke=0)
            canvas.setFont("BodyBold", 8)
            canvas.setFillColor(MUTED)
            canvas.drawString(77, A4[1] - 31, "LPTM / DOKUMENTACJA OPROGRAMOWANIA")
            canvas.setFont("Body", 8)
            canvas.drawRightString(A4[0] - 47, A4[1] - 31, "RAPORT KOŃCOWY · ZAŁĄCZNIK TECHNICZNY")
            canvas.setStrokeColor(colors.HexColor("#D9E4EB"))
            canvas.line(47, 33, A4[0] - 47, 33)
            canvas.setFont("Body", 8)
            canvas.drawString(47, 20, f"Stan dokumentacji: {REPORT_DATE} · wersja 1.1")
            canvas.drawRightString(A4[0] - 47, 20, f"{doc.page:02d}")
        canvas.restoreState()


def build():
    data, tests, counts, commit = evidence()
    plots(data)
    story = [Spacer(1, 82), Paragraph("LPTM", ST["CoverTitle"]),
        Paragraph("Laser Polarisation<br/>Modulation Transciever", ST["CoverSub"]), Spacer(1, 20),
        Paragraph("DOKUMENTACJA OPROGRAMOWANIA<br/>I WYNIKÓW WERYFIKACJI", ST["CoverSub"]),
        Paragraph("Załącznik techniczny do raportu końcowego<br/>grantu rektora", ST["CoverFine"]),
        Spacer(1, 30), Paragraph(f"Stan projektu: {REPORT_DATE}<br/>Wersja dokumentu: 1.1<br/>"
            f"Identyfikacja kodu: {commit[:12]}", ST["CoverFine"]),
        Spacer(1, 22), Paragraph("Warstwa PC · modem programowy · transmisja plików<br/>"
            "diagnostyka sygnału · metodyka i wyniki pomiarów", ST["CoverFine"])]
    MD.append(f"# {TITLE}\n\nDokumentacja oprogramowania i wyników weryfikacji. {REPORT_DATE}.\n")
    story += [PageBreak(), Paragraph("NAWIGACJA", ST["Kicker"]), Paragraph("Spis treści", ST["Section"].clone("TOCHeading"))]
    toc = TableOfContents()
    toc.levelStyles = [ParagraphStyle("TOCItem", fontName="Body", fontSize=9.8, leading=13,
                                      textColor=INK, spaceBefore=2, leftIndent=0, firstLineIndent=0)]
    toc.tableStyle = TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)])
    toc.dotsMinLevel = 0
    story += [toc, Spacer(1, 16), note("Jak czytać raport", "Implementacja, testy programowe, historyczne CSV słabego kanału "
        "oraz nowsze wyniki zespołu po poprawie toru są opisane oddzielnie. Rozdziały 15–16 przedstawiają "
        "przedwzmacniacz 25 V/V i odebrane zdjęcia.")]

    # REPORT_CONTENT
    write_content(story, data, tests, counts, commit)
    document = Report(PDF)
    document.multiBuild(story)
    (HERE / "LPTM_dokumentacja_zrodlo.md").write_text("\n".join(MD), encoding="utf-8")
    print(json.dumps({"pdf": str(PDF), "bytes": PDF.stat().st_size, "tests": tests["liczba_testow"]}, ensure_ascii=False))


def write_content(story, data, tests, counts, commit):
    a, b = data["ber_1x"], data["ber_128B_1x"]
    story += section(1, "Osiągnięte rezultaty", "Streszczenie techniczne")
    story += [p("Opracowano zestaw aplikacji PC do nadawania, odbioru, diagnostyki i oceny jakości transmisji "
        "cyfrowej. System obsługuje tekst, rozmowę dwukierunkową i pliki binarne, korzystając ze wspólnego "
        "modemu programowego i interfejsów audio. Zintegrowany Transceiver udostępnia te funkcje "
        "w jednym oknie, w układzie dwóch kolumn bez zakładek."),
        table(["Rezultat", "Stan udokumentowany"], [
            ["Trzy aplikacje", "Nadajnik, Odbiornik i zintegrowany Transceiver; wspólna implementacja modemu."],
            ["Trzy modulacje", "2FSK, 4FSK i własny wariant 16QAM z pilotem fazowo-amplitudowym."],
            ["Transfer danych", "ASCII / UTF-8, pliki w numerowanych blokach, CRC ramki i SHA-256 całego pliku."],
            ["Diagnostyka i pomiary", "Oscyloskop, poziom AC w dBFS, nagrywanie WAV, BER i zautomatyzowane plany CSV."],
            ["Weryfikacja", f"{tests['liczba_testow']} testów programowych: OK. Osiem wybranych serii archiwalnych: 154 nadania."]
        ], [137, WIDTH - 137]), Spacer(1, 12),
        note("Najważniejszy wniosek", "Powstała spójna, testowalna warstwa programowa transmisji i pomiarów. "
             "Po zastosowaniu przedwzmacniacza 25 V/V zespół uzyskał 5 kbit/s w 2FSK oraz sprawną transmisję zdjęć "
             "w 4FSK przy 2,5 kbit/s i raportowanym BER 0,5%."),
        p("Wcześniejsze serie 50-punktowe dotyczą <b>kanału słabej jakości</b>: rozpoznano w nich 28/50 i 27/50 ramek. "
          "Nie opisują one osiągów po poprawie jakości toru. Nowsze próby potwierdzają użyteczną transmisję "
          "2FSK 10/20 kHz przy 5 kbit/s oraz 4FSK 5–10 kHz przy 2,5 kbit/s. Dwa ukończone obrazy z TRANSMISJA "
          "są zgodne bajt w bajt ze źródłami. Trwają testy zwiększania szybkości 4FSK i 16QAM."),
        source("kod i tests/; archiwalne CSV; uzupełnienie zespołu projektu; TRANSMISJA i porównanie SHA-256.")]

    story += section(2, "Zakres i identyfikacja opracowania", "Przedmiot załącznika")
    story += [p(f"Dokument dotyczy projektu <b>{TITLE}</b> i przedstawia stan jego oprogramowania na dzień "
        f"{REPORT_DATE}. Obejmuje wymagania funkcjonalne, architekturę, format danych, obsługę operatora, "
        "weryfikację oraz analizę zapisanych wyników pomiarowych. Jest samodzielnym załącznikiem technicznym "
        "do raportu końcowego; nie zastępuje części finansowej ani opisu organizacji grantu."),
        note("Granica systemu objętego dokumentacją", "Analizowana implementacja wytwarza i odbiera próbki PCM przez "
             "interfejs audio. Nazwa projektu odnosi się do transceivera laserowego, jednak ten załącznik nie jest "
             "protokołem charakteryzacji źródła światła, detektora ani modulacji polaryzacji w torze optycznym."),
        sub("Trzy poziomy dowodów"),
        table(["Poziom", "Co potwierdza", "Czego nie potwierdza"], [
            ["Implementacja", "Funkcje i ograniczenia zapisane w kodzie.", "Niezawodności w dowolnych warunkach stanowiskowych."],
            ["Testy programowe", "Zachowanie dla określonych scenariuszy, sztucznego PCM i interfejsów testowych.", "Parametrów rzeczywistego toru audio lub optycznego."],
            ["Archiwum pomiarowe", "Wynik konkretnych nadań zapisanych w CSV i metadanych.", "Powtarzalności poza warunkami zarejestrowanej próby."]
        ], [95, 197, WIDTH - 292]),
        p("Uzupełnienie zespołu opisuje nowszy etap stanowiskowy: zastosowanie przedwzmacniacza 25 V/V, "
          "uzyskane szybkości i raportowany BER. Parametry te zachowano jako oddzielny opis prób, a zgodność "
          "odebranych fotografii sprawdzono bezpośrednio na plikach. Nie dopisano tych wyników do wcześniejszych CSV."),
        sub("Identyfikowalność"),
        p(f"Kod odniesienia: <b>{commit[:12]}</b>. Pełny identyfikator rewizji oraz SHA-256 plików źródłowych "
          "i wybranych danych zapisano w dane_i_proweniencja.json. Czasowe etykiety CSV pochodzą z UTC; "
          "datą opracowania dokumentu jest data lokalna Europe/Warsaw. Nie zmieniano danych źródłowych pomiarów."),
        source("repozytorium, metadane JSON i manifest towarzyszący dokumentowi.")]

    story += section(3, "Architektura systemu", "Podział odpowiedzialności")
    story += diagram("architektura", architecture(), "Rys. 1. Rozdzielenie toru danych PCM od lokalnych kanałów wzorca i sterowania.")
    story += [table(["Warstwa", "Moduły i odpowiedzialność"], [
        ["Interfejs operatora", "transceiver.py, transmitter.py, receiver.py — wspólne kontrolery i widoki aplikacji."],
        ["Modem", "modem.py — ramkowanie, CRC, generacja PCM, detekcja symboli i parser przyrostowy."],
        ["Strumienie audio", "audio_runtime.py — odtwarzanie, przechwytywanie, kolejki, pomiary AC i zapis WAV."],
        ["Usługi danych", "transfers.py, chat.py, text_encoding.py — pliki, historia rozmowy, transliteracja ASCII."],
        ["Automatyzacja", "sweep.py, repeat_sweep.py, file_sweep.py — plany prób, logi i wznowienie pomiarów."]
    ], [115, WIDTH - 115]), Spacer(1, 9),
        p("Oddzielenie dostępu do urządzeń od modemu umożliwia weryfikację danych PCM bez uruchamiania fizycznego "
          "wejścia i wyjścia. Operacje audio i nagrywanie korzystają z wątków oraz kolejek; aktualizacja widżetów "
          "pozostaje po stronie pętli zdarzeń Tk. Współdzielenie obiektów ustawień w Transceiverze ogranicza "
          "rozbieżności między częścią nadającą i odbierającą."),
        source("audio_runtime.py; transceiver.py; gui_common.py; ipc_control.py; ipc_reference.py.")]

    story += section(4, "Interfejs operatora", "Jedno okno, dwa obszary robocze")
    story += diagram("interfejs", interface(), "Rys. 2. Mapa funkcjonalna aktualnego interfejsu; schemat opracowany z kodu, nie zrzut ekranu.")
    story += [p("Lewa kolumna skupia bieżącą pracę: rozmowę oraz nadawanie i odbieranie plików. Prawa kolumna "
        "zawiera oscyloskop i wspólne ustawienia transmisji. Generator, lokalne odtwarzanie audio, logowanie "
        "i pomiary CSV są dostępne w rozwijanym obszarze narzędzi dodatkowych, bez zmiany zakładek."),
        table(["Działanie", "Zachowanie interfejsu"], [
            ["Wysłanie odpowiedzi", "Pole czatu → Wyślij lub Ctrl+Enter; Enter dodaje nowy wiersz."],
            ["Zmiana ASCII / UTF-8", "Przy wyborze ASCII treść pola jest transliterowana; znaki bez odpowiednika stają się ?."],
            ["Odbiór pliku", "Postęp bajtowy, stan kompletności, ścieżka docelowa i przycisk Otwórz folder."],
            ["Przerwanie", "Osobne zatrzymanie nadawania i odbioru; niepełny transfer pozostaje w .part."]
        ], [132, WIDTH - 132]),
        source("transceiver.py; Receiver._build_transceiver_view; Transmitter._build_transceiver_view; chat.py.")]

    story += section(5, "Modulacje i parametry transmisji", "Model bitów i symboli")
    story += [p("Parametr bitrate Rb wyrażany jest w bit/s. Liczba bitów przypadających na symbol wynosi "
        "k = log₂(M), a szybkość symbolowa Rs = Rb/k. Dla tej samej liczby bitów 4FSK i 16QAM wykorzystują "
        "odpowiednio dwa i cztery bity na symbol. Parametr baud w klasie konfiguracji przechowuje bitrate, "
        "a nie niezależną szybkość symbolową."),
        table(["Tryb", "k / Rs", "Sposób wyznaczania sygnału"], [
            ["2FSK", "1 / Rb", "Dwie zadane częstotliwości, przypisane do 0 i 1."],
            ["4FSK", "2 / Rb/2", "Cztery równomiernie rozłożone tony między fL i fH; symbole 00, 01, 10, 11."],
            ["16QAM z pilotem", "4 / Rb/4", "Nośna (fL + fH)/2; pilot w pierwszej połowie symbolu, poziomy I/Q w drugiej."]
        ], [107, 70, WIDTH - 177]), Spacer(1, 10),
        sub("Ograniczenia walidatora konfiguracji"),
        p("Dla 2FSK wymagane jest |f1 − f0| ≥ Rb. Dla 4FSK odstęp sąsiednich tonów musi wynosić co najmniej "
          "Rs, co daje fH − fL ≥ 1,5 Rb. Dla 16QAM sprawdzane są fH − fL ≥ Rs oraz fL ≥ 2 Rs. "
          "To warunki dopuszczenia ustawień przez program, a nie dowód optymalnej ortogonalności lub odporności kanału."),
        p("Wariant 16QAM stosuje poziomy Gray: 00→−3, 01→−1, 10→+3, 11→+1. Pilot umożliwia oszacowanie "
          "fazy i wzmocnienia nośnej osobno dla symbolu. Jest to własny format aplikacji; nie deklaruje się "
          "zgodności z zewnętrznym standardem modemu QAM."),
        note("Przykład 4FSK", "Dla fL = 4000 Hz, fH = 10000 Hz i Rb = 1234 bit/s tony wynoszą "
             "4000, 6000, 8000 i 10000 Hz, a Rs = 617 symboli/s. Takie parametry występują w teście programowym z szumem."),
        source("ModemConfig.validate, ModemConfig.tones, fsk_chunks, _qam_symbol; tests/test_modem.py.")]

    story += section(6, "Próbkowanie i synchronizacja", "Od symbolu do próbek PCM")
    story += [table(["Parametr", "Wartość / znaczenie"], [
        ["Format PCM", "Mono, float32; amplituda nadajnika w zakresie 0–1."],
        ["Próbkowanie fs", "48 000, 96 000 lub 192 000 próbek/s."],
        ["Górny limit tonu", "min(48 000 Hz, fs/2 − 100 Hz): 23,9; 47,9 lub 48 kHz."],
        ["Bitrate", "5–10 000 bit/s; Transceiver domyślnie 500 bit/s, samodzielny modem 25 bit/s."],
        ["Blok audio", "Typowo 2048 próbek; parser i dekoder zachowują stan między blokami."],
        ["Hipotezy czasu", "Do ośmiu przesunięć fazy czasowej w obrębie symbolu."]
    ], [135, WIDTH - 135]), Spacer(1, 11),
        sub("Granice symboli bez narastającego dryftu"),
        code("n(j) = round(j · fs / Rs)\nliczba próbek symbolu j = n(j+1) − n(j)"),
        p("Zaokrąglane są skumulowane granice symboli, zamiast powtarzania jednej zaokrąglonej długości. "
          "Pozwala to obsługiwać niecałkowitą liczbę próbek na symbol, np. dla ułamkowego bitratu. "
          "W FSK zachowywana jest ciągłość fazy w ramce; na jej brzegach stosowane jest wygaszanie. "
          "Za ramką dodawany jest zapas ciszy o długości czterech symboli."),
        p("Detekcja FSK porównuje moce obliczone metodą Goertzela dla zadanych tonów. Dekoder przetwarza "
          "kilka hipotez granicy symbolu, a następnie wybiera kandydatów według poprawności CRC i błędów próby BER. "
          "Wariant QAM wykorzystuje dopasowanie składowych sinus/cosinus i odniesienie do pilota."),
        note("Znaczenie limitu 48 kHz", "Ton 48 kHz wymaga w tej aplikacji próbkowania 192 kHz. "
             "Jest to możliwość generacji i dekodowania programowego; rzeczywiste pasmo zależy od użytego DAC, ADC i toru fizycznego."),
        source("modem.py; audio_runtime.py; tests/test_modem.py.")]

    story += section(7, "Ramka warstwy transmisyjnej", "Format, narzut i kontrola CRC")
    story += diagram("ramka", frame_diagram(), "Rys. 3. Wspólny format bitowy dla wiadomości, zapowiedzi konfiguracji i pakietów pliku.")
    story += [table(["Pole", "Rozmiar", "Interpretacja"], [
        ["Preambuła", "32 b", "Naprzemiennie 1 i 0; wyszukiwanie początku ramki."],
        ["SYNC", "32 b", "Stałe słowo 0xDDAA96F3."],
        ["Próba BER", "128 b", "Znany wzorzec pozwalający ocenić odebrane bity bez lokalnego wzorca danych."],
        ["Identyfikator", "64 b", "Osiem bajtów ID wiadomości lub transferu."],
        ["Długość", "16 b", "Liczba bajtów danych; implementacja dopuszcza 1–2048 B."],
        ["Dane", "8N b", "Treść komunikatu lub pakietu wyższego poziomu."],
        ["CRC", "16 b", "CRC-16/CCITT-FALSE identyfikatora i danych."]
    ], [106, 65, WIDTH - 171]), Spacer(1, 10),
        p("Wartości liczbowe i bity bajtów są wysyłane od najstarszego bitu. Stały narzut ramki wynosi "
          "288 bitów, stąd Lramki = 288 + 8N. Pole długości i próba BER nie należą do zakresu obliczania CRC; "
          "z tego powodu poprawność parsowania tych pól ma osobne znaczenie dla synchronizacji i oceny błędów."),
        p("CRC wykorzystuje wielomian 0x1021 i stan początkowy 0xFFFF; test wektora 123456789 daje 0x29B1. "
          "Niepoprawna ramka tekstowa może być pokazana z oznaczeniem błędu. Jej dane nie są przyjmowane jako "
          "poprawny blok pliku."),
        source("encode_payload, crc16, _BitParser; tests/test_modem.py.")]

    story += section(8, "Automatyczne ustawianie odbiornika", "Zapowiedź przez kanał transmisyjny")
    story += [p("Przed normalnym wysłaniem danych nadajnik może nadać komunikat konfiguracyjny stałym trybem "
        "2FSK: 1200/2200 Hz, 500 bit/s. Komunikat ma prefiks LPTN2 i bajt zerowy, a następnie JSON z "
        "konfiguracją oraz kodowaniem tekstu. Przesyłany jest w zwykłej ramce z CRC."),
        table(["Etap", "Działanie"], [
            ["1. Nasłuch", "Odbiornik analizuje zapowiedzi równolegle do aktualnego trybu transmisji."],
            ["2. Weryfikacja", "Wymagane są poprawne CRC, format JSON i prawidłowe wartości ModemConfig."],
            ["3. Przełączenie", "Ustawiane są modulacja, tony, bitrate, próbkowanie i kodowanie. Przy zmianie fs otwierany jest nowy strumień audio."],
            ["4. Przerwa ochronna", "Nadajnik pozostawia około dwóch sekund przed przesłaniem właściwych danych."],
            ["5. Dane", "Odbiór wiadomości lub pakietów pliku w zapowiedzianym trybie."]
        ], [116, WIDTH - 116]), Spacer(1, 14),
        note("Zapowiedź nie jest uzgodnieniem z potwierdzeniem", "Mechanizm jest jednokierunkowy: odbiornik nie "
             "wysyła ACK dla przyjętej konfiguracji. Utrata zapowiedzi może uniemożliwić odbiór następujących po niej danych. "
             "Odbiornik należy uruchomić przed nadawaniem."),
        p("Zapowiedź jest przesyłana przez audio i nie wymaga połączenia sieciowego między komputerami. "
          "Lokalne IPC pełni inną rolę: udostępnia wzorzec danych do BER i steruje zautomatyzowanym pomiarem. "
          "W procedurach pomiarowych wybierany jest ręczny, wspólny tryb 2FSK, aby nie mieszać zapowiedzi "
          "z właściwym oknem pomiarowym."),
        p("Zmiana częstotliwości próbkowania podczas odbioru zamyka aktywne nagranie WAV. Nowy strumień może "
          "zostać uruchomiony tylko wtedy, gdy urządzenie i jego sterownik obsługują zadane fs."),
        source("transfers.py: bootstrap_config, settings_packet, announcement_chunks; Receiver._apply_settings.")]

    story += section(9, "Przesyłanie i zapis plików", "Warstwa binarna niezależna od kodowania tekstu")
    story += diagram("transfer_pliku", transfer_diagram(), "Rys. 4. Odbiór odporny na duplikaty i opóźnioną kopię brakującego bloku.")
    story += [p("Pakiet pliku ma prefiks LPTF2 i bajt zerowy. Pakiet H zawiera tekstowy nagłówek JSON: "
        "nazwę z rozszerzeniem, rozmiar, SHA-256 i block_bytes = 1024. Pakiet D zawiera typ, 32-bitowy numer "
        "bloku i maksymalnie 1024 oryginalne bajty. Pakiet E oznacza koniec nadawania. Dla całego pliku "
        "utrzymywany jest identyfikator transferu."),
        p("JPG i pozostałe obrazy nie są dekodowane jako UTF-8. Trafiają do osobnego panelu plików; "
          "również wybranie obrazu w dawnej ścieżce pliku tekstowego przekierowuje wysłanie do trybu binarnego. "
          "Rozwiązuje to błąd odczytu bajtów takich jak 0xFF jako znaków tekstowych."),
        p("Każdy poprawny blok jest zapisywany i opróżniany do pliku .part na pozycji wynikającej z jego numeru. "
          "Pominięcie jednego bloku nie usuwa późniejszych danych. Po zebraniu całości odbiornik odczytuje "
          "plik i weryfikuje SHA-256, po czym automatycznie nadaje mu docelową nazwę. Zgubienie pakietu E "
          "nie blokuje już ukończenia."),
        note("Integralność i ochrona istniejących danych", "CRC-błędny blok jest pomijany. Domyślnie przesyłane są "
             "dwie kopie, z wyborem 1–3 w interfejsie. Istniejące pliki nie są nadpisywane; konflikt nazwy rozwiązywany "
             "jest przez dodanie ID transferu. Niekompletne dane pozostają jawnie oznaczone jako .part."),
        source("transfers.py: file_packets i FileReceiver; Transmitter.send_file; tests/test_transfers.py.")]

    story += section(10, "Czat, kodowanie i integralność", "Rozróżnienie stanu nadania od odbioru")
    story += [p("Czat utrzymuje historię wiadomości wychodzących i przychodzących. Kolejne fragmenty tej samej "
        "wiadomości aktualizują jeden wpis. Identyfikatory własnych nadań pozwalają odfiltrować ich echo "
        "z historii rozmówcy. Własny komunikat otrzymuje stan Nadano po zakończeniu odtwarzania PCM, "
        "co nie jest potwierdzeniem dostarczenia na drugą stację."),
        table(["Mechanizm", "Cel i ograniczenie"], [
            ["CRC-16 ramki", "Wykrycie uszkodzeń ID i danych. Nie naprawia bitów i nie zabezpiecza kryptograficznie transmisji."],
            ["SHA-256 pliku", "Końcowe porównanie pełnej zawartości z nagłówkiem; nie jest podpisem ani uwierzytelnieniem nadawcy."],
            ["Powtórzenia bloków", "Stała redundancja 1–3 kopii; nie jest to selektywna retransmisja sterowana ACK/NACK."],
            ["ASCII", "Czytelna transliteracja liter, np. Zażółć → Zazolc; nieobsługiwany znak → ?."],
            ["UTF-8", "Odbiór przyrostowy z oczekiwaniem na pełną sekwencję wielobajtowego znaku."]
        ], [124, WIDTH - 124]), Spacer(1, 11),
        sub("Zapis historii i wiadomości niepełnych"),
        p("Rozmowę można wyeksportować do UTF-8. Odbiornik umożliwia również ręczny zapis bieżącej wiadomości "
          "z liczbą bajtów, BER i stanem CRC oraz ciągłe dopisywanie tekstu w trakcie odbioru. Niepełny lub "
          "CRC-błędny tekst pozostaje widoczny i oznaczony. Reguła ta służy diagnostyce; nie znosi wymagań "
          "integralności przy publikowaniu pliku binarnego."),
        p("Konwersja Unicode do ASCII jest celowo nieodwracalna. Dotyczy pola wiadomości i tekstu przed nadaniem; "
          "nigdy nie jest stosowana do zawartości zdjęcia lub innego pliku binarnego."),
        source("chat.py; text_encoding.py; Receiver._show_progress i _log_progress; tests/test_chat.py.")]

    story += section(11, "Oscyloskop i pomiary sygnału", "Jednostki, skale i rejestracja")
    story += [table(["Wskaźnik", "Znaczenie"], [
        ["Oś napięcia", "Stała skala −1…+1 V, 0,5 V na działkę; umowne przeliczenie PCM ±1 ↔ ±1 V."],
        ["Oś czasu", "Okna 5, 10, 20, 50 lub 100 ms, obliczane z aktualnej częstotliwości próbkowania."],
        ["Przebieg", "Surowe próbki przechwytywania, bez normalizacji amplitudy; przy redukcji do pikseli zachowywane są ekstrema."],
        ["Wzmocnienie wykresu", "0–60 dB, wyłącznie prezentacja; przekroczenia zakresu ±1 V są oznaczane."],
        ["Miernik AC", "Szczyt i RMS w dBFS po filtracji składowej wolnozmiennej i odjęciu średniej."],
        ["Nagranie WAV", "Mono float WAV z niezmienionych próbek, w aktualnym fs; osobny wątek zapisu."]
    ], [131, WIDTH - 131]), Spacer(1, 12),
        code("G = 10^(g_dB / 20)\nRMS_AC = sqrt(mean((x − mean(x))²))\nL_RMS = 20 · log10(RMS_AC) [dBFS]"),
        note("Skala V jest założeniem wizualizacji", "Bez kalibracji karty i zewnętrznego toru odczyt ±1 V nie jest "
             "pomiarem napięcia na rzeczywistych zaciskach. dBFS jest poziomem względem pełnej skali cyfrowej, "
             "a procent amplitudy nadajnika nie jest procentem mocy optycznej."),
        p("Kalibracja stanowiskowa powinna oddzielnie wyznaczyć przeliczenie kodu PCM na napięcie, liniowość "
          "i pasmo dla zastosowanego fs. Zmiany wzmocnienia wyświetlania nie zmieniają PCM podawanego do dekodera "
          "ani danych rejestrowanych w WAV."),
        source("scope.py; audio_runtime.py: ac_metrics, HighPass, WaveRecorder; tests/test_audio_metrics.py.")]

    story += section(12, "Metodyka pomiarów BER", "Definicje i ślad eksperymentu")
    story += [p("Plan bazowy obejmuje 50 dopuszczalnych kombinacji częstotliwości i bitratu. Pary tonów powstają "
        "z kolejnych punktów szeregu częstotliwości, a bitrate jest ułamkiem różnicy tonów: 0,25; 0,5 lub 0,75. "
        "Po odrzuceniu punktów przekraczających 23,9 kHz i 10 000 bit/s skrypt wykonuje zaplanowane nadania. "
        "Metadane zapisują wiadomość, jej rozmiar i SHA-256, amplitudę oraz indeksy urządzeń."),
        table(["Miara", "Definicja i zakres"], [
            ["BER wzorca", "Błędy w znanej, 128-bitowej próbie ramki / liczba porównanych bitów tej próby."],
            ["BER danych", "Porównanie odebranych i oczekiwanych bajtów lokalnego wzorca; XOR bitów plus kara za różnicę długości."],
            ["Rozpoznanie ramki", "Status inny niż no_frame; nie oznacza automatycznie poprawnego CRC ani zgodnego ID."],
            ["Ocena no_frame = 100%", "Umowna kara w podsumowaniu skuteczności, nie zmierzony odsetek błędnych bitów."],
            ["Poziom sygnału", "RMS AC w dBFS z okna próby; niezależny od wysokości wykresu oscyloskopu."]
        ], [130, WIDTH - 130]), Spacer(1, 11),
        p("Funkcja porównania danych zlicza błędy w części wspólnej i osiem błędów za każdy brakujący lub "
          "nadmiarowy bajt. Mianownik ma długość dłuższego komunikatu. Przy uszkodzonym polu długości może "
          "więc różnić się między próbami. W raporcie podano również BER ważony: sumę błędów podzieloną "
          "przez sumę rzeczywiście porównanych bitów odebranych ramek."),
        note("Wznawianie nie oznacza nowego pomiaru starego punktu", "Log surowy, metadane i coverage pozwalają "
             "odtworzyć liczbę nadań i rozpoznanych ramek. Punkty niezmierzone pozostają puste. Porównanie serii "
             "wymaga zgodności wiadomości, urządzeń, amplitudy i warunków toru."),
        source("sweep.py; repeat_sweep.aggregate; file_sweep.py; compare_payload_bits; CSV raw i metadata JSON.")]

    story += section(13, "Serie 50-punktowe: słaby kanał", "Archiwum: 9 listopada 2026 · kanał słabej jakości")
    story += [Image(str(ASSETS / "statusy_serii.png"), width=WIDTH, height=WIDTH * 3 / 8.1),
        p("Rys. 5. Kanał słabej jakości: statusy dwóch historycznych serii. Każdy słupek obejmuje 50 ustawień. "
          "Wykres nie przedstawia osiągów po zastosowaniu przedwzmacniacza.", "Fine"),
        table(["Wskaźnik", "Wiadomość 41 B", "Wiadomość 128 B"], [
            ["Amplituda cyfrowa", "40%", "40%"],
            ["Rozpoznane ramki", f"{a['recognized']}/50 (56%)", f"{b['recognized']}/50 (54%)"],
            ["Poprawne CRC", f"{a['crc_ok']}/50", f"{b['crc_ok']}/50"],
            ["Brak rozpoznanej ramki", "22/50", "23/50"],
            ["Błędy / porównane bity", f"{a['errors']} / {a['bits']}", f"{b['errors']} / {b['bits']}"],
            ["BER ważony odebranych", f"{a['pooled_ber']:.3f}%", f"{b['pooled_ber']:.3f}%"],
            ["Średnia ocena z karą za brak", f"{a['score_mean']:.3f}%", f"{b['score_mean']:.3f}%"]
        ], [215, (WIDTH - 215) / 2, (WIDTH - 215) / 2]), Spacer(1, 9),
        p("W obu seriach słabego kanału niewykrycie ramki było istotnym składnikiem niepowodzeń. Bliskie udziały rozpoznanych "
          "ramek nie dowodzą równoważności obu długości wiadomości: na każdą kombinację przypadało jedno nadanie, "
          "a warunki nie tworzą kontrolowanej, powtarzanej próby porównawczej."),
        source("measurements/ber_1x_raw.csv i ber_128B_1x_raw.csv; liczby przeliczone bezpośrednio z logów.")]

    story += section(14, "Serie dziewięciopunktowe: słaby kanał", "Archiwum: 13 listopada 2026 · kanał słabej jakości")
    story += [Image(str(ASSETS / "serie_80procent.png"), width=WIDTH, height=WIDTH * 4.2 / 8.1),
        p("Rys. 6. Historyczne wyniki słabego kanału, wiadomość 128 B, amplituda 80%. Turkus: ok; bordowy: "
          "id_mismatch; bursztynowy: bad_crc; szary: no_frame. "
          "Liczby oznaczają BER danych [%]; brak nie jest wartością liczbową BER.", "Fine"),
        table(["Seria", "Rozpoznane", "CRC OK", "Bez błędów danych", "Brak ramki"], [
            [str(i), str(data[f"ber_128B_pomiar_{i}_80procent"]["recognized"]),
             str(data[f"ber_128B_pomiar_{i}_80procent"]["crc_ok"]),
             str(data[f"ber_128B_pomiar_{i}_80procent"]["zero_ber"]),
             str(data[f"ber_128B_pomiar_{i}_80procent"]["status"].get("no_frame", 0))] for i in range(1, 7)
        ], [58, 105, 95, 140, WIDTH - 398], small=True), Spacer(1, 9),
        p("Zapisana liczba rozpoznanych ramek zmienia się od 6/9 w serii 1 do 1/9 w serii 6. W tych sześciu "
          "logach nie rozpoznano ramek dla trzech najwyższych badanych bitrate’ów: 1500, 3500 i 5000 bit/s. "
          "Nie jest to granica osiągów projektu: w nowszych próbach po poprawie toru osiągnięto 5 kbit/s "
          "w 2FSK i sprawną transmisję obrazów w 4FSK (rozdziały 15–16)."),
        source("measurements/ber_128B_pomiar_1_80procent_raw.csv … ber_128B_pomiar_6_80procent_raw.csv.")]

    story += section(15, "Poprawa toru i nowe wyniki", "Przedwzmacniacz 25 V/V · kanał dobrej jakości")
    story += [p("Po dołączeniu przedwzmacniacza o wzmocnieniu napięciowym <b>25 V/V</b> "
        "(około 28 dB) zespół projektu odnotował poprawę warunków odbioru i zwiększenie osiąganej szybkości "
        "transmisji. W odróżnieniu od wcześniejszych wykresów dla kanału słabej jakości nowsze próby "
        "potwierdziły sprawną transmisję danych i fotografii przy parametrach zestawionych poniżej."),
        table(["Wariant próby", "Konfiguracja", "Uzyskany rezultat"], [
            ["2FSK", "Tony 10 kHz i 20 kHz; bitrate 5 kbit/s.",
             "Transmisja osiągnięta po dodaniu przedwzmacniacza 25 V/V."],
            ["4FSK — zdjęcia", "Dolny ton 5 kHz, górny 10 kHz; bitrate 2,5 kbit/s.",
             "Sprawny transfer obrazów; raportowany BER 0,5%. Odebrane pliki zachowano w TRANSMISJA."],
            ["Dalsze testy", "4FSK oraz 16QAM przy zwiększanych szybkościach.",
             "Badania trwają; wartości końcowe dla szybszych konfiguracji nie zostały jeszcze ustalone."]
        ], [111, 181, WIDTH - 292]), Spacer(1, 13),
        sub("Znaczenie jakości kanału"),
        p("Rezultaty po poprawie toru wskazują na istotny wpływ jakości kanału na użyteczną szybkość "
          "i powodzenie transferu. Wyników historycznych obarczonych licznymi no_frame nie należy "
          "przedstawiać jako granicy możliwości urządzenia. W korzystniejszych warunkach uzyskano "
          "5 kbit/s w 2FSK oraz transmisję zdjęć w 4FSK przy 2,5 kbit/s."),
        note("BER kanału a integralność pliku", "Raportowany BER 0,5% dotyczy próby transmisji, "
             "nie zawartości ukończonego JPEG. Poprawne kopie bloków przechodzą CRC, a plik jest publikowany "
             "po zgodnym SHA-256. Dwa odebrane obrazy są identyczne bajt w bajt z plikami źródłowymi."),
        p("Parametry nowych prób i wartość BER przekazał zespół projektu. Są one dokumentowane odrębnie "
          "od historycznych logów CSV; szczegółowy licznik błędów i rozróżnienie BER wzorca / BER danych "
          "nie zostały podane w tym uzupełnieniu. Zgodność plików sprawdzono niezależnie na dostępnych artefaktach."),
        source("uzupełnienie zespołu projektu z 17.11.2026; wyniki_przedwzmacniacz.json; TRANSMISJA.")]

    transmission = json.loads((HERE / "weryfikacja_TRANSMISJA.json").read_text(encoding="utf-8"))["weryfikacja_odebranych_obrazow"]
    transmission.sort(key=lambda item: item["plik"] != "karmelini.jpg")
    story += section(16, "Potwierdzenie transmisji zdjęć", "Artefakty z katalogu TRANSMISJA")
    story += [p("W katalogu TRANSMISJA zachowano dwa ukończone obrazy JPEG. Poniżej przedstawiono "
        "ich reprodukcje i kontrolę zgodności z plikami źródłowymi o tych samych nazwach w katalogu projektu. "
        "Są to materiały wskazane przez zespół jako rezultat sprawnej transmisji zdjęć." )]
    images, labels = [], []
    for item in transmission:
        factor = min(220 / item["szerokosc"], 165 / item["wysokosc"])
        images.append(Image(str(HERE / item["reprodukcja"]), width=item["szerokosc"] * factor,
                            height=item["wysokosc"] * factor))
        labels.append(Paragraph(escape(item["plik"]), ST["Cell"]))
    gallery = Table([images, labels], colWidths=[WIDTH / 2] * 2)
    gallery.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    story += [gallery, p("Rys. 7. Reprodukcje ukończonych plików z TRANSMISJA. Obrazy nie są symulacją transmisji.", "Fine"),
        table(["Plik odebrany", "Rozmiar", "Wymiary", "Zgodność ze źródłem"], [
            [escape(item["plik"]), f"{item['bajty']} B", f"{item['szerokosc']} × {item['wysokosc']} px",
             "Identyczne bajty; SHA-256 zgodny" if item["identyczne_bajty"] else "Brak potwierdzenia"] for item in transmission
        ], [133, 70, 94, WIDTH - 297]), Spacer(1, 9), sub("Skróty SHA-256 odebranych plików")]
    for item in transmission:
        story += [p(escape(item["plik"]), "Fine"), code(item["sha256_odebranego"])]
        MD.append(f"![Odebrany plik {item['plik']}]({item['reprodukcja']})\n")
    story += [p("Zgodność pełnych plików potwierdza bezbłędne odtworzenie tych dwóch obrazów. "
        "Nie jest ona utożsamiana z zerowym BER wszystkich prób kanału. Katalog i zapis pomocniczy "
        "obejmują również wcześniejsze próby niepełne lub błędne; nie stanowią jednej serii dla podanej wartości 0,5%.", "Fine"),
        source("TRANSMISJA/*.jpg; odpowiadające pliki źródłowe; weryfikacja_TRANSMISJA.json; zapisTransmisji16_11.txt.")]

    story += section(17, "Interpretacja wyników i ich granice", "Słaby kanał a wyniki po poprawie toru")
    story += [sub("1. Rozpoznanie, poprawność bitowa i integralność to różne zdarzenia"),
        p("Ramka może zostać rozpoznana, ale zawierać błąd ID lub CRC. Dlatego w raporcie oddzielono liczbę "
          "rozpoznanych ramek, poprawne CRC, BER danych i brak ramki. Sama średnia kolumny ber_percent "
          "z pięciokolumnowego podsumowania miesza pomiar błędów z umowną karą za utratę ramki."),
        sub("2. Wyższy bitrate w konfiguracji nie gwarantuje skutecznego łącza"),
        p("Walidator sprawdza zakresy liczbowe i minimalne odstępy tonów. Nie mierzy pasma stanowiska, "
          "nieliniowości, nasycenia ani rzeczywistego odstępu sygnału od szumu. Dane archiwalne wykazują "
          "dużą liczbę no_frame w kanale słabej jakości. Wyniki po zastosowaniu przedwzmacniacza pokazują "
          "sprawną pracę w lepszych warunkach: 2FSK 5 kbit/s oraz transfer zdjęć 4FSK 2,5 kbit/s. "
          "Udany test syntetyczny 10 000 bit/s "
          "potwierdza wybrany scenariusz obliczeniowy, nie użytkową szybkość wszystkich konfiguracji."),
        sub("3. Nie należy przypisywać zmian między seriami jednej przyczynie"),
        p("Metadane określają wiadomość, poziom cyfrowy i indeksy urządzeń. Nie zawierają kompletnej "
          "charakterystyki geometrii, toru optycznego, temperatury ani wszystkich ustawień zewnętrznych. "
          "Zmienności między sześcioma seriami nie można więc bezpośrednio przypisać jednemu parametrowi. "
          "Nowe wyniki po wprowadzeniu przedwzmacniacza są odrębnym etapem prób zespołu."),
        sub("4. Kierunek dalszej walidacji"),
        p("Dla wybranego stanowiska należy wykonać powtarzane serie przy stałej geometrii i wiadomości, "
          "rejestrować liczbę utraconych ramek osobno od BER oraz mierzyć czas i skuteczność całego transferu pliku. "
          "Dalsze próby szybszych konfiguracji 4FSK i 16QAM są obecnie prowadzone; ich wyniki należy "
          "uzupełniać z zachowaniem tej samej metodyki."),
        note("Wynik naukowo użyteczny", "Archiwum pokazuje obszary poprawnego działania i niepowodzeń oraz pozwala "
             "wskazać następne eksperymenty. Osiągi w dobrym kanale opisują nowsze próby, a zgodne pliki "
             "JPEG potwierdzają praktyczną skuteczność transferu. Nie należy mieszać obu etapów w jedną średnią."),
        source("logi surowe, metadane i ograniczenia implementacji opisane w rozdziałach 5–8.")]

    story += section(18, "Weryfikacja oprogramowania", "Ponowna kontrola: 17 listopada 2026")
    story += [note(f"Wynik: {tests['liczba_testow']} testów — OK", f"Uruchomiono pełne odkrywanie unittest. "
        f"Czas wykonania: {tests['czas_s']:.3f} s. Kod zakończenia: 0. Zapis weryfikacji: testy_weryfikacja.json."),
        table(["Obszar", "Scenariusze kontrolowane"], [
            ["Modem i CRC", "Szum, nieznany początek rejestracji, fragmentacja PCM, ułamkowe granice symboli, uszkodzony payload i wektor CRC."],
            ["Nowe tryby", "4FSK i 16QAM przy 48/192 kHz, zmienionym wzmocnieniu, szumie i przesunięciu przechwytywania."],
            ["Pliki", "JPG jako oryginalne bajty; brak kopii, powtórzony marker końca, brak markera końca i opóźniony brakujący blok."],
            ["Interfejs i czat", "Brak zakładek w Transceiverze, wspólne ustawienia, oba kierunki czatu, odfiltrowanie własnego echa i ASCII."],
            ["Pomiary i IPC", "Kolejka poleceń, lokalny wzorzec, plany CSV, wznowienie i semantyka no_frame."],
            ["Audio i pliki WAV", "Składowa DC, RMS AC, filtr ze stanem oraz zgodność surowych próbek i częstotliwości zapisu."]
        ], [111, WIDTH - 111]), Spacer(1, 10),
        p("Test JPEG przeprowadza przesłanie pakietów przez generację i dekodowanie PCM, po czym porównuje "
          "odebrany plik z plikiem testowym. Test zapisu bez pakietu E potwierdza, że gotowy plik jest publikowany "
          "po komplecie bloków i zgodnym SHA-256. Osobny test sprawdza przyjęcie brakującego bloku po nadejściu E."),
        p("Część testów GUI zastępuje urządzenia i wywołania odtwarzania obiektami testowymi. Nie jest to "
          "nowy pomiar fizycznego łącza. Szczegółowy wykaz nazw testów znajduje się w katalogu tests/, "
          "a liczebności według plików w dane_i_proweniencja.json."),
        source("tests/; testy_weryfikacja.json. Polecenie: python -m unittest discover -s tests -v.")]

    story += section(19, "Instalacja i uruchomienie", "Odtworzenie środowiska operatora")
    story += [p("Kod wymaga Pythona 3.11 lub nowszego i środowiska graficznego Tk. Do dostępu audio "
        "wykorzystuje sounddevice, a do plików audio soundfile. Tworzenie wykresów wymaga dodatkowo matplotlib. "
        "Pakiety instalowane są w odrębnym środowisku wirtualnym."),
        sub("Windows — uruchomienie ze źródeł"),
        code("py -3 -m venv .venv\n.venv\\Scripts\\python.exe -m pip install -r requirements.txt\n.venv\\Scripts\\python.exe transceiver.py"),
        sub("Samodzielne aplikacje i pakowanie"),
        p("Analogicznie można uruchomić transmitter.py oraz receiver.py. Skrypt build_windows.bat tworzy "
          "Nadajnik.exe, Odbiornik.exe i Transceiver.exe za pomocą PyInstaller. Pliki aplikacji muszą być "
          "zamknięte podczas ich nadpisywania. Skrypt build_macos.sh przewiduje budowę aplikacji .app "
          "i opis dostępu do mikrofonu; nie zastępuje weryfikacji na docelowym komputerze Mac."),
        sub("Warunki stanowiskowe"),
        p("Na obu stacjach należy wybrać właściwe wejście i wyjście. Urządzenia muszą obsługiwać żądaną "
          "częstotliwość próbkowania. Odbiornik uruchamia się przed nadajnikiem. Przy wspólnym komputerze "
          "monitorowanie mikrofonu może powodować sprzężenie; odsłuch nie jest warunkiem dekodowania."),
        note("Odtwarzalność wersji", f"Dla odtworzenia opisanego stanu należy użyć rewizji {commit[:12]} i "
             "porównać SHA-256 plików z manifestem. Wymagania pakietów określają przedziały wersji, nie pełny lockfile środowiska."),
        source("requirements.txt; requirements-experiment.txt; build_windows.bat; build_macos.sh; README.md.")]

    story += section(20, "Procedury odbioru i powtórzenia badań", "Instrukcja weryfikacji stanowiskowej")
    story += [table(["Krok", "Kontrola i kryterium"], [
        ["1. Identyfikacja stanowiska", "Zapisać modele urządzeń, sterowniki, fs, tor fizyczny i geometrię. Sprawdzić poprawny wybór wejścia i wyjścia."],
        ["2. Transmisja tekstu", "Nadać krótki wzorzec, odnotować ID, bajty, CRC, BER i liczbę utraconych ramek; powtórzyć ustaloną liczbę prób."],
        ["3. Transfer JPEG", "Przesłać znany plik, porównać SHA-256 źródła i wyniku, zapisać czas oraz liczbę nadań i powtórzeń."],
        ["4. Scenariusze zakłóceń", "Oddzielnie sprawdzić utratę kopii, utratę końca, niekompletny transfer i zachowanie .part."],
        ["5. Serie parametrów", "Użyć planu CSV, stałego wzorca i amplitudy; zachować raw, summary, coverage oraz metadata."],
        ["6. Ocena", "Raportować skuteczność rozpoznania i ukończenia pliku obok BER. Nie utożsamiać no_frame z pomiarem 100% błędnych bitów."]
    ], [134, WIDTH - 134]), Spacer(1, 12),
        sub("Sprawdzenie planu bez generacji audio"),
        code("python sweep.py --dry-run\npython file_sweep.py --plan-file measurements/plan_example.csv --dry-run"),
        sub("Przykładowe uruchomienie badania"),
        code("python repeat_sweep.py --input-device 1 --output-device 0 --amplitude 0.4\npython -m unittest discover -s tests -v"),
        p("Przykładowe indeksy 0 i 1 muszą zostać zastąpione indeksami rzeczywistych urządzeń. Badanie "
          "automatyczne wymaga odpowiednich aplikacji i wolnych portów lokalnych. Wznowienie stosuje te same "
          "metadane; do nowej serii należy wybrać nową nazwę dziennika."),
        source("sweep.py; repeat_sweep.py; file_sweep.py; measurements/plan_example.csv.")]

    story += section(21, "Ograniczenia i dalsze prace", "Stan dojrzałości rozwiązania")
    story += [table(["Ograniczenie", "Znaczenie / kierunek rozwoju"], [
        ["Brak potwierdzeń i ARQ", "Nadano nie oznacza dostarczenia. Rozszerzenie: ACK/NACK, selektywne ponawianie brakujących bloków i wznowienie transferu."],
        ["Dalsze przyspieszanie", "Po uzyskaniu 2FSK 5 kbit/s i transferu 4FSK 2,5 kbit/s trwają próby szybszych 4FSK i 16QAM. Wymagają dalszej oceny odporności."],
        ["Brak FEC", "Powtórzenia zwiększają redundancję, ale nie zastępują kodu korekcyjnego. Rozszerzenie: kodowanie kanałowe i przeplot."],
        ["Kalibracja", "Skala V jest umowna; brak powiązania procentu PCM z mocą optyczną. Potrzebna procedura kalibracji toru."],
        ["Niepełne dane stanowiska", "Archiwum nie dokumentuje wszystkich parametrów fizycznych. Potrzebna karta pomiarowa i powtarzane serie."],
        ["Brak uwierzytelnienia", "CRC i SHA-256 sprawdzają spójność, a nie tożsamość nadawcy. Rozszerzenie zależy od przyszłego modelu użycia."],
        ["Przenośność sprzętowa", "Dostępność 96/192 kHz, pasmo i sterowniki wymagają sprawdzenia na docelowej platformie."]
    ], [139, WIDTH - 139]), Spacer(1, 14),
        note("Priorytet rozwoju", "Najpierw pomiar powtarzalnej skuteczności całego łącza i niezawodne odzyskiwanie "
             "brakujących bloków; następnie optymalizacja przepustowości. Podnoszenie samego bitratu nie rozwiązuje problemu integralności."),
        p("Rezultat obejmuje spójne oprogramowanie, jego testy oraz odnotowane po poprawie toru osiągi "
          "2FSK i skuteczny transfer zdjęć 4FSK. Zgodność plików potwierdzono przez SHA-256. Obecnie rozwijane "
          "są wyższe szybkości 4FSK i 16QAM. Pełna charakterystyka transceivera wymaga nadal powiązania "
          "wyników z parametrami i pomiarami całego toru optycznego."),
        source("ograniczenia wynikające z kodu, formatów protokołu i zakresu dostępnych danych pomiarowych.")]

    story += section(22, "Materiały źródłowe i pakiet raportowy", "Identyfikacja i ponowne wygenerowanie")
    story += [p("Dokument opracowano z repozytorium, danych archiwalnych, nowszego uzupełnienia zespołu "
        "i odebranych plików. Wyników po zastosowaniu przedwzmacniacza nie dopisywano do historycznych CSV. "
        "Poniższe grupy materiałów pozwalają prześledzić "
        "pochodzenie opisów, liczb i wykresów."),
        table(["Grupa", "Pliki odniesienia"], [
            ["Implementacja i obsługa", "README.md; modem.py; audio_runtime.py; transceiver.py; transmitter.py; receiver.py; scope.py; chat.py; text_encoding.py."],
            ["Protokoły i pomiary", "transfers.py; ipc_control.py; ipc_reference.py; sweep.py; repeat_sweep.py; file_sweep.py; plot_results.py."],
            ["Pełne serie", "measurements/ber_1x_raw.csv, ber_1x_metadata.json, ber_128B_1x_raw.csv, ber_128B_1x_metadata.json."],
            ["Serie porównawcze", "measurements/ber_128B_pomiar_1_80procent_raw.csv … _6_80procent_raw.csv i odpowiadające metadata JSON."],
            ["Wyniki po poprawie toru", "wyniki_przedwzmacniacz.json; weryfikacja_TRANSMISJA.json; TRANSMISJA/*.jpg i odpowiadające źródła; zapisTransmisji16_11.txt."],
            ["Weryfikacja", "tests/test_*.py; tests/fixtures/photo.jpg; testy_weryfikacja.json."],
            ["Dodatki do PDF", "LPTM_dokumentacja_zrodlo.md; dane_i_proweniencja.json; zestawienie_serii.csv; assets/ — wykresy PNG/PDF i diagramy SVG."]
        ], [119, WIDTH - 119], small=True), Spacer(1, 14),
        sub("Regeneracja dokumentu"),
        code("python -m pip install -r docs/raport_grantowy/requirements-docs.txt\npython docs/raport_grantowy/build_report.py"),
        p(f"Identyfikator rewizji źródeł: {commit}. Manifest zawiera rozmiary i pełne skróty SHA-256 "
          "wybranych plików. Wykresy są wyliczane z logów raw, a źródło Markdown powstaje z tych samych "
          "treści co PDF. Generator dokumentacji nie uruchamia pomiarów ani urządzeń audio."),
        source("stan repozytorium z dnia opracowania, pełna lista i skróty w dane_i_proweniencja.json.")]


if __name__ == "__main__":
    build()
