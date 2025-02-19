from pprint import pprint

import pandas as pd
import os
import datetime
import asyncio
from dotenv import load_dotenv

from tinkoff.invest import (
    AsyncClient,
    Quotation,
    Client, OperationType, RequestError,
)
from tinkoff.invest.async_services import AsyncServices
from tinkoff.invest.utils import now, quotation_to_decimal
from tinkoff.invest.services import CandleInterval
from settings import config

try:
    from main_ChatGPT_o1 import ScalpingBot
except ImportError:
    pass

import settings as s

load_dotenv()

TOKEN = os.getenv('TINKOFF_TOKEN')
ACCOUNT_ID = os.getenv('ACCOUNT_ID')
FIGI = config['tinkoff']['figi']
INSTRUMENT_ID = config['tinkoff']['instrument_id']


def load_future():
    with Client(TOKEN) as client:
        try:
            return client.instruments.future_by(id_type=3, id=INSTRUMENT_ID).instrument
        except Exception:
            return client.instruments.share_by(id_type=3, id=INSTRUMENT_ID).instrument


FUTURE = load_future()


def _quotation_to_float(q):
    return q.units + q.nano / 1e9 if q else 0.0


def change_quotation(price_q: Quotation, min_inc_q: Quotation | None = None) -> tuple[Quotation, Quotation]:
    if min_inc_q is None:
        min_inc_q = FUTURE.min_price_increment
    price_q = Quotation(units=price_q.units, nano=price_q.nano)
    high_target_price_q = Quotation(units=price_q.units, nano=price_q.nano)
    low_target_price_q = Quotation(units=price_q.units, nano=price_q.nano)
    price = _quotation_to_float(price_q)
    changing_percent = config['strategy']['stop_percent']
    high_target_price = price + price * changing_percent / 100
    low_target_price = price - price * changing_percent / 100

    while _quotation_to_float(high_target_price_q) < high_target_price:
        high_target_price_q.units += min_inc_q.units
        high_target_price_q.nano += min_inc_q.nano
        if high_target_price_q.nano >= 10 ** 9:
            high_target_price_q.units += high_target_price_q.nano // (10 ** 9)
            high_target_price_q.nano = high_target_price_q.nano % (10 ** 9)

    while _quotation_to_float(low_target_price_q) > low_target_price:
        low_target_price_q.units -= min_inc_q.units
        low_target_price_q.nano -= min_inc_q.nano
        if low_target_price_q.nano < 0:
            low_target_price_q.units -= 1
            low_target_price_q.nano += 1

    return high_target_price_q, low_target_price_q


def get_quotation(price: float) -> Quotation:
    units = int(price)
    nano = int((price - units) * 10 ** 9)
    return Quotation(units=units, nano=nano)


async def get_candles_on_today(figi, client: AsyncServices):
    now_ = now()
    from_today = datetime.datetime(now_.year, now_.month, now_.day, 6, 0, 0)
    candles = await client.market_data.get_candles(
        figi=figi,
        from_=from_today,
        to=now_,
        interval=CandleInterval.CANDLE_INTERVAL_1_MIN
    )
    # pprint(candles.candles)
    return candles.candles


def on_historical_candle(candle, df: pd.DataFrame):
    open_price = _quotation_to_float(candle.open)
    close_price = _quotation_to_float(candle.close)
    high_price = _quotation_to_float(candle.high)
    low_price = _quotation_to_float(candle.low)
    volume_sales = candle.volume

    candle_time = pd.to_datetime(candle.time).to_datetime64()

    # Ensure required columns exist
    expected_columns = ["open", "close", "high", "low", "volume", "EMA_fast", "EMA_slow", "RSI"]
    for col in expected_columns:
        if col not in df.columns:
            df[col] = float('nan')

    new_row = {
        "open": open_price,
        "close": close_price,
        "high": high_price,
        "low": low_price,
        "volume": volume_sales,
        "EMA_fast": float('nan'),
        "EMA_slow": float('nan'),
        "RSI": float('nan'),
    }
    new_row_df = pd.DataFrame([new_row], index=[candle_time])
    df = new_row_df if df.empty else pd.concat([df, new_row_df])
    return df


async def todays_candles_to_df() -> pd.DataFrame:
    df = pd.DataFrame()
    async with AsyncClient(TOKEN) as client:
        future_candles = await get_candles_on_today(FIGI, client)

    for future_candle in future_candles:
        df = on_historical_candle(future_candle, df)
    return df


async def get_data(bot:'ScalpingBot' = None):
    async with AsyncClient(TOKEN) as client:
        positions_task = client.operations.get_positions(account_id=ACCOUNT_ID)
        operations_task = client.operations.get_operations(account_id=ACCOUNT_ID)

        positions, operations = await asyncio.gather(positions_task, operations_task)
        for operation in operations.operations:
            if operation.operation_type in (OperationType.OPERATION_TYPE_BUY, OperationType.OPERATION_TYPE_SELL):
                s.logger.info(f'[get_data] Last operation {operation}')
                s.logger.info(
                    f'[get_data]. Price of last operation: '
                    f'{quotation_to_decimal(Quotation(units=operation.price.units, nano=operation.price.nano))}')
                if bot:
                    bot.last_operations_price = float(
                        quotation_to_decimal(Quotation(units=operation.price.units, nano=operation.price.nano))
                    )
                break
        futures_quantity = 0 if not positions.futures else positions.futures[0].balance
        orders_prices = []
        for operation in operations.operations:
            if len(orders_prices) >= abs(futures_quantity):
                break
            if operation.operation_type in (OperationType.OPERATION_TYPE_BUY, OperationType.OPERATION_TYPE_SELL):
                orders_prices.append(operation.price)
        return futures_quantity, tuple(orders_prices)


def detect_min_incr(bot: 'ScalpingBot') -> bool:
    if bot.futures_quantity == 0: return False
    # print(f'[detect_min_incr] checking')
    min_incr = config['strategy']['min_percent_for_interest']
    last_order_price = float(quotation_to_decimal(bot.order_prices[0]))
    current_price = bot.df.iloc[-1]['close']
    delta = abs(last_order_price - current_price) * 100 / last_order_price
    if delta > min_incr:
        # s.logger.info(f'[detect_min_incr]')
        # s.logger.info(f'*min_incr {min_incr}')
        # s.logger.info(f'*last_order_price {last_order_price}')
        # s.logger.info(f'*current_price {current_price}')
        # s.logger.info(f'*delta {delta}')
        return True

    return False


def is_trading_time():
    """Пример: 9:00–16:00 UTC."""
    # current_time = datetime.datetime.utcnow().time()
    current_time = now().time()
    start_time = datetime.time(7, 0)  # 09:00 UTC
    end_time = datetime.time(21, 0)  # 16:00 UTC
    return start_time <= current_time <= end_time


async def main():
    positions, prices = await get_data()
    pprint(positions)
    pprint(prices)

if __name__ == '__main__':
    asyncio.run(main())
