import pathlib
import pathlib as pl
import logging
import asyncio
import sys
from typing import Annotated
from contextlib import asynccontextmanager

import fastapi
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from jinja2 import FileSystemLoader


if (shared_folder := str((pathlib.Path(".") / "shared").absolute())) not in sys.path:
    sys.path.append(shared_folder)
    print(f"Added {shared_folder} to path")

from shared_modules.logging_utility import prepare_logging
from .config import settings
from .connection_manager import ConnectionManager
from .storage import storage
from .toolapp import ToolApp, log_middleware, timing_request_middleware

from .dependencies import Templating

from .auth import auth_router, NotAuthenticatedException, User, get_optional_user
from .helper import is_htmx_request

from . import tool_loader

import locale

loc = locale.getlocale() 
# use German locale; name might vary with platform
try:
    locale.setlocale(locale.LC_ALL, 'de_DE')
except locale.Error:
    locale.setlocale(locale.LC_ALL, 'de_DE.utf8')

logger = logging.getLogger(__name__)
tailwind_logger = logging.getLogger("tailwind")

async def log_tailwind(reader):
    while True:
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=0.1)
        except TimeoutError:
            continue
        except Exception as e:
            print(vars(e))
            tailwind_logger.critical('Tailwind crashed')
            return
        if not line:
            return
        line = line.decode('utf-8')
        if line.strip() and not line.startswith('sh'):
            tailwind_logger.debug(line.strip())


@asynccontextmanager
async def tailwind_lifetime(app: fastapi.FastAPI):

    if settings.use_tailwind:
        if not settings.tailwind_script_path.exists():
            tailwind_logger.critical('Tailwind not found')
            yield
        else:
            tailwind_process = await asyncio.create_subprocess_shell(
                f'{settings.tailwind_script_path} -i {settings.tailwind_src_file} -o {settings.tailwind_target_file} -w', stderr=asyncio.subprocess.PIPE)
            tailwind_logger.info(f'Tailwind started. src: {settings.tailwind_src_file} tar: {settings.tailwind_target_file}')
            tailwind_logger_task = asyncio.create_task(log_tailwind(tailwind_process.stderr))

            yield

            if tailwind_process.returncode is None:
                tailwind_process.terminate()
            tailwind_logger_task.cancel()
            await tailwind_process.wait()
    else:
        yield


@asynccontextmanager
async def connection_manager_lifetime(app: fastapi.FastAPI):
    if settings.use_update_con:
        logger.info(f'Try to connect to backend on {settings.update_con_address}:{settings.update_con_port}')
        storage.connection_manager = ConnectionManager(settings.update_con_address, settings.update_con_port, storage)
        await storage.connection_manager.connect()
        logger.info("Backend connected")

    yield

    if settings.use_update_con:
        await storage.connection_manager.close()

@asynccontextmanager
async def app_lifetime(app: fastapi.FastAPI):

    async with connection_manager_lifetime(app), tailwind_lifetime(app):
        yield  # execute normal app lifetime


def create_app():

    # create and configure the app
    app_ = ToolApp('maintool', settings=settings,  lifespan=app_lifetime, debug=settings.debug, template_base_loader=FileSystemLoader('frontend/maintool/base_templates'))
    app_.tools = []  # app_ needs this variable later
    app_.mount('/shared', StaticFiles(directory=pl.Path('frontend/shared').absolute(), follow_symlink=True), name='shared')

    app_.middleware('http')(log_middleware)
    app_.middleware('http')(timing_request_middleware)

    tools = tool_loader.load_tools(settings.load_tool_directories)
    for tool in tools:
        tool.set_parent_tool(app_)

    tool_loader.mount_tools(app_, *tools)

    app_.include_router(auth_router)

    @app_.exception_handler(NotAuthenticatedException)
    def auth_exception_handler(request: fastapi.Request, e: NotAuthenticatedException):
        if is_htmx_request(request):
            return fastapi.Response(headers={'HX-Redirect': f'/login?target={request.url}'})
        return RedirectResponse(url=f'/login?target={request.url}', status_code=303)

    for tool in tools:
        tool.exception_handler(NotAuthenticatedException)(auth_exception_handler)

    @app_.get('/', response_class=HTMLResponse)
    async def index(
        templates: Annotated[..., fastapi.Depends(Templating())],
        request: fastapi.Request, 
        user: Annotated[User | None, fastapi.Depends(get_optional_user)],
        ):

        return templates('index', {'tools': app_.tools, 'user': user})

    @app_.get('/login', response_class=HTMLResponse)
    async def login_form(request: fastapi.Request, target: str | None=None):
        return app_._templates.get_template('login.html').render(target=target or '/')

    return app_


prepare_logging()
root_app = create_app()
