"""
market_data.py — Получение рыночных данных от T-Invest API
============================================================
Этот модуль отвечает за всё взаимодействие с биржей:
- Получение списка инструментов и их FIGI (уникальных идентификаторов)
- Загрузка исторических данных (свечей)
- Получение текущих цен и стакана
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import pandas as pd

from tinkoff.invest import (
    Client,
    CandleInterval,
    InstrumentIdType,
)
from tinkoff.invest.sandbox.client import SandboxClient
from tinkoff.invest.utils import quotation_to_decimal


def get_client(token: str, mode: str = "sandbox"):
    """
    Создаёт клиент для подключения к T-Invest API.

    :param token: токен доступа
    :param mode: "sandbox" для песочницы, "production" для реального счёта
    :return: контекстный менеджер клиента
    """
    if mode == "sandbox":
        return SandboxClient(token)
    else:
        return Client(token)


def get_ticker_to_figi_map(token: str, mode: str,
                          tickers: List[str]) -> Dict[str, str]:
    """
    Получает FIGI (уникальный идентификатор биржи) для каждого тикера.

    FIGI нужен для всех операций с T-Invest API — это как ISIN, но проще.
    Например, FIGI Сбербанка: BBG004730N88

    :param token: токен T-Invest
    :param mode: режим работы
    :param tickers: список тикеров, например ["SBER", "GAZP", "LKOH"]
    :return: словарь {тикер: FIGI}
    """
    result = {}
    with get_client(token, mode) as client:
        # Получаем список всех акций на МосБирже
        shares = client.instruments.shares()
        for share in shares.instruments:
            if share.ticker in tickers and share.class_code == "TQBR":
                result[share.ticker] = share.figi

        # Получаем ETF (для защитных инструментов LQDT, SBMM, TMON)
        etfs = client.instruments.etfs()
        for etf in etfs.instruments:
            if etf.ticker in tickers:
                result[etf.ticker] = etf.figi

    return result


def get_candles(token: str, mode: str, figi: str,
               days: int = 250) -> pd.DataFrame:
    """
    Загружает исторические дневные свечи для инструмента.

    :param token: токен T-Invest
    :param mode: режим работы
    :param figi: FIGI инструмента
    :param days: за сколько дней назад загружать
    :return: DataFrame с колонками: time, open, high, low, close, volume
    """
    now = datetime.now(timezone.utc)
    from_date = now - timedelta(days=days)

    candles_data = []

    with get_client(token, mode) as client:
        for candle in client.get_all_candles(
            figi=figi,
            from_=from_date,
            to=now,
            interval=CandleInterval.CANDLE_INTERVAL_DAY,
        ):
            candles_data.append({
                "time": candle.time,
                "open": float(quotation_to_decimal(candle.open)),
                "high": float(quotation_to_decimal(candle.high)),
                "low": float(quotation_to_decimal(candle.low)),
                "close": float(quotation_to_decimal(candle.close)),
                "volume": candle.volume,
            })

    df = pd.DataFrame(candles_data)
    if not df.empty:
        df = df.sort_values("time").reset_index(drop=True)

    return df


def get_last_price(token: str, mode: str, figi: str) -> Optional[float]:
    """
    Получает последнюю цену инструмента.

    :return: цена в рублях или None если не удалось получить
    """
    with get_client(token, mode) as client:
        response = client.market_data.get_last_prices(figi=[figi])
        if response.last_prices:
            return float(quotation_to_decimal(response.last_prices[0].price))
    return None


def get_orderbook(token: str, mode: str, figi: str, depth: int = 1) -> Optional[dict]:
    """
    Получает стакан (лучшие цены покупки и продажи).

    Нужно для проверки спреда — разницы между bid и ask.

    :return: словарь с bid и ask или None
    """
    with get_client(token, mode) as client:
        ob = client.market_data.get_order_book(figi=figi, depth=depth)
        if ob.bids and ob.asks:
            bid = float(quotation_to_decimal(ob.bids[0].price))
            ask = float(quotation_to_decimal(ob.asks[0].price))
            return {"bid": bid, "ask": ask, "spread": ask - bid,
                    "spread_pct": (ask - bid) / bid if bid > 0 else 1.0}
    return None


def get_imoex_data(token: str, mode: str, days: int = 250) -> Optional[pd.DataFrame]:
    """
    Получает дневные данные по индексу МосБиржи (IMOEX).

    Это нужно для рыночного фильтра.

    :return: DataFrame с данными IMOEX или None
    """
    # FIGI индекса МосБиржи: BBG333333333
    # Для индексов используется другой метод
    imoex_figi = "BBG333333333"

    try:
        return get_candles(token, mode, imoex_figi, days)
    except Exception as e:
        print(f"Не удалось получить данные IMOEX: {e}")
        return None


def get_account_id(token: str, mode: str) -> Optional[str]:
    """
    Получает ID счёта.

    Для песочницы — открывает новый счёт если нет, или берёт первый существующий.
    Для реального счёта — возвращает первый брокерский счёт.

    :return: ID счёта
    """
    with get_client(token, mode) as client:
        if mode == "sandbox":
            # Получаем счета песочницы
            accounts = client.users.get_accounts()
            if accounts.accounts:
                return accounts.accounts[0].id
            else:
                # Создаём новый счёт песочницы
                new_account = client.sandbox.open_sandbox_account()
                return new_account.account_id
        else:
            # Реальный счёт
            accounts = client.users.get_accounts()
            for acc in accounts.accounts:
                # Берём первый брокерский счёт
                if hasattr(acc, "type"):
                    return acc.id
            return accounts.accounts[0].id if accounts.accounts else None


def fund_sandbox_account(token: str, account_id: str, amount: int):
    """
    Пополняет счёт в песочнице виртуальными деньгами.

    :param amount: сумма в рублях
    """
    from tinkoff.invest.schemas import MoneyValue

    with get_client(token, "sandbox") as client:
        client.sandbox.sandbox_pay_in(
            account_id=account_id,
            amount=MoneyValue(currency="rub", units=amount, nano=0)
        )


def get_portfolio(token: str, mode: str, account_id: str) -> dict:
    """
    Получает информацию о портфеле: позиции, свободные деньги, общая стоимость.

    :return: словарь с информацией о портфеле
    """
    with get_client(token, mode) as client:
        if mode == "sandbox":
            portfolio = client.sandbox.get_sandbox_portfolio(account_id=account_id)
        else:
            portfolio = client.operations.get_portfolio(account_id=account_id)

        positions = []
        for pos in portfolio.positions:
            positions.append({
                "figi": pos.figi,
                "quantity": float(quotation_to_decimal(pos.quantity)),
                "average_price": float(quotation_to_decimal(pos.average_position_price)),
                "current_price": float(quotation_to_decimal(pos.current_price)) if pos.current_price else 0,
                "expected_yield": float(quotation_to_decimal(pos.expected_yield)),
            })

        total = float(quotation_to_decimal(portfolio.total_amount_portfolio))

        return {
            "total_value": total,
            "positions": positions,
        }
