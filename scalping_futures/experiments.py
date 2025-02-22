import asyncio
import os
from pprint import pprint

from dotenv import load_dotenv
import yaml

from tinkoff.invest import AsyncClient
from tinkoff.invest.schemas import OrderStateStreamRequest, OperationType

load_dotenv()
TOKEN = os.environ["TINKOFF_TOKEN"]
ACCOUNT_ID = os.environ['ACCOUNT_ID']


def load_config(config_path="config.yml"):
    with open(config_path, "r") as file:
        return yaml.safe_load(file)


config = load_config("config.yml")


async def get_last_operation():
    async with AsyncClient(TOKEN) as client:
        # operations = await client.operations.get_operations(account_id=ACCOUNT_ID)
        # for operation in operations.operations:
        #     if operation.operation_type in (OperationType.OPERATION_TYPE_BUY, OperationType.OPERATION_TYPE_SELL):
        #         pprint(operation)
        #         return operation



async def main():
    last_order = await asyncio.gather(get_last_operation())


if __name__ == "__main__":
    asyncio.run(main())
