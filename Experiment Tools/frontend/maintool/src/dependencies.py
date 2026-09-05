from typing import Annotated, Any

from fastapi import Request, Depends, responses


from .auth import get_user as get_user_, User


def context_dep():
    return {}


def tool_dep(request: Request):
    return request.app


def get_user(user: Annotated[User, Depends(get_user_)], ctx: Annotated[dict, Depends(context_dep)]):
    ctx['user'] = user
    return user


def main_tool_dep(tool: Annotated[..., Depends(tool_dep)]):
    return tool.parent


def backend_tool_dep(request: Request, tool: Annotated[Any, Depends(tool_dep)]):
    interface = tool.backend_interface()
    request.scope['backend_interface'] = interface
    return interface


def templates(request: Request, tool: Annotated[Any, Depends(tool_dep)], context: Annotated[...,  Depends(context_dep)]):
    templ = tool.template(context)
    request.scope['template_builder'] = templ
    return templ


def is_htmx_request(request: Request):
    return 'HX-Request' in request.headers


class Templating:

    def __call__(self, request: Request, ctx: Annotated[dict, Depends(context_dep)]):
        def render_template(name, context, status_code=200, items=None, item_name=None, headers=None):
            if items is not None:
                if item_name is None or items is None:
                    raise ValueError('If you want to render multiple templates, tou must set items and item_name')
                
                data = b""
                for item in items:
                    data += request.app._templates.TemplateResponse(request, name + '.html', ctx | context | {item_name: item}).body

                return responses.HTMLResponse(data, status_code=status_code)

            return request.app._templates.TemplateResponse(request, name + '.html', ctx | context, status_code=status_code, headers=headers)
        return render_template