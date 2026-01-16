#!/bin/bash
# install.sh - DBot Installation Script

echo "======================================"
echo "  DBot Installation"
echo "======================================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 nicht gefunden!"
    echo "   Installiere Python 3.8+ und versuche es erneut"
    exit 1
fi

echo "✅ Python gefunden: $(python3 --version)"
echo ""

# Create virtual environment
if [ ! -d ".venv" ]; then
    echo "📦 Erstelle Virtual Environment..."
    python3 -m venv .venv
else
    echo "✅ Virtual Environment existiert bereits"
fi

# Activate venv
source .venv/bin/activate

# Install dependencies
echo "📥 Installiere Dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "======================================"
echo "  ✅ Installation abgeschlossen!"
echo "======================================"
echo ""
echo "Nächste Schritte:"
echo "  1. Konfiguriere secret.json mit deinen API-Keys"
echo "  2. Passe settings.json nach Bedarf an"
echo "  3. Starte den Bot: python master_runner.py"
echo ""
echo "======================================"
