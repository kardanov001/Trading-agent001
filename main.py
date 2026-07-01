"""
main.py — Главный файл торгового агента
=========================================
Это точка входа. Запускается раз в день в 19:00.

Что делает агент при запуске:
1. Подключается к T-Invest API
2. Проверяет рыночный фильтр (индекс МосБиржи)
3. Анализирует новости
4. Проверяет открытые позиции (нужно ли выходить)
5. Ищет сигналы для входа
6. Выставляет заявки (если есть качественные сигналы)
7. Формирует отчёт

ЗАПУСК:
    python main.py            — обычный режим (анализ + торговля)
    python main.py --dry-run  — только анализ, БЕЗ выставления заявок
    python main.py --setup    — первоначальная настройка счёта песочницы
"""

import sys
import os
from datetime import datetime

from dotenv import load_dotenv

import config
from market_data import (
    get_ticker_to_figi_map,
    get_candles,
    get_imoex_data,
    get_orderbook,
    get_account_id,
    get_portfolio,
    fund_sandbox_account,
)
from strategy import (
    check_market_filter,
    check_liquidity,
    find_entry_signal,
    filter_signals_by_diversification,
    prioritize_signals,
    check_exit_conditions,
)
from news_filter import (
    analyze_news_for_tickers,
    get_blocked_tickers,
    get_news_summary_for_report,
)
from trader import (
    place_buy_order,
    place_sell_order,
    get_lot_size,
    shares_to_lots,
)
from reporter import log_trade, print_and_save_report


# Загружаем переменные окружения из файла .env
load_dotenv()

TOKEN = os.getenv("TINKOFF_TOKEN")
MODE = os.getenv("TRADING_MODE", "sandbox")


def setup_sandbox():
    """
    Первоначальная настройка: создаёт счёт песочницы и пополняет его.
    Запускается один раз командой: python main.py --setup
    """
    print("🔧 НАСТРОЙКА ПЕСОЧНИЦЫ")
    print("-" * 40)

    account_id = get_account_id(TOKEN, "sandbox")
    print(f"✅ Счёт песочницы: {account_id}")

    print(f"💰 Пополняю счёт на {config.INITIAL_CAPITAL:,} ₽...")
    fund_sandbox_account(TOKEN, account_id, config.INITIAL_CAPITAL)
    print("✅ Счёт пополнен виртуальными деньгами")

    # Проверяем
    portfolio = get_portfolio(TOKEN, "sandbox", account_id)
    print(f"✅ Текущая стоимость портфеля: {portfolio['total_value']:,.0f} ₽")
    print("\n🎉 Настройка завершена! Теперь можно запускать: python main.py --dry-run")


def run_agent(dry_run: bool = False):
    """
    Основной цикл работы агента.

    :param dry_run: если True — только анализ, без реальных заявок
    """
    print("=" * 60)
    print(f"🤖 ТОРГОВЫЙ АГЕНТ ЗАПУЩЕН")
    print(f"   Режим: {MODE.upper()}")
    print(f"   Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if dry_run:
        print(f"   ⚠️  DRY-RUN: заявки НЕ будут выставлены (только анализ)")
    print("=" * 60)

    # --- Проверка токена ---
    if not TOKEN or TOKEN == "вставьте_ваш_токен_сюда":
        print("❌ ОШИБКА: токен не указан!")
        print("   Откройте файл .env и вставьте ваш токен T-Invest.")
        return

    # =========================================================
    # ШАГ 1: Подключение и получение информации о счёте
    # =========================================================
    print("\n[ШАГ 1] Подключение к T-Invest API...")
    try:
        account_id = get_account_id(TOKEN, MODE)
        print(f"  ✅ Счёт: {account_id}")
    except Exception as e:
        print(f"  ❌ Не удалось подключиться: {e}")
        return

    # Получаем портфель
    try:
        portfolio = get_portfolio(TOKEN, MODE, account_id)
        capital = portfolio["total_value"]
        print(f"  ✅ Капитал: {capital:,.0f} ₽")
    except Exception as e:
        print(f"  ❌ Не удалось получить портфель: {e}")
        return

    # =========================================================
    # ШАГ 2: Получение FIGI для всех бумаг
    # =========================================================
    print("\n[ШАГ 2] Получение идентификаторов бумаг...")
    all_tickers = list(config.WATCHLIST.keys())
    try:
        figi_map = get_ticker_to_figi_map(TOKEN, MODE, all_tickers)
        print(f"  ✅ Получено FIGI для {len(figi_map)} бумаг")
    except Exception as e:
        print(f"  ❌ Ошибка получения FIGI: {e}")
        return

    # =========================================================
    # ШАГ 3: Рыночный фильтр (индекс МосБиржи)
    # =========================================================
    print("\n[ШАГ 3] Проверка рыночного фильтра...")
    imoex_df = get_imoex_data(TOKEN, MODE, config.HISTORY_DAYS)
    if imoex_df is None or imoex_df.empty:
        print("  ⚠️  Не удалось получить данные IMOEX — фильтр считается отрицательным")
        market_filter = {"is_positive": False, "reason": "Нет данных IMOEX"}
    else:
        market_filter = check_market_filter(imoex_df)
        status = "✅ ПОЛОЖИТЕЛЬНЫЙ" if market_filter["is_positive"] else "❌ ОТРИЦАТЕЛЬНЫЙ"
        print(f"  Рыночный фильтр: {status}")
        print(f"  {market_filter['reason']}")

    # =========================================================
    # ШАГ 4: Анализ новостей
    # =========================================================
    print("\n[ШАГ 4] Анализ новостного фона...")
    try:
        ticker_news = analyze_news_for_tickers(max_hours_ago=24)
        blocked_tickers = get_blocked_tickers(ticker_news)
        news_summary = get_news_summary_for_report(ticker_news)
        if blocked_tickers:
            print(f"  ⚠️  Заблокированы из-за новостей: {', '.join(blocked_tickers)}")
        else:
            print(f"  ✅ Негативных новостей по бумагам не обнаружено")
    except Exception as e:
        print(f"  ⚠️  Ошибка анализа новостей: {e}")
        ticker_news = {}
        blocked_tickers = set()
        news_summary = "  Анализ новостей недоступен"

    # =========================================================
    # ШАГ 5: Проверка открытых позиций (выход)
    # =========================================================
    print("\n[ШАГ 5] Проверка открытых позиций...")
    # Здесь должна быть логика сопоставления портфеля с журналом сделок
    # Для прототипа — упрощённо
    open_positions = []  # TODO: загружать из журнала + сверять с портфелем
    if not portfolio["positions"]:
        print("  Открытых позиций нет")
    else:
        print(f"  Открытых позиций: {len(portfolio['positions'])}")
        # Проверка условий выхода для каждой позиции
        for pos in portfolio["positions"]:
            figi = pos["figi"]
            # Находим тикер по FIGI
            ticker = next((t for t, f in figi_map.items() if f == figi), None)
            if ticker:
                candles = get_candles(TOKEN, MODE, figi, config.HISTORY_DAYS)
                exit_reason = check_exit_conditions(
                    {"entry_price": pos["average_price"], "stop_loss": 0,
                     "target_2r": float("inf")},
                    candles, market_filter
                )
                if exit_reason:
                    print(f"  🔔 {ticker}: сигнал на выход — {exit_reason}")

    # =========================================================
    # ШАГ 6: Поиск сигналов входа
    # =========================================================
    print("\n[ШАГ 6] Поиск сигналов входа...")

    signals = []

    # Сигналы ищем только если рыночный фильтр положительный
    if not market_filter["is_positive"]:
        print("  ⏸️  Рыночный фильтр отрицательный — поиск входов пропущен")
        print("  💡 В защитном режиме рекомендуется держать LQDT")
    else:
        # Проверяем лимит позиций
        current_positions_count = len(portfolio["positions"])
        if current_positions_count >= config.MAX_POSITIONS:
            print(f"  ⏸️  Уже открыто {current_positions_count} позиций "
                  f"(лимит {config.MAX_POSITIONS}) — новые входы запрещены")
        else:
            # Проверяем достаточно ли свободных средств
            cash_estimate = capital  # упрощённо
            min_cash = capital * config.MIN_CASH_RATIO

            # Сканируем каждую бумагу
            scanned = 0
            for ticker in all_tickers:
                if ticker in blocked_tickers:
                    continue  # пропускаем заблокированные новостями
                if ticker not in figi_map:
                    continue

                figi = figi_map[ticker]

                try:
                    candles = get_candles(TOKEN, MODE, figi, config.HISTORY_DAYS)
                    if candles.empty:
                        continue

                    # Проверка ликвидности
                    orderbook = get_orderbook(TOKEN, MODE, figi)
                    spread_pct = orderbook["spread_pct"] if orderbook else None
                    liquidity = check_liquidity(candles, spread_pct)
                    if not liquidity["is_liquid"]:
                        continue

                    # Поиск сигнала
                    signal = find_entry_signal(ticker, candles, figi, capital)
                    if signal:
                        signals.append(signal)
                        print(f"  📡 Сигнал: {ticker} ({signal.signal_type}) — {signal.reason}")

                    scanned += 1
                except Exception as e:
                    print(f"  ⚠️  Ошибка анализа {ticker}: {e}")
                    continue

            print(f"  Просканировано бумаг: {scanned}, найдено сигналов: {len(signals)}")

    # =========================================================
    # ШАГ 7: Фильтрация и приоритизация сигналов
    # =========================================================
    selected_signals = []
    if signals:
        print("\n[ШАГ 7] Фильтрация сигналов...")

        # Фильтр по диверсификации (1 позиция на сектор)
        signals = filter_signals_by_diversification(signals, open_positions)

        # Приоритизация по momentum
        signals = prioritize_signals(signals)

        # Сколько позиций можем ещё открыть
        slots_available = config.MAX_POSITIONS - len(portfolio["positions"])
        selected_signals = signals[:slots_available]

        print(f"  Отобрано сигналов к исполнению: {len(selected_signals)}")
        for sig in selected_signals:
            print(f"   ⭐ {sig.ticker}: momentum {sig.momentum_score:+.1f}%, "
                  f"позиция {sig.position_size} шт = {sig.position_cost:,.0f} ₽")

    # =========================================================
    # ШАГ 8: Исполнение сделок
    # =========================================================
    trades_today = []
    if selected_signals and not dry_run:
        print("\n[ШАГ 8] Выставление заявок...")
        for sig in selected_signals:
            lot_size = get_lot_size(TOKEN, MODE, sig.figi)
            lots = shares_to_lots(sig.position_size, lot_size)

            if lots < 1:
                print(f"  ⚠️  {sig.ticker}: позиция меньше 1 лота — пропуск")
                continue

            order = place_buy_order(
                TOKEN, MODE, account_id, sig.figi, lots, sig.entry_price
            )
            if order:
                print(f"  ✅ Заявка на {sig.ticker} выставлена: {order['order_id']}")
                trade_record = {
                    "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "ticker": sig.ticker,
                    "company": config.WATCHLIST[sig.ticker]["name"],
                    "direction": "BUY",
                    "signal_type": sig.signal_type,
                    "entry_price": sig.entry_price,
                    "stop_loss": sig.stop_loss,
                    "risk_per_share": sig.risk_per_share,
                    "position_size": lots * lot_size,
                    "position_cost": sig.position_cost,
                    "risk_rub": sig.risk_rub,
                    "risk_pct": config.MAX_RISK_PER_TRADE * 100,
                    "target_1r": sig.target_1r,
                    "target_2r": sig.target_2r,
                    "reason": sig.reason,
                    "market_filter": "положительный",
                    "result": "открыта",
                }
                log_trade(trade_record)
                trades_today.append(trade_record)
    elif selected_signals and dry_run:
        print("\n[ШАГ 8] DRY-RUN: заявки НЕ выставляются")
        print("  В реальном режиме были бы куплены:")
        for sig in selected_signals:
            print(f"   • {sig.ticker}: {sig.position_size} шт по {sig.entry_price:.2f} ₽")

    # =========================================================
    # ШАГ 9: Формирование отчёта
    # =========================================================
    print("\n[ШАГ 9] Формирование отчёта...")

    report_data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "capital": capital,
        "cash": capital,  # упрощённо
        "drawdown": max(0, (config.INITIAL_CAPITAL - capital) / config.INITIAL_CAPITAL * 100),
        "positions": [
            {"ticker": next((t for t, f in figi_map.items() if f == p["figi"]), p["figi"]),
             "quantity": p["quantity"],
             "entry_price": p["average_price"]}
            for p in portfolio["positions"]
        ],
        "market_filter": market_filter,
        "news_summary": news_summary,
        "blocked_tickers": list(blocked_tickers),
        "signals": [
            {"ticker": s.ticker, "signal_type": s.signal_type,
             "entry_price": s.entry_price, "stop_loss": s.stop_loss}
            for s in signals
        ],
        "trades_today": trades_today,
        "next_plan": "Продолжить мониторинг согласно стратегии",
    }

    print_and_save_report(report_data)

    print("\n✅ Работа агента завершена.")


def main():
    """Точка входа. Разбирает аргументы командной строки."""
    args = sys.argv[1:]

    if "--setup" in args:
        setup_sandbox()
    elif "--dry-run" in args:
        run_agent(dry_run=True)
    else:
        run_agent(dry_run=False)


if __name__ == "__main__":
    main()
