import argparse
import logging
from typing import Optional, Hashable

logged_keys = set()


class TextEffects:
    NORMAL = 0
    BOLD = 1
    SLOW_BLINK = 5

    GREY = 90
    RED = 31
    GREEN = 32
    YELLOW = 33

    GREY_BACKGROUND = 40
    RED_BACKGROUND = 41
    YELLOW_BACKGROUND = 43


class LogFormatter(logging.Formatter):
    # level
    colors1 = {
        "DEBUG": TextEffects.GREY,
        "INFO": TextEffects.GREEN,
        "WARNING": TextEffects.YELLOW,
        # ;{TextEffects.SLOW_BLINK} is maybe a bit too much
        # "ERROR": f"{TextEffects.YELLOW};{TextEffects.BOLD};{TextEffects.RED_BACKGROUND}"
        "ERROR": f"{TextEffects.RED};{TextEffects.BOLD};{TextEffects.YELLOW_BACKGROUND}",
        "CRITICAL": f"{TextEffects.YELLOW};{TextEffects.BOLD};{TextEffects.RED_BACKGROUND};{TextEffects.SLOW_BLINK}"
    }
    # name
    colors2 = {
        "DEBUG": TextEffects.GREY,
        "INFO": TextEffects.NORMAL,
        "WARNING": TextEffects.YELLOW,
        "ERROR": f"{TextEffects.RED}",
        "CRITICAL": f"{TextEffects.RED};{TextEffects.BOLD}"
    }
    # message
    colors3 = {
        "DEBUG": TextEffects.NORMAL,
        "INFO": TextEffects.NORMAL,
        "WARNING": TextEffects.YELLOW,
        "ERROR": f"{TextEffects.RED}",
        "CRITICAL": f"{TextEffects.RED};{TextEffects.BOLD}"
    }

    def format(self, record: logging.LogRecord):
        # record.message did not work for some reason
        return f"\033[{self.colors1.get(record.levelname, 0)}m[{record.levelname:^8}]\033[0m" \
               f"\033[{self.colors2.get(record.levelname, 0)}m({record.name})\033[0m" \
               f"\033[{self.colors3.get(record.levelname, 0)}m {record.msg}\033[0m"


def prepare_logging(enable_log_formatting: bool = True, verbose: bool = False, silent: bool = False):
    _set_verbosity(verbose, silent)
    _set_up_simple_logger()
    if enable_log_formatting:
        _set_up_root_logger()


def _set_verbosity(verbose, silent):
    if verbose:
        log_level = logging.DEBUG
    elif silent:
        log_level = logging.WARNING
    else:
        log_level = logging.INFO
    logging.basicConfig(level=log_level)


# there is probably a more elegant way, this is just the only thing I could come up with for now
def _set_up_simple_logger():
    simple_logger = logging.getLogger("simple")
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    simple_logger.addHandler(handler)
    simple_logger.propagate = False     # do not propagate messages to parent (root)...


def _set_up_root_logger():
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.setFormatter(LogFormatter())


def log_once(msg: str, logger: logging.Logger, key: Hashable = None, level=logging.WARNING):
    if not key:
        key = msg
    if key not in logged_keys:
        logger.log(level, msg)
        logged_keys.add(key)