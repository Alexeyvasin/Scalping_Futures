import os
import asyncio
from pprint import pprint
from tinkoff.invest import AsyncClient, MarketDataRequest, SubscriptionAction # SubscribeMarketDataRequest
from tinkoff.invest.schemas import SubscriptionInterval, SubscribeCandlesRequest
# from tinkoff.invest.market_data_stream_service import CandleInstrument
#from tinkoff.invest.market_data_stream.async_market_data_stream_manager import CandlesStreamManager
from tinkoff.invest.market_data_stream.stream_managers import CandleInstrument
from tinkoff.invest.exceptions import AioRequestError
#from tinkoff.invest.schemas import CandleInterval
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

TOKEN = os.getenv("TINKOFF_TOKEN")
UID = "5bcff194-f10d-4314-b9ee-56b7fdb344fd"
TICKER = "IMOEXF"  # Укажите тикер инструмента


async def get_uid_by_ticker(client, ticker):
    """Получить UID инструмента по тикеру."""
    try:
        instruments_response = await client.instruments.futures()
        for future in instruments_response.instruments:
            if future.ticker == ticker:
                return future.uid
        raise ValueError(f"Instrument with ticker {ticker} not found.")
    except AioRequestError as e:
        print(f"Error fetching instruments: {e.details}")
        return None


async def market_data_stream(uid):
    """Подключение к потоку рыночных данных."""
    async with AsyncClient(TOKEN) as client:
        async def request_generator():
            yield MarketDataRequest(
                subscribe_candles_request=SubscribeCandlesRequest(
                    subscription_action=SubscriptionAction.SUBSCRIPTION_ACTION_SUBSCRIBE,
                    instruments=[
                        CandleInstrument(
                            instrument_id=uid,
                            interval=SubscriptionInterval.SUBSCRIPTION_INTERVAL_ONE_MINUTE,
                        )
                    ],
                )
            )

        try:
            gen = request_generator()
            print(f'gen: {gen}')
            async for market_data in client.market_data_stream.market_data_stream(gen):
                pprint(f'{market_data}')
                await asyncio.sleep(1)
            print('All right')
        except AioRequestError as exc:
            print(f"Error in market data stream: {exc.details}")
        except Exception as exc:
            print(f'Error!: {exc}')


async def main():
    async with AsyncClient(TOKEN) as client:
        try:
            # Получение UID по тикеру
            uid = UID or await get_uid_by_ticker(client, TICKER)
            if not uid:
                print(f"Failed to retrieve UID for ticker {TICKER}.")
                return

            print(f"UID for ticker {TICKER}: {uid}")

            # Подключение к потоку рыночных данных
            await market_data_stream(uid)


        except AioRequestError as e:
            print(f"API Error: {e.details}")
        except Exception as e:
            print(f"Unexpected error: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Program interrupted.")
    except Exception as e:
        print(f"Application error: {e}")
