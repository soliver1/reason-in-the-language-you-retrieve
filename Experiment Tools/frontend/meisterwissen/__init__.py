import logging
from pathlib import Path
from pprint import pprint
from tkinter.font import names
from typing import Annotated

import fastapi
from fastapi import Request
from starlette.responses import HTMLResponse
import markdown
from dataclasses import dataclass, field

# could also import from backend
from shared_modules.MeisterWissen.information_container import BookData, KnowledgeBase, ContentBlock
from frontend.maintool.src.toolapp import ToolApp
from frontend.maintool.src.helper import send_request


LOG_LEVEL_POLLING = logging.NOTSET

app = ToolApp(title="meisterwissen", main_paths=[("", "Hier klicken")], default_response_class=HTMLResponse)

knowledge_base = KnowledgeBase([BookData.load_from_file(Path(f"shared/data/MeisterWissen/5 - information_container/{stem}.yaml"))
                                for stem in ["G01 - In den Dschungeln Meridianas", "G05 - Land der Ersten Sonne", "G08 - Herz des Reiches"]])


references = {'book_1': {'id': 'book_1', 'label': 'Buch 1'}, 'book_2': {'id': 'book_2', 'label': 'Buch 2'}, 'book_3': {'id': 'book_3', 'label': 'Buch 3'}}

# fixme this should be handled on the client side in the future, but currently I don't know how to do this
@dataclass
class Context:
    used_sources: list[str] = field(default_factory=list)

user_interaction_context = Context()


# ToDo Idee:
#  Kommunikation zwischen backend und frontend über named pipe in shared folder
#  Browser fragt regelmäßig beim frontend aktuellen Stand ab (polling)
#  frontend liest aus pipe und speichert zwischenstand, gibt den weiter an browser
#  polling z.B. per
#  hx-trigger="every 1s"
#  https://htmx.org/attributes/hx-trigger/
#  https://hyperscript.org/commands/repeat/

# get, post, put, delete
# get: change nothing
# post: create new
# put: change something (if unsure on put or post: use post)
# delete: delete something
@app.get("/")
async def index():
    # talks to buchstaff
    # data = await send_request('function', {})
    # clear history
    await send_request("clear_history", {}, tool="MeisterWissen")
    # knowledge_sources = await send_request("knowledge_sources", {}, tool="MeisterWissen")
    # render takes parameters needed for index
    # knowledge_references=knowledge_sources
    return app.templates.get_template('index.html').render(knowledge_base=knowledge_base, used_sources=[])


@app.post("/ask_query")
async def ask_query(user_query: Annotated[str, fastapi.Form()], task: Annotated[str, fastapi.Form()]):
    # to discuss:
    # what was the ", request: fastapi.Request" for?
    # it seemed like I had to remove it for the function to work.
    print(user_query)
    print(task)
    # form_data = await request.form()
    # print(form_data)

    user_interaction_context.used_sources = []

    match task:
        case "start":
            await send_request("query", {"query": user_query}, tool="MeisterWissen")

            # fixme: when including ret, somehow the web page is never updated...
            return f'''
                <div class="question p-1 bg-yellow-800 rounded-md self-end w-fit m-1 ml-12">{user_query}</div>
                <div hx-get="/meisterwissen/poll_query_answer" hx-trigger="every 1s" hx-swap="outerHTML" class="answer w-fit p-1 bg-lime-800 rounded-md m-1 mr-12">...<div>
                '''  + '<div id="system-insight" hx-swap-oob="true">Verarbeite Anfrage...</div>' + app.templates.get_template('submit-button.html').render(generation_in_progress=True)
        case "stop":
            await send_request("cancel_query", tool="MeisterWissen")
            return ""
    # + ret


# ToDo include <think> stuff in answer, but make it collapsed by default and let user expand it if wanted

@app.get("/poll_query_answer")
async def poll_query_answer():
    response = await send_request("update_available", {}, tool="MeisterWissen", log_level=LOG_LEVEL_POLLING)
    print("polling query answer...", response)
    empty_answer = '<div hx-get="/meisterwissen/poll_query_answer" hx-trigger="every 1s" hx-swap="outerHTML" class="answer w-fit p-1 bg-lime-800 rounded-md m-1 mr-12">...<div>'
    if not response:
        return empty_answer
    else:
        print(response)
        match response:
            case {"type": "answer", "data": data}:
                inner_monologue, answer = data
                return (app.templates.get_template('chat_answer.html').render(inner_monologue=markdown.markdown(inner_monologue), answer=markdown.markdown(answer)) +
                        app.templates.get_template('submit-button.html').render(generation_in_progress=False))
            case {"type": "notification", "data": (title, message, hidden)}:
                return empty_answer + app.templates.get_template("notification.html").render(title=title, message=message, hidden=hidden)
            case {"type": "retrieved_context", "data": data}:
                print("Retrieved context!")
                reformulated_query, context = data["reformulated_query"], data["context"]
                blocks = [knowledge_base[id] for id in context]
                # pprint(blocks)
                user_interaction_context.used_sources += context

                return (empty_answer + app.templates.get_template('knowledge_references.html').render(knowledge_base=knowledge_base, used_sources=user_interaction_context.used_sources)
                        + app.templates.get_template('system_insight.html').render(reformulated_query=reformulated_query, references=blocks))
            case _:
                print(f"Unknown type: {response['type']}")
                return empty_answer


@app.get("/knowledge_references")
async def knowlegde_references():
    return app.templates.get_template('knowledge_references.html').render(knowledge_base=knowledge_base, used_sources=user_interaction_context.used_sources)

@app.get("/knowledge_reference_content/{id}")
async def knowlegde_reference_content(id: str, request: Request):

    return app.templates.get_template('knowledge_reference_content.html').render(chunk=knowledge_base[id])


# Examples for passing parameters, get and post

# /meisterwissen/5
# /meisterwissen/5?value=hallo
@app.get("/{id}")
async def getter(id: int, value: str=""):
    pass

# put uses same syntax
# delete sometimes uses this syntax, sometimes the get syntax
@app.post("/{id}")
async def ask_query(id: int, value: Annotated[str, fastapi.Form()]):
    pass

