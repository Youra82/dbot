#!/bin/bash
# run_tests.sh — Führt das Test-Sicherheitsnetz für dbot aus
echo "--- Starte dbot Sicherheitsnetz ---"

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
cd "$SCRIPT_DIR"

if [ ! -f ".venv/bin/activate" ]; then
    echo "Fehler: Virtuelle Umgebung nicht gefunden. Bitte install.sh ausführen."
    exit 1
fi

source .venv/bin/activate

echo "Führe Pytest aus..."
export PYTHONPATH="${PYTHONPATH}:$(pwd)/src"

if python3 -m pytest tests/ -v -s 2>/dev/null || python3 -m pytest -v -s; then
    echo "✅ Alle Tests bestanden."
    EXIT_CODE=0
else
    PYTEST_EXIT_CODE=$?
    if [ $PYTEST_EXIT_CODE -eq 5 ]; then
        echo "Keine Tests gefunden (tests/ Verzeichnis leer)."
        EXIT_CODE=0
    else
        echo "❌ Tests fehlgeschlagen (Exit Code: $PYTEST_EXIT_CODE)."
        EXIT_CODE=$PYTEST_EXIT_CODE
    fi
fi

deactivate

echo "--- Sicherheitscheck abgeschlossen ---"
exit $EXIT_CODE
