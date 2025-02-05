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
    OperationType, PostStopOrderResponse,
)
from tinkoff.invest.async_services import AsyncServices, PostOrderAsyncRequest

from utils import TOKEN, FIGI, ACCOUNT_ID, INSTRUMENT_ID, change_quotation


def get_request(direction: OrderDirection, quantity):
    return PostOrderAsyncRequest(
        instrument_id=INSTRUMENT_ID,
        quantity=quantity,
        account_id=ACCOUNT_ID,
        order_type=OrderType.ORDER_TYPE_MARKET,
        direction=direction,
        order_id=str(uuid.uuid4()),
    )


async def open_position(direction: OrderDirection,
                        quantity):
    # positions = await client.operations.get_positions(account_id=ACCOUNT_ID)
    request = get_request(
        quantity=quantity,
        direction=direction,
    )
    async with AsyncClient(TOKEN) as client:
        order_response = await client.orders.post_order_async(request=request)
    return order_response


async def open_stop_order(client: AsyncServices,
                          stop_price: Quotation,
                          direction: StopOrderDirection,
                          stop_order_type: StopOrderType,
                          quantity: int,
                          ):
    # print('*stop_order_type', stop_order_type)
    parameters = {
        'instrument_id': INSTRUMENT_ID,
        'quantity': quantity,
        'stop_price': stop_price,
        'direction': direction,
        'account_id': ACCOUNT_ID,
        'stop_order_type': stop_order_type,
        'exchange_order_type': ExchangeOrderType.EXCHANGE_ORDER_TYPE_MARKET,
        # 'take_profit_type': TakeProfitType.TAKE_PROFIT_TYPE_REGULAR,
        'expiration_type': 1,
    }
    if stop_order_type == StopOrderType.STOP_ORDER_TYPE_TAKE_PROFIT:
        parameters['take_profit_type'] = ExchangeOrderType.EXCHANGE_ORDER_TYPE_MARKET

    stop_response = await client.stop_orders.post_stop_order(**parameters)
    return stop_response


async def get_last_operation(client: AsyncServices):
    operations = await client.operations.get_operations(account_id=ACCOUNT_ID)
    for operation in operations.operations:
        if operation.operation_type in (OperationType.OPERATION_TYPE_BUY, OperationType.OPERATION_TYPE_SELL):
            # pprint(operation)
            return operation

async def post_stop_orders() -> tuple[PostStopOrderResponse, PostStopOrderResponse]:
    async with (AsyncClient(TOKEN) as client):
        # order_response = await open_position(client, OrderDirection.ORDER_DIRECTION_SELL, quantity=1)
        # print(order_response)
        operation = await get_last_operation(client)
        pprint(operation)
        direction_for_stop = StopOrderDirection.STOP_ORDER_DIRECTION_BUY \
            if operation.operation_type == OperationType.OPERATION_TYPE_SELL \
            else StopOrderDirection.STOP_ORDER_DIRECTION_SELL
        take_profit_price_q, stop_loss_price_q = change_quotation(operation.price)
        if direction_for_stop == 1:
            take_profit_price_q, stop_loss_price_q = stop_loss_price_q, take_profit_price_q

        print(direction_for_stop)
        print(take_profit_price_q)
        print(stop_loss_price_q)

        take_profit_task = open_stop_order(client,
                                           quantity=operation.quantity,
                                           stop_price=take_profit_price_q,
                                           direction=direction_for_stop,
                                           stop_order_type=StopOrderType.STOP_ORDER_TYPE_TAKE_PROFIT)

        stop_loss_task = open_stop_order(client,
                                         quantity=operation.quantity,
                                         stop_price=stop_loss_price_q,
                                         direction=direction_for_stop,
                                         stop_order_type=StopOrderType.STOP_ORDER_TYPE_STOP_LOSS)

        take_profit, stop_loss = await asyncio.gather(take_profit_task, stop_loss_task)

        return take_profit, stop_loss

async def main():
    take_profit, stop_loss = await post_stop_orders()
    print(take_profit, stop_loss)

if __name__ == '__main__':
    asyncio.run(main())
