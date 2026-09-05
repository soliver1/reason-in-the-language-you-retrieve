from dataclasses import dataclass


@dataclass
class BaseToolSettings:

    title: str

    backend_tool_id: str | None = None

    route_prefix: str | None = None

