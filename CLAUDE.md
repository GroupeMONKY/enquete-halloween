# Enquête Monky — jeu de piste Halloween (4 parcs)

Mini-jeu web pour les familles : la mascotte Monky a disparu, parent + enfant parcourent le parc en
scannant 6 QR codes (un par poste) et désignent le coupable à la fin. Réussite = 100 bananacoins à
l'accueil, en montrant l'écran de victoire en direct. Même histoire dans les 4 parcs, seuls les lieux changent.
Ouverture : samedi 17 octobre 2026 → 2 novembre 2026 (heure de Paris).

L'utilisateur (Pierre-Elie, Communication & Marketing) pilote tout via Claude Code → GitHub → Vercel.
Il veut qu'on le challenge : signale clairement ce qui est faible ou risqué, ne valide pas par réflexe.

## Le « contrat » gelé après impression des QR
Dès que les parcs ont imprimé, ces éléments NE DOIVENT PLUS CHANGER (sinon des QR collés deviennent faux) :
- l'adresse de base (`base_url` dans `config.json`) et le format `?e=<code>`
- `tokens.json` (les 6 codes par parc) — ne jamais le régénérer ni l'éditer à la main
- les parcs, le nombre de postes (6) et l'ordre des lieux dans `contenu.json`
Tout le reste (textes, énigmes, indices, témoins, design, logique) reste modifiable à volonté.
`python3 build.py --figer` (une fois, après impression) active un verrou : le générateur refuse alors
les changements qui casseraient les QR. `--forcer` ne sert qu'à une réimpression complète volontaire.

## Où modifier quoi
- Histoire, énigmes, indices, témoins (qui parle, sur quel trait), phrases des témoignages (`temoignages`), messages, mots du jour, suspects : `contenu.json`
  (poste 1 = Accueil, poste 6 = Bowling ; la récompense se retire à l'accueil ; chaque `mene_a` doit être le lieu de l'étape suivante).
- Design et comportement : `template.html` (CSS + JS vanille, une seule page).
- Génération : `build.py` (valide le contenu, produit `site/index.html`, les PDF de QR, la fiche équipe).
- `site/index.html` est GÉNÉRÉ mais COMMITÉ : c'est ce que Vercel sert (Root Directory = `site`, pas de commande de build ; en-têtes dans `site/vercel.json`).

## Commandes
- `python3 build.py --site-only` : régénère `site/index.html` (à faire après toute modif de contenu/template).
- `python3 build.py --base https://…/` : feuilles QR (`print/qr/`), fiche équipe (`print/equipe/`), liens de test.
- `python3 build.py --figer` : après impression.
- `python3 tests/run_all.py` : tous les tests (≈ 240 vérifications, 1-2 min).
- Installation : `pip install -r requirements.txt` puis `playwright install chromium`; `pdftoppm` (poppler) requis pour test_qr.

## Règles de qualité (non négociables)
- Mobile d'abord : lisible à 360 px de large, aucun défilement horizontal.
- Aucune ressource externe (pas de police/CDN/analytics), page < 100 Ko, fonctionne sur réseau faible.
- Public = enfants : aucun cookie, aucun traceur, aucune donnée personnelle. Seul stockage : `localStorage`
  (clés `enquete-gagne-<parc>` = « date|suspect » et `enquete-vu-<parc>` = « date|2,3,… » : les postes 2 à 5 déjà vus aujourd'hui).
- Verrou du poste 6 : il ne montre que les témoins déjà interrogés sur ce téléphone, le jour même (les autres sont grisés, le choix du coupable est bloqué). Sans stockage disponible, rien n'est imposé ; un lien de secours (« autre téléphone ») débloque sur parole. Textes : `recits.verrou*` et `recits.temoin_manquant`.
- Typographie française : espace fine insécable avant `! ? : ;` et `»`, après `«` (fonction `typo()`).
  Tout texte affiché passe par elle. Élision correcte (« d'Agen », « de Laval »).
- Le coupable CHANGE CHAQUE JOUR (heure de Paris) : à partir du `coupable` de `contenu.json` (= celui du 1er jour), on avance d'un suspect par jour, en bouclant. Les 4 témoignages se déduisent des attributs du coupable du jour (phrases dans `temoignages`). Formule identique dans `build.py` (`coupable_du_jour`) et `template.html` (`coupableDuJour`) : les modifier ensemble.
- La réponse est vérifiée côté navigateur : c'est du brouillage, PAS de la sécurité.
  L'antifraude repose sur l'écran de victoire en direct (heure de Paris qui défile + mot du jour) vérifié par l'équipe.

## Modes de test
- `?test=1` : ignore la fenêtre de dates. `?test=1&date=AAAA-MM-JJ` : simule un jour (mot du jour, etc.).
- Sans `test=1`, le jeu applique les vrais messages avant/après la période.

## Avant chaque push
1. `python3 build.py --site-only`
2. `python3 tests/run_all.py` doit afficher « TOUS LES TESTS PASSENT »
3. Commiter `site/index.html` avec les sources. Ne jamais commiter `print/`.
4. Après le déploiement : scanner un QR de test avec un vrai téléphone.
