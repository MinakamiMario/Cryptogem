"""
Report generation for backtest and paper trade results.
"""
import math


def print_results(results_list, title="BACKTEST RESULTATEN"):
    """
    Print a summary table of multiple backtest results.

    Args:
        results_list: list of dicts from run_backtest()
        title: Header title
    """
    print(f"\n{'='*110}")
    print(f"  {title}")
    print(f"{'='*110}")
    print(f"  {'#':>3}  {'Strategie':<30} {'Return':>8} {'Trades':>7} {'WR':>6} {'Sharpe':>7} {'MaxDD':>7} {'PF':>6} {'Score':>7}")
    print(f"  {'-'*100}")

    scored = []
    for r in results_list:
        ret = r['return_pct']
        sharpe = r['sharpe']
        dd = r['max_dd']
        wr = r['win_rate']
        pf = r['profit_factor']
        score = math.log1p(max(ret, 0)) * 5 + sharpe * 30 + (100 - dd) * 0.5 + wr * 0.2 + pf * 8
        scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)

    for i, (score, r) in enumerate(scored, 1):
        name = r['strategy']
        if len(name) > 28:
            name = name[:28] + '..'
        print(f"  {i:>3}  {name:<30} {r['return_pct']:>+7.1f}% {r['total_trades']:>6}  "
              f"{r['win_rate']:>5.1f}% {r['sharpe']:>6.3f} {r['max_dd']:>6.1f}% "
              f"{r['profit_factor']:>5.2f} {score:>7.1f}")

    print(f"  {'-'*100}")
    print(f"{'='*110}\n")

    return scored


def print_paper_trades(result, title=None):
    """
    Print detailed paper trade results.

    Args:
        result: dict from run_paper_trade()
        title: Optional title override
    """
    name = title or f"{result['strategy']} ({result['coin']} {result['timeframe']})"
    start = result['start_capital']
    end = result['end_capital']
    trades = result['trades']

    print(f"\n{'='*95}")
    print(f"  PAPER TRADE: {name}")
    print(f"  Periode: {result['start_date'].strftime('%d %b %Y')} - {result['end_date'].strftime('%d %b %Y')}")
    print(f"  Startkapitaal: EUR {start:,.2f}")
    print(f"{'='*95}")

    if not trades:
        print(f"\n  Geen trades in deze periode.")
        print(f"  Portfolio waarde: EUR {end:,.2f}")
        print(f"{'='*95}\n")
        return

    is_hourly = result['timeframe'] == '1h'
    time_label = 'Uren' if is_hourly else 'Dagen'

    print(f"\n  {'#':>3}  {'Entry':<20} {'Prijs':>10}  {'Exit':<20} {'Prijs':>10}  "
          f"{'P&L':>10} {'%':>7} {time_label:>5}  {'Saldo':>10}")
    print(f"  {'-'*98}")

    wins = 0
    losses = 0
    max_win = 0
    max_loss = 0

    for i, t in enumerate(trades, 1):
        entry_dt = t['entry_date'].strftime('%d-%b-%y %H:%M')
        exit_dt = t['exit_date'].strftime('%d-%b-%y %H:%M')
        duration = t['bars']
        pnl = t['pnl']

        if pnl > 0:
            wins += 1
            result_str = "WIN"
            if pnl > max_win:
                max_win = pnl
        else:
            losses += 1
            result_str = "LOSS"
            if pnl < max_loss:
                max_loss = pnl

        time_str = f"{duration}h" if is_hourly else f"{duration}d"
        print(f"  {i:>3}  {entry_dt:<20} ${t['entry_price']:>9,.0f}  {exit_dt:<20} ${t['exit_price']:>9,.0f}  "
              f"EUR{pnl:>+9.2f} {t['pnl_pct']:>+6.1f}% {time_str:>4}  EUR{t['capital_after']:>9.2f}  {result_str}")

    total_pnl = end - start
    total_pnl_pct = (total_pnl / start) * 100
    total_trades = len(trades)
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

    print(f"  {'-'*98}")
    print(f"\n  RESULTAAT:")
    print(f"  {'Startkapitaal:':<25} EUR {start:,.2f}")
    print(f"  {'Eindkapitaal:':<25} EUR {end:,.2f}")
    print(f"  {'Totaal P&L:':<25} EUR {total_pnl:>+,.2f} ({total_pnl_pct:>+.1f}%)")
    print(f"  {'Aantal trades:':<25} {total_trades}")
    print(f"  {'Gewonnen:':<25} {wins} ({win_rate:.0f}%)")
    print(f"  {'Verloren:':<25} {losses}")
    if max_win > 0:
        print(f"  {'Beste trade:':<25} EUR {max_win:>+,.2f}")
    if max_loss < 0:
        print(f"  {'Slechtste trade:':<25} EUR {max_loss:>+,.2f}")
    print(f"{'='*95}\n")


def print_comparison(paper_results, paper_cash=1000.0):
    """
    Print a comparison table of multiple paper trade results.

    Args:
        paper_results: list of dicts from run_paper_trade()
        paper_cash: Starting capital
    """
    print(f"\n{'='*95}")
    print(f"  VERGELIJKING")
    print(f"{'='*95}")
    print(f"  {'Strategie':<35} {'Start':>10} {'Eind':>10} {'P&L':>12} {'Return':>8} {'Trades':>7}")
    print(f"  {'-'*82}")

    for r in paper_results:
        pnl = r['end_capital'] - r['start_capital']
        ret = (pnl / r['start_capital']) * 100
        n_trades = len(r['trades'])
        name = f"{r['strategy']} ({r['timeframe'].upper()})"
        if len(name) > 33:
            name = name[:33] + '..'
        print(f"  {name:<35} EUR{r['start_capital']:>9,.2f} EUR{r['end_capital']:>9,.2f} "
              f"EUR{pnl:>+10,.2f} {ret:>+6.1f}% {n_trades:>6}")

    # Buy & Hold line (use first result's coin data)
    if paper_results:
        r0 = paper_results[0]
        bh_pnl = paper_cash * r0['coin_change_pct'] / 100
        bh_end = paper_cash + bh_pnl
        print(f"  {'Buy & Hold ' + r0['coin']:<35} EUR{paper_cash:>9,.2f} EUR{bh_end:>9,.2f} "
              f"EUR{bh_pnl:>+10,.2f} {r0['coin_change_pct']:>+6.1f}%      -")

    print(f"  {'-'*82}")
    print(f"{'='*95}\n")
