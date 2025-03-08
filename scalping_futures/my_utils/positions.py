import asyncio
from pprint import pprint
import os

from tinkoff.invest import AsyncClient, OperationType
from scalping_futures.utils import TOKEN, ACCOUNT_ID
from get_operations import get_operations


async def get_opens_futures_positions():
    async with AsyncClient(TOKEN) as client:
        positions = await client.operations.get_positions(account_id=ACCOUNT_ID)

    # pprint(positions)
    return positions.futures


async def main():
    positions, operations = await asyncio.gather(get_opens_futures_positions(), get_operations())
    opens_positions = []
    for position in positions:
        for operation in operations.operations:
            if position.position_uid == operation.position_uid and \
                    operation.operation_type in (OperationType.OPERATION_TYPE_BUY, OperationType.OPERATION_TYPE_SELL):
                opens_positions.append(
                    {
                        'uid': position.instrument_uid,
                        'position_uid': position.position_uid,
                        'balance': position.balance,
                        'operation': operation,
                    }
                )
                break
    return opens_positions


if __name__ == '__main__':
    res = asyncio.run(main())

    pprint(res)
