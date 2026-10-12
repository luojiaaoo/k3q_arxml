"""统一配置项目的 Loguru 日志。"""

import sys

from loguru import logger


def configure_logging(level: str = 'INFO') -> None:
    logger.remove()
    logger.add(sys.stderr, level=level, format='{time:YYYY-MM-DD HH:mm:ss} | {level:>10} | {name} | {message}')


configure_logging()
