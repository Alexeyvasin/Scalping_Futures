import asyncio as aio
import uuid
from decimal import Decimal
from pprint import pprint

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
    PostStopOrderRequestTrailingData,
)
from tinkoff.invest.schemas import OrderStateStreamRequest, GetStopOrdersResponse, StopOrderExpirationType
from tinkoff.invest.async_services import AsyncServices, PostOrderAsyncRequest
from tinkoff.invest.utils import now, decimal_to_quotation, quotation_to_decimal

from utils import TOKEN, ACCOUNT_ID, UID, change_quotation
import settings as s
import utils as u


def get_request(direction: OrderDirection, quantity):
    return PostOrderAsyncRequest(
        instrument_id=UID,
        quantity=quantity,
        account_id=ACCOUNT_ID,
        order_type=OrderType.ORDER_TYPE_MARKET,
        direction=direction,
        order_id=str(uuid.uuid4()),
    )


try:
    from main_ChatGPT_o1 import ScalpingBot
except Exception:
    pass

open_position_with_stops_lock = aio.Lock()


async def open_position_with_stops(signal,
                                   # direction: OrderDirection,
                                   # quantity: int,
                                   bot: 'ScalpingBot') -> None:
    async with open_position_with_stops_lock:

        if not u.is_trading_time():
            s.logger.info(f'[o_p_w_s] not trading time. Now is {now()}')
            return
        s.logger.info(f'[o_p_w_s] B---------------------------------')
        s.logger.info(f'[o_p_w_s] Signal is {signal}')
        await bot.update_data()
        direction = None
        quantity = s.config['strategy']['max_contracts']
        if signal == 'long':
            quantity = quantity - bot.futures_quantity
            if quantity > 0:
                direction = OrderDirection.ORDER_DIRECTION_BUY

        elif signal == 'short':
            quantity = quantity + bot.futures_quantity
            if quantity > 0:
                direction = OrderDirection.ORDER_DIRECTION_SELL

        elif signal == 'rsi_for_sell':
            max_contracts = s.config['strategy']['max_contracts']
            if bot.futures_quantity != max_contracts * -1:
                if (quantity := max_contracts + bot.futures_quantity) > 0:
                    s.logger.info(f'It`S NEED TO SELL! RSI = {float(bot.df['RSI'].iloc[-1])}')
                    direction = OrderDirection.ORDER_DIRECTION_SELL
                    s.logger.info(f'[rsi_subscriber]  Trying to SELL. quantity= {quantity}.')

        elif signal == 'rsi_for_buy':
            max_contracts = s.config['strategy']['max_contracts']
            if bot.futures_quantity != max_contracts:
                if (quantity := max_contracts - bot.futures_quantity) > 0:
                    direction = OrderDirection.ORDER_DIRECTION_BUY
                    s.logger.info(f'[rsi_subscriber]  Trying to BUY. quantity= {quantity}.')

        elif signal == 'rsi_for_close':
            s.logger.info(f'It`S NEED TO CLOSE POSITIONS! RSI = {float(bot.df['RSI'].iloc[-1])}')
            quantity = abs(bot.futures_quantity)
            if bot.futures_quantity < 0:
                direction = OrderDirection.ORDER_DIRECTION_BUY
            elif bot.futures_quantity > 0:
                direction = OrderDirection.ORDER_DIRECTION_SELL

        if direction is None or quantity == 0:
            s.logger.info(f'[o_p_w_s]. direction is {direction}. quantity == {quantity}. return')
            return

        if bot.futures_quantity:
            differ = abs(float(quotation_to_decimal(bot.last_deal_price)) - bot.df['close'].iloc[-1]) * 100 / float(quotation_to_decimal(bot.last_deal_price))
            if differ < s.config['strategy']['min_percent_for_interest']:
                s.logger.info(f'[o_p_w_s] cannot be executed. differ is too little: {differ}')
                return
            else:
                s.logger.info(f'[o_p_w_s] Differ is norm! Passed it! last_op_price = {bot.last_deal_price}. '
                              f'price_now = {bot.df['close'].iloc[-1]}')

        if direction == OrderDirection.ORDER_DIRECTION_BUY:
            real_quantity = quantity
        elif direction == OrderDirection.ORDER_DIRECTION_SELL:
            real_quantity = -quantity
        while abs(real_quantity + bot.futures_quantity) > s.config['strategy']['max_contracts'] and quantity > 0:
            if direction == OrderDirection.ORDER_DIRECTION_BUY:
                real_quantity = quantity
            elif direction == OrderDirection.ORDER_DIRECTION_SELL:
                real_quantity = -quantity
            quantity -= 1
        if quantity <= 0:
            s.logger.info(f'[o_p_w_s] The deal cannot commit. quantity = {quantity}')
            return

        resp = await open_position(direction=direction, quantity=quantity)
        s.logger.info(f'[o_p_w_s] {resp}')
        await aio.sleep(20)
        # await bot.update_data()
        stop_resp = await post_stop_orders(bot)
        if stop_resp is not None:
            s.logger.info(f'[o_p_w_s] stop_orders are applied.\n {stop_resp}')
        await aio.sleep(100)
        s.logger.info(f'[o_p_w_s] E---------------------------------')


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
        'instrument_id': UID,
        'quantity': quantity,
        'stop_price': stop_price,
        'direction': direction,
        'account_id': ACCOUNT_ID,
        'stop_order_type': stop_order_type,
        'exchange_order_type': ExchangeOrderType.EXCHANGE_ORDER_TYPE_MARKET,
        # 'take_profit_type': TakeProfitType.TAKE_PROFIT_TYPE_REGULAR,
        'expiration_type': StopOrderExpirationType.STOP_ORDER_EXPIRATION_TYPE_GOOD_TILL_CANCEL,
    }
    if stop_order_type == StopOrderType.STOP_ORDER_TYPE_TAKE_PROFIT:
        parameters['take_profit_type'] = TakeProfitType.TAKE_PROFIT_TYPE_TRAILING
        indent: Quotation = decimal_to_quotation(Decimal(s.config['take_profit']['trailing_indent']))
        trailing_data_parameters = {
            'indent': indent,
            'indent_type': 1,
            #     'spread': Quotation(units=0, nano=5000000),
            #     'spread_type': 2,
        }
        parameters['trailing_data'] = PostStopOrderRequestTrailingData(**trailing_data_parameters)

    stop_response = await client.stop_orders.post_stop_order(**parameters)
    return stop_response


async def get_last_operation(client: AsyncServices):
    operations = await client.operations.get_operations(account_id=ACCOUNT_ID)
    for operation in operations.operations:
        if operation.operation_type in (OperationType.OPERATION_TYPE_BUY, OperationType.OPERATION_TYPE_SELL):
            # pprint(operation)
            return operation


async def post_take_profit(bot) -> PostStopOrderResponse | None:
    async with AsyncClient(TOKEN) as client:
        if bot.futures_quantity == 0:
            return
        quantity = abs(bot.futures_quantity)

        direction_for_stop = StopOrderDirection.STOP_ORDER_DIRECTION_BUY \
            if bot.futures_quantity < 0 else StopOrderDirection.STOP_ORDER_DIRECTION_SELL
        hi_price_q, low_price_q = change_quotation(bot.order_prices[0])
        take_profit_price_q = hi_price_q \
            if direction_for_stop == StopOrderDirection.STOP_ORDER_DIRECTION_SELL else low_price_q

        s.logger.info(f'[take_profit_direction] {direction_for_stop}')
        s.logger.info(f'[take_profit_price] {take_profit_price_q}')
        take_profit_task = open_stop_order(client,
                                           quantity=quantity,
                                           stop_price=take_profit_price_q,
                                           direction=direction_for_stop,
                                           stop_order_type=StopOrderType.STOP_ORDER_TYPE_TAKE_PROFIT)
        return await take_profit_task


async def post_stop_orders(bot) -> tuple[PostStopOrderResponse, PostStopOrderResponse] | None:
    async with AsyncClient(TOKEN) as client:
        # order_response = await open_position(client, OrderDirection.ORDER_DIRECTION_SELL, quantity=1)
        # print(order_response)
        if bot.futures_quantity == 0:
            s.logger.info(f'[bot.futures_quantity] = 0. stops not applied')
            return
        quantity = abs(bot.futures_quantity)
        direction_for_stop = StopOrderDirection.STOP_ORDER_DIRECTION_BUY \
            if bot.futures_quantity < 0 else StopOrderDirection.STOP_ORDER_DIRECTION_SELL
        await bot.update_data()
        take_profit_price_q, stop_loss_price_q = change_quotation(bot.last_deal_price)
        if direction_for_stop == 1:
            take_profit_price_q, stop_loss_price_q = stop_loss_price_q, take_profit_price_q

        s.logger.info(f'[post_stop_orders] Direction for stop = {direction_for_stop}')
        print(f'[post_stop_orders] TP price = {take_profit_price_q}')
        print(f'[post_stop_orders] SL price = {stop_loss_price_q}')

        take_profit_task = open_stop_order(client,
                                           quantity=quantity,
                                           stop_price=take_profit_price_q,
                                           direction=direction_for_stop,
                                           stop_order_type=StopOrderType.STOP_ORDER_TYPE_TAKE_PROFIT)

        stop_loss_task = open_stop_order(client,
                                         quantity=quantity,
                                         stop_price=stop_loss_price_q,
                                         direction=direction_for_stop,
                                         stop_order_type=StopOrderType.STOP_ORDER_TYPE_STOP_LOSS)

        take_profit, stop_loss = await aio.gather(take_profit_task, stop_loss_task)

        return take_profit, stop_loss


async def get_stop_orders():
    async with AsyncClient(TOKEN) as client:
        resp: GetStopOrdersResponse = await client.stop_orders.get_stop_orders(
            account_id=ACCOUNT_ID
        )
    return resp.stop_orders


async def main():
    stop_orders = await aio.gather(get_stop_orders())
    pprint(stop_orders)


if __name__ == '__main__':
    aio.run(main())
