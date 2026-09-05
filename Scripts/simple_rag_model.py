import pprint
from typing import Tuple

import numpy as np
import ollama
from sentence_transformers import SentenceTransformer

from pathlib import Path

from information_container import BookData, ContentBlock
from utility import ask_ollama
import readline
import pickle


"""
A simple prototype of a RAG system, a bit like the final one but with a lot less features and usability.
"""
# task = 'Given a web search query, retrieve relevant passages that answer the query'


class RAGModel:

    def __init__(self):
        # ToDo values hardcoded for now, should be improved later
        self.embedding_model = SentenceTransformer('intfloat/multilingual-e5-large')
        self.book_data = [BookData.load_from_file(Path(f"data/5 - information_container/{stem}.yaml"))
                          for stem in ["G01 - In den Dschungeln Meridianas", "G05 - Land der Ersten Sonne"]]
        self.documents = [chunk for book_data in self.book_data for chunk in book_data.content if chunk.content]

        embedding_save_path = Path("/tmp/ragmodel/embeddings")
        if not embedding_save_path.exists():
            embedding_save_path.parent.mkdir(parents=True, exist_ok=True)
            self.doc_embeddings = self.embedding_model.encode([chunk.text for chunk in self.documents], convert_to_tensor=True,
                                          normalize_embeddings=True)
            with open(embedding_save_path, "wb") as file:
                pickle.dump(self.doc_embeddings, file)
        else:
            with open(embedding_save_path, "rb") as file:
                self.doc_embeddings = pickle.load(file)
        self.chat_history = []

    @property
    def system_prompt(self):
        return """
    Du bist ein Q/A Chatbot für das Rollenspiel "Das Schwarze Auge" (DSA). Deine Aufgabe ist es, Nutzerfragen zu verschiedensten innerweltlichen Thematiken zu beantworten.
    Hierfür werden zunächst zur Frage passende Informationstexte aus Büchern extrahiert, die dir als Kontext gegeben werden.
    Du musst das Wissen aus dem Kontext benutzen um die Fragen des Nutzers zu beantworten. Da die Texte aus Büchern extrahiert werden, 
    wird auch die Reihenfolge der Überschriften unter denen sie zu finden waren gelistet, du kannst sie ebenfalls für deine Antwort nutzen.
    Erwähne in deinen Antworten nicht woher du Informationen hast, beantworte einfach nur die Frage als würdest du sie ohne Hintergrundtext beantworten. Formuliere deine Antworten stets auf deutsch.
    """

    def main(self):
        while True:
            query = input("Stelle eine Frage: ")
            context = self.find_best_chunks(query, 3)
            print(f"Using the following sections as context: \n"
                  f"{'\n'.join(f'{c.id} - {c.headline} (Seiten {c.source_pages})' for score, c in context)}")
            # res = ask_ollama(
            # print(rag_prompt(context, query))
            # res = ask_ollama(rag_prompt(context, query))
            res = self.process_query(context, query)

            pprint.pprint(res["message"])

    def reformulate_query(self, query):
        system = ('Du bist Teil eines Q/A Chatbot Systems für ein Rollenspiel. '
                  'Deine Aufgabe ist es, den bisherigen Chatverlauf zu nutzen um Nutzerfragen so umzuformulieren, '
                  'dass sie auch ohne diesen Kontext verstanden werden können. Sie sollten im Stil einer Anfrage an eine Suchmaschine gestellt sein.')
        messages = [{"role": "system", "content": system}] + self.chat_history + [
            {"role": "user", "content": f"Formuliere nun bitte diese Frage um, so dass sie für sich allein steht: {query}"}]
        res = ollama.chat(model="gemma2-testing", messages=messages)
        return res["message"].content

    def process_query(self, context, query):
        context = f'Hier einige relevante Hintergrundinformationen um die Frage zu beantworten: \n\n{"\n\n".join([self.get_context_knowledge_string(chunk) for chunk in context])}\n\n"'
        messages = [{"role": "system", "content": self.system_prompt}] + self.chat_history + [
            {"role": "user", "content": context + f"Und hier nun meine Frage: {query}"}]
        res = ollama.chat(model="gemma2-testing", messages=messages)
        self.chat_history += [{"role": "user", "content": query}, res["message"]]
        return res

    def find_best_chunks(self, query, n: int = 3) -> list[Tuple[float, ContentBlock]]:
        if n:
            query_embeddings = self.embedding_model.encode(query, convert_to_tensor=True, normalize_embeddings=True)
            scores = ((query_embeddings @ self.doc_embeddings.T) * 100).cpu()
            score_indices = np.argsort(scores)
            context = [(float(scores[i]), self.documents[i]) for i in score_indices[-n:]]
            # print(scores[score_indices[-n:]])
            return context
        return []


    def get_context_knowledge_string(self, chunk: ContentBlock):
        return f"{chunk.text_with_ancestors}\n\n" # {'-' * 20}


    def rag_prompt(self, context: list[ContentBlock], user_question: str):
        return f"""
    Hier nun die relevanten Hintergrundinformationen: 
        
    {"\n\n".join([self.get_context_knowledge_string(chunk) for chunk in context])}
        
    
        
    
    Nutze die Informationen um folgende Frage des Nutzers zu beantworten:
    {user_question}"""



if __name__ == '__main__':
    RAGModel().main()
