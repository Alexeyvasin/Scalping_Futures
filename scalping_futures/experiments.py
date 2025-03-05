from tinkoff.invest.utils import quotation_to_decimal, decimal_to_quotation
from decimal import Decimal

q = decimal_to_quotation(Decimal(0.004))
print(q)