#!/bin/bash
# Dieses Skript führt das komplette Test-Sicherheitsnetz aus.
echo "--- Starte DBot-Sicherheitsnetz ---"

# Aktiviere die virtuelle Umgebung
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "❌ Virtual Environment nicht gefunden"
    echo "   Führe erst ./install.sh aus"
    exit 1
fi

# Führe pytest aus. -v für mehr Details, -s um print() Ausgaben anzuzeigen.
python3 -m pytest -v -s

# Deaktiviere die Umgebung wieder
deactivate

echo "--- Sicherheitscheck abgeschlossen ---"

