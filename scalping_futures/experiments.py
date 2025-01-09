import os
import asyncio
from tinkoff.invest import AsyncClient, MarketDataRequest, SubscriptionAction
from tinkoff.invest.schemas import SubscriptionInterval, SubscribeCandlesRequest
from tinkoff.invest.market_data_stream.stream_managers import CandleInstrument
from tinkoff.invest.exceptions import AioRequestError
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

TOKEN = os.getenv("TINKOFF_TOKEN")
TICKER = "IMOEXF"  # Укажите тикер инструмента


async def get_instruments(client):
    """Получить список доступных инструментов."""
    try:
        instruments_response = await client.instruments.futures()
        return instruments_response.instruments
    except AioRequestError as e:
        print(f"Error fetching instruments: {e.details}")
        return None


async def check_candles_availability(instruments, ticker):
    """Проверка, имеет ли тикер свечи."""
    for instrument in instruments:
        if instrument.ticker == ticker:
            print(f"Instrument {ticker} found: {instrument.uid}")
            return True
    return False


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
            async for market_data in client.market_data_stream.market_data_stream(request_generator()):
                print(f"Received MarketData: {market_data}")
                if market_data.subscribe_candles_response:
                    print("Candle subscription is active")
                elif market_data.candle:
                    print(f"New candle received: {market_data.candle}")
                else:
                    print("No new data in this batch")
                await asyncio.sleep(1)  # Добавляем небольшую задержку для постоянного получения данных

        except AioRequestError as exc:
            print(f"Error in market data stream: {exc.details}")
        except Exception as e:
            print(f"Unexpected error in market data stream: {e}")


async def main():
    async with AsyncClient(TOKEN) as client:
        try:
            # Получаем все доступные инструменты
            instruments = await get_instruments(client)
            if not instruments:
                print("No instruments found.")
                return

            # Проверяем, есть ли свечи для выбранного тикера
            if not await check_candles_availability(instruments, TICKER):
                print(f"Ticker {TICKER} does not support candles data.")
                return

            print(f"Ticker {TICKER} supports candles, proceeding with stream.")

            # Подключаемся к потоку данных
            uid = next((inst.uid for inst in instruments if inst.ticker == TICKER), None)
            if uid:
                await market_data_stream(uid)
            else:
                print(f"UID for ticker {TICKER} not found.")

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
