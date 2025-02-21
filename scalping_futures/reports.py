import tinkoff.invest as ti
from tinkoff.invest import utils
import asyncio
import os
import pandas as pd
import numpy as np
from pprint import pprint
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv('TINKOFF_TOKEN')
A_ID = os.getenv('ACCOUNT_ID')


async def get_trade_stat():
    async with ti.AsyncClient(TOKEN) as client:
        operations = await client.operations.get_operations(account_id=A_ID)

    # Initialize empty dictionaries to avoid repeated concatenation
    commissions_dict = {}
    n_buys_dict, n_sells_dict = {}, {}
    buys_dict, sells_dict = {}, {}
    buys_pt_dict, sells_pt_dict = {}, {}
    on_var_dict, off_var_dict = {}, {}
    others = []

    for operation in operations.operations:
        date_key = pd.to_datetime(operation.date).date()
        amount = utils.quotation_to_decimal(operation.payment)

        if operation.operation_type == ti.OperationType.OPERATION_TYPE_BROKER_FEE:
            commissions_dict[date_key] = commissions_dict.get(date_key, 0) + amount

        elif operation.operation_type == ti.OperationType.OPERATION_TYPE_BUY:
            buys_pt_dict[date_key] = buys_pt_dict.get(date_key, 0) + utils.quotation_to_decimal(
                operation.price) * operation.quantity
            buys_dict[date_key] = buys_dict.get(date_key, 0) + amount
            n_buys_dict[date_key] = n_buys_dict.get(date_key, 0) + operation.quantity

        elif operation.operation_type == ti.OperationType.OPERATION_TYPE_SELL:
            sells_pt_dict[date_key] = sells_pt_dict.get(date_key, 0) + utils.quotation_to_decimal(
                operation.price) * operation.quantity
            sells_dict[date_key] = sells_dict.get(date_key, 0) + amount
            n_sells_dict[date_key] = n_sells_dict.get(date_key, 0) + operation.quantity

        elif operation.operation_type == ti.OperationType.OPERATION_TYPE_ACCRUING_VARMARGIN:
            on_var_dict[date_key] = on_var_dict.get(date_key, 0) + amount

        elif operation.operation_type == ti.OperationType.OPERATION_TYPE_WRITING_OFF_VARMARGIN:
            off_var_dict[date_key] = off_var_dict.get(date_key, 0) + amount

        else:
            others.append(operation)

    # Convert dictionaries to Series
    commissions = pd.Series(commissions_dict, dtype=float)
    buys_pt = pd.Series(buys_pt_dict, dtype=float)
    sells_pt = pd.Series(sells_pt_dict, dtype=float)
    buys = pd.Series(buys_dict, dtype=float)
    sells = pd.Series(sells_dict, dtype=float)
    n_buys = pd.Series(n_buys_dict, dtype=int)
    n_sells = pd.Series(n_sells_dict, dtype=int)
    on_var = pd.Series(on_var_dict, dtype=float)
    off_var = pd.Series(off_var_dict, dtype=float)

    df = pd.DataFrame({
        'buys_pt': buys_pt,
        'n_buys': n_buys,
        'sells_pt': sells_pt,
        'n_sells': n_sells,
        'buys': buys,
        'sells': sells,
        'commissions': commissions,
        'on_var': on_var,
        'off_var': off_var,
    })

    df['avg_buys_pt'] = df['buys_pt'] / df['n_buys']
    df['avg_sells_pt'] = df['sells_pt'] / df['n_sells']

    column_order = [
        'buys_pt', 'n_buys', 'avg_buys_pt',
        'sells_pt', 'n_sells', 'avg_sells_pt',
        'buys', 'sells', 'commissions', 'on_var', 'off_var',
    ]
    df = df[column_order]

    # Apply rounding only to numeric columns
    df[df.select_dtypes(include=['number']).columns] = df.select_dtypes(include=['number']).round(3)

    df.to_csv('stats.csv', sep=';')
    print(df.to_string())

    if len(others) > 0:
        print('*others')
        pprint(others)


async def main():
    await get_trade_stat()


if __name__ == '__main__':
    asyncio.run(main())
