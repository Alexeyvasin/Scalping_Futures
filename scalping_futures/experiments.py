import asyncio
import os
from pprint import pprint
from decimal import Decimal

from dotenv import load_dotenv
import yaml

from tinkoff.invest import AsyncClient, Client
from tinkoff.invest.async_services import AsyncServices
from tinkoff.invest.schemas import OrderStateStreamRequest, OperationType, Quotation, StopOrderDirection, StopOrderType, \
    ExchangeOrderType, TakeProfitType, PostStopOrderRequestTrailingData, PriceType
from tinkoff.invest.utils import decimal_to_quotation, quotation_to_decimal

# from scalping_futures.utils import INSTRUMENT_ID


load_dotenv()
TOKEN = os.environ["EXPERIMENTS_TOKEN"]
ACCOUNT_ID = os.environ['EXPERIMENTS_ACCOUNT_ID']
INSTRUMENT_ID = os.getenv('UID')


def load_config(config_path="config.yml"):
    with open(config_path, "r") as file:
        return yaml.safe_load(file)


config = load_config("config.yml")


async def get_last_operation(status=0):
    async with AsyncClient(TOKEN) as client:
        # operations = await client.operations.get_operations(account_id=ACCOUNT_ID)
        # for operation in operations.operations:
        #     if operation.operation_type in (OperationType.OPERATION_TYPE_BUY, OperationType.OPERATION_TYPE_SELL):
        #         pprint(operation)
        #         return operation
        stops = await client.stop_orders.get_stop_orders(
            account_id=ACCOUNT_ID,
            status=status,
        )
        pprint(sorted(stops.stop_orders, key=lambda x: x.create_date, reverse=True))
        return stops


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
        indent = Quotation(units=0, nano=3000000)
        spread = Decimal(0.05)
        # price = decimal_to_quotation(quotation_to_decimal(stop_price) + indent)
        parameters['take_profit_type'] = TakeProfitType.TAKE_PROFIT_TYPE_TRAILING
        trailing_data_parameters = {
            'indent': indent,
            'indent_type': 1,
            # 'spread': decimal_to_quotation(spread),
            # 'spread_type': 1,
        }
        parameters['trailing_data'] = PostStopOrderRequestTrailingData(**trailing_data_parameters)
        # parameters['price'] = price
        # parameters['price_type'] = PriceType.PRICE_TYPE_CURRENCY

        stop_response = await client.stop_orders.post_stop_order(**parameters)
        # print(f'*price', price)
        return stop_response


async def main():
    # async with AsyncClient(TOKEN) as client:
    #     print(INSTRUMENT_ID)
    #     share = await client.instruments.share_by(id_type=3,
    #                                         id=INSTRUMENT_ID)
    #
    #     pprint(share)

    # async with AsyncClient(TOKEN) as client: # get portfolio
    #     accounts = await client.users.get_accounts()
    #     pprint(accounts)
    #     portf = await client.operations.get_portfolio(account_id=ACCOUNT_ID)
    #
    # pprint(portf)

    last_order, = await asyncio.gather(get_last_operation(status=0))

    if True:  # not last_order.stop_orders:

        async with AsyncClient(TOKEN) as client:
            stop_order = await open_stop_order(
                client,
                stop_price=Quotation(units=4, nano=30000000),
                direction=StopOrderDirection.STOP_ORDER_DIRECTION_BUY,
                stop_order_type=StopOrderType.STOP_ORDER_TYPE_TAKE_PROFIT,
                quantity=1,
            )

        last_order, = await asyncio.gather(get_last_operation())


if __name__ == "__main__":
    asyncio.run(main())
    # with Client(TOKEN) as client:
    #     future = client.stop_orders.cancel_stop_order(account_id=ACCOUNT_ID, stop_order_id='47f2a0d6-75ee-4dea-8d8f-a7ca7602dfa7')
    #
    # pprint(future)
