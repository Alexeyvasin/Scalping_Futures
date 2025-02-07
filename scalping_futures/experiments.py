import asyncio
import os
from dotenv import load_dotenv
import yaml

from tinkoff.invest import AsyncClient
from tinkoff.invest.schemas import OrderStateStreamRequest

load_dotenv()
TOKEN = os.environ["TINKOFF_TOKEN"]


def load_config(config_path="config.yml"):
    with open(config_path, "r") as file:
        return yaml.safe_load(file)


config = load_config("config.yml")



if __name__ == "__main__":
    print(type(config['rsi']['for_close']))