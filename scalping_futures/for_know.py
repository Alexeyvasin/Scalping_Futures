import asyncio
import random
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
    Client
)
from tinkoff.invest.async_services import AsyncServices, PostOrderAsyncRequest

from utils import TOKEN, FIGI, ACCOUNT_ID, INSTRUMENT_ID, change_quotation

from asyncio import Event


import pandas as pd

# with Client(TOKEN) as client:
#     shares = client.instruments.shares()
#     for share in shares.instruments:
#         if  share.ticker == 'GAZP':
#             pprint(share)

# async def async_generator(n):
#     for _ in range(n):
#         yield random.randint(0, 100)
#         await asyncio.sleep(0.01)
#
# async def main():
#     async for x in async_generator(10):
#         print(x)
#
#
#
# if __name__ == '__main__':
#     asyncio.run(main())
import signal
import time

def timeout_handler(signum, frame):
    raise TimeoutError("Функция заняла слишком много времени!")

signal.signal(signal.SIGALRM, timeout_handler)  # Привязываем обработчик сигнала
signal.setitimer(signal.ITIMER_REAL, 1)  # Запускаем таймер на 3 секунды

try:
    print("Читаем файл")
    for ind in range(10000000):
        pass
    print("Файл прочитан полностью!", ind)
except TimeoutError as e:
    print(ind)
    print("Прервано:", e)
finally:
    signal.alarm(0)  # Отключаем сигнал
