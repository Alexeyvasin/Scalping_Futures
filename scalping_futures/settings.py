import asyncio as aio
import yaml
import os
import logging
from logging.handlers import TimedRotatingFileHandler

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

conf_file = 'config.yml'
path = os.getcwd()

config_path = f'{path[:-8]}{conf_file}' if path.endswith('my_utils') else conf_file


def load_config(config_path=config_path):
    # try:
    with open(config_path, "r") as file:
        return yaml.safe_load(file)
    # except FileNotFoundError as exc:
    #     path = os.getcwd()
    #     if path.endswith('my_utils'):
    #         config_path = f'{path[:-8]}config.yml'
    #         print(config_path)
    #         with open(config_path, "r") as file:
    #             return yaml.safe_load(file)
    #     print(os.getcwd())


config = load_config(config_path)

order_event = aio.Event()

rsi_event = aio.Event()
