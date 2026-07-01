"""
reporter.py — Формирование отчётов и журнал сделок
=====================================================
Этот модуль:
- Записывает каждую сделку в журнал (trades.csv)
- Формирует ежедневный отчёт
- Сохраняет отчёты в папку reports/
"""

import os
import csv
from datetime import datetime
from typing import List, Dict

import config


def ensure_directories():
    """Создаёт папки для отчётов, если их нет."""
    os.makedirs(config.REPORTS_DIR, exist_ok=True)
    os.makedirs(config.DAILY_REPORTS_DIR, exist_ok=True)
    os.makedirs(config.WEEKLY_REPORTS_DIR, exist_ok=True)


def log_trade(trade: Dict):
    """
    Записывает сделку в журнал trades.csv.

    :param trade: словарь с данными сделки
    """
    ensure_directories()
    filepath = os.path.join(config.REPORTS_DIR, config.TRADES_LOG_FILE)

    # Заголовки столбцов журнала
    fieldnames = [
        "datetime", "ticker", "company", "direction",
        "signal_type", "entry_price", "stop_loss",
        "risk_per_share", "position_size", "position_cost",
        "risk_rub", "risk_pct", "target_1r", "target_2r",
        "reason", "market_filter", "result",
    ]

    # Если файла нет — создаём с заголовками
    file_exists = os.path.isfile(filepath)

    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        # Записываем только известные поля
        row = {key: trade.get(key, "") for key in fieldnames}
        writer.writerow(row)

    print(f"  📝 Сделка записана в журнал: {trade.get('ticker')}")


def format_daily_report(data: Dict) -> str:
    """
    Формирует текст ежедневного отчёта.

    :param data: словарь со всеми данными за день
    :return: текст отчёта
    """
    lines = []
    lines.append("=" * 60)
    lines.append(f"📅 ЕЖЕДНЕВНЫЙ ОТЧЁТ — {data.get('date', 'н/д')}")
    lines.append("=" * 60)
    lines.append("")

    # Капитал
    lines.append(f"💰 КАПИТАЛ: {data.get('capital', 0):,.0f} ₽")
    cash = data.get("cash", 0)
    capital = data.get("capital", 1)
    cash_pct = (cash / capital * 100) if capital > 0 else 0
    lines.append(f"🆓 СВОБОДНЫЕ СРЕДСТВА: {cash:,.0f} ₽ ({cash_pct:.0f}%)")
    lines.append(f"📉 ТЕКУЩАЯ ПРОСАДКА: {data.get('drawdown', 0):.1f}%")
    lines.append("")

    # Открытые позиции
    positions = data.get("positions", [])
    if positions:
        lines.append("📊 ОТКРЫТЫЕ ПОЗИЦИИ:")
        for pos in positions:
            lines.append(f"   • {pos.get('ticker', '?')}: "
                        f"{pos.get('quantity', 0):.0f} шт по "
                        f"{pos.get('entry_price', 0):.2f} ₽")
    else:
        lines.append("📊 ОТКРЫТЫЕ ПОЗИЦИИ: нет")
    lines.append("")

    # Рыночный фильтр
    mf = data.get("market_filter", {})
    filter_status = "✅ Положительный" if mf.get("is_positive") else "❌ Отрицательный"
    lines.append(f"🔍 РЫНОЧНЫЙ ФИЛЬТР: {filter_status}")
    if mf.get("imoex_price"):
        lines.append(f"   IMOEX: {mf.get('imoex_price', 0):.0f} | "
                    f"EMA50: {mf.get('ema_50', 0):.0f} | "
                    f"EMA200: {mf.get('ema_200', 0):.0f}")
    lines.append(f"   {mf.get('reason', '')}")
    lines.append("")

    # Новостной фон
    lines.append("📰 НОВОСТНОЙ ФОН:")
    lines.append(data.get("news_summary", "  нет данных"))
    blocked = data.get("blocked_tickers", [])
    if blocked:
        lines.append(f"   Исключено из-за новостей: {', '.join(blocked)}")
    lines.append("")

    # Новые сигналы
    signals = data.get("signals", [])
    if signals:
        lines.append("📡 НОВЫЕ СИГНАЛЫ:")
        for sig in signals:
            lines.append(f"   • {sig.get('ticker', '?')} "
                        f"({sig.get('signal_type', '?')}): "
                        f"вход {sig.get('entry_price', 0):.2f}, "
                        f"стоп {sig.get('stop_loss', 0):.2f}, "
                        f"R/R 2:1")
    else:
        lines.append("📡 НОВЫЕ СИГНАЛЫ: нет сигналов")
    lines.append("")

    # Сделки за день
    trades = data.get("trades_today", [])
    if trades:
        lines.append("💼 СДЕЛКИ ЗА ДЕНЬ:")
        for t in trades:
            lines.append(f"   • {t.get('direction', '?')} "
                        f"{t.get('ticker', '?')}: "
                        f"{t.get('position_size', 0)} шт по "
                        f"{t.get('entry_price', 0):.2f} ₽")
    else:
        lines.append("💼 СДЕЛКИ ЗА ДЕНЬ: нет сделок")
    lines.append("")

    # План на следующий день
    lines.append(f"📌 ПЛАН НА СЛЕДУЮЩИЙ ДЕНЬ: {data.get('next_plan', 'продолжить мониторинг')}")
    lines.append("")
    lines.append("=" * 60)

    return "\n".join(lines)


def save_daily_report(report_text: str, date_str: str):
    """
    Сохраняет ежедневный отчёт в файл.

    :param report_text: текст отчёта
    :param date_str: дата в формате YYYY-MM-DD
    """
    ensure_directories()
    filename = f"report_{date_str}.txt"
    filepath = os.path.join(config.DAILY_REPORTS_DIR, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"  💾 Отчёт сохранён: {filepath}")


def print_and_save_report(data: Dict):
    """
    Формирует отчёт, выводит в консоль и сохраняет в файл.

    :param data: словарь со всеми данными за день
    """
    report = format_daily_report(data)
    print("\n" + report)

    date_str = data.get("date", datetime.now().strftime("%Y-%m-%d"))
    save_daily_report(report, date_str)
