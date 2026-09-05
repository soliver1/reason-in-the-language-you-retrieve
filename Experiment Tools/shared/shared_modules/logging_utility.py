import logging
import pprint
from logging import LogRecord
from typing import Hashable

logged_keys = set()


class TextEffects:
    NORMAL = 0
    BOLD = 1
    SLOW_BLINK = 5

    GREY = 90
    RED = 31
    GREEN = 32
    YELLOW = 33
    BLUE = 34
    MAGENTA = 35
    CYAN = 36
    WHITE = 37
    BRIGHT_BLACK = 90

    GREY_BACKGROUND = 40
    RED_BACKGROUND = 41
    GREEN_BACKGROUND = 42
    YELLOW_BACKGROUND = 43
    BLUE_BACKGROUND = 44
    MAGENTA_BACKGROUND = 45
    CYAN_BACKGROUND = 46
    WHITE_BACKGROUND = 47



colors_level = {
    "DEBUG": TextEffects.GREY,
    "INFO": TextEffects.GREEN,
    "WARNING": TextEffects.YELLOW,
    # ;{TextEffects.SLOW_BLINK} is maybe a bit too much
    # "ERROR": f"{TextEffects.YELLOW};{TextEffects.BOLD};{TextEffects.RED_BACKGROUND}"
    "ERROR": f"{TextEffects.RED};{TextEffects.BOLD};{TextEffects.YELLOW_BACKGROUND}",
    "CRITICAL": f"{TextEffects.YELLOW};{TextEffects.BOLD};{TextEffects.RED_BACKGROUND};{TextEffects.SLOW_BLINK}"
}
colors_name = {
    "DEBUG": TextEffects.GREY,
    "INFO": TextEffects.NORMAL,
    "WARNING": TextEffects.YELLOW,
    "ERROR": f"{TextEffects.RED}",
    "CRITICAL": f"{TextEffects.RED};{TextEffects.BOLD}"
}
colors_message = {
    "DEBUG": TextEffects.NORMAL,
    "INFO": TextEffects.NORMAL,
    "WARNING": TextEffects.YELLOW,
    "ERROR": f"{TextEffects.RED}",
    "CRITICAL": f"{TextEffects.RED};{TextEffects.BOLD}"
}


def color_by_level(txt: str, level: str, color_scheme: dict[str, str | int]):
    return f"\033[{color_scheme.get(level, 0)}m{txt}\033[0m "


def color_by_status_code(http_status_code: int):
    return {1: TextEffects.GREY,
            2: TextEffects.GREEN_BACKGROUND,
            3: TextEffects.BLUE,
            4: TextEffects.RED_BACKGROUND,
            5: TextEffects.MAGENTA_BACKGROUND
            }[http_status_code // 100]


class LogFormatter(logging.Formatter):

    def format(self, record: logging.LogRecord):
        # record.message did not work for some reason
        return color_by_level(f"[{record.levelname:^8}]", record.levelname, colors_level) + color_by_level(
            f"({record.name})", record.levelname, colors_name) + color_by_level(record.msg, record.levelname, colors_message)


def wrap_effect(string, effect):
    return f'\033[{effect}m{string}\033[m'


class RequestLogFormatter(logging.Formatter):

    def format(self, record: logging.LogRecord):
        request, response = record.args
        def build_path(path, query_string):
            import urllib.parse as url

            query_params = url.parse_qsl(query_string)

            sep = wrap_effect('&', TextEffects.YELLOW)
            query = sep.join(f"{key}={wrap_effect(val, TextEffects.BLUE)}" for key, val in query_params)

            if query_string:
                return f"{path}{wrap_effect('?', f'4;{TextEffects.YELLOW}')}{query}"
            return path
        if response:

            if 'route' in request.scope:
                route = request.scope['route']
                base_path = route.path
                params = request.scope['path_params']
                path = '~'
                for part in base_path[1:].split('/'):
                    path += '/'
                    if part.startswith('{'):
                        path += f"\033[{TextEffects.BLUE}m{params[part.strip('{}').split(':')[0]]}\033[0m"
                    else:
                        path += part
            else:
                path = build_path(request.scope["path"], request.scope["query_string"])


            ret = (color_by_level(f"[{record.levelname:^8}]", record.levelname, colors_level) + f"\033[{TextEffects.BOLD}m{request.app.title + ':':<19} {request.method:>6} \033[{color_by_status_code(response.status_code)}m{response.status_code}\033[0m "
                    + build_path(path, request.scope['query_string'].decode('utf-8')))
        else:
            ret = (color_by_level(f"[{record.levelname:^8}]", record.levelname, colors_level) +
                    f"\033[{TextEffects.BOLD}m{request.app.title + ':':<19} {request.method:>6} \033[{color_by_status_code(500)}m500\033[0m " +
                    build_path(request.scope["path"], request.scope["query_string"].decode('utf-8')))
        if record.msg:
            print(record.msg + "ss")
            return f"{ret} - Error: {record.msg}"
        return ret
        # return f"[{record.levelname:^8}] {request.app.title}: {request.method} {response.status_code} {request.scope["path"]}?{request.scope["query_string"].decode("utf-8")}"

class UvicornLoggingHandler(logging.Handler):
    def __init__(self):
        super().__init__()

    def emit(self, record: LogRecord):
        pprint.pprint(vars(record))
        # breakpoint()
        


def prepare_logging(enable_log_formatting: bool = True, verbose: bool = False, silent: bool = False):
    # ToDo should use something that easily prevents user from specifying verbose *and* silent...
    # hack: silence uvicorn to prevent duplicate logs from it
    # logging.getLogger("uvicorn").handlers.clear()
    # logging.getLogger("uvicorn.access").handlers.clear()
    # # logging.getLogger("uvicorn.access").addHandler(UvicornLoggingHandler())
    # # logging.getLogger("uvicorn.access").propagate = True
    # logging.getLogger("uvicorn.error").handlers.clear()
    # logging.getLogger("uvicorn.error").propagate = False
    # logging.getLogger("fastapi_cli").handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(RequestLogFormatter())
    logging.getLogger("request").addHandler(handler)
    logging.getLogger("request").propagate = False

    logging.getLogger("tailwind").setLevel(logging.INFO)

    # logging.getLogger("fastapi").handlers.clear()
    # loggers = [logging.getLogger(name) for name in logging.root.manager.loggerDict]
    # for logger in loggers:
    #     logger.handlers.clear()
    #     handler = logging.StreamHandler()
    #     handler.setFormatter(logging.Formatter(f"{logger}: %(message)s"))
    #     logger.addHandler(handler)
    # pprint.pprint(loggers)
    # logging.getLogger("uvicorn.error").handlers.clear()

    set_verbosity(verbose, silent)
    set_up_simple_logger()
    if enable_log_formatting:
        set_up_root_logger()

def set_verbosity(verbose, silent):
    if verbose:
        log_level = logging.DEBUG
    elif silent:
        log_level = logging.WARNING
    else:
        log_level = logging.INFO
    logging.basicConfig(level=log_level)

# there is probably a more elegant way, this is just the only thing I could come up with for now
def set_up_simple_logger():
    simple_logger = logging.getLogger("simple")
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    simple_logger.addHandler(handler)
    simple_logger.propagate = False     # do not propagate messages to parent (root)...


def set_up_root_logger():
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        handler.setFormatter(LogFormatter())


def log_once(msg: str, logger: logging.Logger, key: Hashable = None, level=logging.WARNING):
    if not key:
        key = msg
    if key not in logged_keys:
        logger.log(level, msg)
        logged_keys.add(key)