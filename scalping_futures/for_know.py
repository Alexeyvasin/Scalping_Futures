import asyncio
import time
import uuid
from pprint import pprint

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
)
from tinkoff.invest.async_services import AsyncServices, PostOrderAsyncRequest

from utils import TOKEN, FIGI, ACCOUNT_ID, INSTRUMENT_ID, change_quotation

from asyncio import Event
import keyboard

import pandas as pd

df = pd.DataFrame(
    {'a': [1, 2, 3],
     'b': [3, 1, 5.0]}
)

if __name__ == '__main__':
    print(df.iloc[-1])
