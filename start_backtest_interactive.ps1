# PowerShell: Interaktiver Backtest-Aufruf für DBot
Write-Host "Führe Backtest mit Live-Strategien durch..." -ForegroundColor Cyan
Write-Host "High-Frequency Momentum Scalper" -ForegroundColor Yellow
Write-Host ""
Write-Host "Gib folgendes ein wenn gefragt:" -ForegroundColor Yellow
Write-Host "  Modus: 2"
Write-Host "  Startdatum: 2025-11-01"
Write-Host "  Enddatum: (Enter drücken)"
Write-Host "  Kapital: 250"
Write-Host "  Strategien: (Enter zur Auswahl)"
Write-Host ""
Write-Host "Drücke Enter um zu starten..." -ForegroundColor Green
Read-Host

# Wechsle ins Bash-Umfeld und führe den Backtest aus
bash -c "cd /mnt/c/Users/matol/Desktop/bots/dbot && bash show_results.sh"
