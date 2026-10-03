import logging
import coloredlogs


def get_logger(name: str) -> logging.Logger:
    coloredlogs.install(level='DEBUG', fmt='%(asctime)s %(name)s %(levelname)s %(message)s')
    return logging.getLogger(name)
