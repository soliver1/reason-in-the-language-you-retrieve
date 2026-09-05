import logging
import queue
import threading
from dataclasses import dataclass
from typing import Any

from MeisterWissen.rag_model import RAGModel
from MeisterWissen.agents import Supervisor
from MeisterWissen.utility import FrontendUpdate, split_thinking_response, FrontendNotification

from shared_modules.MeisterWissen.information_container import BookData, ContentBlock



logger = logging.getLogger(__name__)
"""
A simple prototype of a RAG system, a bit like the final one but with a lot less features and usability.
"""



class WorldKnowledge:

    def __init__(self):
        self.rag_model = RAGModel()
        self.frontend_updates: queue.Queue[FrontendUpdate] = queue.Queue()
        self.supervisor_agent = Supervisor(self.rag_model, self.frontend_updates)
        self.history = []
        self.running_thread: threading.Thread = None

    def update_available(self) -> bool:
        try:
            return self.frontend_updates.get(block=False)
        except queue.Empty:
            return False

    def _query(self, query):
        inner_monologue, answer = self.supervisor_agent.ask_query(query, self.history)
        # inner_monologue, answer = split_thinking_response(res.message.content)
        self.frontend_updates.put(FrontendUpdate("answer", (inner_monologue, answer)))
        self.history.append({"role": "user", "content": query})
        self.history.append({"role": "system", "content": answer})
        return


    def query(self, query: str):
        # for now: empty queue on new query to prevent old messages from being processed, there might be better ways
        # ToDO maybe also cancel all running generations?
        #  Or add another button for this?
        self.frontend_updates.queue.clear()
        # ToDo what happens if multiple queries are posted?
        self.running_thread = threading.Thread(target=self._query, args=(query,))
        self.running_thread.start()
        return

    def cancel_query(self):
        # would be nice to have, but is not my main task / research topic currently
        logger.warning("Cancelling queries is not yet implemented!")
        self.frontend_updates.put(FrontendNotification("Not implemented", "Cancelling queries is not yet implemented :/"))

    def clear_history(self):
        logger.info("Clearing history")
        self.history.clear()

    def knowledge_sources(self):
        def transform_book(text_block: BookData | ContentBlock):
            if text_block.children:
                return {block.id: (block.title, transform_book(block)) for block in text_block.children}
            return None
        return {book.id: (book.title, transform_book(book)) for book in self.rag_model.book_data}



if __name__ == '__main__':
    RAGModel().main()
