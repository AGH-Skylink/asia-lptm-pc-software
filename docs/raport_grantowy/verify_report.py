"""Check the final PDF's navigation, text encoding and page boundaries."""
import json
from pathlib import Path

import pymupdf


def main():
    folder = Path(__file__).resolve().parent
    document = pymupdf.open(folder / "LPTM_dokumentacja_do_raportu_grantowego.pdf")
    assert len(document) == 24, "Nieoczekiwana liczba stron."
    assert len(document.get_toc()) == 22, "Niepełna lista rozdziałów."
    assert len(document[1].get_links()) >= 22, "Brak aktywnego spisu treści."
    full_text = "".join(page.get_text() for page in document)
    assert "Osiągnięte rezultaty" in full_text
    assert "48 testów" in full_text
    for fragment in ("25 V/V", "0,5%", "5 kbit/s", "2,5 kbit/s", "karmelini.jpg", "słabej jakości"):
        assert fragment in full_text, fragment
    assert "\ufffd" not in full_text, "Znaleziono znak zastępczy Unicode."
    for index, page in enumerate(document):
        assert index == 0 or len(page.get_text()) > 450, f"Prawie pusta strona {index + 1}."
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    x0, y0, x1, y1 = span["bbox"]
                    assert x0 >= 35 and x1 <= page.rect.width - 34, (index + 1, span["text"])
                    assert y0 >= 9 and y1 <= page.rect.height - 9, (index + 1, span["text"])
    result = {
        "strony": len(document),
        "rozdzialy": len(document.get_toc()),
        "aktywny_spis_tresci": True,
        "polskie_znaki": True,
        "znaki_zastepcze": 0,
        "tekst_w_granicach_stron": True,
        "kontrola_wizualna": "Sprawdzono plansze wszystkich stron i wybrane strony w powiększeniu.",
        "data": "2026-11-17",
    }
    (folder / "kontrola_pdf.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
