import asyncio as aio
import settings as s

orders_lock = aio.Lock()
rsi_lock = aio.Lock()


async def orders_subscriber(event: aio.Event, bot) -> None:
    print(f'orders_subscriber awaits orders..')
    while True:
        async with orders_lock:
            await event.wait()
            print(f'[orders_subscriber]: RECEIVED!')
            await aio.sleep(3)
            await bot.update_data()
            event.clear()


async def rsi_subscriber(event: aio.Event, bot) -> None:
    print(f'[rsi_subscriber] await event..')
    while True:
        # async with rsi_lock:
        await event.wait()
        event.clear()

        last_rsi = float(bot.df['RSI'].iloc[-1])
        s.logger.info(f'NEW RSI! {last_rsi}')

        if last_rsi > s.config['rsi']['for_sell']:
            print(f'It`S NEED TO SELL! RSI = {last_rsi}')

        elif last_rsi < s.config['rsi']['for_buy']:
            print(f'It`S NEED TO BUY! RSI = {last_rsi}')

        elif last_rsi < min(s.config['rsi']['for_close']) or last_rsi > max(s.config['rsi']['for_close']):
            print(f'It`S NEED TO CLOSE POSITIONS! RSI = {last_rsi}')
        print(f'{bot.df.tail().to_string()}')
