import asyncio
import os.path
from pprint import pprint

from tinkoff.invest import AsyncClient, StopOrderStatusOption
from scalping_futures.utils import TOKEN, ACCOUNT_ID


async def get_stops():
    async with AsyncClient(TOKEN) as client:
        stops = await client.stop_orders.get_stop_orders(account_id=ACCOUNT_ID,
                                                         status=StopOrderStatusOption.STOP_ORDER_STATUS_ALL)
    with open(os.path.join('data', 'stops.txt'), 'w') as f_stops:
        pprint(stops.stop_orders[::-1], stream=f_stops)
    pprint(stops.stop_orders)
    return stops


async def main():
    stops, = await asyncio.gather(get_stops())


if __name__ == '__main__':
    asyncio.run(main())
