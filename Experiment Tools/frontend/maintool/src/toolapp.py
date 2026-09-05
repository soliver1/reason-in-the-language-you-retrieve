import json
import logging
import time
import pathlib as pl

import fastapi
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from .template_environment import create_environment

from .storage import storage

from jinja2 import pass_context

from shared_modules.logging_utility import wrap_effect, TextEffects

request_logger = logging.getLogger("request")
timing_logger = logging.getLogger("timing")

# timing_logger.setLevel(logging.WARNING)

async def log_middleware(request: fastapi.Request, call_next):
    try:
        response = await call_next(request)
    except Exception as e:
        request_logger.error(e, request, None)
        raise
        
    request_logger.info("", request, response)
    return response


async def timing_request_middleware(request: fastapi.Request, call_next):

    start = time.time()
    response = await call_next(request)
    end = time.time()

    # import pprint
    # pprint.pprint(vars(request))
    # pprint.pprint(dir(response))

    backend = request.scope.get('backend_interface')
    templates = request.scope.get('template_builder')

    total_time = 0
    backend_time = 0
    template_time = 0


    if backend:
        timing_logger.debug(f'Backend time: {backend.timings}')

        backend_time = sum(time for _, time in backend.timings)

    if templates:
        timing_logger.debug(f'Template render time: {templates.time_rendering}')
        template_time = templates.time_rendering or 0

    runtime = end - start
    total_time = runtime

    def time_to_string(time):
        return f"{int(time)}s {int((time%1)*1000):03}ms"

    backend_percent = backend_time / total_time 
    template_percent = template_time / total_time 
    other_percent = (total_time - backend_time - template_time) / total_time

    length = 60

    timing_logger.info(f'Execution time   Total: {wrap_effect(time_to_string(total_time), TextEffects.BOLD)}(100%)  | {wrap_effect("\u258c", TextEffects.BLUE)}Backend: {time_to_string(backend_time)}({int(backend_percent*100):>3}%)  | {wrap_effect("\u258c", TextEffects.RED)}Template: {time_to_string(template_time)}({int(template_percent*100):>3}%)')
    timing_logger.info(f'Execution time   {wrap_effect("\u2592"*int(length*backend_percent), TextEffects.BLUE)}{wrap_effect("\u2592"*int(length*template_percent), TextEffects.RED)}{"\u2592"*int(length*other_percent)}')


    return response


class ToolBackendInterface:

    def __init__(self, tool_target: str):
        self.tool_target_name = tool_target
        self.timings = []

    @staticmethod
    def make_request(tool, function, delegate=None, params={}):
        if delegate is None:
            return dict(tool=tool, function=function, parameters=params)
        return dict(tool=tool, function=function, parameters=params, delegate=delegate)

    async def send_request(self, func_name, params=None, delegate=None, tool=None):
        payload = json.dumps(self.make_request(tool or self.tool_target_name, func_name, delegate, params or {})).encode('utf8')

        start = time.time()
        data = await storage.connection_manager.send_request(payload)
        end = time.time()
        self.timings.append((func_name, end-start))

        return data



class TemplateResponseBuilder:

    def __init__(self, environment, global_context):
        self.env = environment
        self.templates_to_render = []
        self.global_context = global_context
        self.time_rendering = None

    def add_template(self, name: str, context: dict):
        self.templates_to_render.append((name, context))
        return self

    def _render(self):
        start = time.time()
        data = ''
        for name, context in self.templates_to_render:
            ctx = self.global_context | context
            data += self.env.get_template(name + '.html').render(ctx)
        
        end = time.time()
        self.time_rendering = end-start
        return data

    def make_response(self, status_code=200, headers: dict | None=None):
        return HTMLResponse(self._render(), status_code=status_code, headers=headers)


class ToolApp(fastapi.FastAPI):

    def __init__(
        self, 
        title: str, 
        main_paths: list[tuple]=None, 
        parent_tool = None,
        backend_interface_class=ToolBackendInterface, 
        settings=None, 
        env_callback=None,
        template_context_processors=None, 
        template_router_class=None,
        template_base_loader=None,
        *args, **kwargs):

        assert title, "A Tool needs a name/title"

        super().__init__(*args, title=title, **kwargs)

        self.main_paths = main_paths or []
        self.settings = settings
        self.parent = parent_tool or self
        self.backend_interface_class=backend_interface_class

        self.safe_title = title.lower()

        if self.settings and self.settings.route_prefix is not None:
            self.route_prefix = self.settings.route_prefix 
        else:
            self.route_prefix = title.lower()


        static_dir = pl.Path(f'frontend/{self.title.lower()}/static').absolute()
        static_dir.mkdir(exist_ok=True)

        self.templates_dir = pl.Path(f'frontend/{self.title.lower()}/templates')
        self.templates_dir.mkdir(exist_ok=True)

        self.mount('/static', StaticFiles(directory=static_dir, follow_symlink=True), name='static')

        self._router = template_router_class or _Router

        self.env_callback = env_callback
        self.template_base_loader = template_base_loader
        self.templates = create_environment(self._router(self), env_callback, self.templates_dir, template_base_loader)

        self.template_context_processors = template_context_processors
        # for backwards compability
        self._templates = Jinja2Templates(env=self.templates, context_processors=self.template_context_processors)



    def backend_interface(self):
        return self.backend_interface_class(self.settings.backend_tool_id)

    def get_backend_interface(self):
        return self.backend_interface(self)

    def template(self, context):
        return TemplateResponseBuilder(self.templates, context)

    def set_parent_tool(self, parent):
        self.parent = parent
        self.templates = create_environment(self._router(self), self.env_callback, self.templates_dir, self.parent.template_base_loader)
        self._templates = Jinja2Templates(env=self.templates, context_processors=self.template_context_processors)

    def __repr__(self):
        return f"<ToolApp '{self.title}'>"


class _Router:

    def __init__(self, tool: ToolApp):
        self._tool = tool

    def str_url(self, url):
        r = f"{self._tool.route_prefix}" + (url if url.startswith('/') else f'/{url}')
        return f'/{r}' if not r.startswith('/') else r

    @pass_context
    def routef(self, ctx, name, **kwargs):
        r = f"{self._tool.route_prefix}" + self._tool.url_path_for(name, **kwargs)
        return f'/{r}' if not r.startswith('/') else r

    def __getattr__(self, name):
        @pass_context
        def get_path(ctx, **kwargs):
            return self.routef(ctx, name, **kwargs)
        return get_path

    def tool(self, tool: ToolApp):
        return _Router(tool)

    def shared(self, path, f=None):
        fpath = path.format(*(f or []))
        return '/shared' + (fpath if fpath.startswith('/') else f'/{fpath}')

    def static(self, path, f=None):
        fpath = path.format(*(f or []))
        return '/static' + (fpath if fpath.startswith('/') else f'/{fpath}')