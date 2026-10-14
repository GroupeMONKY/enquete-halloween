#!/usr/bin/env python3
"""Lance tous les tests. À exécuter avant chaque push : python3 tests/run_all.py"""
import subprocess
import sys
from pathlib import Path

ici = Path(__file__).resolve().parent
echecs = []
for t in ("test_build.py", "test_parcours.py", "test_qr.py"):
    print(f"\n===== {t} =====")
    r = subprocess.run([sys.executable, str(ici / t)])
    if r.returncode:
        echecs.append(t)
print("\n" + ("TOUS LES TESTS PASSENT" if not echecs else "ÉCHECS : " + ", ".join(echecs)))
sys.exit(1 if echecs else 0)
