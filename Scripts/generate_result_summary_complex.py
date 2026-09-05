from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import ruamel.yaml


yaml_loader = ruamel.yaml.YAML(typ="safe")


with open(Path("data/RX2 - result grading complex dataset/qa-evaluation-data-fabian.yaml")) as file:
    data_fabian = yaml_loader.load(file)

with open(Path("data/RX2 - result grading complex dataset/qa-evaluation-data-tim.yaml")) as file:
    data_tim = yaml_loader.load(file)

with open(Path("data/RX2 - result grading complex dataset/qa-evaluation-data-oliver.yaml")) as file:
    data_oliver = yaml_loader.load(file)


averages = {l: [] for l in "ABCDEF"}
exp = {"A": "results-RAG-2025-11-27-complex-french.yaml",
       "B": "results-RAG-2025-11-27-complex-unconstrained.yaml",
       "C": "results-RAG-2025-11-26-complex-no-reasoning.yaml",
       "D": "results-RAG-2025-11-27-complex-german.yaml",
       "E": "results-NO_RAG-2025-11-26-complex.yaml",
       "F": "results-RAG-2025-12-01-complex-english-forced.yaml"
       }


summed_ratings = {letter: [0, 0, 0, 0, 0] for letter in exp.keys()}
for reviewer, data in [("R_A", data_fabian), ("R_B", data_tim), ("R_C", data_oliver)]:
    print(reviewer)
    for letter in "ABCDEF":
        ratings = []
        for num in range(1, 6):
            count = len([1 for el in data if el[f"Rating {letter}"] == num])
            ratings.append(count)
            summed_ratings[letter][num - 1] += count
        summed_rating = sum(el[f"Rating {letter}"] for el in data)
        average_rating = summed_rating / len(data)
        # print(letter, summed_rating, f"{average_rating:.3f}", exp[letter])
        print(f"{exp[letter]}\t& {f'\t&\t'.join(f"{count}" for count in ratings)}\t&\t{average_rating:.3f}\t\\\\")
        averages[letter].append(average_rating)
    print("")
    print("------------------------------")
    print("")

print("Average:")
# for letter, avgs in averages.items():
#     for avg in avgs:
#         print(f"{avg:.3f}   &   ", end="")
#     print(f"{sum(avgs) / 3:.3f}", letter, exp[letter])
for letter, ratings in summed_ratings.items():
    print(f"{exp[letter]}\t& {f'\t&\t'.join(f"{count / 3:.2f}" for count in ratings)}\t&\t{sum(i*r for i, r in enumerate(ratings, start=1)) / sum(ratings):.3f}\t\\\\")
    # breakpoint()
