import pandas as pd
import numpy as np
import datetime

# Из tinkoff.invest импортируем нужные классы и функции
from tinkoff.invest import (
    Client,
    CandleInterval,
    OrderDirection,
    OrderType,
    MarketDataRequest,
    MarketDataServerSideStream,
    MarketDataResponse,
    Quotation,
    InstrumentIdType,
    OrderExecutionReportStatus,
    OrderState,
    PositionsResponse,
)
from tinkoff.invest.services import MarketDataStreamService, OrdersService
from tinkoff.invest.request import (
    MarketDataStreamRequest,
    SubscribeCandlesRequest,
    SubscribeCandlesRequestInstrument,
    SubscriptionAction,
    PostOrderRequest,
)

TOKEN = "ВАШ_API_ТОКЕН"  # Токен с нужными правами (Full Access / торговые операции)
ACCOUNT_ID = "ВАШ_ACCOUNT_ID"  # Номер брокерского счёта
FIGI_IMOEXF = "FUT_IMOEX_CODE" # FIGI фьючерса на IMOEX (уточните в Тинькофф или через инструменты API)

COMMISSION_RATE = 0.00025  # 0,025% = 0.00025 за сделку. Учтём round-turn = 0.0005, если хотим "в обе стороны"
SPREAD_TICKS = 2           # Условно считаем 2 тика средним спредом (примеры!). Уточните шаг цены фьючерса!

class ScalpingBot:
    def __init__(self, token, account_id, figi):
        self.token = token
        self.account_id = account_id
        self.figi = figi

        # Храним последние n свечей в Pandas для расчёта индикаторов (например, 50–100)
        self.df = pd.DataFrame(
            columns=["time", "open", "close", "high", "low", "volume"]
        )
        self.df.set_index("time", inplace=True)

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

        # Сохраняем клиент для использования в разных методах
        self.client = Client(self.token)

    def start(self):
        """Запуск бота: подписка на минутные свечи и обработка данных"""
        with self.client as client:
            market_data_stream: MarketDataStreamService = client.create_market_data_stream()
            # Подписываемся на 1-минутные свечи по выбранному FIGI
            subscribe_request = MarketDataStreamRequest(
                subscribe_candles_request=SubscribeCandlesRequest(
                    subscription_action=SubscriptionAction.SUBSCRIPTION_ACTION_SUBSCRIBE,
                    instruments=[
                        SubscribeCandlesRequestInstrument(
                            figi=self.figi,
                            interval=CandleInterval.CANDLE_INTERVAL_1_MIN
                        )
                    ]
                )
            )

            market_data_stream.send_request(subscribe_request)

            print("Запущен стрим. Ожидаем новые свечи...")

            # Получаем поток MarketDataResponse
            for marketdata in market_data_stream:
                if marketdata.candle is not None:
                    candle = marketdata.candle
                    self.on_new_candle(candle)

                # Можно обрабатывать и другие типы сообщений (orderbook, trades и т.д.), если необходимо
                # if marketdata.orderbook:
                #     ...
                # if marketdata.trades:
                #     ...

    def on_new_candle(self, candle):
        """Обработка каждой новой минутной свечи"""
        # Преобразуем Quotation в float
        open_ = self._quotation_to_float(candle.open)
        close_ = self._quotation_to_float(candle.close)
        high_ = self._quotation_to_float(candle.high)
        low_ = self._quotation_to_float(candle.low)
        volume_ = candle.volume

        # Время свечи (UTC). При желании можно конвертировать в локальное
        time_ = candle.time.ToDatetime()

        # Добавляем/обновляем запись о свече в self.df
        # Так как свеча может обновляться несколько раз в течение минуты, проверим: последний индекс тот же?
        if time_ in self.df.index:
            # Обновляем последнюю свечу
            self.df.loc[time_, ["open", "close", "high", "low", "volume"]] = [
                open_, close_, high_, low_, volume_
            ]
        else:
            # Создаём новую запись
            self.df.loc[time_] = [open_, close_, high_, low_, volume_]

        # Чтобы корректно считались индикаторы, оставим в DataFrame последние ~200 (или сколько нужно) записей:
        if len(self.df) > 300:
            self.df = self.df.iloc[-300:]

        # Когда свеча закрылась (is_complete), уже можно принимать решение
        if candle.is_complete:
            self._calculate_indicators()    # Обновляем EMA, RSI и т.д.
            self._generate_signal_and_trade()

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

    def _generate_signal_and_trade(self):
        """Логика генерации сигналов + исполнение сделок (заявок)"""
        # Берём последнюю закрытую свечу
        if len(self.df) < self.ema_slow_period + 1:
            return  # Недостаточно данных, чтобы что-то считать

        last_row = self.df.iloc[-1]
        ema_fast = last_row["EMA_fast"]
        ema_slow = last_row["EMA_slow"]
        rsi_value = last_row["RSI"]
        close_price = last_row["close"]

        # Простейший сигнал: пересечение EMA_fast и EMA_slow
        # (Для полноты нужно ещё смотреть пред. свечи, чтобы уверенно фиксировать факт пересечения)
        # Здесь для упрощения:
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

        # Дополнительно проверим spread и комиссию:
        # - Пусть условно шаг цены = 1, спред ~ 2 тика, комиссия round turn ~ 0.0005 (0.05%)
        # - Если потенциал движения < спред+комиссия, лучше не входить
        # Здесь чисто символический пример, как мы можем проверить средний диапазон свечи
        avg_range = (self.df["high"] - self.df["low"]).tail(10).mean()  # усредн. диапазон последних 10 свечей
        cost_of_spread_and_commission = SPREAD_TICKS + (close_price * COMMISSION_RATE * 2)  # +2 тика + комиссия (тудым-сюдым)

        # Для упрощения: если средний ход свечи меньше, чем стоимость спреда+комиссии, мы пропускаем сделку
        if avg_range < cost_of_spread_and_commission:
            long_signal = False
            short_signal = False

        # Если у нас уже есть позиция, проверим, нужно ли закрыть (противоположный сигнал) или скорректировать стоп
        if self.position == "long":
            # Если пришёл сигнал SHORT — закрываем LONG и открываем SHORT
            if short_signal:
                self.close_position()
                self.open_position(direction="SHORT", current_price=close_price)
            else:
                # Обновляем стоп-лосс (трейлинг)
                self._update_stop_loss()
        elif self.position == "short":
            # Если пришёл сигнал LONG — закрываем SHORT и открываем LONG
            if long_signal:
                self.close_position()
                self.open_position(direction="LONG", current_price=close_price)
            else:
                # Обновляем стоп-лосс (трейлинг)
                self._update_stop_loss()
        else:
            # Пока позиций нет. Если есть сигнал — открываем
            if long_signal:
                self.open_position(direction="LONG", current_price=close_price)
            elif short_signal:
                self.open_position(direction="SHORT", current_price=close_price)

    def open_position(self, direction, current_price):
        """Открытие позиции (размещение заявки). Проверка маржи, установка стоп-лосса и т.д."""
        # 1. Проверяем, достаточно ли свободных средств. Упрощённая логика:
        # Для фьючерсов нужно смотреть гарантийное обеспечение (ГО).
        # В Tinkoff Invest через self.client.orders.get_positions(...) можно получить PositionsResponse
        with self.client as client:
            portfolio: PositionsResponse = client.operations.get_positions(account_id=self.account_id)
            # Здесь нужно найти инструмент, понять free_money и сравнить с требуемой маржей.
            # Для примера сделаем вид, что денег всегда достаточно.

        # 2. Размещаем рыночную заявку (псевдо)
        order_direction = OrderDirection.ORDER_DIRECTION_BUY if direction == "LONG" else OrderDirection.ORDER_DIRECTION_SELL

        # генерируем уникальный order_id (например, на основе времени)
        self.order_id = f"scalping_{datetime.datetime.utcnow().timestamp()}_{direction}"

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
        with self.client as client:
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
        close_order_id = f"close_{datetime.datetime.utcnow().timestamp()}"

        print(f"Закрываем позицию {self.position} рыночным ордером {close_order_id}...")

        with self.client as client:
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

        # Можно примерно прикинуть PnL:
        if self.entry_price is not None:
            last_price = self.df.iloc[-1]["close"]
            if self.position == "long":
                pnl = last_price - self.entry_price
            else:
                pnl = self.entry_price - last_price

            # Учтём комиссию:
            # Допустим, комиссия round turn = COMMISSION_RATE * 2
            # Реальный PnL (за 1 контракт) = pnl - (entry_price * COMMISSION_RATE * 2)
            # Если нужно точнее, надо умножать на объём и т.д.
            comm = self.entry_price * COMMISSION_RATE * 2
            real_pnl = (pnl * self.lot_size) - comm

            print(f"PnL (предварительный) = {pnl:.3f}, за вычетом комиссии ~{comm:.3f}, итого ~{real_pnl:.3f}")

        # Сброс переменных
        self.position = None
        self.entry_price = None
        self.stop_loss_price = None
        self.order_id = None

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

    @staticmethod
    def _quotation_to_float(q):
        """Преобразование Quotation в float (units + nano)"""
        return q.units + q.nano / 1e9 if q else 0.0


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
    except Exception as e:
        print(f"Произошла ошибка: {e}")
