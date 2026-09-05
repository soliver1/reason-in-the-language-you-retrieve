#!/usr/bin/env python3

import argparse
import logging
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

import ruamel.yaml

from utility import TextBlock, TextType, load_word_count_dictionary, punctuation, evaluate_wrapped_word_via_llm, \
    sanitize_for_yaml
from logging_utility import prepare_logging

prepare_logging(verbose=True)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore.connection").setLevel(logging.WARNING)
logging.getLogger("httpcore.http11").setLevel(logging.WARNING)
logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)
logging.getLogger("backoff").setLevel(logging.WARNING)

logger = logging.getLogger("InformationContainer")


class ContentBlock:

    def __init__(self, id_: str, headline: TextBlock, parent: "ContentBlock" = None, content: str = "", source_page_set = None):
        self.id = id_
        self.headline = headline
        self.headline_level = headline.headline_level
        # ToDo after fixing the content text block end wrapped words, there is probably no need to keep the list of textblocks
        self.content_text_blocks: list[TextBlock] = []
        self.content: str = content
        self.source_page_set = source_page_set or {self.headline.origin_page}

        self.parent: Optional[ContentBlock] = parent
        self.children: list[ContentBlock] = []

    @property
    def title(self):
        return self.headline.content.strip("#")

    @property
    def text(self):
        return f"{self.headline.content}\n{self.content}"

    @property
    def full_text(self):
        return f"{self.headline.content}\n{self.content}\n" + "\n".join([d.text for d in self.descendants])

    @property
    def text_with_ancestors(self):
        return "\n".join(anc.headline.content for anc in (self.ancestors + [self])) + f"\n{self.content}"

    @property
    def ancestor_texts(self):
        # not including self text for now
        return "\n".join(anc.text for anc in self.ancestors)

    @property
    def ancestors(self):
        # could also sort by headline level
        return sorted([self.parent] + [a for a in self.parent.ancestors], key=lambda x: x.id) if self.parent is not None else []

    @property
    def descendants(self):
        # includes self for practical reasons (- or not??)
        return sorted(self.children + [d for child in self.children for d in child.descendants], key=lambda x: x.id)

    @property
    def descendant_ids(self):
        return [d.id for d in self.descendants]

    @property
    def child_ids(self):
        return [c.id for c in self.children]

    @property
    def sibling_ids(self):
        # includes self
        # fixme does not work for elements without a parent.
        # should refactor the information container some time and unify BookData and ContentBlock more
        if self.parent:
            return self.parent.child_ids
        return []

    @property
    def source_pages(self):
        return sorted(self.source_page_set)
        # return sorted({el.origin_page for el in self.content_text_blocks + [self.headline]})

    def words_with_descendants(self):
        return len(" ".join([d.content for d in self.descendants + [self]]).split())

    @property
    def num_sentences(self):
        return len(self.content.split("."))

    @property
    def num_words(self):
        return len(self.content.split())

    @property
    def num_characters(self):
        return len(self.content)

    def __len__(self):
        return len(self.content)

    def __repr__(self):
        return f"{repr(self.headline)} (source pages: {self.source_pages}, words: {self.num_words}, total words: {self.words_with_descendants()}, id: {self.id})"   # , characters: {self.num_characters}

    def sanitize_for_yaml(self):
        return self.serialized()

    def serialized(self):
        return {
            "id": self.id,
            "headline": self.headline.content,
            "content": self.content,
            "source_pages": self.source_pages,
            "parent": self.parent.id if self.parent is not None else None,
            "children": [child.id for child in self.children]
        }


class BookData:

    def __init__(self, id_: Optional[str], title: str, content: list[ContentBlock] = None):
        self.id = id_
        self.title = title# .lstrip(id_)  # todo see if this makes sense
        # ToDo I feel like it might make more sense to have a dictionary instead of a list, though I am not sure about it.
        #  hmm, but if list index i just contains ContentBlock with id e.g. G01-i, then I guess just using the list works just as well
        #  => this breaks if I do not load a complete book though! (skipping first pages)
        self.content = content or []

    @property
    def children(self):
        # not 100% correct since it does not include sections before first headline chapter...but this should not matter
        return self.chapters(1)

    @property
    def descendants(self):
        return sorted(self.children + [d for child in self.children for d in child.descendants], key=lambda x: x.id)

    @property
    def descendant_ids(self):
        return [d.id for d in self.descendants]

    @classmethod
    def load_from_file(cls, filepath: Path, start_page = 0, end_page = math.inf):
        with open(filepath) as file:
            data = ruamel.yaml.YAML(typ="safe").load(file)
        cut_content = [da for da in data["content"] if start_page <= da["source_pages"][0] <= end_page]
        content_blocks = {da["id"]: ContentBlock(da["id"], TextBlock(TextType.HEADLINE, da["headline"], da["source_pages"][0]),
                                                 source_page_set=da["source_pages"], content=da["content"])
                          for da in cut_content}
        for cb_data in cut_content:
            if cb_data['parent']:
                content_blocks[cb_data['id']].parent = content_blocks[cb_data['parent']]
            content_blocks[cb_data['id']].children = [content_blocks[child] for child in cb_data['children']]
        return cls(data["id"], data["title"], list(content_blocks.values()))

    @classmethod
    def create_from_textblocks(cls, title: str, data: list[TextBlock], word_counts: Counter, id_: Optional[str] = None):
        logger.info(f"Creating BookData for {title}")
        if not id_:
            id_ = title.split()[0]
        self = cls(id_, title)
        pad_length = len(str(len([h for h in data if h.type == TextType.HEADLINE])))
        for block in data:
            # discard empty blocks (e.g. page with no content)
            if block.content:
                try:
                    if block.type == TextType.HEADLINE:
                        parent: ContentBlock = next(
                            (el for el in reversed(self.content) if el.headline_level < block.headline_level), None)
                        c_block = ContentBlock(f"{self.id}-{len(self.content):0{pad_length}d}", block, parent=parent)
                        if parent is not None:
                            parent.children.append(c_block)
                        self.content.append(c_block)
                    elif block.type == TextType.SECTION:
                        if self.content:
                            # self.content[-1].content_text_blocks.append(block)
                            self.content[-1].source_page_set.add(block.origin_page)
                            self._append_text_content(block, word_counts)
                        else:
                            logger.warning(f"Found text before any headline: {block}. It will be discarded")
                    else:
                        logger.error(f"TextType {TextType} is unknown, handling is not yet implemented!")
                except Exception as e:
                    logger.error(e)
                    breakpoint()
                    sys.exit(1)
        return self

    def full_text(self):
        return "\n".join(chunk.text for chunk in self.content)


    def _append_text_content(self, block: TextBlock, word_counts):
        # handle wrapped words
        # fixme general issue with wrapped words that is still present: [?]
        # example that might be meant: LLM evaluated ('Kriegs-und', 'Kriegsund') to Kriegsund
        # --> maybe could be fixed by passing the LLM a larger context?
        if (prev_text := self.content[-1].content.strip()).endswith("-"):
            first = prev_text.split()[-1]
            second = block.content.strip().split()[0]
            split = f"{first}{second}"
            combined = f"{first.removesuffix("-")}{second}"
            if word_counts[split.strip(punctuation)] > word_counts[combined.strip(punctuation)]:
                self.content[-1].content = prev_text + block.content
            elif word_counts[split.strip(punctuation)] < word_counts[combined.strip(punctuation)]:
                self.content[-1].content = prev_text.removesuffix("-") + block.content.lstrip()
            else:
                res = evaluate_wrapped_word_via_llm(split, combined)
                logger.debug(f"LLM evaluated {split, combined} to {res}")
                if res == split:
                    self.content[-1].content = prev_text + block.content
                else:
                    self.content[-1].content = prev_text.removesuffix("-") + block.content.lstrip()
        else:
            self.content[-1].content += block.content

    def __repr__(self):
        return f"""
        BookData for {self.id} {self.title}
        Content: \n{"\n".join([f"\t" * c.headline_level + f"{c}" for c in self.content])}
        """

    def __len__(self):
        return self.content.__len__()

    def __getitem__(self, item: int | str) -> ContentBlock:
        if isinstance(item, str):
            try:
                item = int(item.removeprefix(f"{self.id}-"))
            except ValueError:
                raise Exception(f"Cannot retrieve content entry for {item}!")
        return self.content[item]

    def sanitize_for_yaml(self):
        return sanitize_for_yaml(vars(self))

    def chapters(self, level=1):
        return [c for c in self.content if c.headline_level == level]


class KnowledgeBase:
    def __init__(self, books: list[BookData]):
        self.books = books
        self.chunks = {chunk.id: chunk for book in books for chunk in book}

    def __getitem__(self, item: str) -> ContentBlock:
        return self.chunks[item]


if __name__ == '__main__':

    arg_parser = argparse.ArgumentParser(description="Creates information container data (BookData)", formatter_class=argparse.RawTextHelpFormatter)
    arg_parser.add_argument("-i", "--input-file-stem", required=True, help="File to process. Only the file stem needs to be given, if a full path is given only the stem will be used.")
    arg_parser.add_argument("--debug", action="store_true", help="Add breakpoint after book-data is created to let the user interact with the data.")
    args = arg_parser.parse_args()
    title = Path(args.input_file_stem).stem
    yaml = ruamel.yaml.YAML(typ="safe")

    out_dir = Path("data/5 - information_container/")

    load_new = True
    if load_new:
        with open(f"data/4 - fixed_order/{title}.yaml") as file:
            data = yaml.load(file)["data"]
        text_blocks = [TextBlock(**el) for key, val in data.items() for el in val]
        book_data = BookData.create_from_textblocks(title, text_blocks, load_word_count_dictionary())
        yaml_writer = ruamel.yaml.YAML()
        # yaml.indent(mapping=2, sequence=4, offset=2)
        out_dir.mkdir(exist_ok=True)
        # fixme it seems like the data is currently getting messed up here somehow...
        with open(out_dir / f"{title}.yaml", "w") as file:
            yaml_writer.dump(sanitize_for_yaml(book_data), file)

    book_data = BookData.load_from_file(out_dir / f"{title}.yaml")
    breakpoint()


    # client = chromadb.Client(Settings(anonymized_telemetry=False))  # https://docs.trychroma.com/telemetry
    # collection = client.get_or_create_collection("sample_collection")
#
    # metadatas = [{"pages": ", ".join([str(p) for p in sec.source_pages]), "headline": sec.headline.content} for sec in book_data.content]
    # documents = [f"{sec.headline}\n{sec.content}" for sec in book_data.content]
    # ids = [sec.id for sec in book_data.content]
#
    # collection.add(
    #     documents=documents, # we embed for you, or bring your own
    #     metadatas=metadatas,       # [{"source": "notion"}, {"source": "google-docs"}], # filter on arbitrary metadata!
    #     ids=ids, # must be unique for each doc
    # )
    # results = collection.query(
    #     query_texts=["Wer ist der Patriarch von Al'Anfa?"],
    #     n_results=5,
    #     # where={"metadata_field": "is_equal_to_this"}, # optional filter
    #     # where_document={"$contains":"Patriarch"}  # optional filter
    # )
#
    # def query(txt: str):
    #     return collection.query(
    #     query_texts=[txt],
    #     n_results=3,
    #     # where={"metadata_field": "is_equal_to_this"}, # optional filter
    #     # where_document={"$contains":"Patriarch"}  # optional filter
    # )

    # breakpoint()