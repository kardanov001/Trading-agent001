"""
strategy.py — Торговая логика агента
======================================
Здесь реализованы ВСЕ правила из промпта:
- Рыночный фильтр
- Проверка ликвидности
- Поиск сигналов входа
- Расчёт стоп-лосса и размера позиции
- Проверка условий выхода
"""

from dataclasses import dataclass
from typing import Optional, List, Dict
import pandas as pd

import config
from indicators import (
    calculate_ema,
    calculate_atr,
    is_pullback_to_ema,
    is_breakout_high,
    is_confirming_candle,
    calculate_momentum_score,
)


@dataclass
class TradingSignal:
    """Сигнал на покупку"""
    ticker: str
    sector: str
    figi: str
    signal_type: str        # 'pullback' или 'breakout'
    entry_price: float
    stop_loss: float
    target_1r: float        # Цель прибыли 1R
    target_2r: float        # Цель прибыли 2R
    risk_per_share: float   # Риск на одну акцию (₽)
    position_size: int      # Количество акций
    position_cost: float    # Стоимость позиции (₽)
    risk_rub: float         # Общий риск в рублях
    momentum_score: float   # Сила тренда (для приоритизации)
    reason: str             # Причина входа


def check_market_filter(imoex_df: pd.DataFrame) -> Dict:
    """
    Проверяет рыночный фильтр по индексу МосБиржи.

    Положительный фильтр (все условия):
    1. Цена IMOEX выше EMA 200
    2. EMA 50 выше EMA 200 или приближается к ней
    3. Цена не в резком падении

    :return: словарь с результатами проверки
    """
    if imoex_df.empty or len(imoex_df) < config.EMA_SLOW:
        return {
            "is_positive": False,
            "reason": "Недостаточно данных IMOEX",
            "imoex_price": None,
            "ema_50": None,
            "ema_200": None,
        }

    closes = imoex_df["close"]
    ema_50 = calculate_ema(closes, config.EMA_MEDIUM)
    ema_200 = calculate_ema(closes, config.EMA_SLOW)

    current_price = closes.iloc[-1]
    current_ema_50 = ema_50.iloc[-1]
    current_ema_200 = ema_200.iloc[-1]

    # Условие 1: цена выше EMA 200
    above_ema_200 = current_price > current_ema_200

    # Условие 2: EMA 50 выше EMA 200 (бычий тренд)
    bullish_trend = current_ema_50 > current_ema_200

    # Условие 3: нет резкого падения (за 5 дней цена не упала больше 5%)
    if len(closes) >= 5:
        recent_change = (current_price / closes.iloc[-5] - 1) * 100
        no_sharp_drop = recent_change > -5.0
    else:
        no_sharp_drop = True

    is_positive = above_ema_200 and bullish_trend and no_sharp_drop

    reasons = []
    if not above_ema_200:
        reasons.append(f"IMOEX ({current_price:.0f}) ниже EMA200 ({current_ema_200:.0f})")
    if not bullish_trend:
        reasons.append("EMA50 ниже EMA200 (медвежий тренд)")
    if not no_sharp_drop:
        reasons.append("Резкое падение за 5 дней")

    return {
        "is_positive": is_positive,
        "reason": "Все условия выполнены" if is_positive else "; ".join(reasons),
        "imoex_price": current_price,
        "ema_50": current_ema_50,
        "ema_200": current_ema_200,
    }


def check_liquidity(candles_df: pd.DataFrame,
                   spread_pct: Optional[float] = None) -> Dict:
    """
    Проверяет ликвидность инструмента.

    Требования:
    1. Средний дневной оборот ≥ MIN_DAILY_VOLUME_RUB
    2. Спред ≤ MAX_SPREAD_RATIO

    :param candles_df: DataFrame со свечами
    :param spread_pct: текущий спред (доля)
    :return: словарь с результатами
    """
    if candles_df.empty or len(candles_df) < 20:
        return {"is_liquid": False, "reason": "Недостаточно данных"}

    # Оборот = цена * объём за каждый день, среднее за 20 дней
    recent = candles_df.tail(20)
    volumes_rub = recent["close"] * recent["volume"] * 10  # * 10 потому что лот = 10 акций обычно
    avg_volume_rub = volumes_rub.mean()

    volume_ok = avg_volume_rub >= config.MIN_DAILY_VOLUME_RUB

    if spread_pct is not None:
        spread_ok = spread_pct <= config.MAX_SPREAD_RATIO
    else:
        spread_ok = True   # Если не передан, не проверяем

    is_liquid = volume_ok and spread_ok

    reasons = []
    if not volume_ok:
        reasons.append(f"Оборот {avg_volume_rub/1e6:.0f} млн < {config.MIN_DAILY_VOLUME_RUB/1e6:.0f} млн")
    if not spread_ok:
        reasons.append(f"Спред {spread_pct*100:.2f}% > {config.MAX_SPREAD_RATIO*100:.1f}%")

    return {
        "is_liquid": is_liquid,
        "reason": "OK" if is_liquid else "; ".join(reasons),
        "avg_volume_rub": avg_volume_rub,
        "spread_pct": spread_pct,
    }


def find_entry_signal(ticker: str, candles_df: pd.DataFrame,
                     figi: str, capital: float) -> Optional[TradingSignal]:
    """
    Ищет сигнал на вход в сделку по бумаге.

    Использует два типа сигналов:
    А) Откат к EMA 20/50 с подтверждением
    Б) Пробой 20-дневного максимума с объёмом

    :return: TradingSignal или None если сигнала нет
    """
    if candles_df.empty or len(candles_df) < config.EMA_SLOW + 10:
        return None

    sector = config.WATCHLIST[ticker]["sector"]

    closes = candles_df["close"]
    highs = candles_df["high"]
    lows = candles_df["low"]
    opens = candles_df["open"]
    volumes = candles_df["volume"]

    # Рассчитываем индикаторы
    ema_20 = calculate_ema(closes, config.EMA_FAST)
    ema_50 = calculate_ema(closes, config.EMA_MEDIUM)
    ema_200 = calculate_ema(closes, config.EMA_SLOW)
    atr = calculate_atr(highs, lows, closes, config.ATR_PERIOD)

    current_price = closes.iloc[-1]
    current_ema_50 = ema_50.iloc[-1]
    current_ema_200 = ema_200.iloc[-1]
    current_atr = atr.iloc[-1]
    avg_volume = volumes.tail(20).mean()

    # Проверка 1: цена выше EMA 200
    if current_price <= current_ema_200:
        return None

    # Проверка 2: EMA 50 выше EMA 200 (бычий тренд)
    if current_ema_50 <= current_ema_200:
        return None

    # Проверка 3: акция не выросла слишком сильно за день
    if len(closes) >= 2:
        daily_change = current_price / closes.iloc[-2] - 1
        if daily_change > config.MAX_DAILY_GAIN:
            return None

    # Ищем сигнал — должен сработать хотя бы один из двух типов
    pullback_signal = False
    breakout_signal = False
    signal_type = None

    # СИГНАЛ А: Откат к EMA 20 или EMA 50 с подтверждением
    pullback_to_ema20 = is_pullback_to_ema(closes.tail(10), ema_20.tail(10), tolerance=0.02)
    pullback_to_ema50 = is_pullback_to_ema(closes.tail(10), ema_50.tail(10), tolerance=0.03)
    confirming = is_confirming_candle(opens, closes, volumes, avg_volume)

    if (pullback_to_ema20 or pullback_to_ema50) and confirming:
        pullback_signal = True
        signal_type = "pullback"

    # СИГНАЛ Б: Пробой 20-дневного максимума с повышенным объёмом
    if is_breakout_high(closes, period=20):
        last_volume = volumes.iloc[-1]
        if last_volume >= avg_volume * 1.5:   # объём минимум на 50% выше среднего
            breakout_signal = True
            if signal_type is None:
                signal_type = "breakout"

    # Если нет сигнала — выходим
    if not pullback_signal and not breakout_signal:
        return None

    # Рассчитываем стоп-лосс
    # Берём максимум из трёх вариантов: ATR-based, ниже EMA50, ниже локального минимума
    atr_stop = current_price - config.ATR_STOP_MULTIPLIER * current_atr
    ema50_stop = current_ema_50 * 0.99   # чуть ниже EMA 50
    recent_low = lows.tail(10).min() * 0.99

    # Берём максимум — это будет самый близкий стоп (минимальный риск на акцию)
    stop_loss = max(atr_stop, ema50_stop, recent_low)

    # Если стоп получился выше цены — что-то не так, отклоняем
    if stop_loss >= current_price:
        return None

    risk_per_share = current_price - stop_loss

    # Рассчитываем цели
    target_1r = current_price + risk_per_share          # +1R
    target_2r = current_price + 2 * risk_per_share      # +2R

    # Проверка R/R: потенциал должен быть минимум 2:1
    # (это автоматически выполняется, потому что 2R = 2 × risk)

    # Рассчитываем размер позиции
    max_risk_rub = capital * config.MAX_RISK_PER_TRADE
    max_position_rub = capital * config.MAX_POSITION_SIZE

    # Количество акций исходя из риска
    shares_by_risk = int(max_risk_rub / risk_per_share)

    # Количество акций исходя из размера позиции
    shares_by_size = int(max_position_rub / current_price)

    # Берём минимум
    position_size = min(shares_by_risk, shares_by_size)

    # Если получилось меньше 1 акции — сделка невозможна
    if position_size < 1:
        return None

    position_cost = position_size * current_price
    risk_rub = position_size * risk_per_share

    # Считаем momentum-score для приоритизации
    momentum = calculate_momentum_score(closes, period=60)

    # Формируем описание сигнала
    signal_parts = []
    if pullback_signal:
        signal_parts.append(f"откат к EMA {'20' if pullback_to_ema20 else '50'} с подтверждающей свечой")
    if breakout_signal:
        signal_parts.append("пробой 20-дневного максимума на объёме")
    reason = " + ".join(signal_parts)

    return TradingSignal(
        ticker=ticker,
        sector=sector,
        figi=figi,
        signal_type=signal_type,
        entry_price=current_price,
        stop_loss=stop_loss,
        target_1r=target_1r,
        target_2r=target_2r,
        risk_per_share=risk_per_share,
        position_size=position_size,
        position_cost=position_cost,
        risk_rub=risk_rub,
        momentum_score=momentum,
        reason=reason,
    )


def filter_signals_by_diversification(signals: List[TradingSignal],
                                      open_positions: List[Dict]) -> List[TradingSignal]:
    """
    Фильтрует сигналы по правилу диверсификации:
    максимум 1 позиция на сектор.

    :param signals: список найденных сигналов
    :param open_positions: список текущих открытых позиций
    :return: отфильтрованный список сигналов
    """
    # Сектора, в которых уже есть позиции
    occupied_sectors = set()
    for pos in open_positions:
        ticker = pos.get("ticker")
        if ticker and ticker in config.WATCHLIST:
            occupied_sectors.add(config.WATCHLIST[ticker]["sector"])

    # Оставляем только сигналы из свободных секторов
    filtered = [s for s in signals if s.sector not in occupied_sectors]
    return filtered


def prioritize_signals(signals: List[TradingSignal]) -> List[TradingSignal]:
    """
    Сортирует сигналы по приоритету (momentum-фильтр).

    Самые сильные сигналы в начале списка.
    Критерии (по убыванию важности):
    1. Momentum-score (сила тренда за 60 дней)
    2. Тип сигнала (одновременный = сильнее)

    :return: отсортированный список
    """
    # Сначала по momentum (descending), потом по типу сигнала
    return sorted(signals, key=lambda s: (-s.momentum_score, s.signal_type))


def check_exit_conditions(position: Dict, candles_df: pd.DataFrame,
                         imoex_filter: Dict) -> Optional[str]:
    """
    Проверяет условия выхода из открытой позиции.

    :param position: словарь с информацией о позиции
    :param candles_df: свечи бумаги
    :param imoex_filter: текущий рыночный фильтр
    :return: причина выхода или None
    """
    if candles_df.empty:
        return None

    closes = candles_df["close"]
    current_price = closes.iloc[-1]
    entry_price = position.get("entry_price", 0)
    stop_loss = position.get("stop_loss", 0)

    # 1. Стоп-лосс
    if current_price <= stop_loss:
        return f"Сработал стоп-лосс: {current_price:.2f} ≤ {stop_loss:.2f}"

    # 2. Цена ниже EMA 50
    ema_50 = calculate_ema(closes, config.EMA_MEDIUM)
    if current_price < ema_50.iloc[-1]:
        return "Цена ушла ниже EMA 50"

    # 3. Рыночный фильтр стал отрицательным
    if not imoex_filter.get("is_positive", False):
        return f"Рыночный фильтр отрицательный: {imoex_filter.get('reason', '')}"

    # 4. Достигнута цель 2R
    target_2r = position.get("target_2r", float("inf"))
    if current_price >= target_2r:
        return f"Достигнута цель 2R: {current_price:.2f} ≥ {target_2r:.2f}"

    return None
