import copy
import gc
import json
import logging
import os
import sys
from dataclasses import dataclass, field, asdict
import pprint

from queue import Queue

import torch
from openai import OpenAI
from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig, BatchEncoding

from MeisterWissen.utility import FrontendUpdate, FrontendNotification, split_thinking_response, \
    method_to_function_outline
from MeisterWissen.rag_model import RAGModel


os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"


@dataclass
class QueryContext:
    retrieved_chunks: list[str] = field(default_factory=list)
    enable_tools = True # is this actually used?

@dataclass
class Model:
    name: str
    think_start: str
    think_start_token: int
    think_end_token: int
    tool_call_start_token: int
    tool_call_end_token: int

@dataclass
class Config:
    force_german_reasoning: bool
    force_french_reasoning: bool
    force_english_reasoning: bool
    model: Model
    context_size: int       # unused
    answer_max_tokens: int  # including thinking tokens
    temperature: float
    top_k: int
    repeat_last_n: int
    repeat_penalty: float
    seed: int

    @property
    def forced_reasoning(self):
        return any((self.force_english_reasoning, self.force_german_reasoning, self.force_french_reasoning))


def research_lore_books(research_target: str) -> str:
    """Findet passende Abschnitte in einer RAG Datenbank die aus Regionalbeschreibungen für DSA besteht.

    Die Datenbank enthält Informationen über alle Aspekte der Welt, etwa wichtige Orte, Institutionen und Persönlichkeiten,
    aber auch vieles mehr.
    Diese Funktion kann beliebig häufig benutzt werden, auch mit derselben Suchanfrage, um weitere Informationen zu recherchieren.

    Args:
        research_target: Schlagworte, bzw. Ziel der Recherche
    """

@dataclass
class ToolCall:
    name: str
    arguments: dict[str, str] = field(default_factory=list)

class MalformedToolCallError(Exception):
    ...

@dataclass
class ModelAnswer:
    # ToDo what should we append to the history?
    # if we wanted to append the full message, we should make this accessible as well...
    thinking_content: str
    answer_content: str
    tool_call_string: str
    tool_call: ToolCall = None
    error: str = None


    def __post_init__(self):
        if self.tool_call_string:
            try:
                self.tool_call = json.loads(self.tool_call_string)
            except json.decoder.JSONDecodeError:
                logging.error(f"Failed to decode model tool call: {self.tool_call_string}")
                raise MalformedToolCallError
            try:
                # if another LLM outputs tool calls in a different format, we should handle it here
                self.tool_call = ToolCall(**self.tool_call)
            except:
                logging.error("Model generated unknown tool call format!")
                pprint.pprint(self.tool_call_string, stream=sys.stderr)
                raise MalformedToolCallError


class Agent:
    def __init__(self, rag_model: RAGModel, frontend_updates: Queue[FrontendUpdate], log_level: int = None):
        self.rag_model = rag_model
        self.frontend_updates: Queue[FrontendUpdate] = frontend_updates
        self.logger = logging.getLogger(self.__class__.__name__)
        self.current_iteration = 0      # only test var for debugging purposes currently
        if log_level:
            self.logger.setLevel(log_level)
        self.retrieved_chunks: list[str] = []

        # huggingface transformers did not like instance methods as "tools", so we need this workaround
        self.tools = [method_to_function_outline(self.research_lore_books),
                      method_to_function_outline(self.retrieve_chunk),
                      ]
        self.tool_mapping = {tool.__name__: getattr(self, tool.__name__) for tool in self.tools}

        self.config = Config(
            force_german_reasoning=False,  # False,
            force_french_reasoning=False,
            force_english_reasoning=True,
            # model="qwen3:30b-a3b",
            model=Model(name="Qwen/Qwen3-30B-A3B",
                        think_start="<think>\n",
                        think_start_token= 151667,       # model specific, this is for qwen3-30b-a3b
                        think_end_token= 151668,
                        tool_call_start_token=151657,
                        tool_call_end_token=151658,
                        ),
            # model="gpt-oss:20b",
            # model="llama3.1:8b",
            # model="mistral:7b",
            context_size= 8192 * 3,  # 12288,
            answer_max_tokens=4096,
            temperature=0,                              # not currently used
            top_k=1,
            repeat_last_n=256,
            repeat_penalty=1.5, # maybe increase to 3 or something
            seed=42,
        )

        quantization_config = BitsAndBytesConfig(  # llm_int8_enable_fp32_cpu_offload=True,
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            # bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.float16,
        )
        # load the tokenizer and the model
        self.tokenizer = AutoTokenizer.from_pretrained(self.config.model.name)

        self.model = AutoModelForCausalLM.from_pretrained(
            self.config.model.name,
            dtype=torch.float16,
            device_map="auto",
            quantization_config=quantization_config,
            low_cpu_mem_usage=True,
            max_memory={
                0: "20GiB",
            },
        )

        self.logger.debug(f"Using max. context size of {self.config.context_size} Tokens")

        self.system_note_no_rag = ("Du bist ein Teil eines Assistenzsystems für das deutsche Pen-and-Paper Fantasy-Rollenspiel 'Das Schwarze Auge' (DSA). "
                                   "DSA spielt in der fiktiven Welt 'Dere', auf dem Kontinent 'Aventurien'.\n"
                                   "- Antworte kurz und prägnant\n"
                                   "- Du kannst vor deiner Antwort in <think> tags nachdenken.")

        self.system_note = ("Du bist ein Teil eines Assistenzsystems für das deutsche Pen-and-Paper Fantasy-Rollenspiel 'Das Schwarze Auge' (DSA). "
                            "DSA spielt in der fiktiven Welt 'Dere', auf dem Kontinent 'Aventurien'.\n"
                            "- Dein eigenes Wissen über diese Welt ist kaum vorhanden, du solltest dich also auf Textquellen stützen!\n"
                            "- Wenn die Text-Quellen keine ausreichenden Informationen bieten, steht es dir auch immer frei noch weiter zu recherchieren.\n"
                            "- Wenn dir Text-Quellen zur Verfügung gestellt werden, sie aber keine ausreichenden Informationen enthalten um die Frage vollständig und umfänglich zu beantworten, musst du noch weiter recherchieren!\n"
                            "- Jede Frage kann beantwortet werden, wenn du nur die richtigen Hintergrundtexte findest. Erzähle dem Nutzer niemals, dass die dir vorliegenden Texte keine Informationen enthalten, stattdessen musst du weiter recherchieren!\n"
                            "- Häufig sind weitere Informationen in Eltern- oder Kindabschnitten zu finden. Wenn du mehr zu einem Thema erfahren möchtest, welches in einem Abschnitt vorkam, kannst du Kinder oder Eltern des Abschnitts per id abrufen und anschauen!\n"
                            "- Antworte kurz und prägnant\n"  
                            "- Du kannst vor deiner Antwort in <think> tags nachdenken.")   #
        if self.config.force_german_reasoning:
            self.system_note += " Deine Gedanken müssen aber ebenfalls auf deutsch sein!"
        if self.config.force_french_reasoning:
            self.system_note += " Deine Gedanken müssen allerdings auf französisch sein!\nDeine finale Antwort soll dennoch auf deutsch formuliert sein."


        # Deine Aufgaben ist es Fragen zu beantworten. Dafür stehen dir verschiedene Tools zur Verfügung um beispielsweise in Hintergrundtexten zu recherchieren. "
        #                             "Wenn du genügend Informationen hast, um eine Frage zu beantworten, musst du keine Tools mehr benutzen, sondern kannst direkt antworten
    def chat(self, prompt: str, history: list[dict[str, str]], force_answer: bool = False) -> ModelAnswer:
        if not force_answer:
            prompt = f"Hier nun die Anfrage des Nutzers: '{prompt}'\n\nFalls dir noch Informationen fehlen um die Anfrage vollständig zu beantworten, verwende die gegebenen Recherche-Tools um mehr herauszufinden! Auch wenn deine erste Recherche nicht zu einem Ergebnis führt, kann eine tiefergehende Recherche helfen!"
        else:
            prompt = f"Hier nun die Anfrage des Nutzers: '{prompt}'\n\nDu hast die Möglichkeiten zur Recherche bereits ausgeschöpft und kannst nicht mehr weiter recherchieren. Du musst nun eine finale Antwort generieren!"
        messages = [{"role": "system", "content": self.system_note}] + history + [{"role": "user", "content": prompt}]
        # try to force the model to reason in german


        if force_answer:
            text = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                # continue_final_message=True,
                enable_thinking=True
            )
        else:
            text = self.tokenizer.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True,
                # continue_final_message=True,
                enable_thinking=True,  # not sure if this really works tbh...
                tools=self.tools,
            )

        full_text = text
        message_prefix_content = f"{self.config.model.think_start}Ich muss zunächst durchgehen, was ich über die Anfrage des Nutzers bereits weiß."
        if self.config.force_french_reasoning:
            message_prefix_content = f"{self.config.model.think_start}D’abord, je dois parcourir ce que je sais déjà sur la demande de l’utilisateur."
        if self.config.force_english_reasoning:
            message_prefix_content = f"{self.config.model.think_start}First, I need to go through what I already know about the user's request."
        if self.config.forced_reasoning:
            prefix_message = {"role": "assistant", "content": message_prefix_content}
            # for some reason does not add double think this way (and does otherwise...)
            full_text = text + self.tokenizer.apply_chat_template([prefix_message], tokenize=False, continue_final_message=True, enable_thinking=True)

        # setting add_special_tokens=False is important according to the huggingface docs (since they are already added earlier), though I did not see any issues without it until now either...
        # transformers.logging.set_verbosity_info()

        self.logger.info("Before generation:")
        self.log_gpu_usage()

        self.model.cuda()
        try:
            model_inputs = self.tokenizer([full_text], return_tensors="pt", add_special_tokens=False).to(self.model.device)
            self.logger.info("On answer generation:")
            self.log_gpu_usage()
            generated_ids = self._predict_answer(model_inputs)
        except torch.OutOfMemoryError as e:
            self.logger.error(e)
            # self.logger.error("Will discard the first two history elements (tool call + answer)")
            self.model.cpu()
            # print(f"{sys.getrefcount(model_inputs) = }")
            del model_inputs
            gc.collect()
            torch.cuda.empty_cache()
            self.log_gpu_usage()
            # print(gpu_tensors)
            return ModelAnswer("", "", "", error="OOM")
            return self.chat(prompt, history[:-2])

        thinking_content, content, tool_call = self.transform_model_answer(generated_ids, model_inputs)
        if not content and not tool_call:
            self.logger.error("Model did not generate an answer but only a thinking trace. Will force it to generate an answer.")
            # actual input is usually BatchEncoding, but normal dict seems to work fine as well
            new_input = {"attention_mask": torch.tensor([[1]*(len(generated_ids[0]) + 1)], device="cuda"), "input_ids": torch.cat((generated_ids, torch.tensor([[self.config.model.think_end_token]], device="cuda")), dim=-1) }
            try:
                generated_ids = self._predict_answer(new_input)
            except torch.OutOfMemoryError as e:
                # ToDo seems that if the model researches for too long, it does run out of memory
                self.logger.error(e)
                self.logger.error("Will discard the first two history elements (tool call + answer)")
                del model_inputs
                torch.cuda.empty_cache()
                return ModelAnswer("", "", "", error="OOM")
            # _ seems to be same as thinking_content, though I would think it should be an empty string...weird.
            _, content, tool_call = self.transform_model_answer(generated_ids, model_inputs)

        self.model.cpu()
        del model_inputs
        torch.cuda.empty_cache()
        self.logger.info("After generation:")
        self.log_gpu_usage()

        # self.tokenizer.decode(output_ids, skip_special_tokens=True)

        if self.config.forced_reasoning:
            thinking_content = message_prefix_content + thinking_content
        # self.logger.info("Thinking: " + thinking_content)
        # tool_call = tool_call[:-3] + tool_call[-2:]
        try:
            return ModelAnswer(thinking_content, content, tool_call)
        except MalformedToolCallError as e:
            tool_call = self.__fix_tool_call(tool_call)
            self.logger.warning(f"Fixed tool call: {tool_call}")
            try:
                return ModelAnswer(thinking_content, content, tool_call)
            except MalformedToolCallError as e:
                self.logger.critical(f"Fixing tool call did not work.")
                breakpoint()

    def log_gpu_usage(self, print_tensors=False):
        objects = []
        bytes = 0
        for obj in gc.get_objects():
            try:
                if torch.is_tensor(obj) or (hasattr(obj, 'data') and torch.is_tensor(obj.data)):
                    if obj.is_cuda:
                        objects.append(obj)
                        bytes += obj.numel() * obj.dtype.itemsize
                        if print_tensors:
                            print(f"GPU Tensor: {obj.size()} | {type(obj)}")
            except:
                pass
        self.logger.info(f"Total number of tensors on GPU: {len(objects)}")
        self.logger.info(f"Total size of tensors: {sum(obj.numel() for obj in objects)}")
        if bytes > 1024**2:
            self.logger.warning(f"Memory estimate: {bytes / 1024**3} GiB")
        else:
            self.logger.info(f"Memory estimate: {bytes / 1024**2} MiB")
        self.logger.info(f"Total GPU usage: {torch.cuda.device_memory_used(device=0) / 1024 ** 2} MiB")

    def transform_model_answer(self, generated_ids, model_inputs):
        output_ids = generated_ids[0][len(model_inputs.input_ids[0]):].tolist()
        # parsing thinking content
        try:
            # rindex finding 151668 (</think>)
            think_end_index = len(output_ids) - output_ids[::-1].index(self.config.model.think_end_token)
        except ValueError:
            if self.config.forced_reasoning or self.config.model.think_start_token in output_ids:
                self.logger.error(
                    "No think end token found in model output, but it did start thinking. This means it never stopped thinking, indicating a endless repetition issue.")
                think_end_index = len(output_ids)
            else:
                think_end_index = 0
        try:
            tool_call_start = output_ids.index(self.config.model.tool_call_start_token)
            tool_call_end = output_ids.index(self.config.model.tool_call_end_token)
        except ValueError:
            tool_call_start, tool_call_end = think_end_index, think_end_index - 1
        thinking_content = self.tokenizer.decode(output_ids[:think_end_index], skip_special_tokens=True).strip("\n")
        if tool_call_end > 0:   # if tool_call_end == -1, there is no tool_call
            tool_call = self.tokenizer.decode(output_ids[tool_call_start + 1:tool_call_end],
                                              skip_special_tokens=True).strip("\n")
        else:
            tool_call = ""
        content = self.tokenizer.decode(output_ids[think_end_index:tool_call_start] + output_ids[tool_call_end + 1:],
                                        skip_special_tokens=True).strip("\n")
        return thinking_content, content, tool_call

    def _predict_answer(self, model_inputs):
        with torch.no_grad():           # should not be needed....but cannot hurt
            generated_ids = self.model.generate(
                **model_inputs,
                max_new_tokens=self.config.answer_max_tokens,
                # parameters for qwen3
                temperature=0.6,
                top_p=0.95,
                top_k=20,
                min_p=0,
                # seems to high, model generates weird stuff with this
                repetition_penalty=1.2,  # huggingface docs for qwen mention "presence_penalty" instead.
                # do_sample=False,
            )
        return generated_ids

    def __fix_tool_call(self, tool_call_string: str):
        self.model.cuda()
        system_note = "You are part of a RAG system with tool calling capabilities."
        prompt = "In a previous run, you generated this tool call, which seems to contain a syntactic error and therefore could not be parsed. You shall now fix it the tool call. Keep its semantic content, and only fix the syntactic errors by generating a new tool call. Do not generate an answer - just call the tool in the correct way. " \
                 "Tool Call: \n" + tool_call_string
        model_inputs = self.tokenizer.apply_chat_template(
            [[{"role": "system", "content": system_note}, {"role": "user", "content": prompt}]],
            add_generation_prompt=True,
            enable_thinking=True,
            tools=self.tools,
            return_dict=True,
            return_tensors="pt"
        ).to(self.model.device)
        generated_ids = self._predict_answer(model_inputs)
        thinking, content, tool_call = self.transform_model_answer(generated_ids, model_inputs)
        del model_inputs
        torch.cuda.empty_cache()
        self.model.cpu()
        return tool_call



    # def chat_ollama(self, prompt: str, history: list[dict[str, str]]):
    #     warnings.warn("Not used anymore due to shift from ollama to transformers backend", DeprecationWarning)
    #     prompt = f"Hier nun die Anfrage des Nutzers: '{prompt}'\n\nFalls dir noch Informationen fehlen um die Anfrage vollständig zu beantworten, verwende die gegebenen Recherche-Tools um mehr herauszufinden! Auch wenn deine erste Recherche nicht zu einem Ergebnis führt, kann eine tiefergehende Recherche helfen!"
    #     messages = [{"role": "system", "content": self.system_note}] + history + [{"role": "user", "content": prompt}]
    #     # try to force the model to reason in german
    #
    #     if self.config.force_german_reasoning:
    #         # seems a bit weird to add half a message but should work this way https://github.com/ollama/ollama/issues/5393
    #         messages.append({"role": "assistant", "content": "<think>Ich muss zunächst durchgehen, was ich über die Anfrage des Nutzers bereits weiß. "})  #  + ("Im Abschnitt " if history else "")
    #     # self.logger.warning(f"start chat (iteration {self.current_iteration})")
    #     self.logger.debug(f"starting ollama chat - {self.current_iteration}")
    #     # for whatever reason, num_predict: 0 did not work for me....
    #     test = ollama.chat(model=self.config.model, messages=messages, stream=False, tools=self.tools.values(), options={"num_ctx": self.config.context_size, "num_predict": 1})
    #     prompt_tokens = test.prompt_eval_count
    #     # we could also set num_predict smaller and not cut num_ctx, but when using a smaller context, more model layers get loaded into VRAM meaning more speed.
    #     res = ollama.chat(model=self.config.model, messages=messages, stream=False, tools=self.tools.values(), keep_alive=0,
    #                       options={"num_ctx": prompt_tokens + self.config.answer_max_tokens,
    #                                "temperature": self.config.temperature,
    #                                "top_k": self.config.top_k,   # output actually seems deterministic now, no matter what we set here.
    #                                "seed": self.config.seed,
    #                                "repeat_last_n": self.config.repeat_last_n,
    #                                "repeat_penalty": self.config.repeat_penalty,
    #                                }
    #                       )
    #     for _ in split_thinking_response(res.message.content):
    #         self.logger.debug(_)
    #     self.logger.debug(f"Tool calls: {res.message.tool_calls}")
    #     # ToDo add statistics on total time spent loading ollama and total time spent using ollama
    #     self.logger.debug("done")
    #     self.logger.debug(f"Prompt Tokens: {res.prompt_eval_count}")
    #     self.logger.info(f"Generated Tokens: {res.eval_count}")
    #     self.logger.debug(f"Done reason: {res.done_reason}")
    #     self.logger.debug(f"Load Duration: {res.load_duration // 1e9} seconds")
    #     self.logger.debug(f"Total Duration: {res.total_duration // 1e9} seconds")
    #     if not res.eval_count < self.config.answer_max_tokens:
    #         logging.warning("Answer was too long, was probably cut!")
    #     # breakpoint()
    #     # ollama.generate(model=self.model, keep_alive=)
    #     # self.logger.warning("end chat")
    #     self.current_iteration += 1
    #     # self.chat_history += [{"role": "user", "content": query}, res["message"]]
    #     # answer = ollama.generate(model=self.model, prompt=prompt)["response"]
    #     if res.message.content and self.config.force_german_reasoning:
    #         res.message.content = "<think>Ich muss zunächst durchgehen, was ich über die Anfrage des Nutzers bereits weiß. " + res.message.content  #  + ("Im Abschnitt " if history else "")
    #
    #     return res

    def research_lore_books(self, research_target: str) -> str:
        """Findet passende Abschnitte in einer RAG Datenbank die aus Regionalbeschreibungen für DSA besteht.

        Die Datenbank enthält Informationen über alle Aspekte der Welt, etwa wichtige Orte, Institutionen und Persönlichkeiten,
        aber auch vieles mehr.
        Diese Funktion kann beliebig häufig benutzt werden, auch mit derselben Suchanfrage, um weitere Informationen zu recherchieren.

        Args:
            research_target: Schlagworte, bzw. Ziel der Recherche
        """
        # if called multiple times for the same query, filter out chunks that have already been retrieved (so that further research yields other chunks)
        context = self.rag_model.find_best_chunks(research_target, n=3, exclude_ids=self.retrieved_chunks)
        self.retrieved_chunks += [c.id for score, c in context]
        self.frontend_updates.put(FrontendUpdate("retrieved_context", {"reformulated_query": research_target, "context": [c.id for score, c in context]}))
        context = "\n\n".join([self.rag_model.get_context_knowledge_string(chunk) for _, chunk in context])
        # self.logger.info(context)
        return context

    def retrieve_chunk(self, chunk_id: str) -> str:
        """
        Gibt einen bestimmten Abschnitt, dessen id bekannt ist zurück.

        Hiermit kann beispielsweise ein Eltern- oder Kind-Abschnitt zu einem bereits gefundenen Text untersucht werden.

        Args:
            chunk_id: ID des Abschnitts
        """
        if chunk := self.rag_model.get_chunk(chunk_id):
            self.frontend_updates.put(FrontendUpdate("retrieved_context",
                                                     {"reformulated_query": chunk_id, "context": [chunk_id]}))
            return self.rag_model.get_context_knowledge_string(chunk)
        return "Dieser Abschnitt existiert nicht."

    def answer(self, answer: str) -> str:
        """Beantwortet dem Nutzer seine Frage mit der gegebenen Antwort.
           Rufe diese Funktion erst auf, wenn du sicher bist eine ausreichende Antwort geben zu können.
        """
        # only used for certain LLMs, may not be needed
        # also, not implemented here since if the tool tries to call it,  this is intercepted anyway
        ...
        # return answer



# ToDo try out always letting model use tool and make answer a tool as well
#  --> if this works, I could get rid of the tool use decision step and therefore save time while processing
class Supervisor(Agent):
    def __init__(self, rag_model: RAGModel, frontend_updates: Queue[FrontendUpdate], log_level: int = None):
        super().__init__(rag_model, frontend_updates, log_level)
        self.agents = []

    def simple_query(self, prompt: str) -> tuple[str, str]:
        """Passes system prompt and user prompt to LLM to generate an answer. Does not use any RAG components."""
        client = OpenAI(base_url="https://ki-chat.uni-mainz.de/api/", api_key=os.environ["JGU_API_KEY"])
        completion = client.chat.completions.create(
            model="Qwen3 235B Thinking",
            messages=[
                {"role": "system", "content": self.system_note_no_rag},
                {"role": "user", "content": prompt},
            ],
            seed=42,
        )
        return completion.choices[0].message.reasoning_content, completion.choices[0].message.content


    def ask_query(self, prompt: str, history: list[dict[str, str]] = None, qc: QueryContext = None):
        if qc is None:
            qc = QueryContext()
            self.frontend_updates.put(FrontendNotification("Received Query", "Deciding on what do next..."))
            self.retrieved_chunks.clear()
        history = copy.copy(history) or []
        force_answer = False
        while True:
            response: ModelAnswer = self.chat(prompt, history, force_answer)
            if response.answer_content or response.tool_call:
                break
            if response.error == "OOM":
                history = history[:-2]
                force_answer = True
                self.logger.error("Chat resulted in OOM Error, will force answer generation with less history.")
            logging.warning("Encountered tool response without answer or tool call, will try again!")

        if response.tool_call:
            self.frontend_updates.put(FrontendNotification("Tool decision successful", f"Will use the following tools: {response.tool_call}"))
            outputs = []
            # ToDo Maybe handle all tool calls individually. dynamic handling may seem elegant, but there are not that many tools and maybe we want to do some special things for some tools.
            #  Alternatively we could find another way to pass additional information elegantly (QC). Maybe by using another object ("Toolkit" or something?)
            # todo seems like model can now only call one tool. Is this safe to assume, or shall we allow multiple calls in theory?
            # let's for now assume multiple tool calls might be a thing in the future
            # huggingface docs state however, that modern models usually only issue one tool call at a time (while the data structures would still in theory allow more)
            # see: https://huggingface.co/docs/transformers/chat_extras
            for tool_call in [response.tool_call]:
                # todo not so clean, just a quick proof of concept
                if tool_call.name == "answer":
                    # not used currently
                    self.logger.info("Answering using answer tool")
                    return "Answer generated per tool call, no reasoning available", tool_call.arguments["answer"]
                try:
                    tool = self.tool_mapping[tool_call.name]
                    self.logger.info(f"Calling tool: {tool_call.name} with arguments: {tool_call.arguments}")
                    outputs.append((tool_call.name, tool(**tool_call.arguments)))
                except KeyError:
                    self.logger.error(f"Model tried to use unknown tool: {tool_call}")
                except TypeError as e:
                    self.logger.error(f"Model generated invalid tool call parameters: {tool_call.arguments}")
                    self.logger.error(f"Full error: {e}")

            # tool call class follows specification in huggingface docs, so we can just use asdict:
            #  https://huggingface.co/docs/transformers/chat_extras
            history.append({"role": "assistant", "tool_calls": [{"type": "function", "function": asdict(tool_call)} for tool_call in [response.tool_call]]})
            # history.append({"role": "assistant", "content": response.answer_content})
            for tool_name, tool_output in outputs:
                history.append({'role': 'tool', 'tool_name': tool_name, 'content': str(tool_output)})
            qc.enable_tools = False
            return self.ask_query(prompt, history, qc)    # currently only one tool call possible
        else:
            return response.thinking_content, response.answer_content




if __name__ == '__main__':
    rag_model = RAGModel()
    supervisor = Supervisor(rag_model, Queue())
    response = supervisor.ask_query("Hallo!")
    # response = supervisor.chat("Was kannst du mir über Rohaja von Gareth, die Kaiserin des Mittelreichs sagen?")
    print(response)
    breakpoint()
    print(response)

