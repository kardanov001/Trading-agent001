"""
trader.py — Исполнение сделок
===============================
Этот модуль отвечает за выставление заявок на покупку и продажу.

ВАЖНО: агент использует ТОЛЬКО лимитные заявки — это безопаснее рыночных,
потому что вы заранее знаете цену исполнения.
"""

from typing import Optional
from decimal import Decimal

from tinkoff.invest import (
    OrderDirection,
    OrderType,
)
from tinkoff.invest.utils import decimal_to_quotation

from market_data import get_client


def place_buy_order(token: str, mode: str, account_id: str,
                   figi: str, quantity_lots: int,
                   price: float) -> Optional[dict]:
    """
    Выставляет лимитную заявку на ПОКУПКУ.

    :param token: токен T-Invest
    :param mode: режим (sandbox/production)
    :param account_id: ID счёта
    :param figi: FIGI инструмента
    :param quantity_lots: количество ЛОТОВ (не акций!)
    :param price: лимитная цена за акцию
    :return: словарь с информацией о заявке или None при ошибке
    """
    try:
        with get_client(token, mode) as client:
            quotation_price = decimal_to_quotation(Decimal(str(round(price, 2))))

            if mode == "sandbox":
                response = client.sandbox.post_sandbox_order(
                    figi=figi,
                    quantity=quantity_lots,
                    price=quotation_price,
                    direction=OrderDirection.ORDER_DIRECTION_BUY,
                    account_id=account_id,
                    order_type=OrderType.ORDER_TYPE_LIMIT,
                )
            else:
                response = client.orders.post_order(
                    figi=figi,
                    quantity=quantity_lots,
                    price=quotation_price,
                    direction=OrderDirection.ORDER_DIRECTION_BUY,
                    account_id=account_id,
                    order_type=OrderType.ORDER_TYPE_LIMIT,
                )

            return {
                "order_id": response.order_id,
                "status": str(response.execution_report_status),
                "direction": "BUY",
                "figi": figi,
                "quantity_lots": quantity_lots,
                "price": price,
            }

    except Exception as e:
        print(f"❌ Ошибка при выставлении заявки на покупку {figi}: {e}")
        return None


def place_sell_order(token: str, mode: str, account_id: str,
                    figi: str, quantity_lots: int,
                    price: float) -> Optional[dict]:
    """
    Выставляет лимитную заявку на ПРОДАЖУ.

    :param quantity_lots: количество ЛОТОВ для продажи
    :param price: лимитная цена за акцию
    :return: словарь с информацией о заявке или None
    """
    try:
        with get_client(token, mode) as client:
            quotation_price = decimal_to_quotation(Decimal(str(round(price, 2))))

            if mode == "sandbox":
                response = client.sandbox.post_sandbox_order(
                    figi=figi,
                    quantity=quantity_lots,
                    price=quotation_price,
                    direction=OrderDirection.ORDER_DIRECTION_SELL,
                    account_id=account_id,
                    order_type=OrderType.ORDER_TYPE_LIMIT,
                )
            else:
                response = client.orders.post_order(
                    figi=figi,
                    quantity=quantity_lots,
                    price=quotation_price,
                    direction=OrderDirection.ORDER_DIRECTION_SELL,
                    account_id=account_id,
                    order_type=OrderType.ORDER_TYPE_LIMIT,
                )

            return {
                "order_id": response.order_id,
                "status": str(response.execution_report_status),
                "direction": "SELL",
                "figi": figi,
                "quantity_lots": quantity_lots,
                "price": price,
            }

    except Exception as e:
        print(f"❌ Ошибка при выставлении заявки на продажу {figi}: {e}")
        return None


def get_lot_size(token: str, mode: str, figi: str) -> int:
    """
    Получает размер лота для инструмента.

    На МосБирже акции торгуются ЛОТАМИ. Например, 1 лот Сбербанка = 10 акций.
    Поэтому при покупке 50 акций нужно купить 5 лотов.

    :return: количество акций в одном лоте
    """
    try:
        with get_client(token, mode) as client:
            from tinkoff.invest import InstrumentIdType
            instrument = client.instruments.get_instrument_by(
                id_type=InstrumentIdType.INSTRUMENT_ID_TYPE_FIGI,
                id=figi,
            )
            return instrument.instrument.lot
    except Exception as e:
        print(f"❌ Ошибка получения размера лота {figi}: {e}")
        return 1


def get_active_orders(token: str, mode: str, account_id: str) -> list:
    """
    Получает список активных (неисполненных) заявок.

    :return: список заявок
    """
    try:
        with get_client(token, mode) as client:
            if mode == "sandbox":
                response = client.sandbox.get_sandbox_orders(account_id=account_id)
            else:
                response = client.orders.get_orders(account_id=account_id)

            return [
                {
                    "order_id": o.order_id,
                    "figi": o.figi,
                    "direction": str(o.direction),
                }
                for o in response.orders
            ]
    except Exception as e:
        print(f"❌ Ошибка получения активных заявок: {e}")
        return []


def cancel_order(token: str, mode: str, account_id: str, order_id: str) -> bool:
    """
    Отменяет заявку по её ID.

    :return: True если успешно отменена
    """
    try:
        with get_client(token, mode) as client:
            if mode == "sandbox":
                client.sandbox.cancel_sandbox_order(
                    account_id=account_id, order_id=order_id)
            else:
                client.orders.cancel_order(
                    account_id=account_id, order_id=order_id)
            return True
    except Exception as e:
        print(f"❌ Ошибка отмены заявки {order_id}: {e}")
        return False


def shares_to_lots(shares: int, lot_size: int) -> int:
    """
    Переводит количество акций в количество лотов (округляя вниз).

    Пример: хотим 53 акции, лот = 10 → покупаем 5 лотов = 50 акций.

    :param shares: желаемое количество акций
    :param lot_size: размер лота
    :return: количество лотов
    """
    if lot_size <= 0:
        return 0
    return shares // lot_size
