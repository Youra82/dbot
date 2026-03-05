#!/bin/bash
set -e

echo "--- Sicheres Update wird ausgeführt ---"

# 1. secret.json sichern
echo "1. Erstelle Backup von 'secret.json'..."
cp secret.json secret.json.bak

# 2. Neuesten Stand von GitHub holen
echo "2. Hole den neuesten Stand von GitHub..."
git fetch origin

# 3. Lokal auf GitHub-Stand zurücksetzen
echo "3. Setze alle Dateien auf den neuesten Stand zurück..."
git reset --hard origin/master

# 4. secret.json wiederherstellen
echo "4. Stelle 'secret.json' aus dem Backup wieder her..."
cp secret.json.bak secret.json
rm secret.json.bak

# 5. Python-Cache löschen
echo "5. Lösche alten Python-Cache..."
find . -type f -name "*.pyc" -delete
find . -type d -name "__pycache__" -delete

# 6. Ausführungsrechte setzen
echo "6. Setze Ausführungsrechte für alle .sh-Skripte..."
chmod +x *.sh

echo "✅ Update erfolgreich abgeschlossen."
