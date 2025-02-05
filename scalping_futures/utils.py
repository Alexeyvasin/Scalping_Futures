from pprint import pprint

import pandas as pd
import os
import datetime
import yaml
import asyncio
from dotenv import load_dotenv

from tinkoff.invest import (
    AsyncClient,
    Quotation,
    Client,
)
from tinkoff.invest.async_services import AsyncServices
from tinkoff.invest.utils import now
from tinkoff.invest.services import CandleInterval

load_dotenv()


def load_config(config_path="config.yml"):
    with open(config_path, "r") as file:
        return yaml.safe_load(file)

config = load_config("config.yml")

TOKEN = os.getenv('TINKOFF_TOKEN')
ACCOUNT_ID = os.getenv('ACCOUNT_ID')
FIGI = config['tinkoff']['figi']
INSTRUMENT_ID = config['tinkoff']['instrument_id']

def load_future():
    with Client(TOKEN) as client:
        return client.instruments.future_by(id_type=3, id=INSTRUMENT_ID).instrument

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


if __name__ == '__main__':
    take_profit, stop_loss = change_quotation(
        Quotation(units=3, nano=123000000)
    )
    print(take_profit)
    print(stop_loss)

