from os import getenv

from tinkoff.invest.utils import now
from tinkoff.invest import (
    Client,
    AsyncClient,
    OrderDirection,
    OrderType,
    PositionsResponse,
    MarketDataRequest,
    SubscribeCandlesRequest,
    SubscriptionAction,
    PostOrderRequest,
    CandleInstrument,
    SubscriptionInterval,
    StopOrderDirection,
    Quotation,
    StopOrderType,
    ExchangeOrderType,
)

from utils import TOKEN, FIGI

account_id = getenv('ACCOUNT_ID')


def open_position_sync(direction, current_price):
    """Синхронное открытие позиции (размещение заявки)."""
    # 1) Проверяем маржу (упрощённо)
    with Client(TOKEN) as client:
        positions = client.operations.get_positions(account_id=account_id)
        print('*pos', positions)
        # Допустим, всё ок.

    # 2) Отправляем рыночную заявку
    order_direction = (
        OrderDirection.ORDER_DIRECTION_BUY if direction == "LONG"
        else OrderDirection.ORDER_DIRECTION_SELL
    )
    order_id = f"scalping_{now().timestamp()}_{direction}"

    request = {
        'figi': FIGI,
        'quantity':1,
        'price': None,  # market order, if supported
        'direction': order_direction,
        'account_id': account_id,
        'order_type': OrderType.ORDER_TYPE_MARKET,
    }
    print(f"Открываем позицию...")

    with Client(TOKEN) as client:
        order_response = client.orders.post_order(**request)
        # Считаем, что заполнился моментально по current_price

    print('*order_resp', order_response)

    position = "long" if direction == "LONG" else "short"
    # self.entry_price = current_price

    # Пример: стоп-лосс на 0.3% от цены
    stop_offset = current_price * 0.003
    if position == "long":
        stop_loss_price = current_price - stop_offset
    else:
        stop_loss_price = current_price + stop_offset

    print(
        f"Позиция {position} открыта ~{current_price:.2f}, "
        f"стоп-лосс {stop_loss_price:.2f}"
    )


def stop_loss(price: Quotation, direction: StopOrderDirection, quantity: int=1):

    with Client(TOKEN) as client:
        resp_stop_loss = client.stop_orders.post_stop_order(
            figi=FIGI,
            quantity=quantity,
            stop_price=price,
            direction=direction,
            account_id=account_id,
            expiration_type=1,
            stop_order_type=StopOrderType.STOP_ORDER_TYPE_STOP_LOSS,
            exchange_order_type=ExchangeOrderType.EXCHANGE_ORDER_TYPE_MARKET,

        )
    return resp_stop_loss


def take_profit(price: Quotation, direction:StopOrderDirection, quantity: int=1):
    with Client(TOKEN) as client:
        resp_take_profit = client.stop_orders.post_stop_order(
            figi=FIGI,
            quantity=quantity,
            stop_price=price,
            direction=direction,
            account_id=account_id,
            expiration_type=1,
            stop_order_type=StopOrderType.STOP_ORDER_TYPE_TAKE_PROFIT,
            exchange_order_type=ExchangeOrderType.EXCHANGE_ORDER_TYPE_MARKET,

        )
    return resp_take_profit


if __name__ == '__main__':
    # print(take_profit())
    stop_loss_price = Quotation(units=3, nano=500000000)
    direction = StopOrderDirection.STOP_ORDER_DIRECTION_BUY
    print(type(direction))
    # print(stop_loss(stop_loss_price, direction))
    # open_position_sync('SHORT', 3.190000)
