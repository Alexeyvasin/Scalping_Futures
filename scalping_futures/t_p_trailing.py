"""Example - Trailing Stop Take Profit order.
spread=0.5 relative value
indent=0.5 absolute value
"""

import json
import logging
import os
from decimal import Decimal
from pprint import pprint

from tinkoff.invest import (
    Client,
    ExchangeOrderType,
    GetStopOrdersRequest,
    PostStopOrderRequest,
    PostStopOrderRequestTrailingData,
    StopOrderDirection,
    StopOrderExpirationType,
    StopOrderTrailingData,
    StopOrderType,
    TakeProfitType,
    PriceType,
)
from dotenv import load_dotenv
from tinkoff.invest.schemas import TrailingValueType
from tinkoff.invest.utils import decimal_to_quotation


load_dotenv()
TOKEN = os.environ["EXPERIMENTS_TOKEN"]

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


INSTRUMENT_ID = os.getenv('EXPERIMENTS_UID')
QUANTITY = 1
PRICE = 93.0
STOPPRICE = 92.95
INDENT = 0.02
SPREAD = 0.04


def main():
    logger.info("Getting Max Lots")
    with Client(TOKEN) as client:
        response = client.users.get_accounts()
        account, *_ = response.accounts
        account_id = account.id

        logger.info(
            "Post take profit stop order for instrument=%s and trailing parameters: indent=%s, spread=%s, price=%s ",
            INSTRUMENT_ID,
            INDENT,
            SPREAD,
            STOPPRICE,
        )

        post_stop_order = client.stop_orders.post_stop_order(
            figi='BBG004730ZJ9',
            price_type=PriceType.PRICE_TYPE_CURRENCY,
            quantity=QUANTITY,
            price=decimal_to_quotation(Decimal(PRICE)),
            # stop_price=decimal_to_quotation(Decimal(STOPPRICE)),
            direction=StopOrderDirection.STOP_ORDER_DIRECTION_SELL,
            account_id=account_id,
            stop_order_type=StopOrderType.STOP_ORDER_TYPE_TAKE_PROFIT,
            instrument_id=INSTRUMENT_ID,
            expiration_type=StopOrderExpirationType.STOP_ORDER_EXPIRATION_TYPE_GOOD_TILL_CANCEL,
            exchange_order_type=ExchangeOrderType.EXCHANGE_ORDER_TYPE_LIMIT,
            take_profit_type=TakeProfitType.TAKE_PROFIT_TYPE_TRAILING,
            trailing_data=StopOrderTrailingData(
                indent=decimal_to_quotation(Decimal(INDENT)),
                indent_type=TrailingValueType.TRAILING_VALUE_ABSOLUTE,
                spread=decimal_to_quotation(Decimal(SPREAD)),
                spread_type=TrailingValueType.TRAILING_VALUE_ABSOLUTE,
            ),
        )

        # def post_stop_order(
        #         self,
        #         *,
        #         figi: str = "",
        #         quantity: int = 0,
        #         price: Optional[Quotation] = None,
        #         stop_price: Optional[Quotation] = None,
        #         direction: StopOrderDirection = StopOrderDirection(0),
        #         account_id: str = "",
        #         expiration_type: StopOrderExpirationType = StopOrderExpirationType(0),
        #         stop_order_type: StopOrderType = StopOrderType(0),
        #         expire_date: Optional[datetime] = None,
        #         instrument_id: str = "",
        #         exchange_order_type: ExchangeOrderType = ExchangeOrderType(0),
        #         take_profit_type: TakeProfitType = TakeProfitType(0),
        #         trailing_data: Optional[PostStopOrderRequestTrailingData] = None,
        #         price_type: PriceType = PriceType(0),
        #         order_id: str = "",

    pprint(post_stop_order)


if __name__ == "__main__":
    main()

    # with Client(TOKEN) as client:
    #     share = client.instruments.share_by(id_type=3, id=INSTRUMENT_ID)
    #     pprint(share)