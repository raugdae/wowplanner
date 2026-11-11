import logging

import discord

from .bot import WowPlannerBot
from .config import load_config


def main() -> None:
    discord.utils.setup_logging(level=logging.INFO)
    config = load_config()
    WowPlannerBot(config).run(config.token, log_handler=None)


if __name__ == "__main__":
    main()
