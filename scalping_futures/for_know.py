import asyncio
import uuid
from pprint import pprint

from tinkoff.invest.utils import now
from tinkoff.invest import (
    AsyncClient,
    OrderDirection,
    OrderType,
    StopOrderDirection,
    Quotation,
    StopOrderType,
    ExchangeOrderType,
    TakeProfitType,
    OperationType,
)
from tinkoff.invest.async_services import AsyncServices, PostOrderAsyncRequest

from utils import TOKEN, FIGI, ACCOUNT_ID, INSTRUMENT_ID, change_quotation


async def func():
    async with AsyncClient(TOKEN) as client:
        await client.stop_orders.post_stop_order(
        instrument_id=INSTRUMENT_ID,
        quantity=1,
        stop_price=Quotation(units=3, nano=100000000),
        direction=StopOrderDirection.STOP_ORDER_DIRECTION_SELL,
        account_id=ACCOUNT_ID,
        stop_order_type=StopOrderType.STOP_ORDER_TYPE_STOP_LOSS,
        exchange_order_type=ExchangeOrderType.EXCHANGE_ORDER_TYPE_MARKET,
        # take_profit_type=TakeProfitType.TAKE_PROFIT_TYPE_REGULAR,
        expiration_type=1,
        )

if __name__ == '__main__':
    asyncio.run(func())