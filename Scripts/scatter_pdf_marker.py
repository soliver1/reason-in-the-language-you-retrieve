import multiprocessing
import os
import shutil
from argparse import ArgumentParser
from pathlib import Path
import subprocess


import logging_utility
import logging

logging_utility.prepare_logging(verbose=True)
logger = logging.getLogger("scatter_pdf_marker")



parser = ArgumentParser(description="Takes a pdf file and converts it to one markdown file "
                                    "(+ some extra and an overly complex folder structure) per page.")
parser.add_argument("-i", "--input_file", help="pdf file to convert. If a directory is given, all pdf files will be converted.", type=Path, required=True)
# parser.add_argument("-w", "--workdir", help="(working) directory to place the pdf pages. Will be cleaned in the process.", default="workdir/single_page_pdfs", type=Path)
parser.add_argument("-o", "--output", help="output directory", type=Path, default="data/3 - validation_marker")
args = parser.parse_args()


# prepare empty workdir
# workdir = args.workdir / args.input_file.stem

def prepare_empty_dir(path: Path):
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(exist_ok=True, parents=True)

# split pdf in parts
# prepare_empty_dir(workdir)

# since I don't want to install a library to get the pdf page count, we just do it until we run into an error. Should be ok.
# pages = 0
# try:
#     while True:
#         logger.debug(f"Extracting page {pages}")
#         subprocess.run(["pdftk", args.input_file, "cat", str(pages), "output", f"{workdir/args.input_file.stem}-page-{pages}.pdf"], check=True)
#         pages += 1
# except subprocess.CalledProcessError:
#     logger.info(f"Split file into {pages} pages.")

# ok, marker seems not to need the scattered pdf, it can be told to parse just one page. Let's try this.

def scatter_pdf(input_file: Path):
    output = args.output / input_file.stem
    logger.info(f"Scattering '{input_file}' to '{output}'")
    prepare_empty_dir(output)
    page = 0
    try:
        while True:
            logger.debug(f"Extracting page {page} of book {input_file.stem}")
            # ToDo should this be page instead of page + 1?
            # subprocess.run(
            #     ["marker_single", input_file, output / str(page), "--start_page", str(page), "--max_pages", "1",
            #      "--langs", "de"], check=True)
            # ToDo redirect output to DEVNULL? (at least for multithreaded case, otherwise there is too much noise)
            subprocess.run(
                 ["marker_single", "--output_dir", output / str(page + 1), "--page_range", str(page), "--languages", "de", input_file], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            page += 1
    except subprocess.CalledProcessError:
        logger.info(f"Split book {input_file.stem} into {page} pages.")


args.input_file: Path
if args.input_file.is_file():
    scatter_pdf(args.input_file)
elif args.input_file.is_dir():
    # let's just always use multiprocessing
    with multiprocessing.Pool(processes=4) as pool:
        pool: multiprocessing.Pool
        for file in args.input_file.iterdir():
            if file.suffix == ".pdf":
                pool.apply_async(scatter_pdf, (file,))
        pool.close()
        pool.join()
    # processes = [multiprocessing.Process(target=scatter_pdf, args=(file,))
    #              for file in args.input_file.iterdir() if file.suffix == ".pdf"]
    # for p in processes:
    #     p.start()
    # for p in processes:
    #     p.join()

    # for file in args.input_file.iterdir():
    #     if file.suffix == ".pdf":
    #         scatter_pdf(file)
