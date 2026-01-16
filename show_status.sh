#!/bin/bash
# show_status.sh - Zeige DBot Status

echo "======================================"
echo "  DBot Status"
echo "======================================"
echo ""

# Check if bot is running
if pgrep -f "dbot" > /dev/null; then
    echo "✅ DBot läuft"
    echo ""
    echo "Aktive Prozesse:"
    ps aux | grep -E "[p]ython.*dbot" | awk '{print "   PID:", $2, "| CPU:", $3"%", "| MEM:", $4"%"}'
else
    echo "❌ DBot läuft NICHT"
fi

echo ""
echo "======================================"
echo "  Letzte Log-Einträge"
echo "======================================"
echo ""

# Show recent logs
for log_file in logs/dbot_*.log; do
    if [ -f "$log_file" ]; then
        echo "📝 $(basename "$log_file"):"
        tail -n 5 "$log_file" | sed 's/^/   /'
        echo ""
    fi
done

echo "======================================"
echo "  Nützliche Befehle"
echo "======================================"
echo "  tail -f logs/dbot_*.log    # Alle Logs live"
echo "  pkill -f dbot              # Bot stoppen"
echo "  python master_runner.py    # Bot starten"
echo "======================================"
