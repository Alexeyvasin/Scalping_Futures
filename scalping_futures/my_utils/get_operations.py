import asyncio
from pprint import pprint
import os

from tinkoff.invest import AsyncClient
from scalping_futures.utils import TOKEN, ACCOUNT_ID


async def get_operations():
    async with AsyncClient(TOKEN) as client:
        operations = await client.operations.get_operations(account_id=ACCOUNT_ID)

    with open(os.path.join('data', 'operations.txt'), 'w') as f_handle:
        pprint(operations.operations, stream=f_handle)
        # pprint(operations.operations[::-1])
    return operations


async def main():
    operations, = await asyncio.gather(get_operations())
    pprint(operations.operations[::-1])


if __name__ == '__main__':
    asyncio.run(main())
