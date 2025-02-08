import asyncio as aio

from tinkoff.invest import OrderDirection

import settings as s
import orders
try:
    from  main_ChatGPT_o1 import ScalpingBot
except ImportError:
    pass


orders_lock = aio.Lock()
rsi_lock = aio.Lock()


async def orders_subscriber(event: aio.Event, bot: 'ScalpingBot') -> None:
    print(f'orders_subscriber awaits orders..')
    while True:
        async with orders_lock:
            await event.wait()
            print(f'[orders_subscriber]: RECEIVED!')
            await aio.sleep(3)
            await bot.update_data()
            event.clear()


async def rsi_subscriber(event: aio.Event, bot: 'ScalpingBot') -> None:
    print(f'[rsi_subscriber] await event..')
    while True:
        # async with rsi_lock:
        await event.wait()
        event.clear()

        last_rsi = float(bot.df['RSI'].iloc[-1])
        s.logger.info(f'NEW RSI! {last_rsi}')

        if last_rsi > s.config['rsi']['for_sell']:
            max_contracts = s.config['strategy']['max_contracts']
            if bot.futures_quantity != max_contracts * -1:
                s.logger.info(f'It`S NEED TO SELL! RSI = {last_rsi}')
                quantity = max_contracts  + bot.futures_quantity
                direction = OrderDirection.ORDER_DIRECTION_SELL
                if  quantity > 0:
                    resp = await orders.open_position(direction=direction, quantity=quantity)
                    s.logger.info(f'[rsi_subscriber] SOLD positions')
                    s.logger.info(f'{resp}')

        elif last_rsi < s.config['rsi']['for_buy']:
            max_contracts = s.config['strategy']['max_contracts']
            if bot.futures_quantity != max_contracts:
                s.logger.info(f'It`S NEED TO BUY! RSI = {last_rsi}')
                quantity = max_contracts - bot.futures_quantity
                direction = OrderDirection.ORDER_DIRECTION_BUY
                if quantity > 0:
                    resp = await orders.open_position(direction=direction, quantity=quantity)
                    s.logger.info(f'[rsi_subscriber] BOUGHT positions')
                    s.logger.info(f'{resp}')


        elif last_rsi < min(s.config['rsi']['for_close']) or last_rsi > max(s.config['rsi']['for_close']):
            if bot.futures_quantity != 0:
                s.logger.info(f'It`S NEED TO CLOSE POSITIONS! RSI = {last_rsi}')
                quantity = abs(bot.futures_quantity)
                direction = OrderDirection.ORDER_DIRECTION_BUY if bot.futures_quantity < 0 \
                    else OrderDirection.ORDER_DIRECTION_SELL
                resp = await orders.open_position(direction=direction, quantity=quantity)
                s.logger.info(f'[rsi_subscriber] CLOSED positions')
                s.logger.info(f'{resp}')

