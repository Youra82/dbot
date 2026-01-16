# PowerShell Script: Korrekter Backtest mit DBot Live-Strategien

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  DBot: Korrekter Backtest mit Live-Strategien" -ForegroundColor Cyan
Write-Host "  High-Frequency Momentum Scalper" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Starte Backtest mit den aktiven Strategien aus settings.json"
Write-Host "1m/5m Timeframes für hochfrequenten Trading"
Write-Host ""
Write-Host "Zeitraum: 2025-11-01 bis heute"
Write-Host "Startkapital: 250 USDT"
Write-Host "============================================================"
Write-Host ""

# Erstelle Eingabedatei für automatische Eingaben
$input = @"
2
2025-11-01

250
1,2,3,4,5,6
"@

# Führe show_results.sh mit automatischen Eingaben aus
$input | bash show_results.sh

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  Backtest abgeschlossen!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Starte nun Vergleich mit Real-Trades..."
& "C:/Users/matol/Desktop/bots/dbot/.venv/Scripts/python.exe" compare_real_vs_backtest.py
