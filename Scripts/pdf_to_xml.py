import os
import shutil
from argparse import ArgumentParser
from collections import defaultdict
from pathlib import Path
import subprocess
from subprocess import CalledProcessError

import ruamel.yaml

import logging_utility
import logging

logging_utility.prepare_logging(verbose=True)
logger = logging.getLogger("pdf_to_xml")



parser = ArgumentParser()
parser.add_argument("-i", "--input_directory", help="directory containing pdf files to convert", type=Path, required=True)
parser.add_argument("--pdfalto", "--binary", help="path to pdfalto binary", default="~/Downloads/pdfalto/pdfalto")
parser.add_argument("-o", "--output", help="output directory", type=Path, default="data/1 - xml_alto")
parser.add_argument("--validation_output", help="output directory for validation data", type=Path, default="data/1 - validation_pdfalto")
args = parser.parse_args()

args.output.mkdir(exist_ok=True)
args.validation_output.mkdir(exist_ok=True)

# ToDo these numbers are not yet correct (may relate to book page, not pdf page)
offset = {
    "G00 - Geographia Aventurica": 1,
    "G01 - In den Dschungeln Meridianas": 1,
    "G05 - Land der Ersten Sonne": 0,
    "G08 - Herz des Reiches": 1,
    "G12 - Reich des Horas": 1,
    "G13 - Im Bann des Nordlichts": 1,
    "G14 - Schattenlande": 1,           # ToDo not checked
    "G15 - Die Reisende Kaiserin": 2
}

yaml = ruamel.yaml.YAML()
yaml.indent(mapping=4, sequence=4, offset=4)


def remove_page_numbers(validation_book: dict[str, str]):
    for page, content in validation_book.items():
        if content[0].isnumeric() and int(content[0]) in range(page - 5, page + 5):
            content.pop(0)
        elif content[-1].isnumeric() and int(content[-1]) in range(page - 5, page + 5):
            content.pop()
        else:
            logger.debug(f"No page number found for page {page}")
    return validation_book  # not necessary since content is passed by reference, but I think it is clearer this way

valid_files = []
for file in os.listdir(args.input_directory):
    file_path = args.input_directory / file
    if file_path.suffix == ".pdf":
        try:
            logger.info(f"Converting {file_path}")
            # , "-f", "106", "-l", "107"
            # when called with "-verbose", the missing tokens are included in the terminal output. So pdfalto does find
            # them. They are sorted out from the result though...but why?
            valid_files.append(args.output / f"{file_path.stem}.xml")
            pro = subprocess.run([os.path.expanduser(args.pdfalto), "-noImage", "-verbose", file_path, args.output / f"{file_path.stem}.xml"], check=True, stdout=subprocess.PIPE)     # , text=True, encoding="ISO-8859-2"
            lines = [line for line in pro.stdout.decode("utf-8", errors="replace").split("\n")]
            page_found = False
            validation_book = {}
            page_num = offset[file_path.stem]
            for line in lines:
                if line.startswith("token :"):
                    token = line.removeprefix("token : ")
                    if not page_found:
                        # usually relevant pages start with their page numbers. Sometimes, the page number is at the
                        # end instead though
                        page_num += 1
                        validation_book[page_num] = []
                        validation_book[page_num].append(token)
                        if token.isnumeric():
                            ...
                            # page_num = int(token) + 1  # assumption: pdf page number is book page number + 1
                            # logger.info(f"Found digit! {token}")
                            # # ToDo: it may make sense to handle wrapped words here in the same way as in the xml-to-yaml
                            # #  script
                            # validation_book[page_num].append(token)
                        else:
                            ...
                            # logger.warning(f"First token on page is not numeric, instead it is {token}")
                        page_found = True
                    # not sure if this is still relevant actually...
                    elif page_num > offset[file_path.stem]:
                        # ToDo maybe ignore last token on page if it is a number --> easier to remove them later, probably
                        # do not save text at book start, when there is no page number known
                        validation_book[page_num].append(token)
                if not line.startswith("token : "):
                    page_found = False
            # remove page numbers
            content = remove_page_numbers(validation_book)
            # note: it seems like sometimes words are randomly split, e.g.
            #     - Einﬂ
            #     - ussbereichen
            #  or
            #     - häuﬁ
            #     - g
            with open(args.validation_output / f"{file_path.stem}.yaml", "w") as out_file:
                yaml.dump(validation_book, out_file)

        except CalledProcessError as e:
            logger.error(e)

# remove extra files (metadata)
for file in Path(args.output).iterdir():
    if file not in valid_files and "metadata" in file.name:
        os.remove(file)