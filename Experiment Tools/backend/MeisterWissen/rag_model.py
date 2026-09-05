import json
import logging
import pickle
import pprint
import time
from pathlib import Path
from typing import Tuple, Optional, Iterable

from queue import Queue
import numpy as np
# import ollama
import torch
from sentence_transformers import SentenceTransformer

from MeisterWissen.utility import FrontendUpdate
from shared_modules.MeisterWissen.information_container import BookData, ContentBlock
from transformers import AutoModel, AutoTokenizer, AutoModelForCausalLM

logger = logging.getLogger(__name__)


class Reranker:

    def __init__(self):
        # self.tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen3-Reranker-4B", padding_side='left')
        self.tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen3-Reranker-0.6B", padding_side='left')
        # self.model = AutoModelForCausalLM.from_pretrained("Qwen/Qwen3-Reranker-4B").cuda().eval()
        self.model = AutoModelForCausalLM.from_pretrained("Qwen/Qwen3-Reranker-0.6B").eval()  # .cuda()
        self.token_false_id = self.tokenizer.convert_tokens_to_ids("no")
        self.token_true_id = self.tokenizer.convert_tokens_to_ids("yes")
        self.instruction = "Given a web search query, retrieve relevant passages that answer the query"
        prefix = "<|im_start|>system\nJudge whether the Document meets the requirements based on the Query and the Instruct provided. Note that the answer can only be \"yes\" or \"no\".<|im_end|>\n<|im_start|>user\n"
        suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"
        self.prefix_tokens = self.tokenizer.encode(prefix, add_special_tokens=False)
        self.suffix_tokens = self.tokenizer.encode(suffix, add_special_tokens=False)

    def preprocess_inputs(self, pairs, max_length = 8192):
        inputs = self.tokenizer(
            pairs, padding=False, truncation='longest_first',
            return_attention_mask=False, max_length=max_length - len(self.prefix_tokens) - len(self.suffix_tokens)
        )
        for i, ele in enumerate(inputs['input_ids']):
            # wrap res with prefix and suffix tokens
            inputs['input_ids'][i] = self.prefix_tokens + ele + self.suffix_tokens
        # pad after adding prefix/
        # breakpoint()
        inputs = self.tokenizer.pad(inputs, padding=True, return_tensors="pt")  # , max_length=max_length
        # inputs = self.tokenizer.pad(inputs, padding=max_length, return_tensors="pt")
        for key, val in inputs.items():
            inputs[key] = val.to(self.model.device)
        return inputs

    @torch.no_grad()
    def compute_logits(self, inputs, **kwargs):
        # ToDo since I don't really use batch processing currently due to memory constraints, could change to just take one input
        with torch.no_grad():
            batch_scores = self.model(**inputs).logits[:, -1, :]
        true_vector = batch_scores[:, self.token_true_id]
        false_vector = batch_scores[:, self.token_false_id]
        batch_scores = torch.stack([false_vector, true_vector], dim=1)
        batch_scores = torch.nn.functional.log_softmax(batch_scores, dim=1)
        scores = batch_scores[:, 1].exp().tolist()
        return scores

    def rerank(self, query: str, documents: list[ContentBlock]) -> list[float]:
        # documents = documents[0:7]
        # documents = documents
        # inputs = self.preprocess_inputs([f"<Instruct>: {self.instruction}\n<Query>: {query}\n<Document>: {doc.text_with_ancestors}" for doc in documents])
        # torch.cuda.memory._record_memory_history(True)
        # logger.debug("Start reranking")
        # breakpoint()
        self.model.cuda()
        torch.cuda.empty_cache()
        scores = []
        for doc in documents:
            inputs = self.preprocess_inputs([f"<Instruct>: {self.instruction}\n<Query>: {query}\n<Document>: {doc.text_with_ancestors}"])
            score = self.compute_logits(inputs)[0]
            del inputs
            torch.cuda.empty_cache()
            scores.append(score)
            # breakpoint()

        # ToDo is this list comprehension causing memory issues?
        # scores = [self._score_document(doc, query) for doc in documents]
            # todo try calling gc.collect to collect the tensor
            # + torch.cuda.empty_cache + del
            # del inputs
            # for tensor in inputs.values():
            #     tensor.cpu()
            # time.sleep(0.05)
        self.model.cpu()
        torch.cuda.empty_cache()
        # breakpoint()
        # logger.debug("Finished reranking")
        return scores

    def _score_document(self, doc: ContentBlock, query: str):
        # logger.debug(f"Scoring doc {doc}")
        inputs = self.preprocess_inputs(
            [f"<Instruct>: {self.instruction}\n<Query>: {query}\n<Document>: {doc.text_with_ancestors}"])
        score = self.compute_logits(inputs)
        del inputs
        torch.cuda.empty_cache()
        return score[0]


class RAGModel:

    # task = 'Given a web search query, retrieve relevant passages that answer the query'
    def __init__(self, device="cpu"):
        # ToDo values hardcoded for now, should be improved later

        self.embedding_model = SentenceTransformer('intfloat/multilingual-e5-large', device=device)
        # self.embedding_model.cpu()
        self.reranker = Reranker()
        self.book_data = [BookData.load_from_file(Path(f"shared/data/MeisterWissen/5 - information_container/{stem}.yaml"))
                          for stem in ["G01 - In den Dschungeln Meridianas", "G05 - Land der Ersten Sonne", "G08 - Herz des Reiches"]]
        self.documents = [chunk for book_data in self.book_data for chunk in book_data.content if chunk.content]

        # embedding_save_path = Path("/tmp/ragmodel/embeddings")
        embedding_save_path = Path("backend/MeisterWissen/embeddings-information-container")
        if not embedding_save_path.exists():
            embedding_save_path.parent.mkdir(parents=True, exist_ok=True)
            self.doc_embeddings = self.embedding_model.encode([chunk.text for chunk in self.documents],
                                                              convert_to_tensor=True,
                                                              normalize_embeddings=True)
            with open(embedding_save_path, "wb") as file:
                pickle.dump(self.doc_embeddings, file)
        else:
            with open(embedding_save_path, "rb") as file:
                self.doc_embeddings = pickle.load(file)

        if not self.doc_embeddings.device == torch.device(device):
            logger.debug(f"Loaded doc embeddings on wrong device, moving to {device}")
            self.doc_embeddings = self.doc_embeddings.to(device)
            torch.cuda.empty_cache()
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
            context = self.find_best_chunks(query, n=3)
            print(f"Using the following sections as context: \n"
                  f"{'\n'.join(f'{c.id} - {c.headline} (Seiten {c.source_pages})' for score, c in context)}")
            res = self.process_query(context, query)
            pprint.pprint(res["message"])

    def reformulate_query(self, query):
        system = ('Du bist Teil eines Q/A Chatbot Systems für ein Rollenspiel. '
                  'Deine Aufgabe ist es, den bisherigen Chatverlauf zu nutzen um Nutzerfragen so umzuformulieren, '
                  'dass sie auch ohne diesen Kontext verstanden werden können. Sie sollten im Stil einer Anfrage an eine Suchmaschine gestellt sein.')
        messages = [{"role": "system", "content": system}] + self.chat_history + [
            {"role": "user",
             "content": f"Formuliere nun bitte diese Frage um, so dass sie für sich allein steht: {query}"}]
        res = ollama.chat(model="gemma2-testing", messages=messages)
        return res["message"].content

    def process_query(self, context, query):
        context = f'Hier einige relevante Hintergrundinformationen um die Frage zu beantworten: \n\n{"\n\n".join([self.get_context_knowledge_string(chunk) for _, chunk in context])}\n\n"'
        messages = [{"role": "system", "content": self.system_prompt}] + self.chat_history + [
            {"role": "user", "content": context + f"Und hier nun meine Frage: {query}"}]
        # res = ollama.chat(model="gemma2-testing", messages=messages)
        res = ollama.chat(model="qwq", messages=messages)
        self.chat_history += [{"role": "user", "content": query}, res["message"]]
        return res

    def find_best_chunks(self, query, n: int = 3, rerank_chunks: int = 30, exclude_ids: list[str] = None, enable_reranking=True) -> list[Tuple[float, ContentBlock]]:
        exclude_ids = exclude_ids or []
        if n:
            query_embeddings = self.embedding_model.encode(query, convert_to_tensor=True, normalize_embeddings=True, show_progress_bar=False)
            scores = ((query_embeddings @ self.doc_embeddings.T) * 100).cpu()
            score_indices = np.argsort(scores)
            if enable_reranking:
                context = self._filter_context(scores, score_indices, rerank_chunks, exclude_ids)
                try:
                    rerank_scores = self.reranker.rerank(query, [c[1] for c in context])
                except torch.cuda.OutOfMemoryError as e:
                    logger.error(e)
                    breakpoint()
                # print(f"Query: {query}")
                # print("Rerank  -    RAG   - Chunk")
                # for rerank_score, (orig_score, chunk) in zip(rerank_scores, context):
                #     print(f"{rerank_score:.5f} - {orig_score:.5f} - {chunk}")
                rerank_indices = np.argsort(rerank_scores)
                # breakpoint()
                return [(rerank_scores[i], context[i][1]) for i in rerank_indices[-n:]]
            else:
                return self._filter_context(scores, score_indices, n, exclude_ids)
        return []

    def _filter_context(self, scores: Iterable, score_indices: np.array, num_chunks: int, exclude_ids: list[str]) -> list[Tuple[float, ContentBlock]]:
        context = [(float(scores[i]), self.documents[i]) for i in score_indices[-num_chunks - len(exclude_ids):]]
        return [(score, chunk) for score, chunk in context if chunk.id not in exclude_ids][-num_chunks:]


    def get_chunk(self, chunk_id: str) -> Optional[ContentBlock]:
        # ToDo improve with a better data structure
        for chunk in self.documents:
            if chunk.id == chunk_id:
                return chunk
        logger.error(f"Chunk {chunk_id} not found!")
        return None

    def get_context_knowledge_string(self, chunk: ContentBlock):
        # ToDo maybe ancestors should be given as list of dicts, not list of tuples?
        res = {
            "headline": chunk.headline.content,
            "id": chunk.id,
            "ancestors": [(anc.id, anc.headline.content) for anc in chunk.ancestors],
            "children": [(child.id, child.headline.content) for child in chunk.children],
            "content": chunk.content
        }
        # return json.dumps(res, indent=4)
        return json.dumps(res, indent=4, ensure_ascii=False)
        # return f"{chunk.text_with_ancestors}\n\n"  # {'-' * 20}

    def rag_prompt(self, context: list[ContentBlock], user_question: str):
        return f"""
    Hier nun die relevanten Hintergrundinformationen: 

    {"\n\n".join([self.get_context_knowledge_string(chunk) for chunk in context])}




    Nutze die Informationen um folgende Frage des Nutzers zu beantworten:
    {user_question}"""
