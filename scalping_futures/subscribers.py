import asyncio as aio

from tinkoff.invest import OrderDirection

import settings as s
import orders

try:
    from main_ChatGPT_o1 import ScalpingBot
except ImportError:
    pass

orders_lock = aio.Lock()
rsi_lock = aio.Lock()


async def orders_subscriber(event: aio.Event, bot: 'ScalpingBot') -> None:
    print(f'orders_subscriber awaits orders..')
    while True:
        await event.wait()
        async with orders_lock:
            print(f'[orders_subscriber]: RECEIVED!')
            await aio.sleep(4)
            await bot.update_data()
            event.clear()


async def rsi_subscriber(event: aio.Event, bot: 'ScalpingBot') -> None:
    print(f'[rsi_subscriber] await event..')
    while True:
        await event.wait()
        async with rsi_lock:
            event.clear()
            # print(f'Hello from rsi_subscriber!')
            last_rsi = float(bot.df['RSI'].iloc[-1])
            # s.logger.info(f'[rsi_subscriber] RSI = {last_rsi}')
            if last_rsi > s.config['rsi']['for_sell']:
                await orders.open_position_with_stops('rsi_for_sell', bot)
                # max_contracts = s.config['strategy']['max_contracts']
                # if bot.futures_quantity != max_contracts * -1:
                #     if (quantity := max_contracts + bot.futures_quantity) > 0:
                #         s.logger.info(f'It`S NEED TO SELL! RSI = {last_rsi}')
                #         direction = OrderDirection.ORDER_DIRECTION_SELL
                #         s.logger.info(f'[rsi_subscriber]  Trying to SELL. quantity= {quantity}.')
                #         await orders.open_position_with_stops(direction, quantity, bot)

            elif last_rsi < s.config['rsi']['for_buy']:
                await orders.open_position_with_stops('rsi_for_buy')
                # print(f' Hi from buy!')
                # max_contracts = s.config['strategy']['max_contracts']
                # if bot.futures_quantity != max_contracts:
                #     if (quantity := max_contracts - bot.futures_quantity) > 0:
                #         direction = OrderDirection.ORDER_DIRECTION_BUY
                #         # s.logger.info(f'It`S NEED TO BUY! RSI = {last_rsi}')
                #         s.logger.info(f'[rsi_subscriber]  Trying to BUY. quantity= {quantity}.')
                #         await orders.open_position_with_stops(direction, quantity, bot)

            elif last_rsi < min(s.config['rsi']['for_close']): # and bot.futures_quantity < 0:
                await orders.open_position_with_stops('rsi_for_close', bot)
                # print(f'Hi from CLOSE!')
                # s.logger.info(f'It`S NEED TO CLOSE POSITIONS! RSI = {last_rsi}')
                # # deal = 'ClOSE'
                # quantity = abs(bot.futures_quantity)
                # direction = OrderDirection.ORDER_DIRECTION_BUY
                # await orders.open_position_with_stops(direction, quantity, bot)

            # elif last_rsi > max(s.config['rsi']['for_close']) and bot.futures_quantity > 0:
                # # deal = 'CLOSE'
                # s.logger.info(f'It`S NEED TO CLOSE POSITIONS! RSI = {last_rsi}')
                # quantity = abs(bot.futures_quantity)
                # direction = OrderDirection.ORDER_DIRECTION_SELL
                # await orders.open_position_with_stops(direction, quantity, bot)
