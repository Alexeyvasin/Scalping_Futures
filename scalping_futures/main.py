import time
import random
import pandas as pd
from os import getenv
from dotenv import load_dotenv
import datetime
from tinkoff.invest.utils import now
from tinkoff.invest import (
    Client,
    CandleInterval,
    OrderDirection,
    OrderType,
    Quotation,
    InstrumentIdType,
    OrderExecutionReportStatus,
    OrderState,
    PositionsResponse,
    MarketDataRequest,
    SubscribeCandlesRequest,
    SubscriptionAction,
    PostOrderRequest,
    CandleInstrument,
    SubscriptionInterval,
)
from tinkoff.invest.market_data_stream.market_data_stream_manager import MarketDataStreamManager

load_dotenv()

TOKEN = getenv('TINKOFF_TOKEN')  # Токен с нужными правами (Full Access / торговые операции)
ACCOUNT_ID = getenv('ACCOUNT_ID')  # Номер брокерского счёта
FIGI_IMOEXF = getenv('FIGI')  # FIGI фьючерса на IMOEX (уточните в Тинькофф или через инструменты API)

COMMISSION_RATE = 0.00025  # 0,025% = 0.00025 за сделку. Учтём round-turn = 0.0005, если хотим "в обе стороны"
SPREAD_TICKS = 2  # Условно считаем 2 тика средним спредом (примеры!). Уточните шаг цены фьючерса!


class ScalpingBot:
    def __init__(self, token, account_id, figi):
        self.trading_active = None
        self.token = token
        self.account_id = account_id
        self.figi = figi

        # Храним последние n свечей в Pandas для расчёта индикаторов (например, 50–100)
        self.df = pd.DataFrame(
            columns=["time", "open", "close", "high", "low", "volume"]
        )
        self.df.set_index("time", inplace=True)

        self.last_candle_time = None

        self.position = None  # "long" или "short"
        self.entry_price = None
        self.order_id = None
        self.stop_loss_price = None
        self.last_signal = None

        # Параметры индикаторов
        self.ema_fast_period = 9
        self.ema_slow_period = 21
        self.rsi_period = 14

        # Размер контракта (примеры!). В реальности уточните ГО и минимальный шаг.
        self.lot_size = 1
        # Сколько мы готовы торговать (контрактов)
        self.max_contracts = 1

        self.max_drawdown = 0.1  # 10% max drawdown
        self.daily_loss_limit = 0.02  # 2% daily loss limit
        self.daily_loss = 0
        self.starting_balance = self.get_account_balance()
        self.current_balance = self.starting_balance
        self.risk_per_trade = 0.01  # 1% risk per trade

        # Add performance metrics tracking
        self.trades_history = []
        self.daily_pnl = 0
        self.win_rate = 0
        self.total_trades = 0
        self.winning_trades = 0

    def get_account_balance(self):
        # Implement a method to fetch the current account balance
        with Client(self.token) as client:
            portfolio: PositionsResponse = client.operations.get_positions(account_id=self.account_id)
            # Assume we have a method to extract balance from portfolio
            # return portfolio.total_amount_currencies.units  # Example, adjust as needed
            balance = portfolio.money[0].units
            return balance

    def calculate_position_size(self, stop_distance):
        account_value = self.get_account_balance()
        risk_amount = account_value * self.risk_per_trade
        position_size = risk_amount / stop_distance
        return min(position_size, self.max_contracts)

    def start(self):
        """Запуск бота: подписка на минутные свечи и обработка данных"""
        self.trading_active = True
        retry_delay = 1  # Initial retry delay in seconds
        max_retry_delay = 60  # Maximum retry delay
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

                    print("Запущен стрим. Ожидаем новые свечи...")

                    # Получаем поток MarketDataResponse
                    for marketdata in market_data_stream:
                        if marketdata.candle is not None:
                            candle = marketdata.candle
                            self.on_new_candle(candle)

                    # If the loop exits, it means the stream is over
                    print("Stream ended unexpectedly, will try to reconnect")
            except Exception as e:
                print(f"Error in stream processing, will retry after delay: {type(e)} {e}")
                time.sleep(retry_delay)
                retry_delay = min(retry_delay * 2 + random.uniform(0, 1),
                                  max_retry_delay)  # exponential backoff + jitter
            else:
                # Reset retry delay if stream succeeded (unlikely to happen often)
                retry_delay = 1

    def on_new_candle(self, candle):
        """Обработка каждой новой минутной свечи"""
        open_price = self._quotation_to_float(candle.open)
        close_price = self._quotation_to_float(candle.close)
        high_price = self._quotation_to_float(candle.high)
        low_price = self._quotation_to_float(candle.low)
        volume_sales = candle.volume
        current_candle_time = pd.to_datetime(candle.time).to_datetime64()

        # Ensure all expected columns exist
        expected_columns = ["open", "close", "high", "low", "volume", "EMA_fast", "EMA_slow", "RSI"]
        for col in expected_columns:
            if col not in self.df.columns:
                self.df[col] = pd.NA

        # Debug incoming candle
        print(
            f"Incoming candle data: {current_candle_time}, {open_price}, {close_price}, {high_price}, {low_price}, {volume_sales}"
        )

        # Add or update the row
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
        if not new_row_df.isnull().all(axis=1).iloc[0]:  # Check if the row is not all NaN
            if current_candle_time in self.df.index:
                # Update only if any of the new values are not NA
                for col in new_row_df.columns:
                    if not pd.isna(new_row_df[col].iloc[0]):
                        self.df.loc[current_candle_time, col] = new_row_df[col].iloc[0]
            else:

                self.df = pd.concat([self.df, new_row_df])
                # print(self.df)

        # Log updated DataFrame
        print(f"Updated DataFrame preview:\n{self.df.tail()}")

        # Clean old records if DataFrame grows too large
        if len(self.df) > 500:
            self.df = self.df.iloc[-500:]

        if self.last_candle_time and current_candle_time != self.last_candle_time:
            self._on_candle_closed_handler(self.last_candle_time)

        self.last_candle_time = current_candle_time

    def _on_candle_closed_handler(self, closed_candle_time):
        """
        Вызывается, когда свеча с временем closed_candle_time завершена.
        Здесь можно рассчитать индикаторы и вызывать логику торговых сигналов.
        """
        # У нас в DataFrame уже лежат финальные данные по свече closed_candle_time
        # Можно делать технический анализ на основании всех предыдущих свечей
        closed_candle_time = pd.to_datetime(closed_candle_time)

        # Convert to datetime64
        closed_candle_time_index = pd.to_datetime(closed_candle_time).to_datetime64()

        try:
            # Пример: посмотрим последнюю "закрытую" цену
            closed_candle = self.df.loc[closed_candle_time_index]
            close_price = closed_candle["close"]
            print(f"Свеча {closed_candle_time} закрылась. Цена закрытия: {close_price}")

            # Например, вызываем логику стратегии (упрощённо)
            self._calculate_indicators()
            self._generate_signal_and_trade()
        except KeyError as e:
            print(f"KeyError accessing dataframe during candle closing: {e}")

    def _calculate_indicators(self):
        """Расчёт EMA9, EMA21, RSI на основе нашего DataFrame"""
        df = self.df

        # EMA (Exponential Moving Average)
        df["EMA_fast"] = df["close"].ewm(span=self.ema_fast_period, adjust=False).mean()
        df["EMA_slow"] = df["close"].ewm(span=self.ema_slow_period, adjust=False).mean()

        # RSI
        delta = df["close"].diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        roll_up = up.rolling(self.rsi_period).mean()
        roll_down = down.rolling(self.rsi_period).mean()
        rs = roll_up / roll_down
        df["RSI"] = 100.0 - (100.0 / (1.0 + rs))

        # Debugging: Log calculated indicators
        print("Indicators updated:")
        print(df[["EMA_fast", "EMA_slow", "RSI"]].tail())

    def _generate_signal_and_trade(self):
        """Логика генерации сигналов + исполнение сделок (заявок)"""
        # Add market regime detection
        market_regime = self.detect_market_regime()
        if market_regime == "ranging":
            print("Market is ranging, skipping trade.")
            return

        # Add volatility filters
        if not self.is_volatile_enough():
            print("Market volatility is too low, skipping trade.")
            return

        # Add time-based filters
        if not self.is_trading_time():
            print("Outside of trading hours, skipping trade.")
            return

        # Берём последнюю закрытую свечу
        if len(self.df) < self.ema_slow_period + 1:
            print("Not enough data for EMA calculations.")
            return  # Недостаточно данных, чтобы что-то считать

        last_row = self.df.iloc[-1]
        ema_fast = last_row["EMA_fast"]
        ema_slow = last_row["EMA_slow"]
        rsi_value = last_row["RSI"]
        close_price = last_row["close"]

        # Debugging: Log indicator values
        print(f"Debugging Indicators - EMA_fast: {ema_fast}, EMA_slow: {ema_slow}, RSI: {rsi_value}")

        prev_row = self.df.iloc[-2]
        prev_ema_fast = prev_row["EMA_fast"]
        prev_ema_slow = prev_row["EMA_slow"]

        # Проверяем LONG сигнал (купить)
        long_signal = False
        if prev_ema_fast < prev_ema_slow and ema_fast > ema_slow and rsi_value < 70:
            long_signal = True

        # Проверяем SHORT сигнал (продать)
        short_signal = False
        if prev_ema_fast > prev_ema_slow and ema_fast < ema_slow and rsi_value > 30:
            short_signal = True

        # Проверяем, нужно ли открывать, закрывать, или обновлять позиции
        if self.position == "long":
            if short_signal:
                self.close_position()
                self.open_position(direction="SHORT", current_price=close_price)
            else:
                self._update_stop_loss()
        elif self.position == "short":
            if long_signal:
                self.close_position()
                self.open_position(direction="LONG", current_price=close_price)
            else:
                self._update_stop_loss()
        else:
            if long_signal:
                self.open_position(direction="LONG", current_price=close_price)
            elif short_signal:
                self.open_position(direction="SHORT", current_price=close_price)

    def open_position(self, direction, current_price):
        """Открытие позиции (размещение заявки). Проверка маржи, установка стоп-лосса и т.д."""
        # 1. Проверяем, достаточно ли свободных средств. Упрощённая логика:
        # Для фьючерсов нужно смотреть гарантийное обеспечение (ГО).
        # В Tinkoff Invest через self.client.orders.get_positions(...) можно получить PositionsResponse
        with Client(self.token) as client:
            portfolio: PositionsResponse = client.operations.get_positions(account_id=self.account_id)
            # Здесь нужно найти инструмент, понять free_money и сравнить с требуемой маржей.
            # Для примера сделаем вид, что денег всегда достаточно.

        # 2. Размещаем рыночную заявку (псевдо)
        order_direction = OrderDirection.ORDER_DIRECTION_BUY if direction == "LONG" else OrderDirection.ORDER_DIRECTION_SELL

        # генерируем уникальный order_id (например, на основе времени)
        self.order_id = f"scalping_{now().timestamp()}_{direction}"

        request = PostOrderRequest(
            figi=self.figi,
            quantity=self.lot_size,  # 1 контракт
            price=None,  # None => рыночная заявка (Market), если поддерживается
            direction=order_direction,
            account_id=self.account_id,
            order_type=OrderType.ORDER_TYPE_MARKET,
            order_id=self.order_id,
        )

        print(f"Открываем позицию {direction}. Отправляем рыночный ордер {self.order_id}...")
        with Client(self.token) as client:
            order_response = client.orders.post_order(request=request)

        # В реальности нужно дождаться статуса исполнения, проверить, что сделка действительно исполнилась.
        # Для упрощения считаем, что она сразу исполнилась. Узнаем «исполненную» цену:
        filled_price = current_price  # будем считать, что примерно по close_price

        self.position = "long" if direction == "LONG" else "short"
        self.entry_price = filled_price

        # Устанавливаем стоп-лосс (например, 0.5 ATR ниже для LONG или выше для SHORT)
        # Тут для простоты пусть стоп = 0.3% от цены
        stop_offset = filled_price * 0.003
        if self.position == "long":
            self.stop_loss_price = filled_price - stop_offset
        else:
            self.stop_loss_price = filled_price + stop_offset

        print(f"Позиция {self.position} открыта по цене ~{filled_price:.2f}, стоп-лосс {self.stop_loss_price:.2f}")

    def close_position(self):
        """Закрытие текущей позиции (рыночным ордером)"""
        if not self.position:
            return

        direction = OrderDirection.ORDER_DIRECTION_SELL if self.position == "long" else OrderDirection.ORDER_DIRECTION_BUY
        close_order_id = f"close_{now().timestamp()}"

        print(f"Закрываем позицию {self.position} рыночным ордером {close_order_id}...")

        with Client(self.token) as client:
            request = PostOrderRequest(
                figi=self.figi,
                quantity=self.lot_size,
                price=None,  # рыночная заявка
                direction=direction,
                account_id=self.account_id,
                order_type=OrderType.ORDER_TYPE_MARKET,
                order_id=close_order_id,
            )
            order_response = client.orders.post_order(request=request)
            # Аналогично — в реальности ждём статуса исполнения

        # Calculate PnL for the closed trade
        if self.entry_price is not None:
            last_price = self.df.iloc[-1]["close"]
            if self.position == "long":
                pnl = last_price - self.entry_price
            else:
                pnl = self.entry_price - last_price

            # Adjust for commission
            comm = self.entry_price * COMMISSION_RATE * 2
            real_pnl = (pnl * self.lot_size) - comm

            # Track trade performance
            self.trades_history.append({"pnl": real_pnl})
            self.daily_pnl += real_pnl
            self.total_trades += 1
            if real_pnl > 0:
                self.winning_trades += 1

            print(f"PnL (предварительный) = {pnl:.3f}, за вычетом комиссии ~{comm:.3f}, итого ~{real_pnl:.3f}")

        # Update performance metrics
        self.update_performance_metrics()

        # Reset position variables
        self.position = None
        self.entry_price = None
        self.stop_loss_price = None
        self.order_id = None

        self.update_balance_and_check_limits()

    def _update_stop_loss(self):
        """Простейший трейлинг-стоп для уже открытой позиции"""
        if not self.position:
            return
        last_price = self.df.iloc[-1]["close"]
        # Например, подтягивать стоп на 0.3% от последней цены, если это выгоднее.
        new_stop = None

        if self.position == "long":
            potential_stop = last_price - last_price * 0.003
            # Стоп двигаем только вверх, если новый выше старого
            if potential_stop > self.stop_loss_price:
                new_stop = potential_stop
        elif self.position == "short":
            potential_stop = last_price + last_price * 0.003
            # Стоп двигаем только вниз, если новый ниже старого
            if potential_stop < self.stop_loss_price:
                new_stop = potential_stop

        if new_stop:
            print(f"Обновляем стоп-лосс c {self.stop_loss_price:.2f} до {new_stop:.2f}")
            self.stop_loss_price = new_stop

        # Если цена уже зашла за стоп (т.е. выбило бы по стопу), то закрываем
        if self.position == "long" and last_price < self.stop_loss_price:
            print("Цена упала ниже стоп-лосса, закрываем LONG.")
            self.close_position()
        elif self.position == "short" and last_price > self.stop_loss_price:
            print("Цена поднялась выше стоп-лосса, закрываем SHORT.")
            self.close_position()

    def update_balance_and_check_limits(self):
        # Update current balance and check drawdown and daily loss limits
        self.current_balance = self.get_account_balance()
        drawdown = (self.starting_balance - self.current_balance) / self.starting_balance
        if drawdown > self.max_drawdown:
            print("Max drawdown exceeded, stopping trading.")
            self.stop_trading()

        daily_loss = (self.starting_balance - self.current_balance) / self.starting_balance
        if daily_loss > self.daily_loss_limit:
            print("Daily loss limit exceeded, stopping trading for today.")
            self.stop_trading()

    def stop_trading(self):
        # Implement logic to stop trading, e.g., by setting a flag
        self.trading_active = False
        # ... additional logic to safely stop trading ...

    @staticmethod
    def _quotation_to_float(q):
        """Преобразование Quotation в float (units + nano)"""
        return q.units + q.nano / 1e9 if q else 0.0

    def detect_market_regime(self):
        """Detects if the market is trending or ranging."""
        # Simple example using moving average slope
        df = self.df
        if len(df) < self.ema_slow_period + 1:
            return "unknown"

        ema_slope = df["EMA_slow"].diff().mean()
        if abs(ema_slope) < 0.01:  # Example threshold for ranging market
            return "ranging"
        else:
            return "trending"

    def is_volatile_enough(self):
        """Checks if the market is volatile enough to trade."""
        df = self.df
        if len(df) < 20:
            return False

        # Example using Average True Range (ATR)
        df["TR"] = df["high"] - df["low"]
        atr = df["TR"].rolling(window=14).mean().iloc[-1]
        return atr > 0.5  # Example threshold for volatility

    def is_trading_time(self):
        """Checks if the current time is within trading hours."""
        current_time = datetime.datetime.utcnow().time()
        start_time = datetime.time(9, 0)  # 9:00 AM UTC
        end_time = datetime.time(16, 0)  # 4:00 PM UTC

        return start_time <= current_time <= end_time

    def update_performance_metrics(self):
        """Update performance metrics like win rate."""
        if self.total_trades > 0:
            self.win_rate = self.winning_trades / self.total_trades
        print(f"Win Rate: {self.win_rate:.2%}, Daily PnL: {self.daily_pnl:.2f}")

    def reset_daily_metrics(self):
        """Reset daily metrics at the end of the trading day."""
        self.daily_pnl = 0
        self.trades_history.clear()
        self.total_trades = 0
        self.winning_trades = 0


if __name__ == "__main__":
    bot = ScalpingBot(
        token=TOKEN,
        account_id=ACCOUNT_ID,
        figi=FIGI_IMOEXF,
    )

    try:
        bot.start()
    except KeyboardInterrupt:
        print("Остановка бота по Ctrl+C")
    except ValueError as exc:
        print(f"Произошла ошибка ValueError {exc}")
    except Exception as e:
        print(f"Произошла ошибка:{type(e)} {e}")
