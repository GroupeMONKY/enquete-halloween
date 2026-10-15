#!/usr/bin/env python3
"""Teste le jeu comme une famille sur un téléphone : les 4 parcs, les 6 postes, l'aide,
la mauvaise et la bonne réponse, le mot du jour, les dates d'ouverture et de fermeture
(en mode réel, sans test=1), et l'absence de débordement sur un petit écran.

Usage : python3 tests/test_parcours.py
"""
import datetime
import functools
import http.server
import json
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import build  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")
resultats = []


def check(cond, msg):
    resultats.append(bool(cond))
    print(("OK     " if cond else "ECHEC  ") + msg)


def typo(s):
    """Même règle que le jeu : espace fine insécable avant ! ? : ; » et après «."""
    s = re.sub(r" ([!?:;»])", "\u202f\\1", s)
    return re.sub(r"(«) ", "\\1\u202f", s)


def serveur(dossier):
    class H(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a, **k):
            pass
    h = functools.partial(H, directory=str(dossier))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def paris(*args):
    return datetime.datetime(*args, tzinfo=PARIS)


def main():
    c = json.loads((ROOT / "contenu.json").read_text(encoding="utf-8"))
    tk = json.loads((ROOT / "tokens.json").read_text(encoding="utf-8"))
    data = build.construire_donnees(c, tk)
    mots = data["mots"]
    debut = datetime.date.fromisoformat(c["periode"]["debut"])
    fin = datetime.date.fromisoformat(c["periode"]["fin"])
    mascotte = c["mascotte"]

    def mot(jour):
        return mots[(jour - debut).days % len(mots)]

    jour_test = "2026-10-20"
    d_test = datetime.date.fromisoformat(jour_test)

    def temoignages(pid, jour):
        """Les 4 témoignages attendus ce jour-là : calculés depuis les attributs du coupable du jour."""
        sid = build.coupable_du_jour(c, pid, jour)
        return [build.texte_temoignage(c, e["temoin"]["trait"], c["suspects"][sid]) for e in c["parcs"][pid]["etapes"][1:5]]

    tmp = Path(tempfile.mkdtemp())
    r = subprocess.run([sys.executable, str(ROOT / "build.py"), "--site-only", "--out", str(tmp), "--sans-verrou"],
                       capture_output=True, text=True)
    check(r.returncode == 0, "le générateur produit le site (" + (r.stderr.strip().splitlines()[-1] if r.stderr.strip() else "ok") + ")")
    page = tmp / "site" / "index.html"
    poids = page.stat().st_size
    check(poids < 100 * 1024, f"le site pèse {poids // 1024} Ko (limite : 100 Ko)")
    html_site = page.read_text(encoding="utf-8")
    externes = re.findall(r'(?:src|href)=["\'](https?://[^"\']+)', html_site)
    check(not externes, f"aucune ressource externe chargée (trouvé : {externes[:3]})")

    srv = serveur(tmp / "site")
    BASE = f"http://127.0.0.1:{srv.server_address[1]}/"
    erreurs_js = []

    def surveiller(pg):
        pg.on("pageerror", lambda e: erreurs_js.append(str(e)))
        pg.on("console", lambda m: erreurs_js.append(m.text) if m.type == "error" else None)

    try:
        with sync_playwright() as pw:
            nav = pw.chromium.launch()
            ctx = nav.new_context(viewport={"width": 360, "height": 740}, is_mobile=True, has_touch=True,
                                  locale="fr-FR", timezone_id="Europe/Paris")
            pg = ctx.new_page()
            surveiller(pg)

            def debordement():
                return pg.evaluate("document.documentElement.scrollWidth > window.innerWidth")

            # ---- cas sans code et code inconnu
            pg.goto(BASE + "?test=1")
            check(typo(c["messages"]["sans_code"]) in pg.inner_text("body"), "sans code : consigne de départ")
            pg.goto(BASE + "?e=zzzzzzz&test=1")
            check(typo(c["messages"]["code_inconnu"]) in pg.inner_text("body"), "code inconnu : message clair")

            def voir_temoins(pid, jour, postes=(2, 3, 4, 5)):
                """Passe devant les postes donnés, comme une famille qui scanne les affiches."""
                for n in postes:
                    pg.goto(f"{BASE}?e={tk['parcs'][pid][n - 1]}&test=1&date={jour}")

            # ---- les 4 parcs, les 6 postes
            for pid, p in c["parcs"].items():
                sid_jour = build.coupable_du_jour(c, pid, d_test)
                culpable = c["suspects"][sid_jour]
                for s in range(1, 7):
                    et = p["etapes"][s - 1]
                    pg.goto(f"{BASE}?e={tk['parcs'][pid][s - 1]}&test=1&date={jour_test}")
                    txt = pg.inner_text("body")
                    check(f"Poste {s} sur 6" in txt and f"Parc {build.de_parc(p['nom'])}" in txt,
                          f"{pid} poste {s} : en-tête et parc")
                    check(not debordement(), f"{pid} poste {s} : pas de débordement à 360 px")
                    if s < 6:
                        check(typo(et["enigme"]) in txt, f"{pid} poste {s} : énigme vers {et['mene_a']}")
                        pg.get_by_role("button", name="Un coup de pouce").click()
                        check(typo(et["indice1"]) in pg.inner_text("body"), f"{pid} poste {s} : coup de pouce 1")
                        pg.get_by_role("button", name="Je ne trouve toujours pas").click()
                        check(typo(et["indice2"]) in pg.inner_text("body"), f"{pid} poste {s} : coup de pouce 2")
                    if 2 <= s <= 5:
                        t = et["temoin"]
                        check(typo(temoignages(pid, d_test)[s - 2]) in txt and t["nom"] in txt, f"{pid} poste {s} : témoignage de {t['nom']}")
                    if s == 6:
                        for t, texte in zip((e["temoin"] for e in p["etapes"][1:5]), temoignages(pid, d_test)):
                            check(typo(texte) in txt, f"{pid} poste 6 : rappel du témoignage de {t['nom']}")

                # ---- mauvaise puis bonne réponse
                pg.goto(f"{BASE}?e={tk['parcs'][pid][5]}&test=1&date={jour_test}")
                pg.evaluate("localStorage.clear()")
                voir_temoins(pid, jour_test)
                pg.goto(f"{BASE}?e={tk['parcs'][pid][5]}&test=1&date={jour_test}")
                faux = next(k for k in c["suspects"] if k != sid_jour)
                nom_faux = c["suspects"][faux]["nom"]
                pg.get_by_role("button", name=re.compile(re.escape(nom_faux), re.I)).click()
                pg.get_by_role("button", name="Désigner le coupable").click()
                check(typo(c["recits"]["mauvaise"]) in pg.inner_text("body"), f"{pid} : mauvaise réponse refusée")
                check(pg.get_by_role("button", name=re.compile("Réessayer")).is_disabled(), f"{pid} : bouton verrouillé après erreur")
                pg.reload()
                pg.get_by_role("button", name=re.compile(re.escape(culpable["nom"]), re.I)).click()
                pg.get_by_role("button", name="Désigner le coupable").click()
                txt = pg.inner_text("body")
                titre = typo(c["recits"]["victoire_titre"].replace("{m}", mascotte))
                check(titre in txt and culpable["nom"] in txt, f"{pid} : victoire avec le bon coupable")
                check(c["recompense"] in txt, f"{pid} : récompense annoncée ({c['recompense']})")
                check(mot(datetime.date.fromisoformat(jour_test)) in txt, f"{pid} : mot du jour du {jour_test}")
                check(not debordement(), f"{pid} : écran de victoire sans débordement à 360 px")
                pg.reload()
                check(titre in pg.inner_text("body"), f"{pid} : victoire conservée après rechargement")

            # ---- verrou du poste 6 : seuls les témoins déjà interrogés sont montrés
            pidv = next(iter(c["parcs"]))
            url6 = f"{BASE}?e={tk['parcs'][pidv][5]}&test=1&date={jour_test}"
            lot = temoignages(pidv, d_test)
            pg.goto(url6)
            pg.evaluate("localStorage.clear()")
            pg.reload()
            txt = pg.inner_text("body")
            check(not any(typo(t) in txt for t in lot), f"{pidv} poste 6 direct : aucun témoignage n'est révélé")
            check(all(typo(c["recits"]["temoin_manquant"].replace("{n}", str(n))) in txt for n in (2, 3, 4, 5)), f"{pidv} poste 6 direct : 4 témoins verrouillés")
            check(typo(c["recits"]["verrou_titre"]) in txt, f"{pidv} poste 6 direct : message « il te manque des témoignages »")
            check(pg.get_by_role("button", name="Désigner le coupable").count() == 0, f"{pidv} poste 6 direct : pas de choix du coupable")
            voir_temoins(pidv, jour_test, postes=(2, 4))
            pg.goto(url6)
            txt = pg.inner_text("body")
            check(typo(lot[0]) in txt and typo(lot[2]) in txt and typo(lot[1]) not in txt and typo(lot[3]) not in txt,
                  f"{pidv} poste 6 : seuls les témoins des postes 2 et 4 sont montrés")
            check(all(typo(c["recits"]["temoin_manquant"].replace("{n}", str(n))) in txt for n in (3, 5)) and "postes 3, 5" in txt, f"{pidv} poste 6 : il est dit lesquels manquent")
            voir_temoins(pidv, jour_test, postes=(3, 5))
            pg.goto(url6)
            txt = pg.inner_text("body")
            check(all(typo(t) in txt for t in lot), f"{pidv} poste 6 : les 4 témoignages après les 4 postes")
            check(pg.get_by_role("button", name="Désigner le coupable").count() == 1, f"{pidv} poste 6 : choix du coupable disponible")
            # un autre jour : il faut les reparcourir (la mémoire est quotidienne)
            autre = (d_test + datetime.timedelta(days=1)).isoformat()
            pg.goto(f"{BASE}?e={tk['parcs'][pidv][5]}&test=1&date={autre}")
            check(typo(c["recits"]["verrou_titre"]) in pg.inner_text("body"), f"{pidv} poste 6 le lendemain : de nouveau verrouillé")
            # lien de secours (autre téléphone)
            pg.get_by_role("button", name=re.compile("autre téléphone")).click()
            txt = pg.inner_text("body")
            check(all(typo(t) in txt for t in temoignages(pidv, d_test + datetime.timedelta(days=1))) and
                  pg.get_by_role("button", name="Désigner le coupable").count() == 1, f"{pidv} poste 6 : le lien de secours débloque")
            # stockage indisponible (navigation privée stricte) : on n'impose rien
            ctx2 = nav.new_context(viewport={"width": 360, "height": 740}, locale="fr-FR", timezone_id="Europe/Paris")
            ctx2.add_init_script("Object.defineProperty(window,'localStorage',{get(){throw new Error('bloqué')}})")
            p3 = ctx2.new_page()
            p3.goto(url6)
            t3 = p3.inner_text("body")
            check(all(typo(t) in t3 for t in lot) and p3.get_by_role("button", name="Désigner le coupable").count() == 1,
                  f"{pidv} poste 6 sans stockage : tout est montré (pas de blocage injuste)")
            ctx2.close()

            # ---- le coupable change chaque jour (et diffère d'un parc à l'autre)
            ids = list(c["suspects"])
            for pid in c["parcs"]:
                vus = [build.coupable_du_jour(c, pid, debut + datetime.timedelta(days=i)) for i in range(len(ids))]
                check(sorted(vus) == sorted(ids), f"{pid} : les {len(ids)} suspects sont coupables à tour de rôle ({len(ids)} premiers jours)")
            for i in range(len(ids) + 1):
                jr = debut + datetime.timedelta(days=i)
                du_jour = [build.coupable_du_jour(c, pid, jr) for pid in c["parcs"]]
                check(len(set(du_jour)) == len(du_jour), f"{jr} : chaque parc a un coupable différent")
            pidr = next(iter(c["parcs"]))
            for i in range(len(ids) + 1):
                jr = debut + datetime.timedelta(days=i)
                pg.evaluate("localStorage.clear()")
                voir_temoins(pidr, jr.isoformat())
                pg.goto(f"{BASE}?e={tk['parcs'][pidr][5]}&test=1&date={jr.isoformat()}")
                txt = pg.inner_text("body")
                check(all(typo(t) in txt for t in temoignages(pidr, jr)), f"{pidr} {jr} : témoignages du coupable du jour")
                if i > 0:
                    hier = temoignages(pidr, jr - datetime.timedelta(days=1))
                    check(hier != temoignages(pidr, jr), f"{pidr} {jr} : indices différents de la veille")
                sid_r = build.coupable_du_jour(c, pidr, jr)
                veille = build.coupable_du_jour(c, pidr, jr - datetime.timedelta(days=1))
                pg.get_by_role("button", name=re.compile(re.escape(c["suspects"][veille]["nom"]), re.I)).click()
                pg.get_by_role("button", name="Désigner le coupable").click()
                check(typo(c["recits"]["mauvaise"]) in pg.inner_text("body"), f"{pidr} {jr} : le coupable de la veille est refusé")
                pg.reload()
                pg.get_by_role("button", name=re.compile(re.escape(c["suspects"][sid_r]["nom"]), re.I)).click()
                pg.get_by_role("button", name="Désigner le coupable").click()
                check(c["suspects"][sid_r]["nom"] in pg.inner_text("body"), f"{pidr} {jr} : le coupable du jour ({sid_r}) gagne")

            # ---- mot du jour : chaque jour de la période
            ecarts = 0
            pid0 = next(iter(c["parcs"]))
            sid0 = c["parcs"][pid0]["coupable"]
            j = debut
            while j <= fin:
                pg.goto(f"{BASE}?e={tk['parcs'][pid0][5]}&test=1&date={j.isoformat()}")
                pg.evaluate(f"localStorage.setItem('enquete-gagne-{pid0}','{j.isoformat()}|{sid0}')")
                pg.reload()
                if mot(j) not in pg.inner_text("body"):
                    ecarts += 1
                j += datetime.timedelta(days=1)
            nb = (fin - debut).days + 1
            check(ecarts == 0, f"mot du jour du jeu = tableau de la fiche équipe, {nb} jours vérifiés")
            ctx.close()

            # ---- mode réel (sans test=1) : dates d'ouverture et de fermeture, heure de Paris
            def a_la_date(dt, url):
                cx = nav.new_context(viewport={"width": 360, "height": 740}, is_mobile=True, has_touch=True,
                                     locale="fr-FR", timezone_id="Europe/Paris")
                cx.clock.install(time=dt)
                p2 = cx.new_page()
                surveiller(p2)
                p2.goto(url)
                return cx, p2

            url0 = f"{BASE}?e={tk['parcs'][pid0][0]}"
            cas = [
                ("veille de l'ouverture, 23 h 59", paris(debut.year, debut.month, debut.day - 1, 23, 59), "avant"),
                ("jour d'ouverture, 00 h 00", paris(debut.year, debut.month, debut.day, 0, 0), "ouvert"),
                ("dernier jour, 23 h 59", paris(fin.year, fin.month, fin.day, 23, 59), "ouvert"),
                ("lendemain de la fermeture, 00 h 00", paris(fin.year, fin.month, fin.day + 1, 0, 0), "apres"),
            ]
            for nom, dt, attendu in cas:
                cx, p2 = a_la_date(dt, url0)
                txt = p2.inner_text("body")
                if attendu == "avant":
                    ok = typo(c["messages"]["avant"]) in txt
                elif attendu == "apres":
                    ok = typo(c["messages"]["apres"]) in txt
                else:
                    ok = "Poste 1 sur 6" in txt
                check(ok, f"mode réel, {nom} : {attendu}")
                cx.close()

            # parcours complet en mode réel, un jour de l'heure d'hiver (le 25/10/2026 le décalage change)
            for jour_reel in (paris(2026, 10, 24, 15, 0), paris(2026, 10, 26, 15, 0)):
                p = c["parcs"][pid0]
                cx, p2 = a_la_date(jour_reel, url0)
                ok = True
                for s in range(1, 7):
                    p2.goto(f"{BASE}?e={tk['parcs'][pid0][s - 1]}")
                    ok = ok and f"Poste {s} sur 6" in p2.inner_text("body")
                check(ok, f"mode réel {jour_reel:%d/%m} : les 6 postes s'ouvrent sans test=1")
                p2.get_by_role("button", name=re.compile(re.escape(c["suspects"][build.coupable_du_jour(c, pid0, jour_reel.date())]["nom"]), re.I)).click()
                p2.get_by_role("button", name="Désigner le coupable").click()
                attendu_mot = mot(jour_reel.date())
                check(attendu_mot in p2.inner_text("body"), f"mode réel {jour_reel:%d/%m} : mot du jour {attendu_mot}")
                h1 = p2.locator(".heure").inner_text()
                p2.wait_for_timeout(1300)
                h2 = p2.locator(".heure").inner_text()
                check(h1 != h2, f"mode réel {jour_reel:%d/%m} : l'heure défile ({h1} -> {h2})")
                cx.close()

            # ---- l'écran de victoire expire, et ne se refait pas le jour même
            minutes = c.get("validite_ecran_minutes", 60)
            cx, p4 = a_la_date(paris(2026, 10, 24, 15, 0), url0)
            d24 = datetime.date(2026, 10, 24)
            for s_ in range(1, 7):
                p4.goto(f"{BASE}?e={tk['parcs'][pid0][s_ - 1]}")
            nom_e = c["suspects"][build.coupable_du_jour(c, pid0, d24)]["nom"]
            p4.get_by_role("button", name=re.compile(re.escape(nom_e), re.I)).click()
            p4.get_by_role("button", name="Désigner le coupable").click()
            txt = p4.inner_text("body")
            limite = (datetime.datetime(2026, 10, 24, 15, 0) + datetime.timedelta(minutes=minutes)).strftime("%H h %M")
            check(f"avant {limite}" in txt.replace("\u00a0", " "), f"victoire : « à présenter avant {limite} » (valable {minutes} min)")
            p4.clock.fast_forward((minutes - 1) * 60 * 1000)
            p4.wait_for_timeout(200)
            check(typo(c["recits"]["victoire_titre"].replace("{m}", mascotte)) in p4.inner_text("body"), f"victoire : encore valable à {minutes - 1} min")
            p4.clock.fast_forward(2 * 60 * 1000)
            p4.wait_for_timeout(200)
            txt = p4.inner_text("body")
            check(typo(c["recits"]["expire_titre"]) in txt, f"victoire : l'écran expire seul après {minutes} min")
            check(c["recompense"] not in txt and "Mot du jour" not in txt, "écran expiré : ni mot du jour ni récompense")
            p4.reload()
            check(typo(c["recits"]["expire_titre"]) in p4.inner_text("body"), "écran expiré : toujours expiré après rechargement")
            p4.goto(f"{BASE}?e={tk['parcs'][pid0][5]}")
            txt = p4.inner_text("body")
            check(typo(c["recits"]["expire_titre"]) in txt and p4.get_by_role("button", name="Désigner le coupable").count() == 0,
                  "poste 6 rouvert le même jour : pas de nouvelle victoire possible")
            p4.clock.fast_forward(24 * 3600 * 1000)       # lendemain
            d25 = datetime.date(2026, 10, 25)
            for s_ in range(2, 6):
                p4.goto(f"{BASE}?e={tk['parcs'][pid0][s_ - 1]}")
            p4.goto(f"{BASE}?e={tk['parcs'][pid0][5]}")
            nom_e2 = c["suspects"][build.coupable_du_jour(c, pid0, d25)]["nom"]
            p4.get_by_role("button", name=re.compile(re.escape(nom_e2), re.I)).click()
            p4.get_by_role("button", name="Désigner le coupable").click()
            check(typo(c["recits"]["victoire_titre"].replace("{m}", mascotte)) in p4.inner_text("body"), "le lendemain : nouvelle enquête, nouvelle victoire possible")
            cx.close()

            nav.close()
    finally:
        srv.shutdown()

    check(not erreurs_js, "aucune erreur JavaScript ni erreur de console" + (f" : {erreurs_js[:3]}" if erreurs_js else ""))
    n_ok = sum(resultats)
    print(f"\nRÉSULTAT : {'TOUT OK' if all(resultats) else 'ÉCHECS'} ({n_ok}/{len(resultats)} vérifications)")
    return 0 if all(resultats) else 1


if __name__ == "__main__":
    sys.exit(main())
