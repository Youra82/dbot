#!/bin/bash
# run_tests.sh - Run DBot Tests

echo "======================================"
echo "  DBot Tests"
echo "======================================"
echo ""

# Activate venv
if [ -d ".venv" ]; then
    source .venv/bin/activate
else
    echo "❌ Virtual Environment nicht gefunden"
    echo "   Führe erst ./install.sh aus"
    exit 1
fi

# Run pytest
echo "🧪 Führe Tests aus..."
pytest tests/ -v --tb=short

echo ""
echo "======================================"
echo "  Tests abgeschlossen"
echo "======================================"
