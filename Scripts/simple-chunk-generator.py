#!/usr/bin/env python3
"""
Tasked with generating simple, evenly sized chunks (in contrast to the normally used chunks based on book sections).
"""
import math
from pathlib import Path

import ruamel.yaml
from transformers import AutoTokenizer

from information_container import BookData



data_dir = Path("data/5 - information_container/")
model_name = "Qwen/Qwen3-30B-A3B"
tokenizer = AutoTokenizer.from_pretrained(model_name)

books = {path: BookData.load_from_file(path) for path in data_dir.iterdir()}

total_tokens = sum(len(tokenizer.encode(book.full_text())) for book in books.values())
total_chunks = sum(len(book) for book in books.values())
print(f"Total tokens: {total_tokens}")
print(f"Total chunks: {total_chunks}")


for book_path, book_data in books.items():
# for book_path in data_dir.iterdir():
#     book_data = BookData.load_from_file(book_path)
    full_text = book_data.full_text()
    with open(Path("data") / "6 - full_text" / f"{book_path.stem}.md", "w") as file:
        file.write(full_text)
    tokens = tokenizer.encode(full_text)
    # tokens_per_chunk = math.floor(len(tokens) / len(book_data))
    tokens_per_chunk = math.floor(total_tokens / total_chunks)
    print(f"Tokens per chunk: {tokens_per_chunk}")
    print(f"Tokens per chunk: {total_tokens / total_chunks:.2f}")
    chunks = [tokens[i:i + tokens_per_chunk] for i in range(0, len(tokens), tokens_per_chunk)]
    chunk_texts = [tokenizer.decode(chunk) for chunk in chunks]
    with open(Path("data") / "7 - simple_chunks" / f"{book_path.stem}.yaml", "w") as file:
        yaml = ruamel.yaml.YAML()
        yaml.dump({"tokenizer": "Qwen/Qwen3-30B-A3B", "total_tokens": len(tokens), "tokens_per_chunk_orig": round(len(tokens) / len(book_data), 2), "num_chunks_orig": len(book_data), "num_chunks_new": len(chunks), "chunk_texts": chunk_texts}, file)
