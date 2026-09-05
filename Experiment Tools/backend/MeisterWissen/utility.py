from datetime import timedelta, datetime
from dataclasses import dataclass
from typing import Any, Callable
import inspect

@dataclass
class FrontendUpdate:
    type: str
    data: Any


def FrontendNotification(title=None, message=None, hidden=None):
    assert title or message, "No title or message given to frontend notification"
    return FrontendUpdate("notification", (title, message, hidden))


def split_thinking_response(response, end_tag: str = "</think>") -> tuple[str, str]:
    if end_tag not in response:
        return "", response
    inner_monologue, answer = response.split("</think>")
    return inner_monologue.strip(end_tag.replace("/", "")).strip(), answer.strip()


def method_to_function_outline(method: Callable) -> Callable:
    """Transforms method to function, stripping all functionality"""
    def func(*args, **kwargs):
        ...

    func.__name__ = method.__name__
    func.__doc__ = method.__doc__
    func.__annotations__ = getattr(method, '__annotations__', {})
    func.__signature__ = inspect.signature(method)
    # breakpoint()

    return func

def convert_time_string(time_string: str) -> timedelta:
    try:
        time_obj = datetime.strptime(time_string, '%H:%M:%S.%f')
    except ValueError:
        time_obj = datetime.strptime(time_string, '%H:%M:%S')
    return timedelta(
        hours=time_obj.hour,
        minutes=time_obj.minute,
        seconds=time_obj.second,
        microseconds=time_obj.microsecond
    )