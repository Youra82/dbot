#!/bin/bash

echo "--- Richte den Simple Bitget Downloader ein ---"

# 1. Virtuelle Umgebung erstellen
echo "Erstelle Python Virtual Environment in '.venv'..."
python3 -m venv .venv

# 2. Umgebung aktivieren und Anforderungen installieren
echo "Aktiviere Umgebung und installiere ccxt & pandas..."
source .venv/bin/activate
pip install -r requirements.txt
deactivate

echo -e "\n✔ Einrichtung abgeschlossen!"
echo "Du kannst den Downloader jetzt mit 'source .venv/bin/activate' und dann 'python3 dbot.py' starten."
