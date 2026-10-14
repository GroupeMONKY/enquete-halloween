#!/usr/bin/env python3
"""Aperçu local : feuilleter les 6 postes de chaque parc sans scanner de QR.

Usage : python3 apercu/serveur.py   puis ouvrir http://127.0.0.1:8766/
Hors de site/ : ce dossier n'est jamais déployé. Lecture seule sur le dépôt.
"""
import http.server
import pathlib

RACINE = pathlib.Path(__file__).resolve().parent.parent
PORT = 8766
FICHIERS = {
    "/": (RACINE / "apercu" / "apercu.html", "text/html; charset=utf-8"),
    "/jeu": (RACINE / "site" / "index.html", "text/html; charset=utf-8"),
    "/tokens.json": (RACINE / "tokens.json", "application/json"),
}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        chemin = self.path.split("?", 1)[0]
        if chemin.startswith("/img/") and ".." not in chemin:
            image = RACINE / "site" / chemin.lstrip("/")
            if image.is_file():
                corps = image.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/webp" if image.suffix == ".webp" else "image/png")
                self.send_header("Content-Length", str(len(corps)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(corps)
                return
        if chemin not in FICHIERS:
            self.send_error(404)
            return
        fichier, type_mime = FICHIERS[chemin]
        corps = fichier.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", type_mime)
        self.send_header("Content-Length", str(len(corps)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corps)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"Aperçu : http://127.0.0.1:{PORT}/")
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
