import asyncio
from pprint import pprint

from tinkoff.invest import AsyncClient
from utils import TOKEN, ACCOUNT_ID


async def get_operations():
    async with AsyncClient(TOKEN) as client:
        operations = await client.operations.get_operations(account_id=ACCOUNT_ID)

    with open('operations.txt', 'w') as f_handle:

        pprint(operations.operations, stream=f_handle)
    return operations

async def main():
    operations, = await asyncio.gather(get_operations())

if __name__ == '__main__':
    asyncio.run(main())