import asyncio
import yaml
import time
import random
import pandas as pd
import os
import logging
from logging.handlers import TimedRotatingFileHandler
from os import getenv
from dotenv import load_dotenv
import datetime

from tinkoff.invest.utils import now
from tinkoff.invest import (
    Client,
    OrderDirection,
    OrderType,
    PositionsResponse,
    MarketDataRequest,
    SubscribeCandlesRequest,
    SubscriptionAction,
    PostOrderRequest,
    CandleInstrument,
    SubscriptionInterval,
)
from tinkoff.invest.market_data_stream.market_data_stream_manager import MarketDataStreamManager

from utils import config
from utils import todays_candles_to_df
from orders import open_position, post_stop_orders

# ----------------------------------------------------------------
# 1) Setup your "logs" folder and configure Python logging
# ----------------------------------------------------------------
os.makedirs("logs", exist_ok=True)  # Create "logs" dir if not exists

# Create a logger
logger = logging.getLogger("ScalpingBot")
logger.setLevel(logging.INFO)

# TimedRotatingFileHandler rotates logs at midnight each day
log_file_path = "logs/scalping"  # base file name in logs/ folder
handler = TimedRotatingFileHandler(
    filename=log_file_path,
    when="midnight",
    interval=1,
    backupCount=7,  # keep last 7 log files (for example)
    encoding="utf-8",
)
# By default, the rotation creates files like "scalping.2025-01-30.log"
handler.suffix = "%Y-%m-%d.log"

# Format logs: date-time, level, message
formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s")
handler.setFormatter(formatter)

# (Optional) Also log to the console
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)

logger.addHandler(handler)
logger.addHandler(console_handler)

# ----------------------------------------------------------------
load_dotenv()

# def load_config(config_path="config.yml"):
#     with open(config_path, "r") as file:
#         return yaml.safe_load(file)
#
#
# config = load_config("config.yml")

TOKEN = getenv('TINKOFF_TOKEN')  # Токен с нужными правами (Full Access / торговые операции)
ACCOUNT_ID = getenv('ACCOUNT_ID')  # Номер брокерского счёта
FIGI = config['tinkoff']['figi']  # FIGI фьючерса на IMOEX (уточните при необходимости)

COMMISSION_RATE = config['strategy']['commission_rate']  # Пример: 0.025% (round-turn => 0.0005)
SPREAD_TICKS = config['strategy']['spread_ticks']  # Пример: 2 тика


class ScalpingBot:
    def __init__(self, token, account_id, figi):
        self.main_loop = None
        self.trading_active = False
        self.token = token
        self.account_id = account_id
        self.figi = figi

        # Храним последние n свечей в DataFrame
        self.df = pd.DataFrame(columns=["time", "open", "close", "high", "low", "volume"])
        self.df.set_index("time", inplace=True)

        self.last_candle_time = None

        self.position = None  # "long" или "short"
        self.entry_price = None
        self.order_id = None
        self.stop_loss_price = None
        self.last_signal = None

        # Параметры индикаторов
        self.ema_fast_period = config['strategy']['ema_fast_period']
        self.ema_slow_period = config['strategy']['ema_slow_period']
        self.rsi_period = config['strategy']['rsi_period']

        # Торговые параметры
        self.lot_size = config['strategy']['lot_size']
        self.max_contracts = config['strategy']['max_contracts']

        self.max_drawdown = config['strategy']['max_drawdown']  # 10%
        self.daily_loss_limit = config['strategy']['daily_loss_limit']  # 2%
        self.daily_loss = 0

        # Считаем начальный баланс (блокирующий вызов, оборачиваем в to_thread когда нужно)
        self.starting_balance = self.get_account_balance_sync()
        self.current_balance = self.starting_balance
        self.risk_per_trade = config['strategy']['risk_per_trade']  # 1%

        # Метрики продуктивности
        self.trades_history = []
        self.daily_pnl = 0
        self.win_rate = 0
        self.total_trades = 0
        self.winning_trades = 0

    # -------------------------------------------------------------------------
    # Methods below can be used via asyncio.to_thread(...) if we want them async
    # -------------------------------------------------------------------------
    def get_account_balance_sync(self):
        """Синхронно получает баланс счёта.
           Запускайте через asyncio.to_thread(...) для асинхронности."""
        with Client(self.token) as client:
            portfolio: PositionsResponse = client.operations.get_positions(account_id=self.account_id)
            # Упрощённый пример. Для реальной логики проверьте все деньги, валюты, фьючерсную маржу и т.д.
            balance = portfolio.money[0].units
            return balance

    def open_position_sync(self, direction, current_price):
        """Синхронное открытие позиции (размещение заявки)."""
        # 1) Проверяем маржу (упрощённо)
        with Client(self.token) as client:
            _ = client.operations.get_positions(account_id=self.account_id)
            # Допустим, всё ок.

        # 2) Отправляем рыночную заявку
        order_direction = (
            OrderDirection.ORDER_DIRECTION_BUY if direction == "LONG"
            else OrderDirection.ORDER_DIRECTION_SELL
        )
        self.order_id = f"scalping_{now().timestamp()}_{direction}"

        request = PostOrderRequest(
            figi=self.figi,
            quantity=self.lot_size,
            price=None,  # market order, if supported
            direction=order_direction,
            account_id=self.account_id,
            order_type=OrderType.ORDER_TYPE_MARKET,
            order_id=self.order_id,
        )
        logger.info(f"Открываем позицию {direction}. Ордер {self.order_id}...")

        with Client(self.token) as client:
            order_response = client.orders.post_order(request=request)
            # Считаем, что заполнился моментально по current_price

        self.position = "long" if direction == "LONG" else "short"
        self.entry_price = current_price

        # Пример: стоп-лосс на 0.3% от цены
        stop_offset = current_price * 0.003
        if self.position == "long":
            self.stop_loss_price = current_price - stop_offset
        else:
            self.stop_loss_price = current_price + stop_offset

        logger.info(
            f"Позиция {self.position} открыта ~{self.entry_price:.2f}, "
            f"стоп-лосс {self.stop_loss_price:.2f}"
        )

    def close_position_sync(self):
        """Синхронное закрытие текущей позиции (рыночным ордером)."""
        if not self.position:
            return

        direction = (
            OrderDirection.ORDER_DIRECTION_SELL
            if self.position == "long"
            else OrderDirection.ORDER_DIRECTION_BUY
        )
        close_order_id = f"close_{now().timestamp()}"

        logger.info(f"Закрываем позицию {self.position} рыночным ордером {close_order_id}...")

        with Client(self.token) as client:
            request = PostOrderRequest(
                figi=self.figi,
                quantity=self.lot_size,
                price=None,
                direction=direction,
                account_id=self.account_id,
                order_type=OrderType.ORDER_TYPE_MARKET,
                order_id=close_order_id,
            )
            _ = client.orders.post_order(request=request)

        # PnL расчёт
        if self.entry_price is not None:
            last_price = self.df.iloc[-1]["close"]
            if self.position == "long":
                pnl = last_price - self.entry_price
            else:
                pnl = self.entry_price - last_price

            comm = self.entry_price * COMMISSION_RATE * 2
            real_pnl = (pnl * self.lot_size) - comm

            self.trades_history.append({"pnl": real_pnl})
            self.daily_pnl += real_pnl
            self.total_trades += 1
            if real_pnl > 0:
                self.winning_trades += 1

            logger.info(
                f"PnL (предварительный) = {pnl:.3f}, "
                f"комиссия ~{comm:.3f}, итого ~{real_pnl:.3f}"
            )

        # Обновляем метрики
        self.update_performance_metrics()

        # Сброс переменных по позиции
        self.position = None
        self.entry_price = None
        self.stop_loss_price = None
        self.order_id = None

        # Обновляем баланс / проверяем лимиты
        self.update_balance_and_check_limits_sync()

    def update_balance_and_check_limits_sync(self):
        """Синхронный расчёт текущего баланса, проверка дроудауна/дневного лимита."""
        self.current_balance = self.get_account_balance_sync()
        drawdown = (self.starting_balance - self.current_balance) / self.starting_balance
        if drawdown > self.max_drawdown:
            logger.warning("Max drawdown exceeded, stopping trading.")
            self.stop_trading()

        daily_loss = (self.starting_balance - self.current_balance) / self.starting_balance
        if daily_loss > self.daily_loss_limit:
            logger.warning("Daily loss limit exceeded, stopping trading for today.")
            self.stop_trading()

    # ----------------------------------------------------------
    # Asynchronous methods
    # ----------------------------------------------------------
    async def get_account_balance(self):
        """Asynchronously get account balance by delegating to a thread."""
        return await asyncio.to_thread(self.get_account_balance_sync)

    async def calculate_position_size(self, stop_distance):
        account_value = await self.get_account_balance()
        risk_amount = account_value * self.risk_per_trade
        position_size = risk_amount / stop_distance
        return min(position_size, self.max_contracts)

    async def open_position(self, direction, current_price):
        """Wrap synchronous open_position_sync in asyncio.to_thread."""
        await asyncio.to_thread(self.open_position_sync, direction, current_price)

    async def close_position(self):
        """Wrap synchronous close_position_sync in asyncio.to_thread."""
        await asyncio.to_thread(self.close_position_sync)

    async def update_balance_and_check_limits(self):
        """Wrap synchronous method in asyncio.to_thread."""
        await asyncio.to_thread(self.update_balance_and_check_limits_sync)

    # ----------------------------------------------------------
    # The core streaming loop, run in a thread
    # ----------------------------------------------------------
    def _run_stream_loop(self):
        """Blocking method that opens the market data stream and iterates."""
        with Client(self.token) as client:
            market_data_stream: MarketDataStreamManager = client.create_market_data_stream()

            subscribe_request = MarketDataRequest(
                subscribe_candles_request=SubscribeCandlesRequest(
                    subscription_action=SubscriptionAction.SUBSCRIPTION_ACTION_SUBSCRIBE,
                    instruments=[
                        CandleInstrument(
                            figi=self.figi,
                            interval=SubscriptionInterval.SUBSCRIPTION_INTERVAL_ONE_MINUTE,
                        )
                    ],
                )
            )
            market_data_stream.subscribe(subscribe_request)

            logger.info("Запущен стрим. Ожидаем новые свечи...")

            # Blocking iteration:
            for marketdata in market_data_stream:
                if not self.trading_active:
                    # If we decided to stop while streaming, break
                    break
                if marketdata.candle is not None:
                    candle = marketdata.candle
                    self.on_new_candle(candle)

            # If the for-loop exits naturally, it means the stream ended
            logger.warning("Stream ended or disconnected from Tinkoff")

    async def start(self):
        """Запуск бота (асинхронно): подписка на минутные свечи и обработка данных."""
        self.trading_active = True
        retry_delay = 1
        max_retry_delay = 60

        self.df = await todays_candles_to_df()  # getting a DataFrame with historical candles on today
        # print(self.df.to_string())

        while self.trading_active:
            try:
                # Run the blocking streaming in a background thread
                await asyncio.to_thread(self._run_stream_loop)

                # If we exit the loop, it means the stream ended or we broke out
                # We'll try to reconnect (unless self.trading_active was set to False)
                if self.trading_active:
                    logger.warning("Stream ended unexpectedly, will try to reconnect")
            except Exception as e:
                logger.error(f"Error in stream processing: {type(e)} {e}")
                logger.info(f"Will retry after {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)

                # Exponential backoff + jitter
                retry_delay = min(retry_delay * 2 + random.uniform(0, 1), max_retry_delay)
            else:
                # If no exception, reset retry delay
                retry_delay = 1

            # If trading_active is False, we break the loop
            if not self.trading_active:
                break

    # ----------------------------------------------------------
    # Candle & strategy logic
    # ----------------------------------------------------------
    def on_new_candle(self, candle):
        """Обработка каждой новой минутной свечи (sync code, called from the streaming thread)."""
        open_price = self._quotation_to_float(candle.open)
        close_price = self._quotation_to_float(candle.close)
        high_price = self._quotation_to_float(candle.high)
        low_price = self._quotation_to_float(candle.low)
        volume_sales = candle.volume

        current_candle_time = pd.to_datetime(candle.time).to_datetime64()

        # Ensure required columns exist
        expected_columns = ["open", "close", "high", "low", "volume", "EMA_fast", "EMA_slow", "RSI"]
        for col in expected_columns:
            if col not in self.df.columns:
                self.df[col] = pd.NA

        # logger.info(
        #     f"Incoming candle data: {current_candle_time}, "
        #     f"{open_price}, {close_price}, {high_price}, {low_price}, {volume_sales}"
        # )

        new_row = {
            "open": open_price,
            "close": close_price,
            "high": high_price,
            "low": low_price,
            "volume": volume_sales,
            "EMA_fast": pd.NA,
            "EMA_slow": pd.NA,
            "RSI": pd.NA,
        }
        new_row_df = pd.DataFrame([new_row], index=[current_candle_time])

        # Drop rows with all NaN values before concatenation
        if not new_row_df.isnull().all(axis=1).iloc[0]:
            if current_candle_time in self.df.index:
                for col in new_row_df.columns:
                    if not pd.isna(new_row_df[col].iloc[0]):
                        self.df.loc[current_candle_time, col] = new_row_df[col].iloc[0]
            else:
                self.df = pd.concat([self.df, new_row_df])

        logger.debug(f"Updated DataFrame tail:\n{self.df.tail()}")

        # Keep only 500 last rows
        if len(self.df) > 500:
            self.df = self.df.iloc[-500:]

        # If a new candle has indeed started (i.e. the time changed),
        # call our candle-closed logic on the previous candle.
        if self.last_candle_time and current_candle_time != self.last_candle_time:
            self._on_candle_closed_handler(self.last_candle_time)

        self.last_candle_time = current_candle_time

    def _on_candle_closed_handler(self, closed_candle_time):
        """При закрытии свечи рассчитываем индикаторы и вызываем генерацию сигналов."""
        closed_candle_time_index = pd.to_datetime(closed_candle_time).to_datetime64()

        try:
            closed_candle = self.df.loc[closed_candle_time_index]
            close_price = closed_candle["close"]
            logger.info(f"Свеча {closed_candle_time} закрылась. "
                        f" открытия: {closed_candle['open']}"
                        f" макс: {closed_candle['high']}"
                        f" мин: {closed_candle['low']}"
                        f" закрытия: {close_price}")

            self._calculate_indicators()
            print(self.df.to_string())
            # Because we want to do trades (which are async now),
            # we can schedule that with asyncio.create_task.
            # loop = asyncio.get_event_loop()
            # loop.create_task(self._generate_signal_and_trade())
            asyncio.run_coroutine_threadsafe(self._generate_signal_and_trade(), self.main_loop)
        except KeyError as e:
            logger.error(f"KeyError accessing dataframe during candle closing: {e}")

    def _calculate_indicators(self):
        """Расчёт EMA9, EMA21, RSI."""
        df = self.df
        df["EMA_fast"] = df["close"].ewm(span=self.ema_fast_period, adjust=False).mean()
        df["EMA_slow"] = df["close"].ewm(span=self.ema_slow_period, adjust=False).mean()

        delta = df["close"].diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        roll_up = up.rolling(self.rsi_period).mean()
        roll_down = down.rolling(self.rsi_period).mean()
        rs = roll_up / roll_down
        df["RSI"] = 100.0 - (100.0 / (1.0 + rs))

        logger.debug("Indicators updated:")
        logger.debug(df[["EMA_fast", "EMA_slow", "RSI"]].tail())

    async def _generate_signal_and_trade(self):
        """Асинхронная логика генерации сигналов + исполнение сделок."""

        # Check we have enough data
        if len(self.df) < self.ema_slow_period + 1:
            logger.info("Not enough data for EMA calculations.")
            return

        # Market regime filter
        market_regime = self.detect_market_regime()
        if market_regime == "ranging":
            logger.info("Market is ranging, skipping trade.")
            return

        # Volatility filter
        if not self.is_volatile_enough():
            logger.info("Market volatility is too low, skipping trade.")
            return

        # Time-based filter
        if not self.is_trading_time():
            logger.info("Outside of trading hours, skipping trade.")
            return

        last_row = self.df.iloc[-1]
        print('*last_row', last_row)
        ema_fast = last_row["EMA_fast"]
        ema_slow = last_row["EMA_slow"]
        rsi_value = last_row["RSI"]
        close_price = last_row["close"]

        logger.info(
            f"[Generate Signal] EMA_fast={ema_fast:.3f}, "
            f"EMA_slow={ema_slow:.3f}, RSI={rsi_value:.3f}"
        )

        prev_row = self.df.iloc[-2]
        prev_ema_fast = prev_row["EMA_fast"]
        prev_ema_slow = prev_row["EMA_slow"]

        # Detect signals
        long_signal = False
        if prev_ema_fast < prev_ema_slow and ema_fast > ema_slow and rsi_value < 70:
            long_signal = True

        short_signal = False
        if prev_ema_fast > prev_ema_slow and ema_fast < ema_slow and rsi_value > 30:
            short_signal = True
        quantity = config['strategy']['max_contracts']
        # Position handling logic
        # if self.position == "long":
        #     if short_signal:
        #         await self.close_position()
        #         await self.open_position(direction="SHORT", current_price=close_price)
        #     else:
        #         self._update_stop_loss()
        # elif self.position == "short":
        #     if long_signal:
        #         await self.close_position()
        #         await self.open_position(direction="LONG", current_price=close_price)
        #     else:
        #         self._update_stop_loss()
        # else:
        if long_signal:
            # await self.open_position(direction="LONG", current_price=close_price)# chatGPT
            resp = await open_position(direction=OrderDirection.ORDER_DIRECTION_BUY, quantity=quantity)
            logger.info(f'[commit buy order] {resp}')
            if resp:
                self.position = 'long'
            take_profit, stop_loss = await post_stop_orders()
            logger.info(take_profit)
            logger.info(stop_loss)

        elif short_signal:
            # await self.open_position(direction="SHORT", current_price=close_price)# chatGPT
            resp = await open_position(direction=OrderDirection.ORDER_DIRECTION_SELL, quantity=quantity)
            logger.info(f'[commit sell order] {resp}')
            if resp:
                self.position = 'short'
            take_profit, stop_loss = await post_stop_orders()
            logger.info(take_profit)
            logger.info(stop_loss)

    def _update_stop_loss(self):
        """Простейший трейлинг-стоп (синхронно, вызывается в streaming thread)."""
        if not self.position:
            return
        last_price = self.df.iloc[-1]["close"]
        new_stop = None

        if self.position == "long":
            potential_stop = last_price - last_price * 0.003
            if potential_stop > self.stop_loss_price:
                new_stop = potential_stop
        elif self.position == "short":
            potential_stop = last_price + last_price * 0.003
            if potential_stop < self.stop_loss_price:
                new_stop = potential_stop

        if new_stop:
            logger.info(f"Трейлинг стоп-лосс c {self.stop_loss_price:.2f} до {new_stop:.2f}")
            self.stop_loss_price = new_stop

        # Стоп выбит?
        if self.position == "long" and last_price < self.stop_loss_price:
            logger.warning("Цена ниже стоп-лосса, закрываем LONG.")
            # loop = asyncio.get_event_loop()
            # loop.create_task(self.close_position())
            asyncio.run_coroutine_threadsafe(self.close_position(), self.main_loop)

        elif self.position == "short" and last_price > self.stop_loss_price:
            logger.warning("Цена выше стоп-лосса, закрываем SHORT.")
            # loop = asyncio.get_event_loop()
            # loop.create_task(self.close_position())
            asyncio.run_coroutine_threadsafe(self.close_position(), self.main_loop)

    @staticmethod
    def _quotation_to_float(q):
        return q.units + q.nano / 1e9 if q else 0.0

    def detect_market_regime(self):
        return 'trending'
        # """Возвращает 'ranging' или 'trending' (или 'unknown')."""
        # df = self.df
        # if len(df) < self.ema_slow_period + 1:
        #     return "unknown"
        # ema_slope = df["EMA_slow"].diff().mean()
        # if abs(ema_slope) < 0.01:
        #     return "ranging"
        # else:
        #     return "trending"

    def is_volatile_enough(self):
        return True
        # """
        # Checks if the market is volatile enough to trade using a more realistic ATR(14) calculation.
        #
        # 1. True Range (TR) = max(
        #      current_high - current_low,
        #      abs(current_high - previous_close),
        #      abs(current_low - previous_close)
        #    )
        # 2. ATR(14) = rolling mean of TR over the last 14 candles.
        # 3. Compare ATR(14) to a fraction of the latest closing price (e.g. 0.5%).
        # """
        # df = self.df
        #
        # # Need at least 15 rows to properly compute a 14-period ATR (TR depends on previous close).
        # if len(df) < 15:
        #     logging.info('Not enough candles')
        #     return False
        #
        # # Make sure we have a "PrevClose" column to use in True Range calculations:
        # if "PrevClose" not in df.columns:
        #     df["PrevClose"] = df["close"].shift(1)
        #
        # # Calculate True Range for each row:
        # # TR = max( (high-low), |high - prev_close|, |low - prev_close| )
        # df["TR"] = df.apply(
        #     lambda row: max(
        #         row["high"] - row["low"],
        #         abs(row["high"] - row["PrevClose"]),
        #         abs(row["low"] - row["PrevClose"])
        #     ),
        #     axis=1
        # )
        #
        # # Compute the 14-period Average True Range (rolling mean or ewm is typical; here we use rolling mean)
        # df["ATR_14"] = df["TR"].rolling(window=14).mean()
        #
        # # Get the latest computed ATR
        # current_atr = df["ATR_14"].iloc[-1]
        #
        # # Also get the latest close price
        # last_close_price = df["close"].iloc[-1]
        # if last_close_price <= 0:
        #     # If price is invalid or zero, can't proceed
        #     return False
        #
        # # Define a threshold. For example:
        # # require the ATR to be at least 0.5% of the current close (i.e. 0.005 * close_price)
        # threshold = 0.005 * last_close_price
        #
        # # Return True if the market is sufficiently volatile:
        # return current_atr > threshold

    def is_trading_time(self):
        """Пример: 9:00–16:00 UTC."""
        # current_time = datetime.datetime.utcnow().time()
        current_time = datetime.datetime.now(datetime.UTC).time()
        print('*curr_time UTC: ', current_time)
        start_time = datetime.time(6, 0)  # 09:00 UTC
        end_time = datetime.time(18, 0)  # 16:00 UTC
        return start_time <= current_time <= end_time

    def update_performance_metrics(self):
        """Обновляем винрейт и печатаем статистику."""
        if self.total_trades > 0:
            self.win_rate = self.winning_trades / self.total_trades
        logger.info(f"Win Rate: {self.win_rate:.2%}, Daily PnL: {self.daily_pnl:.2f}")

    def reset_daily_metrics(self):
        """Сбросить ежедневные метрики."""
        self.daily_pnl = 0
        self.trades_history.clear()
        self.total_trades = 0
        self.winning_trades = 0

    def stop_trading(self):
        """Устанавливает флаг останова, стрим при этом прервётся."""
        self.trading_active = False


# ----------------------------------------------------------------
# Asynchronous entry point
# ----------------------------------------------------------------
async def main():
    bot = ScalpingBot(
        token=TOKEN,
        account_id=ACCOUNT_ID,
        figi=FIGI,
    )

    # 1) Grab the currently running event loop:
    loop = asyncio.get_running_loop()
    # 2) Store it on the bot instance for later use:
    bot.main_loop = loop

    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("Остановка бота по Ctrl+C")
    except ValueError as exc:
        logger.error(f"Произошла ошибка ValueError: {exc}")
    except Exception as e:
        logger.exception(f"Произошла непредвиденная ошибка: {type(e)} {e}")
    finally:
        # If needed, ensure we stop everything gracefully
        bot.stop_trading()


if __name__ == "__main__":
    asyncio.run(main())
