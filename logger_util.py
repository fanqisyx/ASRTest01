import logging
from logging.handlers import RotatingFileHandler
import os


_LOGGER = None


def _ensure_logger():
    global _LOGGER
    if _LOGGER is not None:
        return _LOGGER
    logger = logging.getLogger("asr_app")
    logger.setLevel(logging.DEBUG)

    # 日志文件路径（当前工作目录）
    log_path = os.path.abspath(os.path.join(os.getcwd(), "app_debug.log"))

    # 轮转文件：5MB x 3 份
    fh = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(threadName)s] %(name)s %(module)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    fh.setFormatter(fmt)

    # 防止重复添加 handler
    if not any(isinstance(h, RotatingFileHandler) for h in logger.handlers):
        logger.addHandler(fh)

    _LOGGER = logger
    return _LOGGER


def get_logger():
    return _ensure_logger()


def debug(msg):
    _ensure_logger().debug(msg)


def info(msg):
    _ensure_logger().info(msg)


def warning(msg):
    _ensure_logger().warning(msg)


def error(msg):
    _ensure_logger().error(msg)


def exception(msg):
    _ensure_logger().exception(msg)
