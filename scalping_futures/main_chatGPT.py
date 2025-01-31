import time
import random
import pandas as pd
import yaml
import datetime
import os
import logging
from os import getenv
from dotenv import load_dotenv
from tinkoff.invest.utils import now
from tinkoff.invest import (
    Client,
    CandleInterval,
    OrderDirection,
    OrderType,
    Quotation,
    PositionsResponse,
    MarketDataRequest,
    SubscribeCandlesRequest,
    SubscriptionAction,
    PostOrderRequest,
    CandleInstrument,
    SubscriptionInterval,
)
from tinkoff.invest.market_data_stream.market_data_stream_manager import MarketDataStreamManager

# Загружаем переменные окружения
load_dotenv()

TOKEN = getenv('TINKOFF_TOKEN')
ACCOUNT_ID = getenv('ACCOUNT_ID')

# Настройка логирования
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
log_file = os.path.join(LOG_DIR, f"{datetime.date.today()}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)

# Загружаем конфигурацию из файла .yml
def load_config(config_path="config.yml"):
    with open(config_path, "r") as file:
        return yaml.safe_load(file)

# Загружаем параметры из конфигурации
config = load_config("config.yml")

class ScalpingBot:
    def __init__(self, token, account_id, config):
        self.trading_active = None
        self.token = token
        self.account_id = account_id
        self.figi = config['tinkoff']['figi']

        # Параметры торговой стратегии
        self.ema_fast_period = config['strategy']['ema_fast_period']
        self.ema_slow_period = config['strategy']['ema_slow_period']
        self.rsi_period = config['strategy']['rsi_period']
        self.max_drawdown = config['strategy']['max_drawdown']
        self.daily_loss_limit = config['strategy']['daily_loss_limit']
        self.risk_per_trade = config['strategy']['risk_per_trade']
        self.lot_size = config['strategy']['lot_size']
        self.max_contracts = config['strategy']['max_contracts']

        # DataFrame для хранения свечей
        self.df = pd.DataFrame(
            columns=["time", "open", "close", "high", "low", "volume"]
        )
        self.df.set_index("time", inplace=True)

        self.last_candle_time = None
        self.position = None
        self.entry_price = None
        self.order_id = None
        self.stop_loss_price = None
        self.last_signal = None

        # Баланс аккаунта и метрики
        self.starting_balance = self.get_account_balance()
        self.current_balance = self.starting_balance
        self.daily_pnl = 0
        self.trades_history = []
        self.total_trades = 0
        self.winning_trades = 0

        logging.info("ScalpingBot initialized.")

    def get_account_balance(self):
        with Client(self.token) as client:
            portfolio: PositionsResponse = client.operations.get_positions(account_id=self.account_id)
            balance = portfolio.money[0].units
            logging.info(f"Account balance fetched: {balance}")
            return balance

    def calculate_position_size(self, stop_distance):
        account_value = self.get_account_balance()
        risk_amount = account_value * self.risk_per_trade
        position_size = risk_amount / stop_distance
        return min(position_size, self.max_contracts)

    def start(self):
        self.trading_active = True
        retry_delay = 1
        max_retry_delay = 60
        while self.trading_active:
            try:
                with Client(self.token) as client:
                    market_data_stream: MarketDataStreamManager = client.create_market_data_stream()
                    subscribe_request: MarketDataRequest = MarketDataRequest(
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

                    logging.info("Stream started. Waiting for new candles...")

                    for marketdata in market_data_stream:
                        if marketdata.candle is not None:
                            candle = marketdata.candle
                            self.on_new_candle(candle)

            except Exception as e:
                logging.error(f"Error in stream processing: {type(e)} {e}. Retrying after {retry_delay} seconds.")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2 + random.uniform(0, 1), max_retry_delay)

    def on_new_candle(self, candle):
        open_price = self._quotation_to_float(candle.open)
        close_price = self._quotation_to_float(candle.close)
        high_price = self._quotation_to_float(candle.high)
        low_price = self._quotation_to_float(candle.low)
        volume_sales = candle.volume
        current_candle_time = pd.to_datetime(candle.time).to_datetime64()
        print(current_candle_time)

        new_row = {
            "open": open_price,
            "close": close_price,
            "high": high_price,
            "low": low_price,
            "volume": volume_sales,
        }
        new_row_df = pd.DataFrame([new_row], index=[current_candle_time])
        self.df = pd.concat([self.df, new_row_df])

        logging.info(f"New candle received: {new_row}")

        if len(self.df) > 500:
            self.df = self.df.iloc[-500:]

        if self.last_candle_time and current_candle_time != self.last_candle_time:
            self._on_candle_closed_handler(self.last_candle_time)

        self.last_candle_time = current_candle_time

    def _on_candle_closed_handler(self, closed_candle_time):
        closed_candle_time = pd.to_datetime(closed_candle_time).to_datetime64()
        closed_candle = self.df.loc[closed_candle_time]
        close_price = closed_candle["close"]

        logging.info(f"Candle closed at {closed_candle_time}. Close price: {close_price}")

        self._calculate_indicators()
        self._generate_signal_and_trade()

    def _calculate_indicators(self):
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

        logging.info("Indicators calculated.")

    def _generate_signal_and_trade(self):
        if len(self.df) < self.ema_slow_period + 1:
            return

        last_row = self.df.iloc[-1]
        ema_fast = last_row["EMA_fast"]
        ema_slow = last_row["EMA_slow"]
        rsi_value = last_row["RSI"]

        prev_row = self.df.iloc[-2]
        prev_ema_fast = prev_row["EMA_fast"]
        prev_ema_slow = prev_row["EMA_slow"]

        long_signal = prev_ema_fast < prev_ema_slow and ema_fast > ema_slow and rsi_value < 70
        if long_signal:
            logging.info(f'long_signal {ema_fast} {ema_slow}')
        short_signal = prev_ema_fast > prev_ema_slow and ema_fast < ema_slow and rsi_value > 30
        if short_signal:
            logging.info(f'short_signal {ema_fast} {ema_slow}')
        if self.position == "long":
            if short_signal:
                self.close_position()
                self.open_position("SHORT", last_row["close"])
            else:
                self._update_stop_loss()
        elif self.position == "short":
            if long_signal:
                self.close_position()
                self.open_position("LONG", last_row["close"])
            else:
                self._update_stop_loss()
        else:
            if long_signal:
                self.open_position("LONG", last_row["close"])
            elif short_signal:
                self.open_position("SHORT", last_row["close"])

    def open_position(self, direction, current_price):
        logging.info(f"Opening position: {direction} at price {current_price}")
        self.position = direction
        self.entry_price = current_price

        stop_offset = current_price * 0.003
        if self.position == "long":
            self.stop_loss_price = current_price - stop_offset
        else:
            self.stop_loss_price = current_price + stop_offset

        logging.info(f"Position {self.position} opened at {current_price}. Stop-loss set at {self.stop_loss_price}.")

    def close_position(self):
        if not self.position:
            return

        logging.info(f"Closing position: {self.position}")

        last_price = self.df.iloc[-1]["close"]
        pnl = (last_price - self.entry_price) if self.position == "long" else (self.entry_price - last_price)
        comm = self.entry_price * 0.0005
        real_pnl = pnl - comm

        self.daily_pnl += real_pnl
        self.total_trades += 1
        if real_pnl > 0:
            self.winning_trades += 1

        logging.info(f"PnL for this trade: {real_pnl:.2f}")

        self.position = None
        self.entry_price = None
        self.stop_loss_price = None

        self.update_balance_and_check_limits()

    def _update_stop_loss(self):
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
            logging.info(f"Updating stop-loss from {self.stop_loss_price:.2f} to {new_stop:.2f}")
            self.stop_loss_price = new_stop

        if (self.position == "long" and last_price < self.stop_loss_price) or \
           (self.position == "short" and last_price > self.stop_loss_price):
            logging.info(f"Stop-loss triggered. Closing {self.position} position.")
            self.close_position()

    def update_balance_and_check_limits(self):
        self.current_balance = self.get_account_balance()
        drawdown = (self.starting_balance - self.current_balance) / self.starting_balance
        if drawdown > self.max_drawdown:
            logging.warning("Max drawdown exceeded. Stopping trading.")
            self.stop_trading()

        daily_loss = abs(self.daily_pnl) / self.starting_balance
        if daily_loss > self.daily_loss_limit:
            logging.warning("Daily loss limit exceeded. Stopping trading for today.")
            self.stop_trading()

    def stop_trading(self):
        self.trading_active = False
        logging.info("Trading has been stopped.")

    @staticmethod
    def _quotation_to_float(q):
        return q.units + q.nano / 1e9 if q else 0.0


if __name__ == "__main__":
    bot = ScalpingBot(
        token=TOKEN,
        account_id=ACCOUNT_ID,
        config=config
    )
    try:
        bot.start()
    except KeyboardInterrupt:
        logging.info("Bot stopped by user.")
