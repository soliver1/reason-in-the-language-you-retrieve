import json
from urllib.parse import urlparse, parse_qs

import fastapi

from .storage import storage


def make_request(tool, function, delegate=None, params={}, log_level=None):
    request = dict(tool=tool, function=function, parameters=params)
    if delegate is not None:
        request['delegate'] = delegate
    if log_level is not None:
        request['log_level'] = log_level
    return request


def dumps_cmd(cmd):
    return json.dumps(cmd).encode('utf8')

# todo rework
def send_request(func_name, params=None, delegate=None, tool='MeisterWissen', log_level=None):
    payload = dumps_cmd(make_request(tool, func_name, delegate, params or {}, log_level))

    return storage.connection_manager.send_request(payload)

# ?
def push_events(response, events, header='HX-Trigger'):
    response.headers[header] = json.dumps(events)


# ?
def get_htmx_current_query(request):
    if request.headers.get('HX-Request'):
        from_ = request.headers['HX-Current-URL']
        url = urlparse(from_)
        query = parse_qs(url.query)
        return query
    return {}


# ?
class NoneHTMXRequest(Exception):
    pass


def is_htmx_request(request: fastapi.Request):
    return 'HX-Request' in request.headers

# ?
def htmx_request_dependency(request: fastapi.Request):
    if not is_htmx_request(request):
        raise NoneHTMXRequest()
