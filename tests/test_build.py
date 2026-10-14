#!/usr/bin/env python3
"""Teste les garde-fous du générateur dans une copie jetable du dépôt (rien n'est modifié ici).
Usage : python3 tests/test_build.py
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FICHIERS = ["build.py", "template.html", "contenu.json", "tokens.json", "config.json"]
resultats = []


def check(cond, msg):
    resultats.append(bool(cond))
    print(("OK     " if cond else "ECHEC  ") + msg)


def copie():
    d = Path(tempfile.mkdtemp())
    for f in FICHIERS:
        shutil.copy(ROOT / f, d / f)
    return d


def lance(d, *args):
    r = subprocess.run([sys.executable, str(d / "build.py"), *args], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def jl(p):
    return json.loads(p.read_text(encoding="utf-8"))


def je(p, o):
    p.write_text(json.dumps(o, ensure_ascii=False, indent=2), encoding="utf-8")


def modifier(d, fn):
    c = jl(d / "contenu.json")
    fn(c)
    je(d / "contenu.json", c)


def main():
    # --- le contenu actuel est valide
    d = copie()
    rc, out = lance(d, "--site-only", "--out", str(d / "o"))
    check(rc == 0, "le contenu du dépôt est valide et se construit")
    check((d / "o/site/index.html").exists(), "site/index.html produit")

    # --- erreurs de validation
    def cas(nom, fn, attendu):
        d = copie()
        modifier(d, fn)
        rc, out = lance(d, "--site-only", "--out", str(d / "o"))
        check(rc == 1 and attendu.lower() in out.lower(), f"validation : {nom}")

    cas("énigme qui ne mène pas au lieu suivant",
        lambda c: c["parcs"]["agen"]["etapes"][0].update(mene_a="Bowling"), "mene_a")
    cas("indice vide", lambda c: c["parcs"]["laval"]["etapes"][1].update(indice1=""), "indice")
    cas("témoignage vide dans la bibliothèque", lambda c: c["temoignages"]["tenue"].update(claire=""), "temoignages")
    cas("trait de témoin inconnu", lambda c: c["parcs"]["laval"]["etapes"][2]["temoin"].update(trait="couleur"), "trait")
    cas("5 étapes au lieu de 6", lambda c: c["parcs"]["agen"]["etapes"].pop(), "6")

    def ambigu(c):
        # le coupable déclaré ne se distingue plus des autres suspects
        for k in c["suspects"]:
            c["suspects"][k]["chapeau"] = True
            c["suspects"][k]["tenue"] = "x"
            c["suspects"][k]["cape"] = True
            c["suspects"][k]["objet"] = "x"
    d = copie()
    modifier(d, ambigu)
    rc, out = lance(d, "--site-only", "--out", str(d / "o"))
    check(rc == 1, "validation : coupable non identifiable de façon unique")

    # --- pas de QR/PDF sans adresse
    d = copie()
    rc, out = lance(d, "--out", str(d / "o"))
    check(rc == 1 and "base_url" in out, "impression refusée tant que l'adresse n'est pas renseignée")
    rc, out = lance(d, "--base", "https://exemple.invalid/A_REMPLIR/", "--out", str(d / "o"))
    check(rc == 1, "impression refusée avec une adresse contenant A_REMPLIR")

    # --- verrou après impression
    d = copie()
    cfg = jl(d / "config.json")
    cfg["base_url"] = "https://enquete.exemple.fr/"
    je(d / "config.json", cfg)
    rc, out = lance(d, "--figer", "--site-only", "--out", str(d / "o"))
    check(rc == 0 and jl(d / "config.json")["imprime"] is True, "--figer enregistre l'état imprimé")
    rc, out = lance(d, "--site-only", "--out", str(d / "o"))
    check(rc == 0, "après figer : le site se reconstruit")

    # texte modifié : autorisé
    modifier(d, lambda c: c["parcs"]["agen"]["etapes"][0].update(enigme=c["parcs"]["agen"]["etapes"][0]["enigme"] + " Courage !"))
    rc, out = lance(d, "--site-only", "--out", str(d / "o"))
    check(rc == 0, "après figer : modifier un texte reste autorisé")

    # ordre des lieux modifié : refusé
    d2 = copie()
    cfg = jl(d2 / "config.json"); cfg["base_url"] = "https://enquete.exemple.fr/"; je(d2 / "config.json", cfg)
    lance(d2, "--figer", "--site-only", "--out", str(d2 / "o"))

    def permute(c):
        e = c["parcs"]["agen"]["etapes"]
        e[1]["lieu"], e[2]["lieu"] = e[2]["lieu"], e[1]["lieu"]
        for i in range(5):
            e[i]["mene_a"] = e[i + 1]["lieu"]
    modifier(d2, permute)
    rc, out = lance(d2, "--site-only", "--out", str(d2 / "o"))
    check(rc == 1 and "REFUSÉ" in out, "après figer : changer l'ordre des lieux est refusé")
    rc, out = lance(d2, "--site-only", "--forcer", "--out", str(d2 / "o"))
    check(rc == 0, "après figer : --forcer permet de passer outre")

    # tokens modifiés : refusé
    d3 = copie()
    cfg = jl(d3 / "config.json"); cfg["base_url"] = "https://enquete.exemple.fr/"; je(d3 / "config.json", cfg)
    lance(d3, "--figer", "--site-only", "--out", str(d3 / "o"))
    tk = jl(d3 / "tokens.json"); tk["parcs"]["agen"][0] = "aaaaaaa"; je(d3 / "tokens.json", tk)
    rc, out = lance(d3, "--site-only", "--out", str(d3 / "o"))
    check(rc == 1 and "tokens.json" in out, "après figer : toucher à tokens.json est refusé")

    # nouveau parc : refusé (il faudrait de nouveaux QR)
    d4 = copie()
    cfg = jl(d4 / "config.json"); cfg["base_url"] = "https://enquete.exemple.fr/"; je(d4 / "config.json", cfg)
    lance(d4, "--figer", "--site-only", "--out", str(d4 / "o"))
    modifier(d4, lambda c: c["parcs"].update(nouveau=json.loads(json.dumps(c["parcs"]["agen"]))))
    rc, out = lance(d4, "--site-only", "--out", str(d4 / "o"))
    check(rc == 1, "après figer : ajouter un parc est refusé")

    # changer l'adresse : refusé (hors --site-only)
    d5 = copie()
    cfg = jl(d5 / "config.json"); cfg["base_url"] = "https://enquete.exemple.fr/"; je(d5 / "config.json", cfg)
    lance(d5, "--figer", "--site-only", "--out", str(d5 / "o"))
    rc, out = lance(d5, "--base", "https://autre.exemple.fr/", "--out", str(d5 / "o"))
    check(rc == 1 and "adresse" in out.lower(), "après figer : changer l'adresse est refusé")

    print(f"\nRÉSULTAT : {'TOUT OK' if all(resultats) else 'ÉCHECS'} ({sum(resultats)}/{len(resultats)} vérifications)")
    return 0 if all(resultats) else 1


if __name__ == "__main__":
    sys.exit(main())
