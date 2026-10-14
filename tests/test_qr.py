#!/usr/bin/env python3
"""Fabrique les feuilles QR et vérifie qu'un lecteur les décode vers la bonne adresse.
Usage : python3 tests/test_qr.py   (nécessite pdftoppm, opencv et zxing-cpp)
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import zxingcpp

ROOT = Path(__file__).resolve().parent.parent
resultats = []


def check(cond, msg):
    resultats.append(bool(cond))
    print(("OK     " if cond else "ECHEC  ") + msg)


def decoder(png):
    img = cv2.imread(str(png))
    lus = zxingcpp.read_barcodes(img)      # décodeur de référence (ZXing)
    if lus:
        return lus[0].text
    txt, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
    if txt:
        return txt
    h, w = img.shape[:2]
    for sc in (0.6, 0.4):
        txt, _, _ = cv2.QRCodeDetector().detectAndDecode(cv2.resize(img, (int(w * sc), int(h * sc))))
        if txt:
            return txt
    return ""


def main():
    c = json.loads((ROOT / "contenu.json").read_text(encoding="utf-8"))
    tk = json.loads((ROOT / "tokens.json").read_text(encoding="utf-8"))
    base = "https://enquete.exemple.fr/jeu/"
    out = Path(tempfile.mkdtemp())
    r = subprocess.run([sys.executable, str(ROOT / "build.py"), "--sans-verrou", "--base", base, "--out", str(out)],
                       capture_output=True, text=True)
    check(r.returncode == 0, "build complet avec adresse (" + (r.stderr.strip().splitlines()[-1] if r.returncode else "ok") + ")")
    check((out / "print/equipe/fiche-equipe.pdf").exists(), "fiche équipe produite")
    for pid in c["parcs"]:
        pdfs = list((out / "print/qr").glob(f"*{pid}*.pdf"))
        check(len(pdfs) == 1, f"{pid} : une feuille PDF")
        if not pdfs:
            continue
        pre = out / f"{pid}"
        subprocess.run(["pdftoppm", "-r", "150", "-png", str(pdfs[0]), str(pre)], check=True)
        pngs = sorted(out.glob(f"{pid}-*.png"))
        check(len(pngs) == 6, f"{pid} : 6 pages (une par poste)")
        for i, png in enumerate(pngs):
            attendu = f"{base}?e={tk['parcs'][pid][i]}"
            lu = decoder(png)
            check(lu == attendu, f"{pid} poste {i + 1} : QR décodé = {attendu}")
        info = subprocess.run(["pdfinfo", str(pdfs[0])], capture_output=True, text=True).stdout
        check("A4" in info or "595" in info, f"{pid} : format A4")
    print(f"\nRÉSULTAT : {'TOUT OK' if all(resultats) else 'ÉCHECS'} ({sum(resultats)}/{len(resultats)} vérifications)")
    return 0 if all(resultats) else 1


if __name__ == "__main__":
    sys.exit(main())
