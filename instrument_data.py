import asyncio
from pprint import pprint

from dotenv import load_dotenv
from tinkoff.invest import AsyncClient
from os import getenv

load_dotenv()

TOKEN = getenv('TINKOFF_TOKEN')


async def get_instrument(ticker):
    async with AsyncClient(TOKEN) as client:
        future_task = client.instruments.futures()
        share_task = client.instruments.shares()

        futures, shares = await asyncio.gather(future_task, share_task)

    instruments = (*futures.instruments, *shares.instruments)

    for instrument in instruments:
        if instrument.ticker == ticker:
            return instrument


async def main():
    instrument = await get_instrument('NRH5')
    pprint(instrument)


if __name__ == '__main__':
    asyncio.run(main())
