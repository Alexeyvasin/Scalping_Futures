import asyncio
import datetime
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

import sys
import pandas as pd




if __name__ == '__main__':
    df = pd.read_csv('store.csv', encoding='windows-1251', sep=';')
    print(df)
    df.to_xml('store.xml')
