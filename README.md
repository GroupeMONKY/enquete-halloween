# Enquête Monky

Jeu de piste Halloween pour les parcs Monky (Agen, Laval, Châteauroux, Mont-de-Marsan).
Voir `CLAUDE.md` pour le fonctionnement détaillé et les règles.

## Mise en ligne (GitHub → Vercel)
1. `git init`, premier commit, dépôt GitHub **privé**, `git push`.
2. Vercel → *Add New Project* → importer le dépôt. Réglages : *Root Directory* = `site` (important : sinon Vercel
   voit les fichiers Python à la racine et tente un déploiement Python), *Framework Preset* = Other,
   *Build Command* et *Output Directory* = vides. Les en-têtes (noindex) sont dans `site/vercel.json`.
3. Ouvrir `https://<projet>.vercel.app/?e=<code>&test=1` : le jeu doit s'afficher.

**Attention — licence Vercel.** Le plan Hobby (gratuit) est réservé à un usage non commercial. Un jeu qui
promeut des parcs payants est difficilement « non commercial » : vérifier ses conditions actuelles ou prendre
un plan Pro (≈ 20 $/mois). Alternative gratuite plus claire : Cloudflare Pages (même dossier `site/`).

## Choisir l'adresse AVANT d'imprimer
L'adresse est gravée dans les QR imprimés. Mettre la définitive dans `config.json` (`base_url`, avec `/` final),
puis `python3 build.py` : les PDF sortent dans `print/qr/` (6 pages par parc, A4) avec la fiche équipe.
Après impression : `python3 build.py --figer` (verrou).

## Test avant ouverture (obligatoire)
Dans chaque parc, avec un vrai téléphone en 4G : scanner les 6 QR dans l'ordre, tester les coups de pouce,
une mauvaise réponse, la bonne, et l'écran de victoire. Vérifier que les QR se scannent à distance réaliste
et à la lumière du lieu.

## Exploitation
- Bug ou faute de frappe : corriger `contenu.json` / `template.html`, `python3 build.py --site-only`,
  `python3 tests/run_all.py`, commit, push (Vercel redéploie en ~1 min).
- Un QR abîmé ou volé : réimprimer la même page PDF (même code). Ne jamais régénérer `tokens.json`.
- Accueil : valider la victoire = écran en direct (heure qui défile) + mot du jour du jour (fiche équipe).
