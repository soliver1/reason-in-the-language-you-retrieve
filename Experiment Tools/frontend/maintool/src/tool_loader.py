import pathlib as pl
import importlib
import logging
from datetime import datetime


logger = logging.getLogger(__name__)


def mount_tools(app, *tools):
    for tool in tools:
        tool_settings = tool.settings

        app.mount(f'/{tool_settings.route_prefix if tool_settings is not None else tool.title.lower()}', tool)
        app.tools.append(tool)

        message = f'{tool.title.capitalize()} mounted.'
        logger.info(message)


def load_tools(dirs):
    loaded_tools = []

    for d in dirs:
        path = 'frontend' / pl.Path(d)
        if path.exists():

            start = datetime.now()
            module = importlib.import_module(f'frontend.{d}')
            try:
                tool_app = module.app
            except AttributeError:
                raise ValueError(f'Tool path {path} does not contain an app')

            time = datetime.now() - start

            logger.info(f'Tool {tool_app.title} loaded in {int(time.total_seconds())}s {time.microseconds//1000}ms')

            logger.debug(f'''Loaded tool "{tool_app.title}":
    safe_title: {tool_app.safe_title}
    url_prefix: {tool_app.route_prefix}

            ''')

            loaded_tools.append(tool_app)
        else:
            raise ValueError(f'Path for tool does not exists: {path.absolute()}')
    
    return loaded_tools
