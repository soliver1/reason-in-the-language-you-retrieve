from __future__ import annotations

import enum
import json
import subprocess
import sys
import termios
import time
from collections import Counter
from dataclasses import dataclass, is_dataclass, asdict
from pathlib import Path
from typing import Any
from transformers import LlamaTokenizer
import torch

import ollama
import logging


logger = logging.getLogger(__name__)

punctuation = ",.;:!’‘”()"

class TextType(enum.Enum):
    SECTION = 1
    HEADLINE = 2


@dataclass
class TextBlock:
    # type currently does not really contain any useful data (since headline can be checked via .startswith("#"))
    # If I would add some special stuff, like italic text, quotes, etc. to this, it might be useful though.
    type: TextType
    content: str
    origin_page: int = None

    def __post_init__(self):
        if isinstance(self.type, int):
            self.type = TextType(self.type)

    def short_repr(self, head: int = 50, tail: int = None):
        if not tail:
            tail = head
        sep = "... [...] ..."
        if len(self.content) < head + tail + len(sep):
            return self.content
        return self.content[:head] + sep + self.content[-tail:]

    @property
    def headline_level(self):
        if self.type == TextType.HEADLINE:
            return len(self.content.strip().split()[0])
        return 0

    def __repr__(self):
        return self.short_repr()

    def __bool__(self):
        return bool(self.content)

def ask_ollama(prompt: str, model: str = 'gemma3:27b', allowed_answers: list[str] = None, temperature: int=None):
    if temperature is None:
        answer = ollama.generate(model=model, prompt=prompt)["response"]
    else:
        answer = ollama.generate(model=model, prompt=prompt, options={"temperature": temperature})["response"]
    # ToDo maybe there is a way to restrict the model answers to the allowed ones, if yes I should use it here.
    if allowed_answers and not answer in allowed_answers:
        logger.error(f"Ollama generated unallowed answer: {answer}\n Allowed answers were: {allowed_answers}")
    return answer

# ToDo find correct tokenizer for whatever model I'll be using and use #tokens for some descisions (e.g. max chunk length)
def calculate_token_length(text):
    tokenizer = LlamaTokenizer.from_pretrained("decapoda-research/llama-3-3-hf")
    inputs = tokenizer(text, return_tensors="pt")
    return len(inputs["input_ids"][0])



def open_pdf_in_viewer(name: str| Path, page:int|str, pdf_base_path: str | Path = None, find: str = None):
    name = Path(name)
    if not (name.is_file() and name.suffix == ".pdf"):
        if pdf_base_path is None:
            logger.error(f"Cannot open pdf viewer for file {name} without a pdf_base_path given.")
        name = Path(pdf_base_path) / f"{name.stem}.pdf"
    if find:
        cmd = ["okular", "--page", str(page), "--unique", "--noraise", "--find", find, name]
    else:
        cmd = ["okular", "--page", str(page), "--unique", "--noraise", name]
    return subprocess.Popen(cmd)


def simplify_string(inp: str):
    return "".join(c for c in inp if c.isalpha() or c.isdigit() or c == " ").lower().strip()


def load_word_count_dictionary(save_file="word_counts.json"):
    with open(save_file) as file:
        return Counter(json.load(file))


def sanitize_for_yaml(data: Any):
    try:
        if hasattr(data, "sanitize_for_yaml"):
            return sanitize_for_yaml(data.sanitize_for_yaml())
        if is_dataclass(data):
            return sanitize_for_yaml(asdict(data))
        elif isinstance(data, dict):
            return {key: sanitize_for_yaml(val) for key, val in data.items()}
        elif isinstance(data, list):
            return [sanitize_for_yaml(el) for el in data]
        elif isinstance(data, enum.Enum):
            return data.value
        else:
            return data
    except:
        breakpoint()


def evaluate_wrapped_word_via_llm(split, combined):
    # ToDo this still produces some false results, especially for words the model does not know.
    #  Maybe another approach would be to generate a wordlist and allow all words in this list?
    #  => If we encounter an unknown word, we could still use this function as backup
    request = f"Welches der folgenden Wörter ist richtig: 1. {split} oder 2. {combined}? Antworte nur mit der Zahl des richtigen Wortes."
    return [split, combined][int(ask_ollama(request, temperature=0)) - 1]


def flush_input_buffer():
    time.sleep(0.1)
    termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)


class EndInteractiveSession(Exception):
    ...


def ask_accept(default_true: bool=False) -> bool:
    flush_input_buffer()
    inp = "X"
    while inp not in "yjn":
        inp = input(f"Annehmen? {'[J]' if default_true else 'J'}/N: ").lower() or ("y" if default_true else "X")
    return inp in "yj"
