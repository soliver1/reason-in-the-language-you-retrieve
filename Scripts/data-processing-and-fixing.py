#!/usr/bin/env python3
import argparse
import copy
import difflib
import logging
import os
import sys
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
import re
import readline

import ruamel.yaml

from pathlib import Path

from numpy.ma.core import argmin
from pynput import keyboard
from pynput.keyboard import Key
from rapidfuzz.distance.metrics_cpp_avx2 import levenshtein_distance

import logging_utility
import utility
from logging_utility import TextEffects
from utility import TextType, TextBlock, open_pdf_in_viewer, simplify_string, punctuation, load_word_count_dictionary, \
    sanitize_for_yaml, flush_input_buffer

logging_utility.prepare_logging(verbose=True)
logger = logging.getLogger("data-fixing")


def get_validation_data_marker(page: int, file_stem: str, base_path: str | Path = "data/3 - marker_validation_data") -> list[TextBlock]:
    # get second source
    # f"{page - 1}"?
    with open(Path(base_path) / file_stem / f"{page}" / file_stem /f"{file_stem}.md") as file:
        validation_page = file.read()
    validation_page = preprocess_marker_pdf(validation_page) + "\n"  # should end with \n for easier processing
    validation_sections = []
    validation_headlines = []
    validation_data = []
    headline_end = 0
    while True:
        headline_index = validation_page[headline_end:].find("#") + headline_end
        if headline_index == headline_end - 1:
            headline_index = -1
        section = validation_page[headline_end:headline_index].strip().replace("\n\n", "\n")
        if section:
            validation_sections.append(section)
            validation_data.append(TextBlock(TextType.SECTION, section))
        if headline_index == -1:
            break
        headline_end = validation_page[headline_index:].find("\n") + headline_index
        headline = validation_page[headline_index:headline_end]
        # new marker version makes headlines bold for some reason
        headline = headline.replace("**", "")
        # check double headline
        headline = _check_double_headline(headline)
        validation_headlines.append(headline)
        validation_data.append(TextBlock(TextType.HEADLINE, headline))

    # won't need validation_sections and validation_headlines I think, can probably remove them
    return validation_data


def preprocess_marker_pdf(content: str):
    image_ref = fr"\s*\!\[.*\]\(.*\.[pP]ng\)\s*"
    # res = re.finditer(pattern, content)
    return re.sub(image_ref, "\n", content)


def _check_double_headline(headline):
    stripped = headline.strip("# ")
    mid = len(stripped) // 2
    if stripped[mid:].strip() == stripped[:mid].strip():
        logger.debug(f"Cleaning headline: '{headline}' ---> '{headline[:-mid].strip()}'")
        headline = headline[:-mid].strip()
    return headline

def correct_page_headlines(test_page: list[str], validation_data: list[TextBlock], page_num: int, file_stem: str, pdf_base_path ="./data/0 - pdf"):
    base_headlines = [el for el in test_page if el.startswith("#")]
    headlines = [simplify_string(hl) for hl in base_headlines]
    headlines_validation = [simplify_string(hl.content) for hl in validation_data if
                            hl.type == TextType.HEADLINE]
    headlines_val_only = set(headlines_validation) - set(headlines)
    headlines_base_only = set(headlines) - set(headlines_validation)

    # restore original headlines
    headlines_val_only = [hl.content for hl in validation_data if simplify_string(hl.content) in headlines_val_only]
    headlines_base_only = [hl for hl in base_headlines if simplify_string(hl) in headlines_base_only]
    ret = None
    if headlines_val_only:
        if not headlines_base_only:
            while not ret:
                pdf_process = open_pdf_in_viewer(file_stem, page_num, pdf_base_path,
                                                 find=headlines_val_only[0].strip("# "))
                logger.debug(f"Base healdines on this page: {base_headlines}")
                selection = input(f"The following missing headlines are detected for page {page_num}: '{", ".join(headlines_val_only)}'.\nWould you like to change the level? (input options: number, nothing, X (to ignore these headlines)) ")
                pdf_process.terminate()
                match selection:
                    case num if num.isdigit() and len(num) == 1:
                        ret = headlines_val_only
                        for i, hl in enumerate(ret):
                            ret[i] = f"{'#' * int(num)}{hl.strip('#')}"
                    case "":        # empty input: use heading as it is
                        ret = headlines_val_only
                    case "X" | "x":
                        return None
                    case _:
                        ...
        else:
            while not ret:
                pdf_process = open_pdf_in_viewer(file_stem, page_num, pdf_base_path, find=headlines_val_only[0].strip("# "))
                logger.debug(f"Base headlines on this page: {base_headlines}")
                # possible inputs (ToDo transfer to some README):
                # 1, 2 -- use this headline
                # 1X, 2X (where X is a digit) -- use headline(s) 1/2, but replace the headline levels with level X
                # 1U, 2U -- use headlines 1/2, but only unique ones, remove duplicates
                # hl1, hl2, hl3 -- manually pass headlines as string, comma separated
                selection = input(f"Which headline(s) is/are correct?\n"
                                  f"1. {"; ".join(headlines_base_only)}\n2. {"; ".join(headlines_val_only)}\n")
                pdf_process.terminate()
                match selection:
                    case "1":
                        return None
                    case "2":
                        ret = headlines_val_only
                    case num if num.isdigit():
                        # first number is index, second number is headline level
                        if len(num) == 2 and num[0] in "12":
                            ret = copy.copy([headlines_base_only, headlines_val_only][int(num[0]) - 1])
                            for i, hl in enumerate(ret):
                                ret[i] = f"{'#' * int(num[1])}{hl.strip('#')}"
                        else:
                            logger.error(f"Number {num} is not valid for headline selection!")
                    case "1u" | "1U" | "2u" | "2U":
                        if selection[0] == "1":
                            ret = list(set(headlines_base_only))
                        if selection[0] == "2":
                            ret = list(set(headlines_val_only))
                    case _:
                        ret = [hl.strip() for hl in selection.split(";")]
        logger.debug(f"Corrected headline(s) for page {page_num}: {ret}!")
        return headlines_base_only, ret     # headlines_base_only headlines shall be removed/replaced!
    return

def fix_text_block(txt1, txt2, matches: list[difflib.Match], word_counts: Counter, page_num: int) -> str:
    result_colored = txt1
    result_clean = txt1
    added = 0
    # print("Matches: ", matches)
    for i in range(len(matches) - 1):
        a, b, size = matches[i]
        a2, b2, size2 = matches[i + 1]
        # print(f"'{txt1[a + size:a2]}' vs. '{txt2[b + size:b2]}'")
        # anything relevant?
        if simplify_string(txt2[b + size:b2]):
            # logger.debug(f"'{txt1[a + size:a2]}' vs. '{txt2[b + size:b2]}'")
            result_colored = result_colored[:a + size + added] + f"\033[{TextEffects.YELLOW}m"+ txt2[b + size:b2] + "\033[0m" + txt1[a2:]
            result_clean = result_clean[:a + size + len(result_clean) - len(txt1)] + txt2[b + size:b2] + txt1[a2:]
            len_effects = len(f"\033[{TextEffects.YELLOW}m") + len("\033[0m")
            added += (b2 - b) - (a2 - a) + len_effects
    if result_colored != txt1:
        # logger.debug("Text after fixing:\n" + result_colored)
        # logger.debug("-------------------------------")
        result_clean = result_clean.replace("- ", "-")
        # the [:-1] ensures that each word may *end* with a "-"
        for dw in [w for w in result_clean.split() if "-" in w[:-1]]:
            # fixme does not yet handle words with multiple "-" correctly (e.g. Phileasson-Ex-pedition)
            word = dw.strip(punctuation)
            if word_counts[word.replace("-", "")] > word_counts[word]:
                logger.debug(f"Corrected word: {word} ---> {word.replace("-", "")}")
                result_clean = result_clean.replace(word,  word.replace("-", ""))
    diff = (len(result_clean) - len(txt1)) / len(txt1)
    # large diffs may be a sign of an error. Ask user if they should be used (?)
    if diff > 0.2:
        # ToDo this heuristic may not be optimal, I suspect there could still be some duplicate texts...should maybe come up with something better.
        logger.warning(f"Large difference detected when cleaning text block on page {page_num}: {len(result_clean)} vs. {len(txt1)} ({diff * 100 :.1f}%)")
        logging.getLogger("simple").log(logging.WARNING, "Text after fixing:\n" + result_colored)
        while True:
            answer = input("Does this result look correct? (Y/N)")
            match answer:
                case "Y" | "y":
                    logger.info("Accepted result")
                    return result_clean
                case "N" | "n":
                    logger.info("Kept original text block")
                    return txt1
            logger.error("Answer format incorrect.")
    return result_clean


class NoValidSafeError(Exception):
    ...


class TextOrderFixer:

    def __init__(self, file_stem: str, save_dir: Path = Path("data/4 - fixed_order")):
        self.logger = logging.getLogger(f"TextOrderFixer({file_stem})")
        self.yaml_reader = ruamel.yaml.YAML(typ="safe")
        self.file_stem = file_stem
        self.save_dir = save_dir
        save_dir.mkdir(exist_ok=True, parents=True)

    def fix_text_order(self, file_stem: str, start_new: bool, pdf_base_path: str = "./data/0 - pdf"):
        # ToDo decide automatically (or using cmd-line arg) if save-file should be loaded or new version should be created
        #  Could also ask user of course...
        if not start_new:
            try:
                # load saved file
                page, data = self.load_saved_file(file_stem, self.yaml_reader)
                self.logger.info(f"Loaded save file, processed until page {page}")
            except Exception as e:
                logger.warning(f"Failed to load save file: {e}.")
                start_new = True
                breakpoint()
        if start_new:
            data = self.load_new_data(file_stem, self.yaml_reader)
            page = 0
            self.logger.info("Loaded new data")

        # save_path = Path(f"data/fixed_order/{file_stem}.yaml")
        yaml_writer = ruamel.yaml.YAML()
        os.system("clear")
        # for page in data.keys():
        # page = data.get("current_page", 0)  # start at saved page
        max_page = max([key for key in data.keys() if isinstance(key, int)])
        # loaded = False
        while page <= max_page:
            backwards = False
            # current_data is special field, no page data can be found here
            if page not in data:  # or page == "current_data"
                page += 1
                continue
            content = copy.deepcopy(data[page] + (data[page + 1] if page + 1 < len(data) else []))
            # self.logger.info(f"Current Page layout: \n{"\n".join(content)}")
            curr_index = 0
            rerun_search = True
            page_sorted = not bool(data[page])  # do not process empty pages
            next_page_start = 0
            info_log = None
            # enable_save = True
            while not page_sorted:
                try:
                    next_page_start = len(content) - next(
                        (i for i, el in enumerate(reversed(content)) if el.origin_page == page))
                except:
                    breakpoint()
                    page_sorted = True
                    continue
                if rerun_search:
                    pdf_process = open_pdf_in_viewer(file_stem, page, pdf_base_path, find=" ".join(
                        content[curr_index].content.strip("# ").replace("*", "").split(" ")[:4]))
                    rerun_search = False
                next_index = min(curr_index + 1, len(content) - 1)
                prev_index = max(curr_index - 1, 0)
                self.logger.info(
                    f"Sorting page content for page {page} / {len(data)} of {file_stem} ({page / len(data) * 100:.1f}% done!)")

                for i, block in enumerate(content):
                    if i == next_page_start:
                        print("")
                        print("======================= Next page content =====================================")
                        print("")
                    print(f"{f"\033[{TextEffects.YELLOW}m*\033[0m" if i == curr_index else " "} {block}")

                print("""\n\n\nOptions:
←/→             move text block
↑/↓             move selection
h               move next headline to this point
b               move next non-headline text block to this point
x               delete first word of current text block
y               delete last word of current text block
d               delete complete text block
e               extract headline (first n words from current text block)
i               add additional headline
Enter           next page
p               previous page
u               undo changes to this page by reloading page content
s               save
esc             exit
""")


                with keyboard.Events() as events:
                    event_found = False
                    # ToDo maybe add "h" for help...
                    while not event_found:
                        event = events.get()  # --1.0-- do not use timeout for now...
                        # event: keyboard.Events.Press
                        if isinstance(event, keyboard.Events.Press):
                            event_found = True
                            match event.key:
                                case Key.up:
                                    rerun_search = not (curr_index == prev_index)
                                    curr_index = prev_index
                                case Key.down:
                                    rerun_search = not (curr_index == next_index)
                                    curr_index = next_index
                                case Key.right:
                                    content[curr_index], content[next_index] = content[next_index], content[curr_index]
                                    curr_index = next_index
                                case Key.left:
                                    content[curr_index], content[prev_index] = content[prev_index], content[curr_index]
                                    curr_index = prev_index
                                case Key.enter:
                                    page_sorted = True
                                case Key.esc:
                                    flush_input_buffer()
                                    sys.exit(42)
                                case _:
                                    try:
                                        match event.key.char:
                                            case "h":
                                                # if no headline is found, this raises StopIteration and nothing is done
                                                next_headline = next(i for i, el in enumerate(content)
                                                                     if el.content.startswith("#") and i > curr_index)
                                                content.insert(curr_index, content.pop(next_headline))
                                                rerun_search = True
                                                # curr_index = next_index
                                            case "u":
                                                # undo changes to the current page, by reloading page content
                                                content = copy.deepcopy(
                                                    data[page] + (data[page + 1] if page + 1 < len(data) else []))
                                            case "b":
                                                next_textblock = next(i for i, el in enumerate(content) if
                                                                      not el.content.startswith("#") and i > curr_index)
                                                content.insert(curr_index, content.pop(next_textblock))
                                                rerun_search = True
                                                # curr_index = next_index
                                            case "x":
                                                # special case: delete first word of text block
                                                content[curr_index].content = " ".join(
                                                    content[curr_index].content.split(" ")[1:])
                                            case "y":
                                                # special case: delete last word of text block
                                                content[curr_index].content = " ".join(
                                                    content[curr_index].content.split(" ")[:-1])
                                            case "d":
                                                # special case: delete complete line/block
                                                content.pop(curr_index)
                                                # content[curr_index].content = " ".join(content[curr_index].content.split(" ")[1:])
                                            case "p":
                                                # previous page
                                                backwards = True
                                                page_sorted = True
                                            case "i":
                                                flush_input_buffer()
                                                # if a headline is missing, now is the last chance to manually add it
                                                headline = input("\rFound additional headline? ").strip()
                                                if headline.startswith("#"):
                                                    content.insert(min(curr_index, next_page_start),
                                                                   TextBlock(TextType.HEADLINE, headline, page))
                                                    # next_page_start += 1
                                                    info_log = f"Added headline: {headline}"
                                                else:
                                                    info_log = f"Discarded headline input."
                                            case "e":
                                                try:
                                                    if content[curr_index].content.startswith("#"):
                                                        break
                                                    # extract headline
                                                    flush_input_buffer()
                                                    inp = input(
                                                        "Please specify headline format [number of words, level; no separator. number of words may also be the text 'bold' (or 'b'), then all bold text from the beginning is used]")
                                                    num_words, level = inp[:-1], int(inp[-1])
                                                    if num_words in ["bold", "b"]:
                                                        end_bold = content[curr_index].content[2:].find("**")
                                                        if end_bold:
                                                            headline = f"{level * '#'} {content[curr_index].content[:end_bold + 4].replace("**", "").strip()}"
                                                            content[curr_index].content = content[curr_index].content[end_bold + 4:].strip()
                                                    else:
                                                        num_words = int(num_words)
                                                        block = content[curr_index].content.split(" ")
                                                        headline = f"{level * '#'} {" ".join(block[:num_words])}".replace("**", "")
                                                        content[curr_index].content = " ".join(block[num_words:])
                                                    # content.insert(min(curr_index, next_page_start),
                                                    content.insert(curr_index, TextBlock(TextType.HEADLINE, headline,
                                                                                         content[
                                                                                             curr_index].origin_page))
                                                    # next_page_start += 1
                                                    info_log = f"Added headline: {headline}"
                                                except Exception as e:
                                                    info_log = f"Failed to extract headline (check if input format was correct), {e}"
                                            case "1" | "2" | "3" | "4" | "5":
                                                # extract bold text as headline
                                                level = int(event.key.char)
                                                end_bold = content[curr_index].content[2:].find("**")
                                                if end_bold:
                                                    headline = f"{level * '#'} {content[curr_index].content[:end_bold + 4].replace("**", "").strip()}"
                                                    content[curr_index].content = content[curr_index].content[end_bold + 4:].strip()
                                                    content.insert(curr_index, TextBlock(TextType.HEADLINE, headline,
                                                                                         content[curr_index].origin_page))
                                                    info_log = f"Added headline: {headline}"
                                                    curr_index = next_index
                                                else:
                                                    info_log = f"Failed to extract headline"
                                            case "s":
                                                try:
                                                    # data["current_page"] = page
                                                    # data[page]["content"] = [block.content for block in content]
                                                    data[page] = copy.deepcopy(content[:next_page_start])
                                                    data[page + 1] = copy.deepcopy(content[next_page_start:])
                                                    save_data = {"current_page": page, "data": data}
                                                    # data[page]["content"] = [block.content for block in content[:next_page_start]]
                                                    # data[page + 1]["content"] = [block.content for block in content[next_page_start:]]
                                                    with open(self.save_dir / f"{file_stem}.yaml", "w") as file:
                                                        yaml_writer.dump(sanitize_for_yaml(save_data), file)
                                                    info_log = f"Saved progress to {self.save_dir / f"{file_stem}.yaml"}."
                                                    # create backup
                                                    with open(self.backup_path, "w") as file:
                                                        yaml_writer.dump(sanitize_for_yaml(save_data), file)
                                                    Path("data_backup/fixed_text")
                                                except Exception as e:
                                                    print(e)
                                                    breakpoint()
                                            case _:
                                                event_found = False
                                    except:
                                        event_found = False
                os.system("clear")
                if info_log:
                    self.logger.info(info_log)
                    info_log = None
            # save modified order to data
            data[page] = content[:next_page_start]
            data[page + 1] = content[next_page_start:]
            page += -1 if backwards else 1
            # breakpoint()
        save_data = {"current_page": page, "data": data}
        with open(self.save_dir / f"{file_stem}.yaml", "w") as file:
            yaml_writer.dump(sanitize_for_yaml(save_data), file)

    @property
    def backup_path(self):
        Path("data_backup/fixed_order").mkdir(exist_ok=True)
        return Path(f"data_backup/fixed_order/{self.file_stem}-{datetime.now().strftime('%Y-%m-%d_%H-%M')}.yaml")

    def load_new_data(self, file_stem, yaml_reader):
        with open(f"data/4 - fixed_textblock_contents/{file_stem}.yaml") as yaml_file:
            data = yaml_reader.load(yaml_file)
        data = {page: [TextBlock(TextType.HEADLINE if block.startswith("#") else TextType.SECTION, block, page)
                       for block in di["content"]] for page, di in
                data.items() if isinstance(page, int)}
        return data

    def load_saved_file(self, file_stem, yaml_reader) -> tuple[int, dict]:
        with open(self.save_dir / f"{file_stem}.yaml") as yaml_file:
            data = yaml_reader.load(yaml_file)
        start_page = data.get("current_page", 0)
        data = {key: [TextBlock(**el) for el in val] for key, val in data["data"].items()}
        return start_page, data


def main():
    # just uses hardcoded data paths for now
    arg_parser = argparse.ArgumentParser(description="1. fixes missing headlines\n2. tries to fix missing words\n3. let's user fix text block order", formatter_class=argparse.RawTextHelpFormatter)
    arg_parser.add_argument("-i", "--input-file-stem", required=True, help="File to process. Only the file stem needs to be given, if a full path is given only the stem will be used.")
    arg_parser.add_argument("--start-new", action="store_true", help="begin processing from base version, ignore/overwrite saves if there are any")
    args = arg_parser.parse_args()
    file_stem = Path(args.input_file_stem).stem

    yaml_reader = ruamel.yaml.YAML(typ="safe")


    logger.info(f"Fixing {file_stem}")
    with open(f"data/2 - yaml_base/{file_stem}.yaml") as yaml_file:
        data = yaml_reader.load(yaml_file)
    with open(Path("data/1 - validation_pdfalto") / f"{file_stem}.yaml") as file:
        validation_data_pdfalto = yaml_reader.load(file)
    word_counts = load_word_count_dictionary()
    # also a good page to check: 116
    # page = 123

    fixed_headlines_file = f"data/4 - fixed_headlines/{file_stem}.yaml"
    if not Path(fixed_headlines_file).is_file() or args.start_new:
        fix_headlines(data, file_stem, Path(fixed_headlines_file))

    with open(fixed_headlines_file) as yaml_file:
        data = yaml_reader.load(yaml_file)

    fixed_textblocks_file = Path(f"data/4 - fixed_textblock_contents/{file_stem}.yaml")
    if not Path(fixed_textblocks_file).is_file() or args.start_new:
        fix_textblock_contents(data, validation_data_pdfalto, word_counts, fixed_textblocks_file)

        # ToDo note: for G1, for pages ~130 - 160 (maybe longer), the first ~sentence on each page was flawed
        # I did fix most of it manually by now (for G1).
        # => maybe I could find a way to fix this for the other books if it happens there as well
        # fix_textblock_contents(data, validation_data_pdfalto, word_counts, Path(f"data/4 - fixed_textblock_contents/{file_stem}.yaml"))
        utility.flush_input_buffer()
        input(f"The textblock contents have been fixed now, the result is written to '{fixed_textblocks_file}'.\n"
              f"If you want to perform some manual editing, you may do it now. Once you are ready, press enter to continue.")
    text_order_fixer = TextOrderFixer(file_stem)
    text_order_fixer.fix_text_order(file_stem, args.start_new)
    


def fix_textblock_contents(data, validation_data_pdfalto, word_counts, save_path: Path):
    yaml_writer = ruamel.yaml.YAML()
    # validation_data_marker = get_validation_data_marker(page, file_stem=file_stem)
    for page, page_data in data.items():
        logger.info(f"Fixing text block contents for page {page}")
        # page = 123
        test_page = page_data["content"]
        test_page: list

        base_headlines = [el for el in test_page if el.startswith("#")]
        base_textblocks = [el for el in test_page if not el.startswith("#")]

        # ---------------------------------

        remove_dot_symbol = "❌"
        block_ends = [b.split()[-1] for b in base_textblocks + base_headlines if not b.split()[-1].endswith(".")]

        validation_text_pdfalto = " ".join(validation_data_pdfalto.get(page, []))
        for block_end_word in set(block_ends):
            validation_text_pdfalto = validation_text_pdfalto.replace(block_end_word,
                                                                      block_end_word + f"{remove_dot_symbol}.")
        validation_text_pdfalto = validation_text_pdfalto.split(".")

        if len(validation_text_pdfalto) > 1000:
            logger.warning(f"To many validation splits found on page {page}. This page will be skipped.")
            continue
        options_pdfalto = [(".".join(validation_text_pdfalto[i:j]) + ".").replace(f"{remove_dot_symbol}.", "")
                           for i in range(len(validation_text_pdfalto)) for j in range(i, len(validation_text_pdfalto))]

        for i, block in enumerate(test_page):
            if not block.startswith("#"):
                test_page[i] = fix_textblock(block, page, word_counts, options_pdfalto)

    with open(save_path, "w") as file:
        yaml_writer.dump(data, file)

def fix_headlines(data, file_stem, save_path: Path):
    yaml_writer = ruamel.yaml.YAML()  # safe yaml parser does not have nice format
    try:
        for page, page_data in data.items():
            logger.info(f"Fixing headlines for page {page}")
            test_page = page_data["content"]
            test_page: list
            try:
                validation_data_marker = get_validation_data_marker(page, file_stem)
            except OSError:
                logger.warning(f"Failed to load marker data to fix headlines on page {page}, will skip it.")
                continue
            missing_headlines = correct_page_headlines(test_page, validation_data_marker, page, file_stem)
            if missing_headlines:
                headlines_to_replace, new_headlines = missing_headlines
                # ToDo maybe it would be nice to sort headlines that replace another one at the same position
                #  ...but this would also be relatively complex, I think for now I will leave it as it is
                for hl in headlines_to_replace:
                    test_page.remove(hl)
                test_page += new_headlines
            # ToDo save intermediate result (might be useful, e.g. in case of crash later)
            with open(save_path, "w") as file:
                yaml_writer.dump(data, file)
    except Exception as e:
        logger.error(f"Error when trying to fix headlines: {e}")
        breakpoint()
        sys.exit(1)
    input(f"Saved fixed doc version with fixed headlines to {save_path}. If you want to manually change something, you have the chance now. Once you are done and want the tool to continue, just press enter.")


def fix_textblock(block: str, page: int, word_counts: Counter, val_block_options: list[str]):
    # fixme (kind of) works for small changes, but gets almost every larger diff wrong. Might want to look at this again
    #  if I find the time...
    distances = [levenshtein_distance(block, option) for option in val_block_options]
    closest_match = val_block_options[argmin(distances)]
    # ToDo if block starts with words that are missing in closest_match, I could use
    #  SequenceMatcher(None, closest_match, block) instead => maybe I need to try both and check?
    seq_matcher1 = SequenceMatcher(None, block, closest_match)
    matches1 = seq_matcher1.get_matching_blocks()
    return fix_text_block(block, closest_match, matches1, word_counts, page)


main()

# breakpoint()
# textblocks[4] += textblocks.pop(5)
"""
def ollama_api():
    for headline in headlines:
        request = (f'Hier sind einige Textabschnitte: \n{"\n".join(f"{i}:\n {block}" for i, block in enumerate(textblocks, start=1))}\n\n'
                   f'Hier ist eine Überschrift: "{headline}"\n'
                   f'**Deine Aufgabe ist es, die Überschrift dem richtigen Textabschnitt zuzuordnen. Bitte gib mir nur die Nummer zurück die zu dem Textabschnitt gehört, zu welchem die Überschrift am besten passt. Deine Antwort soll nur aus einer einzelnen Zahl bestehen. \n')
        print(request)
        response = ollama.generate(model='gemma2-testing', prompt=request)
        # response = ollama.chat(model='llama3.1:8b-instruct-fp16', messages=[
        #   {
        #     'role': 'user',
        #     'content': request,
        #   },
        # ])
        pprint(response["response"])
        breakpoint()

# ollama_api()

def oobabooga_api():
    url = "http://127.0.0.1:5000/v1/completions"

    headers = {
        "Content-Type": "application/json"
    }
    for headline in headlines:
        request = (
            f'Hier sind einige Textabschnitte: \n{"\n".join(f"{i}:\n {block}" for i, block in enumerate(textblocks, start=1))}\n\n'
            f'Hier ist eine Überschrift: "{headline}"\n'
            f'**Deine Aufgabe ist es, die Überschrift dem richtigen Textabschnitt zuzuordnen. Bitte gib mir nur die Nummer zurück die zu dem Textabschnitt gehört, zu welchem die Überschrift am besten passt. Deine Antwort soll nur aus einer einzelnen Zahl bestehen. \n')
        print(request)
        # messages = [{"role": "user", "content": request}]
        # data = {
        #     "mode": "instruct",
        #     "instruction_template": "Llama-V3",
        #     "messages": messages
        # }
        data = {"prompt": request}

        response = requests.post(url, headers=headers, json=data, verify=False)
        res = response.json()
        pprint(res)

        breakpoint()
# ollama testing
"""