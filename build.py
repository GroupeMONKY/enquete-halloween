#!/usr/bin/env python3
"""Générateur du jeu "L'enquête de la mascotte".

Commandes courantes
    python3 build.py --site-only        # régénère site/index.html (le seul fichier publié)
    python3 build.py                    # + feuilles QR (PDF) et fiche équipe, dans print/
    python3 build.py --figer            # à lancer UNE FOIS, quand les QR sont imprimés

Lit contenu.json (textes), template.html (design et logique), tokens.json (codes des QR)
et config.json (adresse du jeu). Écrit site/index.html et, sans --site-only, print/.

Après --figer, le générateur refuse tout changement qui rendrait les QR collés dans les
parcs inutilisables : adresse, codes, nombre ou ordre des postes. Les textes, le design
et la logique restent modifiables à volonté.
"""
import argparse
import copy
import datetime
import hashlib
import html
import json
import random
import secrets
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"   # pas de 0/o, 1/l/i : lisible à la main
A_REMPLIR = "A_REMPLIR"
TRAITS = ("chapeau", "tenue", "cape", "objet")


class Erreur(Exception):
    pass


def coupable_du_jour(c, pid, jour):
    """Le coupable avance d'un suspect par jour (heure de Paris), à partir de celui du premier jour.
    MÊME formule que dans template.html (coupableDuJour)."""
    ids = list(c["suspects"])
    depart = ids.index(c["parcs"][pid]["coupable"])
    ecart = (jour - datetime.date.fromisoformat(c["periode"]["debut"])).days
    return ids[(depart + ecart) % len(ids)]


def texte_temoignage(c, trait, suspect):
    """Ce que dit un témoin à propos d'un trait du coupable (phrases de 'temoignages' dans contenu.json)."""
    biblio = c["temoignages"][trait]
    valeur = suspect[trait]
    if trait == "objet":
        return biblio.replace("{objet}", valeur)
    return biblio["oui" if valeur is True else "non" if valeur is False else valeur]


def lire_json(chemin):
    return json.loads(Path(chemin).read_text(encoding="utf-8"))


def ecrire_json(chemin, obj):
    Path(chemin).write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def lieux_du_parc(p):
    return [e["lieu"] for e in p["etapes"]]


def de_parc(nom):
    return ("d'" if nom[0].upper() in "AEIOUYÂÊÉÈ" else "de ") + nom


def normaliser_base(base):
    base = (base or "").strip()
    if base and not (base.endswith("/") or base.endswith(".html")):
        base += "/"
    return base


def base_valide(base):
    return base.startswith(("http://", "https://")) and A_REMPLIR not in base


# ---------------------------------------------------------------- validation du contenu
def valider(c):
    """Vérifie le contenu. Lève Erreur avec TOUS les problèmes trouvés. Renvoie les avertissements."""
    err, avert = [], []
    for cle in ("marque", "titre", "mascotte", "recompense", "periode", "messages", "recits",
                "suspects", "parcs", "mots_du_jour", "temoignages"):
        if cle not in c:
            err.append(f"contenu.json : la clé '{cle}' est absente.")
    if err:
        raise Erreur("\n".join(err))

    try:
        debut = datetime.date.fromisoformat(c["periode"]["debut"])
        fin = datetime.date.fromisoformat(c["periode"]["fin"])
        if fin < debut:
            err.append("periode : 'fin' est avant 'debut'.")
        elif len(c["mots_du_jour"]) < (fin - debut).days + 1:
            avert.append(f"Il y a moins de mots du jour ({len(c['mots_du_jour'])}) que de jours "
                         f"({(fin - debut).days + 1}) : des mots seront réutilisés.")
    except (KeyError, ValueError):
        err.append("periode : 'debut' et 'fin' doivent être des dates AAAA-MM-JJ.")

    v = c.get("validite_ecran_minutes", 60)
    if not isinstance(v, int) or isinstance(v, bool) or not 5 <= v <= 24 * 60:
        err.append("validite_ecran_minutes : un nombre entier de minutes entre 5 et 1440.")
    suspects = c["suspects"]
    for sid, s in suspects.items():
        manque = [t for t in ("nom",) + TRAITS if t not in s]
        if manque:
            err.append(f"suspect '{sid}' : champs manquants {manque}.")
    if err:
        raise Erreur("\n".join(err))

    # bibliothèque des témoignages : une phrase non vide pour chaque trait et chaque valeur utilisée
    biblio = c["temoignages"]
    for trait in TRAITS:
        if trait not in biblio:
            err.append(f"temoignages : la phrase du trait '{trait}' est absente.")
    for trait in TRAITS:
        if trait not in biblio:
            continue
        if trait == "objet":
            if "{objet}" not in str(biblio[trait]):
                err.append("temoignages.objet : la phrase doit contenir {objet}.")
            continue
        for sid, s in suspects.items():
            cle = "oui" if s[trait] is True else "non" if s[trait] is False else s[trait]
            if not isinstance(biblio[trait], dict) or not str(biblio[trait].get(cle, "")).strip():
                err.append(f"temoignages.{trait} : phrase '{cle}' vide ou absente (utilisée par le suspect '{sid}').")
    if err:
        raise Erreur("\n".join(err))

    for pid, p in c["parcs"].items():
        def e(msg):
            err.append(f"parc '{pid}' : {msg}")
        for k in ("nom", "coupable", "recompense_lieu", "etapes"):
            if k not in p:
                e(f"champ '{k}' manquant.")
        if "coupable" not in p or "etapes" not in p:
            continue
        if p["coupable"] not in suspects:
            e(f"coupable inconnu : '{p['coupable']}'.")
        etapes = p["etapes"]
        if len(etapes) != 6:
            e(f"il faut exactement 6 étapes (il y en a {len(etapes)}).")
            continue
        for i, et in enumerate(etapes, start=1):
            def f(msg):
                err.append(f"parc '{pid}', poste {i} : {msg}")
            if et.get("poste") != i:
                f(f"'poste' doit valoir {i}.")
            if not str(et.get("lieu", "")).strip():
                f("'lieu' est vide.")
            if i == 1 and et.get("lieu") != "Accueil":
                f("le poste 1 doit être 'Accueil'.")
            if i < 6:
                if et.get("mene_a") != etapes[i]["lieu"]:
                    f(f"'mene_a' doit être '{etapes[i]['lieu']}' (le lieu du poste suivant).")
                for k in ("enigme", "indice1", "indice2"):
                    if not str(et.get(k, "")).strip():
                        f(f"'{k}' est vide.")
            else:
                for k in ("enigme", "indice1", "indice2", "mene_a"):
                    if k in et:
                        f(f"le dernier poste n'a pas de '{k}'.")
            if 2 <= i <= 5:
                t = et.get("temoin")
                if not isinstance(t, dict):
                    f("'temoin' manquant.")
                else:
                    for k in ("icone", "nom", "trait"):
                        if not str(t.get(k, "")).strip():
                            f(f"temoin.{k} est vide.")
                    if t.get("trait") not in TRAITS:
                        f(f"temoin.trait doit être l'un de {list(TRAITS)}.")
            elif "temoin" in et:
                f("seuls les postes 2 à 5 ont un témoin.")
        # chaque suspect sera coupable un jour : il doit être le seul compatible avec ses 4 témoignages
        if not err:
            traits = [et["temoin"]["trait"] for et in etapes[1:5]]
            for sid, cand in suspects.items():
                compatibles = [k for k, s in suspects.items() if all(s[t] == cand[t] for t in traits)]
                if compatibles != [sid]:
                    e(f"si '{sid}' est le coupable, les témoignages ne le désignent pas seul "
                      f"(compatibles : {compatibles}). Les traits évoqués sont {traits}.")
    if err:
        raise Erreur("\n".join(err))
    return avert


# ---------------------------------------------------------------- codes des QR
def charger_tokens(parcs, verrouille):
    chemin = ROOT / "tokens.json"
    existant = lire_json(chemin) if chemin.exists() else None
    tk = copy.deepcopy(existant) if existant else {}
    tk.setdefault("sel", secrets.token_hex(4))
    tk.setdefault("parcs", {})
    pris = {t for liste in tk["parcs"].values() for t in liste}
    for pid in parcs:
        liste = tk["parcs"].setdefault(pid, [])
        while len(liste) < 6:
            t = "".join(secrets.choice(ALPHABET) for _ in range(7))
            if t not in pris:
                liste.append(t)
                pris.add(t)
    if tk != existant:
        if verrouille:
            raise Erreur("Il faudrait créer de nouveaux codes de QR, mais les QR sont déjà imprimés "
                         "(config.json : imprime = true). Ajouter un parc ou un poste oblige à "
                         "imprimer de nouvelles affiches. Si c'est voulu, relance avec --forcer.")
        ecrire_json(chemin, tk)
    return tk


def empreinte(tk):
    return hashlib.sha256(json.dumps(tk, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------- verrou après impression
def verifier_verrou(cfg, c, tk, base, avec_adresse):
    if not cfg.get("imprime"):
        return
    pb = []
    if avec_adresse and base != cfg.get("base_url"):
        pb.append(f"L'adresse a changé : figée sur {cfg.get('base_url')}, demandée {base}. "
                  "Les QR déjà collés pointent vers l'adresse figée.")
    if empreinte(tk) != cfg.get("tokens_empreinte"):
        pb.append("tokens.json a changé depuis l'impression : les QR collés ne correspondraient plus aux étapes.")
    actuels = {pid: lieux_du_parc(p) for pid, p in c["parcs"].items()}
    if actuels != cfg.get("lieux"):
        pb.append("Les parcs ou l'ordre des lieux ont changé depuis l'impression. "
                  "Figé : " + json.dumps(cfg.get("lieux"), ensure_ascii=False))
    if pb:
        raise Erreur("CHANGEMENT REFUSÉ : il casserait des QR déjà imprimés.\n- " + "\n- ".join(pb) +
                     "\nSi tu réimprimes volontairement toutes les affiches, relance avec --forcer, "
                     "puis --figer --forcer.")


def figer(cfg, c, tk, base):
    if not base_valide(base):
        raise Erreur("Renseigne d'abord l'adresse définitive du jeu : base_url dans config.json (ou --base).")
    cfg.update({
        "base_url": base,
        "imprime": True,
        "tokens_empreinte": empreinte(tk),
        "lieux": {pid: lieux_du_parc(p) for pid, p in c["parcs"].items()},
        "fige_le": datetime.date.today().isoformat(),
    })
    ecrire_json(ROOT / "config.json", cfg)


# ---------------------------------------------------------------- données du site
def construire_donnees(c, tk):
    suspects = c["suspects"]
    mots = list(c["mots_du_jour"])
    random.Random(2026).shuffle(mots)

    data = {
        "titre": c["titre"], "mascotte": c["mascotte"], "recompense": c["recompense"],
        "periode": c["periode"], "messages": c["messages"], "recits": c["recits"],
        "suspects": {k: {"nom": v["nom"]} for k, v in suspects.items()},
        "suspectsListe": list(suspects.keys()),
        "mots": mots, "parcs": {}, "tokens": {},
        "validiteMinutes": c.get("validite_ecran_minutes", 60),
    }
    ids = list(suspects)
    for pid, p in c["parcs"].items():
        etapes = []
        for i, et in enumerate(p["etapes"], start=1):
            e = {"lieu": et["lieu"]}
            if i < 6:
                e["vers"] = {"enigme": et["enigme"], "indice1": et["indice1"], "indice2": et["indice2"]}
            if 2 <= i <= 5:
                t = et["temoin"]
                e["temoin"] = {"icone": t["icone"], "nom": t["nom"]}
            etapes.append(e)
        traits = [et["temoin"]["trait"] for et in p["etapes"][1:5]]
        data["parcs"][pid] = {
            "nom": p["nom"], "etapes": etapes,
            "depart": ids.index(p["coupable"]),
            # les 4 témoignages selon le coupable du jour
            "variantes": {sid: [texte_temoignage(c, t, suspects[sid]) for t in traits] for sid in ids},
            "recompenseLieu": p["recompense_lieu"],
        }
        for s, t in enumerate(tk["parcs"][pid], start=1):
            data["tokens"][t] = {"p": pid, "s": s}
    return data


def ecrire_site(data, out):
    tpl = (ROOT / "template.html").read_text(encoding="utf-8")
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = tpl.replace("/*__DATA__*/null", js)
    chemin = out / "site" / "index.html"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(page, encoding="utf-8")
    # les images (site/img) font partie du site : on les recopie si on construit hors du dépôt
    src_img, dst_img = ROOT / "site" / "img", chemin.parent / "img"
    if src_img.is_dir() and src_img.resolve() != dst_img.resolve():
        shutil.copytree(src_img, dst_img, dirs_exist_ok=True)
    return chemin


# ---------------------------------------------------------------- feuilles QR
# Charte de chaque parc pour les feuilles (couleurs reprises du jeu : voir THEMES dans template.html)
FEUILLES_THEMES = {
    "agen":         {"haut": "#27465f", "bas": "#0d1522", "titre": "#FFFFFF", "kicker": "#F5A623",
                     "bouton": "#F5A623", "bouton_txt": "#161d2a", "cadre": "#F5A623", "texte": "#DCE6F1", "pos": "50% 20%"},
    "chateauroux":  {"haut": "#0e0e14", "bas": "#4a1216", "titre": "#F0E9CD", "kicker": "#FF5A60",
                     "bouton": "#E11F26", "bouton_txt": "#FFFFFF", "cadre": "#E11F26", "texte": "#E8DFC0", "pos": "50% 55%"},
    "laval":        {"haut": "#cd3a50", "bas": "#b02f45", "titre": "#FFF4EE", "kicker": "#530b2d",
                     "bouton": "#FBF1E2", "bouton_txt": "#530b2d", "cadre": "#FBF1E2", "texte": "#FFF4EE",
                     "rayures": True, "pos": "50% 58%"},
    "montdemarsan": {"haut": "#3f1d68", "bas": "#1f0f38", "titre": "#FBF2DA", "kicker": "#F7931E",
                     "bouton": "#E0145A", "bouton_txt": "#FFFFFF", "cadre": "#F7931E", "texte": "#E6DAF5",
                     "fanions": True, "pos": "50% 12%"},
}
FEUILLE_PAR_DEFAUT = {"haut": "#2A1A45", "bas": "#2A1A45", "titre": "#FFFFFF", "kicker": "#FFC93C",
                      "bouton": "#FFC93C", "bouton_txt": "#1E1233", "cadre": "#FFC93C", "texte": "#E7E0F5", "pos": "50% 40%"}
FANIONS_SVG = ('<svg viewBox="0 0 400 48" preserveAspectRatio="none">'
               '<path d="M0 6Q200 18 400 6" fill="none" stroke="#F3E9C2" stroke-width="2"/>'
               + "".join(f'<path d="M{4 + i * 39.5} 8h32v24l-16 12-16-12Z" fill="{["#E0145A", "#1AA0A5", "#F7931E", "#F3E9C2"][i % 4]}"/>'
                         for i in range(10)) + '</svg>')

CSS_FEUILLES = """
@page { size: A4; margin: 0 }
* { box-sizing: border-box }
html, body { margin: 0; padding: 0 }
body { font-family: "Avenir Next Rounded","Arial Rounded MT Bold","Trebuchet MS",Arial,sans-serif; color: #1E1233 }
.page { width: 210mm; height: 297mm; padding: 13mm 15mm 10mm; display: flex; flex-direction: column; align-items: center; page-break-after: always; position: relative; overflow: hidden; color: var(--texte) }
.page:last-child { page-break-after: auto }
.fond { position: absolute; inset: 0; background: linear-gradient(180deg, var(--haut), var(--bas) 75%) }
.rayures .fond { background: repeating-linear-gradient(90deg, rgba(255,255,255,.07) 0 17mm, transparent 17mm 34mm), linear-gradient(180deg, var(--haut), var(--bas) 75%) }
.cadre { position: absolute; inset: 6mm; border: 1.6mm solid var(--cadre); border-radius: 9mm; opacity: .9 }
.fanions { position: absolute; left: 0; right: 0; top: 0; height: 15mm; z-index: 1 }
.fanions svg { width: 100%; height: 100% }
.page > * { z-index: 1 }
.logo { height: 18mm; width: auto; margin-top: 3mm }
.kicker { font-size: 6mm; font-weight: 800; color: var(--kicker); margin: 4mm 0 1.5mm; text-transform: uppercase; letter-spacing: .06em; text-align: center }
h1 { font-size: 14mm; line-height: 1.04; margin: 0; letter-spacing: -.02em; font-weight: 800; color: var(--titre); text-align: center }
.sous { font-size: 5.8mm; margin: 3mm 6mm 0; line-height: 1.3; text-align: center }
.scene { width: 120mm; height: 43mm; object-fit: cover; object-position: var(--pos); border-radius: 6mm; margin-top: 5mm; border: .9mm solid rgba(255,255,255,.35) }
.bouton { margin-top: 5mm; background: var(--bouton); color: var(--bouton_txt); border-radius: 12mm; padding: 3.4mm 10mm; font-size: 7.4mm; font-weight: 800; text-align: center; box-shadow: 0 1.4mm 0 rgba(0,0,0,.25) }
.fleche { margin-top: 1.5mm; font-size: 6mm; line-height: 1; color: var(--bouton) }
.qr { background: #fff; border: 1.4mm solid var(--cadre); border-radius: 7mm; padding: 6mm; margin-top: 1.5mm; width: 96mm; height: 96mm; display: flex }
.qr svg { width: 100%; height: 100% }
.regle { margin-top: 4mm; font-size: 4.4mm; font-weight: 600; text-align: center; opacity: .92 }
.officiel { margin-top: auto; font-size: 4mm; font-weight: 700; text-align: center; opacity: .85 }
.pied { margin-top: 1.5mm; text-align: center; font-size: 3.2mm; opacity: .7 }
"""


def _img64(chemin):
    import base64
    return "data:image/webp;base64," + base64.b64encode(Path(chemin).read_bytes()).decode("ascii")


def feuille_html(parc, num, lieu, url, c, domaine, pid=None):
    import segno
    qr = segno.make(url, error="q", micro=False)
    svg = qr.svg_inline(border=0, dark="#1E1233", light="#FFFFFF", omitsize=True, scale=1)
    th = FEUILLES_THEMES.get(pid, FEUILLE_PAR_DEFAUT)
    nom_parc = html.escape(de_parc(parc['nom']))
    regle = ""
    if num == 1:
        kicker = f"Parc {nom_parc}"
        titre = f"{html.escape(c['mascotte'])} a disparu !"
        sous = f"Aide-nous à le retrouver : mène l'enquête dans tout le parc et gagne {html.escape(c['recompense'])}."
        bouton = "Scanne pour commencer l'enquête"
        regle = "Un adulte + un enfant · 6 postes à trouver · environ 15 minutes"
        pied = f"Parc {de_parc(parc['nom'])} · poste 1/6 · {lieu} (affiche de départ)"
    elif num < 6:
        kicker = f"Poste {num} sur 6"
        titre = "Tu as trouvé<br>le bon endroit !"
        sous = "Un témoin attend de te parler. Scanne le QR code pour l'écouter."
        bouton = "Scanne pour continuer l'enquête"
        pied = f"Parc {de_parc(parc['nom'])} · poste {num}/6 · emplacement : {lieu}"
    else:
        kicker = "Dernier poste"
        titre = "Il est temps de<br>désigner le coupable !"
        sous = "Tu as interrogé tous les témoins. Scanne le QR code pour relire leurs indices et choisir."
        bouton = "Scanne pour désigner le coupable"
        pied = f"Parc {de_parc(parc['nom'])} · poste 6/6 · {lieu}"
    images = ROOT / "site" / "img"
    logo = f'<img class="logo" src="{_img64(images / "logo-blanc.webp")}" alt="Monky">' if (images / "logo-blanc.webp").exists() else ""
    scene_f = images / f"{pid}-scene.webp"
    scene = f'<img class="scene" src="{_img64(scene_f)}" alt="">' if scene_f.exists() else ""
    fanions = f'<div class="fanions">{FANIONS_SVG}</div>' if th.get("fanions") else ""
    style = "".join(f"--{k}:{v};" for k, v in th.items() if isinstance(v, str))
    classe = "page rayures" if th.get("rayures") else "page"
    officiel = f"Jeu officiel des parcs {html.escape(c['marque'])} · {html.escape(domaine)}"
    return f"""<section class="{classe}" style="{style}"><div class="fond"></div><div class="cadre"></div>{fanions}
    {logo}
    <p class="kicker">{kicker}</p>
    <h1>{titre}</h1>
    <p class="sous">{sous}</p>
    {scene}
    <div class="bouton">{html.escape(bouton)}</div>
    <div class="fleche">&#9660;</div>
    <div class="qr">{svg}</div>
    <div class="regle">{regle}</div>
    <div class="officiel">{officiel}</div>
    <div class="pied">{html.escape(pied)} · ne pas découper cette ligne</div></section>"""


def ecrire_feuilles(c, tk, base, out, rendre_pdf):
    dossier = out / "print" / "qr"
    dossier.mkdir(parents=True, exist_ok=True)
    domaine = urlparse(base).netloc
    sorties = []
    for pid, p in c["parcs"].items():
        pages = []
        for num, (lieu, tok) in enumerate(zip(lieux_du_parc(p), tk["parcs"][pid]), start=1):
            pages.append(feuille_html(p, num, lieu, f"{base}?e={tok}", c, domaine, pid))
        doc = (f"<!doctype html><html lang='fr'><head><meta charset='utf-8'><title>QR {p['nom']}</title>"
               f"<style>{CSS_FEUILLES}</style></head><body>{''.join(pages)}</body></html>")
        h = dossier / f"QR-{pid}.html"
        h.write_text(doc, encoding="utf-8")
        sorties.append((h, dossier / f"QR-{pid}.pdf"))
    rendre_pdf(sorties)
    for h, _ in sorties:
        h.unlink()
    return [pdf for _, pdf in sorties]


# ---------------------------------------------------------------- fiche équipe
def mot_du_jour(mots, debut, jour):
    return mots[(jour - debut).days % len(mots)]


def duree_fr(minutes):
    if minutes % 60 == 0:
        h = minutes // 60
        return f"{h} heure" + ("s" if h > 1 else "")
    return f"{minutes} minutes"


def ecrire_fiche(c, data, out, rendre_pdf):
    debut = datetime.date.fromisoformat(c["periode"]["debut"])
    fin = datetime.date.fromisoformat(c["periode"]["fin"])
    jours_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    mois_fr = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
               "septembre", "octobre", "novembre", "décembre"]
    def num(d):
        return "1er" if d.day == 1 else str(d.day)

    lignes, j = [], debut
    while j <= fin:
        lignes.append((f"{jours_fr[j.weekday()]} {num(j)} {mois_fr[j.month-1]}", mot_du_jour(data["mots"], debut, j)))
        j += datetime.timedelta(days=1)
    moitie = (len(lignes) + 1) // 2

    def tableau(rows):
        return "<table>" + "".join(f"<tr><td>{html.escape(a)}</td><td class='m'>{html.escape(b)}</td></tr>" for a, b in rows) + "</table>"

    lieu_reco = sorted({p["recompense_lieu"] for p in c["parcs"].values()})
    css = """
    @page { size: A4; margin: 0 }
    * { box-sizing: border-box }
    body { margin: 0; font-family: "Avenir Next Rounded","Trebuchet MS",Arial,sans-serif; color: #1E1233; font-size: 11pt; line-height: 1.4 }
    .p { width: 210mm; height: 297mm; padding: 16mm 18mm; }
    h1 { font-size: 22pt; margin: 0 0 2mm; color: #2A1A45 }
    h2 { font-size: 13pt; margin: 6mm 0 2mm; color: #F26B1D }
    p, li { margin: 0 0 1.5mm }
    ol, ul { margin: 0; padding-left: 5mm }
    .cols { display: flex; gap: 8mm }
    .cols > div { flex: 1 }
    table { border-collapse: collapse; width: 100% }
    td { padding: 1.4mm 2mm; border-bottom: .3mm solid #D9D0EC; font-size: 10pt }
    td.m { font-weight: 800; letter-spacing: .03em; text-align: right }
    .note { background: #FFF4D1; border-radius: 3mm; padding: 3mm 4mm; margin-top: 4mm; font-size: 10pt }
    """
    corps = f"""<section class="p">
    <h1>Fiche équipe : {html.escape(c['titre'])}</h1>
    <p>Jeu de piste Halloween pour les familles, du {num(debut)} {mois_fr[debut.month-1]} au {num(fin)} {mois_fr[fin.month-1]}. Un adulte et un enfant scannent 6 QR codes dans le parc, puis désignent le coupable sur leur téléphone. S'ils réussissent, ils gagnent <b>{html.escape(c['recompense'])}</b>.</p>

    <h2>Chaque matin (2 minutes)</h2>
    <ol>
      <li>Passer devant les 6 affiches de votre parc : toutes en place, propres, bien à plat, à hauteur d'enfant (environ 1 mètre).</li>
      <li>Une affiche abîmée ou arrachée : la réimprimer à partir du PDF du parc et la recoller. Sans elle, les familles sont bloquées à cette étape.</li>
    </ol>

    <h2>Quand une famille se présente pour sa récompense</h2>
    <ol>
      <li>Elle vous montre l'écran de victoire <b>en direct</b> sur son téléphone, à {html.escape(' / '.join(lieu_reco))}.</li>
      <li>Vérifiez que le <b>mot du jour</b> affiché correspond au tableau ci-dessous, et que l'heure défile et <b>correspond à l'heure réelle</b> (une capture d'écran ne défile pas).</li>
      <li>Vérifiez la mention <b>« À présenter avant … h … »</b> : l'écran n'est valable que {html.escape(duree_fr(c.get('validite_ecran_minutes', 60)))}. Passé ce délai, il affiche « Cet écran a expiré » : ne créditez pas (sauf geste de votre part).</li>
      <li>Créditez {html.escape(c['recompense'])}. Une récompense par famille et par jour.</li>
    </ol>
    <div class="note">Si le mot ne correspond pas, ne créditez pas : dites simplement à la famille que l'écran n'est pas celui du jour et invitez-la à refaire l'enquête.</div>

    <h2>Mot du jour</h2>
    <div class="cols"><div>{tableau(lignes[:moitie])}</div><div>{tableau(lignes[moitie:])}</div></div>

    <h2>En cas de souci</h2>
    <ul>
      <li>Le QR ne se scanne pas : vérifier qu'il est bien à plat, propre et non plié. S'il est abîmé, le réimprimer à partir du PDF du parc.</li>
      <li>La page ne charge pas : le réseau mobile est faible à cet endroit ; la famille peut se connecter au wifi du parc s'il existe.</li>
      <li>Une famille bloquée : le jeu propose un coup de pouce, puis le nom du lieu. Vous pouvez aussi lui indiquer la zone.</li>
    </ul>
    </section>"""
    doc = f"<!doctype html><html lang='fr'><head><meta charset='utf-8'><title>Fiche équipe</title><style>{css}</style></head><body>{corps}</body></html>"
    dossier = out / "print" / "equipe"
    dossier.mkdir(parents=True, exist_ok=True)
    h = dossier / "fiche-equipe.html"
    h.write_text(doc, encoding="utf-8")
    rendre_pdf([(h, dossier / "fiche-equipe.pdf")])
    h.unlink()
    return dossier / "fiche-equipe.pdf"


def ecrire_liens_test(c, tk, base, out):
    lignes = []
    for pid, p in c["parcs"].items():
        lignes.append(f"<h2>{html.escape(p['nom'])}</h2><table><tr><th>Poste</th><th>Lieu</th><th>Lien de test</th></tr>")
        for num, (lieu, tok) in enumerate(zip(lieux_du_parc(p), tk["parcs"][pid]), start=1):
            u = f"{base}?e={tok}&test=1"
            lignes.append(f"<tr><td>{num}</td><td>{html.escape(lieu)}</td><td><a href='{u}'>{u}</a></td></tr>")
        lignes.append("</table>")
    doc = ("<!doctype html><html lang='fr'><head><meta charset='utf-8'><meta name='robots' content='noindex'>"
           "<title>Liens de test (ne pas mettre en ligne)</title>"
           "<style>body{font-family:system-ui,sans-serif;max-width:900px;margin:24px auto;padding:0 16px}"
           "td,th{border-bottom:1px solid #ddd;padding:6px 8px;text-align:left;font-size:14px}"
           "table{border-collapse:collapse;width:100%;margin-bottom:24px}h2{margin-top:28px}"
           ".n{background:#fff4d1;padding:10px 14px;border-radius:8px}</style></head><body>"
           "<h1>Liens de test</h1><p class='n'>Le paramètre <code>test=1</code> contourne les dates d'ouverture. "
           "Ajoutez <code>&amp;date=2026-10-20</code> pour simuler un jour précis et vérifier le mot du jour. "
           "<b>Ne mettez pas ce fichier en ligne.</b></p>" + "".join(lignes) + "</body></html>")
    dossier = out / "print" / "equipe"
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "liens-test.html").write_text(doc, encoding="utf-8")


def rendre_pdf(paires):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        for src, dst in paires:
            pg = nav.new_page()
            pg.goto(src.resolve().as_uri())
            pg.pdf(path=str(dst), prefer_css_page_size=True, print_background=True)
            pg.close()
        nav.close()


# ---------------------------------------------------------------- programme principal
def main():
    ap = argparse.ArgumentParser(description="Génère le jeu et, au besoin, les feuilles à imprimer.")
    ap.add_argument("--base", help="adresse du jeu (sinon : base_url de config.json)")
    ap.add_argument("--out", default=str(ROOT), help="dossier de sortie (défaut : le dépôt)")
    ap.add_argument("--site-only", action="store_true", help="ne génère que site/index.html")
    ap.add_argument("--figer", action="store_true", help="à lancer une fois, quand les QR sont imprimés")
    ap.add_argument("--forcer", action="store_true", help="passer outre le verrou (réimpression complète)")
    ap.add_argument("--sans-verrou", action="store_true", help="réservé aux tests automatiques")
    a = ap.parse_args()

    try:
        c = lire_json(ROOT / "contenu.json")
        for w in valider(c):
            print("Attention :", w)
        cfg = lire_json(ROOT / "config.json") if (ROOT / "config.json").exists() else {}
        base = normaliser_base(a.base or cfg.get("base_url", A_REMPLIR))
        verrou = bool(cfg.get("imprime")) and not (a.forcer or a.sans_verrou)

        tk = charger_tokens(c["parcs"].keys(), verrou)
        if verrou:
            verifier_verrou(cfg, c, tk, base, avec_adresse=not a.site_only)
        if not a.site_only and not base_valide(base):
            raise Erreur("Il faut l'adresse définitive du jeu pour fabriquer les QR codes : renseigne "
                         "base_url dans config.json (ex. https://mon-projet.vercel.app/) ou passe --base.")

        if a.figer:
            figer(cfg, c, tk, base)
            print(f"Figé : adresse {base}, {sum(len(v) for v in tk['parcs'].values())} codes, "
                  "structure des parcs. Les changements qui casseraient les QR collés seront refusés.")

        out = Path(a.out)
        data = construire_donnees(c, tk)
        print("Site        :", ecrire_site(data, out))
        if not a.site_only:
            print("Adresse QR  :", base)
            for p in ecrire_feuilles(c, tk, base, out, rendre_pdf):
                print("Feuilles QR :", p)
            print("Fiche équipe:", ecrire_fiche(c, data, out, rendre_pdf))
            ecrire_liens_test(c, tk, base, out)
    except Erreur as e:
        print("\nERREUR\n" + str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
