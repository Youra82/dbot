#!/bin/bash
# update.sh - Update DBot from Git

echo "======================================"
echo "  DBot Update"
echo "======================================"
echo ""

# Stop bot
echo "🛑 Stoppe DBot..."
pkill -f "dbot"
sleep 2

# Git pull
echo "📥 Hole Updates von Git..."
git pull origin main

# Update dependencies
echo "📦 Update Dependencies..."
if [ -d ".venv" ]; then
    source .venv/bin/activate
    pip install -r requirements.txt --upgrade
else
    echo "⚠️  Keine Virtual Environment gefunden"
    echo "   Führe erst ./install.sh aus"
    exit 1
fi

echo ""
echo "✅ Update abgeschlossen!"
echo ""
echo "💡 Bot neu starten mit: python master_runner.py"
echo "======================================"
