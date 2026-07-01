"""
indicators.py — Расчёт технических индикаторов
================================================
EMA (Exponential Moving Average) — экспоненциальная скользящая средняя
ATR (Average True Range) — средний истинный диапазон (волатильность)
"""

import pandas as pd
import numpy as np


def calculate_ema(prices: pd.Series, period: int) -> pd.Series:
    """
    Рассчитывает экспоненциальную скользящую среднюю (EMA).

    EMA даёт больший вес последним значениям, поэтому быстрее реагирует
    на изменения цены, чем простая средняя.

    :param prices: pandas Series с ценами закрытия
    :param period: период EMA (например, 20, 50, 200)
    :return: pandas Series со значениями EMA
    """
    return prices.ewm(span=period, adjust=False).mean()


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series,
                  period: int = 14) -> pd.Series:
    """
    Рассчитывает ATR (Average True Range) — индикатор волатильности.

    Истинный диапазон (TR) — максимум из трёх:
    1. Сегодняшний максимум минус сегодняшний минимум
    2. Сегодняшний максимум минус вчерашнее закрытие (по модулю)
    3. Сегодняшний минимум минус вчерашнее закрытие (по модулю)

    ATR = скользящее среднее TR за period дней.

    :param high: pandas Series с максимумами дня
    :param low: pandas Series с минимумами дня
    :param close: pandas Series с ценами закрытия
    :param period: период ATR (стандарт — 14)
    :return: pandas Series со значениями ATR
    """
    # Сдвигаем закрытия на 1 день назад
    prev_close = close.shift(1)

    # Три варианта истинного диапазона
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()

    # True Range — максимум из трёх
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # ATR — скользящее среднее TR
    atr = true_range.rolling(window=period).mean()

    return atr


def is_pullback_to_ema(prices: pd.Series, ema: pd.Series,
                       tolerance: float = 0.02) -> bool:
    """
    Проверяет, сделала ли цена откат к EMA.

    Откат — это когда после восходящего движения цена снижается
    и приближается к EMA снизу. Это потенциальная точка покупки.

    :param prices: pandas Series с ценами закрытия (последние 5-10 дней)
    :param ema: pandas Series с EMA (того же периода что и prices)
    :param tolerance: насколько близко к EMA должна подойти цена (доля)
    :return: True если откат произошёл, иначе False
    """
    if len(prices) < 5:
        return False

    # Берём последние 5 дней
    recent_prices = prices.tail(5)
    recent_ema = ema.tail(5)

    # Цена должна была коснуться или почти коснуться EMA
    # tolerance=0.02 означает в пределах 2% от EMA
    distances = (recent_prices - recent_ema) / recent_ema
    min_distance = distances.min()

    # Откат произошёл, если минимальное расстояние было в пределах tolerance
    return -tolerance <= min_distance <= tolerance


def is_breakout_high(prices: pd.Series, period: int = 20) -> bool:
    """
    Проверяет, пробила ли цена локальный максимум последних N дней.

    Это второй тип сигнала — пробой максимума.

    :param prices: pandas Series с ценами закрытия (последние period+1 дней)
    :param period: за сколько дней брать максимум
    :return: True если последняя цена пробила максимум, иначе False
    """
    if len(prices) < period + 1:
        return False

    # Максимум предыдущих period дней (БЕЗ последнего дня)
    prev_max = prices.iloc[-period - 1:-1].max()

    # Последнее закрытие
    last_close = prices.iloc[-1]

    return last_close > prev_max


def is_confirming_candle(open_prices: pd.Series, close_prices: pd.Series,
                        volumes: pd.Series, avg_volume: float) -> bool:
    """
    Проверяет, является ли последняя дневная свеча подтверждающей.

    Подтверждающая свеча должна быть:
    1. Бычьей (закрытие выше открытия), И
    2. Закрытие выше вчерашнего закрытия, И
    3. Объём выше среднего за 20 дней

    :param open_prices: цены открытия
    :param close_prices: цены закрытия
    :param volumes: объёмы торгов
    :param avg_volume: средний объём за 20 дней
    :return: True если свеча подтверждающая
    """
    if len(close_prices) < 2:
        return False

    last_open = open_prices.iloc[-1]
    last_close = close_prices.iloc[-1]
    prev_close = close_prices.iloc[-2]
    last_volume = volumes.iloc[-1]

    # Бычья свеча (закрытие выше открытия)
    is_bullish = last_close > last_open

    # Закрытие выше вчерашнего
    higher_close = last_close > prev_close

    # Объём выше среднего
    volume_ok = last_volume >= avg_volume

    return is_bullish and higher_close and volume_ok


def calculate_momentum_score(prices: pd.Series, period: int = 60) -> float:
    """
    Рассчитывает momentum (силу тренда) за последние N дней.

    Чем выше значение, тем сильнее тренд.
    Используется для приоритизации сигналов: покупаем самые сильные бумаги.

    :param prices: pandas Series с ценами закрытия
    :param period: за сколько дней считать (60 дней по умолчанию)
    :return: процент роста за период
    """
    if len(prices) < period:
        return 0.0

    price_then = prices.iloc[-period]
    price_now = prices.iloc[-1]

    if price_then <= 0:
        return 0.0

    return (price_now / price_then - 1) * 100  # в процентах
