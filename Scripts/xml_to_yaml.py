import argparse
import json
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import ruamel.yaml
import ollama
import logging

from pprint import pprint

from fsspec.utils import other_paths

import logging_utility
from utility import punctuation, load_word_count_dictionary, evaluate_wrapped_word_via_llm
from xml_fonts import FontConverter, Book, Font, DummyFontConverter, DefaultFont, Headline, DebugFontConverter

logging_utility.prepare_logging(verbose=True)
logger = logging.getLogger("XML-to-YAML")

logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)



# ToDo There are still plenty of errors in the text, e.g. missing words and other issues. I should try to improve the
#  situation continuously from time to time.

def chilren(tag):
    for child in tag:
        print(child.tag, child.attrib)

@dataclass
class TextBlockBox:
    hpos: float
    vpos: float
    width: float
    height: float
    h_mid: float = field(init=False)

    def __post_init__(self):
        self.h_mid = self.hpos + self.width / 2

    def __lt__(self, other: "TextBlockBox"):
        if self.h_mid < other.h_mid:
            return True
        if self.h_mid == other.h_mid:
            return self.vpos < other.vpos
        return False


class ALTOHandler:
    # fixme WIP

    def __init__(self):
        self.ns = {'alto': 'http://www.loc.gov/standards/alto/ns-v3#'}
        self.reset_data()
        self.font_converter: FontConverter = None

    def _read_xml(self, path: str | Path):
        tree = ET.parse(path)
        root = tree.getroot()
        return root

    def xml_to_dict(self, xml_path: str | Path, dictionary: Counter):
        root = self._read_xml(xml_path)
        description = root[0]
        styles = root[1]
        layout = root[2]
        book = Book[Path(xml_path).stem.strip().split()[0]]
        try:
            self.font_converter = FontConverter(book, styles)
        except:
            logger.error(f"Failed to get font converter for book: {book}")
            return 
        # self.font_converter = DebugFontConverter(styles)
        # dictionary = self.create_dictionary(layout)
        logger.info(f"Processing {xml_path.name}.")
        return self._process_document(layout, dictionary)

    def create_dictionary(self, xml_path: str | Path) -> Counter:
        root = self._read_xml(xml_path)
        layout = root[2]
        self.font_converter = DummyFontConverter()
        dict_data = self._process_document(layout)
        # dictionary_counter = collections.defaultdict(int)
        dictionary_counter = Counter()
        words = [word for page in dict_data.values() for block in page["content"] for word in block.split()]
        for word in words:
            dictionary_counter[word] += 1
        return dictionary_counter

    def _process_document(self, layout, dictionary: Counter=None):
        # ToDo huge ugly function, should refactor when I have time
        self.reset_data()

        # if not dictionary:
        #     logger.info("No dictionary given, will process document in dictionary-generation-mode")
        font = DefaultFont()
        for page in layout:
            page: ET.Element
            page_id = int(page.get("ID").lstrip("Page"))
            self.content[page_id] = {"content": []}
            self.bounding_boxes[page_id] = []
            for text_block in page.findall(".//alto:TextBlock", self.ns) or []:
                # ToDo wenn Block mit "-" endet, muss noch das nächste Wort angefügt werden. Dazu muss ich aber sicher sein,
                #  welcher Block als nächstes kommt, d.h. das kann ich erst später machen.
                block = ""
                # if isinstance(font, Headline):
                #     font = DefaultFont()    # headlines can never span over multiple blocks
                for j, line in enumerate(text_block.findall(".//alto:TextLine", self.ns)):
                    for i, word in enumerate(line.findall(".//alto:String", self.ns)):
                        # if type(self.font_converter[word.get("STYLEREFS")]) != type(font)
                        #     or isinstance(font, Headline) and font.level != self.font_converter[word.get("STYLEREFS")].level:
                        # headlines can never span over multiple blocks
                        if self.font_converter[word.get("STYLEREFS")] != font or (isinstance(font, Headline) and j == i == 0):
                            if block:
                                block = block.removesuffix(" ") + font.after() + " "
                            else:
                                # start of block (maybe even page), add end to last block
                                self.append_to_last_block(font.after(), page_id)
                            font = self.font_converter[word.get("STYLEREFS")]
                            block += font.before()
                        if i == 0:
                            if dictionary:
                                if block.endswith("- "):
                                    last_word = block.split()[-1]
                                    split = f"{last_word}{word.get("CONTENT")}"
                                    combined = f"{last_word.removesuffix("-")}{word.get("CONTENT")}"
                                    split_count = dictionary[split.strip(punctuation)]
                                    combined_count = dictionary[combined.strip(punctuation)]
                                    space = 30
                                    if split_count > combined_count:
                                        # logger.debug(f"Page: {page_id} {split.ljust(space)} {combined.ljust(space)} {split.ljust(space)}")
                                        block = block.removesuffix(" ")
                                        self.statistics["wrapped_words_split_by_dict"] += 1
                                    elif combined_count > split_count:
                                        # logger.debug(f"Page: {page_id} {split.ljust(space)} {combined.ljust(space)} {combined.ljust(space)}")
                                        self.statistics["wrapped_words_combined_by_dict"] += 1
                                        block = block.removesuffix("- ")
                                    else:
                                        block = block.removesuffix("- ")
                                        # fixme enable LLM again later
                                        if True:
                                            res = evaluate_wrapped_word_via_llm(split, combined)
                                            logger.info(
                                                f"Page: {page_id} {split.ljust(space)} {combined.ljust(space)} {res.ljust(space)}")
                                            if res == split:
                                                self.statistics["wrapped_words_split_by_llm"] += 1
                                                block = block.removesuffix(" ")
                                            else:
                                                self.statistics["wrapped_words_combined_by_llm"] += 1
                                                block = block.removesuffix("- ")
                            else:
                                # do not include wrapped words in dictionary
                                if block.endswith("- "):
                                    block = block.rsplit(maxsplit=1)[0] + " "
                                    continue
                        if dictionary:
                            if not font.ignore():
                                block += f'{word.get("CONTENT")} '
                            else:
                                ...
                                # logger.debug(f"Ignored word: {word.get("CONTENT")}")
                        else:
                            block += f'{word.get("CONTENT").strip(punctuation)} '
                if block:
                    # ignore TextBlocks with only one String (== page number)
                    if not (block.strip().isdigit() and int(block) == int(page_id) - 1):
                        # self.merge_text_blocks(block, page_id)
                        self.content[page_id]["content"].append(block)
                        self.bounding_boxes[page_id].append(
                            TextBlockBox(float(text_block.get("HPOS")), float(text_block.get("VPOS")),
                                               float(text_block.get("WIDTH")), float(text_block.get("HEIGHT"))))

        # sort content
        for page in self.content.keys():
            blocks = list(zip(self.content[page]["content"], self.bounding_boxes[page]))
            blocks: list[tuple[str, TextBlockBox]]
            large_headings = [b for b in blocks if (b[0].strip().startswith("## ") or b[0].startswith("# "))]
            large_headings = sorted(large_headings, key=lambda x:x[1].vpos)
            other = [b for b in blocks if b not in large_headings]
            # unify horizontal positions. There is probably a smart academic way, maybe using k-means clustering or
            # something. I will just keep it simple for now....
            max_dist = 50       # maximum horizontal distance between two text blocks in the same column. Magic number guess.
            for block in other:
                col = block[1].h_mid
                for block2 in other:
                    if abs(block2[1].h_mid - col) < max_dist:
                        block2[1].h_mid = col

            ordered_blocks = []
            for h in large_headings:
                sec_blocks = [b for b in other if b[1].vpos < h[1].vpos]
                ordered_blocks += sorted(sec_blocks, key=lambda x: x[1])
                ordered_blocks.append(h)
                other = [b for b in other if b not in ordered_blocks]
            ordered_blocks += sorted(other, key=lambda x: x[1])
            self.content[page]["content"] = [text for text, bounding_box in ordered_blocks]
        return self.content

    def append_to_last_block(self, appendix, page_id):
        for page in range(page_id, 0, -1):
            if self.content[page]["content"]:
                self.content[page]["content"][-1] = self.content[page]["content"][-1].removesuffix(" ") + appendix + " "
                return
        if appendix:
            logger.warning(f"Failed to append '{appendix}' before page {page_id} (no text blocks found)")


    def reset_data(self):
        # reset file content and statistics at start of processing, so ALTOHandler could in theory be reused
        self.content = {}
        self.bounding_boxes = {}
        self.statistics = defaultdict(int)

    # def convert_text_block(self, text_block, page_id, dictionary=None):
    #
    #     return block

    def detect_duplicate_headline(self, block, font, page_id, word) -> bool:
        if font != word.get("STYLEREFS"):
            if not word.get("STYLEREFS") in self.font_to_header:
                print(word.get("STYLEREFS"), block)
                breakpoint()
            if "#" in self.font_to_header[font] and "#" in self.font_to_header[word.get("STYLEREFS")]:
                if block.split()[1] == word.get("CONTENT"):
                    # example: '# Die Geschichte des Südens Die Geschichte des Südens '
                    # logger.debug(f"Detected same word different style issue on page {page_id}: {word.get('CONTENT')}")
                    return True
        return False

    def merge_text_blocks(self, block, page_id):
        # NOT USED
        # is this block a new one or is it connected to the previous one?
        # ToDo handle blocks spanning over page margins
        if self.content[page_id]["content"]:
            prev_block = self.content[page_id]["content"][-1]
            if False and not (prev_block.startswith("#") or block.startswith("#")):
                request = (
                    f'Hier sind zwei Textabschnitte: \n\n 1. {prev_block} \n\n 2. {block}'
                    f'\n\n\n'
                    f'**Beide kommen aus dem selben Buch, eventuell aber aus unterschiedlichen Unterkapiteln mit unterschiedlichen Überschriften. '
                    f'Bewerte die Wahrscheinlichkeit, dass diese beiden Abschnitte direkt hintereinander stehen, ohne irgendetwas dazwischen, und Teil eines größeren Textes sind, der ein einziges Thema behandelt. Eine 1 bedeutet dabei "Diese Abschnitte gehören definitiv nicht zusammen", eine 10 bedeutet "diese Abschnitte gehören definitiv zusammen".'
                    f'Deine Antwort soll nur aus einer Zahl bestehen.** \n')
                # Falls du der Meinung bist, dass sie zusammen gehören, schreibe "zusammen". Falls du der Meinung sind dass es verschiedene Abschnitte sind, schreibe "verschieden".  Wenn du nicht sicher bist ob die Abschnitte zusammengehören, schreibe "verschieden". Deine Antwort soll nur aus einem Wort bestehen.\n
                if page_id > 15:
                    print(request)
                    response = ollama.generate(model='gemma2-testing', prompt=request)
                    print(response["response"])
                    breakpoint()


# fonts --> heading mappings could maybe be evaluated from the styles description, for now I will just take them as they are
# simple idea: bold fonts may be headlines, others not
# oh, another thing: bold (and italic and so on) words inside text are not treated specially yet, should be 2 - yaml_base
# to markdown emphasis later

# content = {}

def create_word_count_dictionary(data_dir: Path = Path("data/1 - xml_alto"), save_file: Path = Path("word_counts.json")):
    alto_handler = ALTOHandler()
    counter = Counter()
    for file in Path(data_dir).iterdir():
        counter += alto_handler.create_dictionary(file)
        logger.info("10 most common words:")
        logger.info(counter.most_common(10))
    with open(save_file, "w") as file:
        json.dump(counter, file, indent=4, ensure_ascii=False)
    return counter


def main():
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument("--recreate-wordcounts", action="store_true",
                            help="recreate the wordcount list, by parsing all documents given and creating the dictionary first")
    arg_parser.add_argument("-wc", "--wordcount-path", help="Path to wordcount file", default="word_counts.json")
    arg_parser.add_argument("-i", "--input-dir", help="Directory containing input xml/alto files", type=Path,
                            default="data/1 - xml_alto")
    arg_parser.add_argument("-o", "--output-dir", help="Output directory path", type=Path, default="data/2 - yaml_base")
    args = arg_parser.parse_args()
    alto_handler = ALTOHandler()
    if args.recreate_wordcounts:
        counter = create_word_count_dictionary(args.input_dir, args.wordcount_path)
    else:
        counter = load_word_count_dictionary(args.wordcount_path)
    for file in Path(args.input_dir).iterdir():
        content = alto_handler.xml_to_dict(file, counter)
        if not content:
            continue
        pprint(alto_handler.statistics)

        yaml = ruamel.yaml.YAML()
        logger.info("Writing yaml file")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        with open(args.output_dir / f"{file.stem}.yaml", "w") as outfile:
            yaml.dump(content, outfile)
    # content = alto_handler.xml_to_dict("data/G01 - In den Dschungeln Meridianas.xml", counter)
    # sys.exit(42)
    # yaml = ruamel.yaml.YAML()
    # logger.info("Writing yaml file")
    # with open("data/2 - yaml_base/G1 - In den Dschungeln Meridianas.yaml", "w") as outfile:
    #     yaml.dump(content, outfile)

if __name__ == '__main__':
    main()

# old font to header notes
#         self.font_to_header = {
#         "font0": "# ",
#         "font1": "### ",
#         "font2": "",
#         "font3": "",
#         "font4": "",
#         "font5": "",
#         "font6": "",
#         "font7": "## ",  # section headline
#         "font8": "# ",  # chapter headline
#         "font9": "",  # font 9 only used for page numbers, maybe I could just suppress them with this as well?
#         "font10": "",  # normal font
#         "font11": "",
#         # bold font, normal size        # ToDo maybe (small) headline, but may also occur in normal text. Maybe I will need to check for the complete line to be in this font to be sure...uff
#         "font12": "",  # italic font, normal size
#         "font13": "### ",  # subsection headline
#         "font14": "# ",  # chapter headline (again, same headline appears multiple times)
#         "font15": "# ",  # chapter headline (again, same headline appears multiple times)
#         "font16": "",  # some special stuff (•)
#         "font17": "#### ",  # subsubsection headline
#         "font18": "",  # bold large special font for image descriptions...can probably be ignored for now (?)
#         "font19": "",  # bold font, normal size
#         "font21": "",  # italic font, normal size
#         "font20": "",  # normal font (ok, sans serif, but apart from that its normal), used for summary boxes
#         "font22": "",  # bold large special font for image descriptions...can probably be ignored for now (?)
#         "font23": "",  # bold font, normal size, sans serif
#         "font24": "",  # normal size, sans serif
#         "font25": "",  # bold font, probably usually for image descriptions
#         "font26": "",  # italic font, normalsize - Image subscript/description. Remove? (example: page 73)
#         "font27": "",  # special ("*)") in footnote)
#         "font28": "",  # bold font, used for numbers in enumerations (1., 2., ...)
#         "font29": "",  # some special stuff (•), less bold and more grey than font 16
#         "font30": "",  # Index of words    (TODO could I use this for RAG?)
#         "font31": "",  # bold font, normal size, used in appendix
#         "font32": "",  # smallcaps font, indicating liturgie (should be marked somehow)
#         "font33": "",  # back cover font 0
#         "font34": "",  # back cover font 1
#         "font35": "",  # back cover font 1.5 (large)
#         "font36": "",  # back cover font 2
#         "font37": "",  # back cover font 3
#         "font38": "",
#         # back cover font 4 (special large first letter) - if I need this, a space after this should be removed / not inserted!
#         "font39": "",  # back cover font 4.5 (large)
#         "font40": "",  # back cover font 5
#         "font41": "",  # back cover font 5 (small)
#         "font42": "",  # back cover font 5.5
#         "font43": "",  # back cover font 5 pdf number
#         "font44": "",  # back cover font 6 (small)
#         "font45": "",  # back cover font 7 ISBN
#         "font46": "",  # back cover font 8 (small)
#         "font47": "",  # back cover font 9 (small)
#         "font48": "",  # back cover font 10 (bold, weblink)
#         "font49": "",  # back cover font 11
#         "font50": "",  # back cover font 12
#         "font51": "",  # back cover font 13 ISBN
#         "font52": "",  # back cover font 14
#         "font53": "",  # back cover font 15
#         "font54": "",  # back cover font 16 (special large first letter)
#         "font56": "",  # back cover font 17
#         "font57": "",  # back cover font 18
#     }