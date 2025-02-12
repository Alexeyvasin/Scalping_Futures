import asyncio
import decimal
import random
import time
import uuid
from pprint import pprint

import pandas
from tinkoff.invest.utils import now
from tinkoff.invest import (
    AsyncClient,
    OrderDirection,
    OrderType,
    StopOrderDirection,
    Quotation,
    StopOrderType,
    ExchangeOrderType,
    TakeProfitType,
    OperationType,
    Client
)
from tinkoff.invest.async_services import AsyncServices, PostOrderAsyncRequest

from utils import TOKEN, FIGI, ACCOUNT_ID, INSTRUMENT_ID, change_quotation

from asyncio import Event

from tinkoff.invest.utils import quotation_to_decimal

import pandas as pd

df = pd.DataFrame({
    'a': [1, 2, 9, 4],
    'b': [2, 3, pd.NA, 10]
})

# # Drop rows with all NaN values before concatenation
# if not new_row_df.isnull().all(axis=1).iloc[0]:
#     if current_candle_time in self.df.index:
#         for col in new_row_df.columns:
#             if not pd.isna(new_row_df[col].iloc[0]):
#                 self.df.loc[current_candle_time, col] = new_row_df[col].iloc[0]
#     else:
#         self.df = pd.concat([self.df, new_row_df])

if __name__ == '__main__':
    price_q = Quotation(units=3, nano=123000000)
    price: decimal.Decimal = quotation_to_decimal(price_q)
    print(price.from_float())
