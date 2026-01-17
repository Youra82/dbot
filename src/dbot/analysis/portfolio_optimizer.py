# src/dbot/analysis/portfolio_optimizer.py (deprecated)
import sys
print("portfolio_optimizer.py ist veraltet. dbot nutzt keine ANN-Pipeline mehr. Bitte ./show_results.sh für SMC-Backtests verwenden.")
sys.exit(1)


def run_portfolio_optimizer(start_capital, strategies_data, start_date, end_date, max_drawdown=100.0):
    """
    Findet die beste Kombination von Strategien, um den Profit zu maximieren,
    ohne dabei liquidiert zu werden ODER den maximalen Drawdown zu überschreiten,
    unter Verwendung eines Greedy-Algorithmus.
    """
    print("\n--- Starte automatische Portfolio-Optimierung... ---")

    if not strategies_data:
        print("Keine Strategien zum Optimieren gefunden.")
        return None

    print("1/3: Analysiere Einzel-Performance jeder Strategie...")
    single_strategy_results = []

    for filename, strat_data in tqdm(strategies_data.items(), desc="Bewerte Einzelstrategien"):
        sim_data = {strat_data['symbol']: strat_data}
        result = run_portfolio_simulation(start_capital, sim_data, start_date, end_date)

        if result and not result.get("liquidation_date") and result['max_drawdown_pct'] <= max_drawdown:
            score = result['total_pnl_pct'] / result['max_drawdown_pct'] if result['max_drawdown_pct'] > 0 else result['total_pnl_pct']
            single_strategy_results.append({'filename': filename, 'score': score, 'result': result})

    if not single_strategy_results:
        print(f"Keine einzige Strategie konnte die DD-Beschränkung von {max_drawdown:.2f}% einhalten. Portfolio-Optimierung nicht möglich.")
        return None

    single_strategy_results.sort(key=lambda x: x['score'], reverse=True)

    best_portfolio_files = [single_strategy_results[0]['filename']]
    best_portfolio_score = single_strategy_results[0]['score']
    best_portfolio_result = single_strategy_results[0]['result']

    candidate_pool = [res['filename'] for res in single_strategy_results[1:]]

    print(f"2/3: Star-Spieler gefunden: {best_portfolio_files[0]} (Score: {best_portfolio_score:.2f})")
    print("3/3: Suche die besten Team-Kollegen...")

    while True:
        best_next_addition = None
        best_score_with_addition = best_portfolio_score

        progress_bar = tqdm(candidate_pool, desc=f"Teste Team mit {len(best_portfolio_files)+1} Mitgliedern")
        for candidate_file in progress_bar:
            current_team_files = best_portfolio_files + [candidate_file]

            unique_check = set()
            is_valid_team = True
            for f in current_team_files:
                key = strategies_data[f]['symbol'] + strategies_data[f]['timeframe']
                if key in unique_check:
                    is_valid_team = False
                    break
                unique_check.add(key)

            if not is_valid_team:
                continue

            current_team_data = {strategies_data[fname]['symbol']: strategies_data[fname] for fname in current_team_files}

            result = run_portfolio_simulation(start_capital, current_team_data, start_date, end_date)

            if result and not result.get("liquidation_date") and result['max_drawdown_pct'] <= max_drawdown:
                score = result['total_pnl_pct'] / result['max_drawdown_pct'] if result['max_drawdown_pct'] > 0 else result['total_pnl_pct']
                if score > best_score_with_addition:
                    best_score_with_addition = score
                    best_next_addition = candidate_file
                    best_portfolio_result = result

        if best_next_addition:
            print(f"-> Füge hinzu: {best_next_addition} (Neuer Score: {best_score_with_addition:.2f})")
            best_portfolio_files.append(best_next_addition)
            best_portfolio_score = best_score_with_addition
            candidate_pool.remove(best_next_addition)
        else:
            print("Keine weitere Verbesserung durch Hinzufügen von Strategien gefunden. Optimierung beendet.")
            break

    return {"optimal_portfolio": best_portfolio_files, "final_result": best_portfolio_result}
