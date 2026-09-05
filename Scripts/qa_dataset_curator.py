#!/usr/bin/env python3

import argparse
import os
from pathlib import Path

import numpy as np
import ruamel.yaml

from information_container import BookData
from utility import effect_string, TextEffects, await_user_input, open_pdf_in_viewer, input_with_default
import readline
import logging

logger = logging.getLogger("QADatasetCurator")

type QAPair = dict[str, str | bool | int]


class QACurator:

    def __init__(self, book_data: BookData, save_path: Path):
        self.book_data: BookData = book_data
        self.save_path = save_path

    def curate_qa_data(self, qa_dataset: dict[str, dict[str, list[QAPair]]], min_rating: int, max_rating: int):
        os.system("clear")

        # ToDo maybe add option to edit answer directly.
        def qa_is_ignored(qa_data: QAPair, chunk: str) -> bool:
            # as inefficient as it gets... but seems fast enough still
            same_chunk_questions = [qa_pair for chunk_, qa_pairs in qa_dataset["questions"].items() for question_index, qa_pair in enumerate(qa_pairs, start=1) if chunk_ == chunk]
            argmax = np.argmax([q["rating"] for q in same_chunk_questions])
            return qa_data == same_chunk_questions[argmax]
        # data = [(chunk, qa_data, question_index) for chunk, qa_pairs in qa_dataset["questions"].items() for question_index, qa_data in enumerate(qa_pairs, start=1) if min_rating <= qa_data['rating'] <= max_rating]
        # filtered_data = [(chunk, qa_data, question_index) for chunk, qa_pairs in qa_dataset["questions"].items() for question_index, qa_data in enumerate(qa_pairs, start=1) if not (min_rating <= qa_data['rating'] <= max_rating)]
        data = [(chunk, qa_data, question_index) for chunk, qa_pairs in qa_dataset["questions"].items() for question_index, qa_data in enumerate(qa_pairs, start=1) if qa_is_ignored(qa_data, chunk)]
        filtered_data = [(chunk, qa_data, question_index) for chunk, qa_pairs in qa_dataset["questions"].items() for question_index, qa_data in enumerate(qa_pairs, start=1) if not qa_is_ignored(qa_data, chunk)]

        # for chunk, qa_pairs in qa_dataset.items():
        #     for question_index, qa_data in enumerate(qa_pairs, start=1):
        i = qa_dataset.get("curation_current_index", 0)
        if i > 0:
            print(f"Loaded saved progress, you will start right where you left off (may not be correct if you changed the filtering options)!")
        while i < len(data):
            chunk, qa_data, question_index = data[i]

            self.render_user_interface(chunk, data, i, qa_data, question_index)

            inp = await_user_input(["1", "2", "x", "y", "p", "n", "\n", "c", "s", "o", "q", "a"], True)
            message = None
            match inp:
                case "1" | "↓":
                    message = f"Question {question_index} for chunk {chunk} {effect_string('rejected', TextEffects.YELLOW)}!"
                    qa_data["user_rating"] = False
                case "2" | "↑":
                    message = f"Question {question_index} for chunk {chunk} {effect_string('accepted', TextEffects.GREEN)}!"
                    qa_data["user_rating"] = True
                case "x":
                    message = f"Remaining questions for chunk {chunk} {effect_string('deleted', TextEffects.RED)}!"
                    while chunk == data[i][0]:
                        data.pop(i)
                    i -= 1
                case "y":
                    message = f"Question {question_index} for chunk {chunk} {effect_string('deleted', TextEffects.RED)}!"
                    data.pop(i)
                    i -= 1
                case "c":
                    qa_data["user_rating"] = False
                    qa_data["user_critique"] = input(effect_string("\nCritique: ", TextEffects.YELLOW))
                case "q":
                    qa_data["user_rating"] = True
                    print(effect_string("Question:", TextEffects.YELLOW))
                    qa_data["question"] = input_with_default("", qa_data["question"])
                case "a":
                    qa_data["user_rating"] = True
                    print(effect_string("Answer:", TextEffects.YELLOW))
                    qa_data["answer"] = input_with_default("", qa_data["answer"])
                case "s":
                    yaml_writer = ruamel.yaml.YAML()
                    self.save_path.parent.mkdir(exist_ok=True, parents=True)
                    chunks = sorted({chunk for chunk, *_ in data + filtered_data})
                    questions = {chunk: [] for chunk in chunks}
                    for da in data + filtered_data:
                        chunk, qa_data, _ = da
                        questions[chunk].append(qa_data)
                    with open(self.save_path, "w") as file:
                        yaml_writer.dump(qa_dataset | {"questions": questions, "curation_current_index": i}, file)
                    message = self.saved_message()
                    i -= 1
                case "o":
                    message = "Opened book"
                    open_pdf_in_viewer(self.book_data.title, self.book_data[chunk].source_pages[0], find=self.book_data[chunk].title.strip())
                    i -= 1
                case "p" | "←":
                    i -= 2
                    message = "Returned to previous question."
                case "n" | "\n" | "→":
                    message = f"Question {question_index} for Chunk {chunk} skipped!"
                case _:
                    message = f"Invalid input received!"
                    i -= 1
            os.system("clear")
            if message:
                print(message)
            i += 1

    def saved_message(self):
        terminal_width, terminal_height = os.get_terminal_size()
        lines = ["=" * terminal_width, " " * (terminal_width // 2 - 7) + "Saved progress", "="*terminal_width]
        return effect_string("\n".join(lines), TextEffects.GREEN)

    def render_user_interface(self, chunk, data, i, qa_data, question_index):
        terminal_width, terminal_height = os.get_terminal_size()
        # for a correct calculation, we would need to correctly calculate the interface dimension.
        # This is possible, but out of scope for now.
        max_chunk_display_length = (terminal_height - 37) * terminal_width

        print(effect_string(f"\nQA-Pair {i:<4}/{len(data)}: Chunk {chunk} Question {question_index}", TextEffects.BOLD))
        print("\n")
        print("=" * terminal_width)
        print("")
        print(effect_string("Question: ", TextEffects.BOLD) + qa_data['question'])
        print("")
        print("-" * terminal_width)
        print("")
        print(effect_string("Answer: ", TextEffects.BOLD) + qa_data['answer'])
        print("")
        print("=" * terminal_width)
        if qa_data['rating'] == 1:
            print(effect_string(f"\nSystem rating: {qa_data['rating']}", TextEffects.RED) + f" - {qa_data['reason']}")
        elif qa_data['rating'] == 5:
            print(effect_string(f"\nSystem rating: {qa_data['rating']}", TextEffects.GREEN) + f" - {qa_data['reason']}")
        else:
            print(f"\nSystem rating: {qa_data['rating']} - {qa_data['reason']}")
        if "user_rating" in qa_data:
            print(effect_string(f"User rating ('accepted'): {qa_data['user_rating']}", TextEffects.YELLOW))
        if "user_critique" in qa_data:
            print(effect_string(f"User critique: {qa_data['user_critique']}", TextEffects.YELLOW))
        print("")
        print(f"How would you rate this QA-Pair?")
        print("↓ 1 - Bad, should be revisited by the QA-Creation model")
        print("↑ 2 - Great, can stay as it is!")
        print("← P - Go back to previous chunk")
        print("→ N - Skip to next chunk")
        print("  X - remove this chunk and related questions completely")
        print("  Y - remove this QA-Pair completely (but not the whole chunk)")
        print("  C - Add own critique")
        print("  Q - Manually edit question")
        print("  A - Manually edit answer")
        print("  S - Save current progress")
        print("  O - Open book page for more context")
        print("\n\n")
        print(f"System context: {qa_data['context']}")
        print(" --> ".join([a.headline.content for a in self.book_data[chunk].ancestors]))
        print(f"Chunk content: {self.book_data[chunk].text[:max_chunk_display_length]}" + (
            effect_string("[...]", TextEffects.YELLOW) if len(
                self.book_data[chunk].text) > max_chunk_display_length else ""))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input-file", type=Path,
                        default="data/QA1 - Initial QA dataset/G01 - In den Dschungeln Meridianas.yaml",
                        help="Input file")
    parser.add_argument("-o", "--output-file", type=Path,
                        default="data/QA2 - Curated QA dataset/G01 - In den Dschungeln Meridianas.yaml",
                        help="Output/save file path. If same as input file path, input file will be overwritten.")
    parser.add_argument("--min-rating", type=int, default=1, help="Only show QA-Pairs with at least this system rating.")
    parser.add_argument("--max-rating", type=int, default=5, help="Only show QA-Pairs with not more than this system rating.")
    args = parser.parse_args()
    yaml_loader = ruamel.yaml.YAML(typ="safe")
    with open(args.input_file) as file:
        qa_data = yaml_loader.load(file)
    book_data = BookData.load_from_file(qa_data["source_path"])
    qa_curator = QACurator(book_data, args.output_file)
    try:
        qa_curator.curate_qa_data(qa_data, args.min_rating, args.max_rating)
    except KeyboardInterrupt as e:
        logger.info("Keyboard interrupt received, terminating.")


if __name__ == '__main__':
    main()
