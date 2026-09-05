from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import ruamel.yaml


yaml_loader = ruamel.yaml.YAML(typ="safe")


with open(Path("data/R2 - results/results-NO_RAG-2025-11-03-graded-alternative.yaml")) as file:
    data_no_rag = yaml_loader.load(file)

with open(Path("data/R2 - results/results-NO_RAG_LOCAL-2025-12-02-graded-alternative.yaml")) as file:
    data_no_rag_local = yaml_loader.load(file)

with open(Path("data/R2 - results/results-RAG-2025-11-15-simple-chunks-german-graded-alternative.yaml")) as file:
    data_simple_rag_german = yaml_loader.load(file)

with open(Path("data/R2 - results/results-RAG-2025-11-19-simple-chunks-unconstrained-graded-alternative.yaml")) as file:
    data_simple_rag_unconstrained = yaml_loader.load(file)

with open(Path("data/R2 - results/results-RAG-2025-12-12-simple-chunks-english-reasoning-forced-graded-alternative.yaml")) as file:
    data_simple_rag_english = yaml_loader.load(file)

with open(Path("data/R2 - results/results-2025-10-09-german-reasoning-graded-alternative.yaml")) as file:
    data_semantic_rag_german = yaml_loader.load(file)

with open(Path("data/R2 - results/results-RAG-2025-12-01-english-reasoning-forced-graded-alternative.yaml")) as file:
    data_semantic_rag_english_forced = yaml_loader.load(file)

with open(Path("data/R2 - results/results-2025-10-15-english-reasoning-graded-alternative.yaml")) as file:
    data_semantic_rag_english = yaml_loader.load(file)

with open(Path("data/R2 - results/results-RAG-2025-11-25-french-reasoning-graded-alternative.yaml")) as file:
    data_semantic_rag_french = yaml_loader.load(file)

with open(Path("data/R2 - results/results-RAG-2025-11-22-no-reasoning-graded-alternative.yaml")) as file:
    data_semantic_rag_no_reasoning = yaml_loader.load(file)


grades_simple_german = Counter([r["grade"] for r in data_simple_rag_german["results"]])
grades_simple_unconstrained = Counter([r["grade"] for r in data_simple_rag_unconstrained["results"]])
grades_simple_english = Counter([r["grade"] for r in data_simple_rag_english["results"]])
grades_german = Counter([r["grade"] for r in data_semantic_rag_german["results"]])
grades_english = Counter([r["grade"] for r in data_semantic_rag_english["results"]])
grades_english_forced = Counter([r["grade"] for r in data_semantic_rag_english_forced["results"]])
grades_french = Counter([r["grade"] for r in data_semantic_rag_french["results"]])
grades_no_rag = Counter([r["grade"] for r in data_no_rag["results"]])
grades_no_rag_local = Counter([r["grade"] for r in data_no_rag_local["results"]])
grades_no_reasoning = Counter([r["grade"] for r in data_semantic_rag_no_reasoning["results"]])

grades = (1, 2, 3, 4, 5)

for res in [grades_simple_german, grades_simple_unconstrained, grades_simple_english, grades_german, grades_english, grades_english_forced, grades_french, grades_no_rag, grades_no_rag_local, grades_no_reasoning]:
    print(f"Name\t&\t", end="")
    print("\t&\t".join([str(res[grade]) for grade in grades] + [f"{(sum([key * val for key, val in res.items()]) / sum(res.values())):.3f}"]))

# grades = (0, 1, 2, 3, 4)
ratings = {
    # 'Simple RAG': [grades_simple[i] for i in grades],
    # 'Semantic RAG (german)': [grades_german[i] for i in grades],
    # 'Semantic RAG (english)': [grades_english[i] for i in grades],
    # 'Semantic RAG (english, forced)': [grades_english_forced[i] for i in grades],
    # 'Semantic RAG (french)': [grades_french[i] for i in grades],
    # 'Semantic RAG (no reasoning)': [grades_no_reasoning[i] for i in grades],
    'No RAG (english, large model)': [grades_no_rag[i] for i in grades],
    'No RAG (english, small model)': [grades_no_rag_local[i] for i in grades],
}


x = np.arange(len(grades))  # the label locations
width = 0.25  # the width of the bars
multiplier = 0

fig, ax = plt.subplots(layout='constrained')

for attribute, measurement in ratings.items():
    offset = width * multiplier
    rects = ax.bar(x + offset, measurement, width, label=attribute)
    ax.bar_label(rects, padding=3)
    multiplier += 1

# Add some text for labels, title and custom x-axis tick labels, etc.
ax.set_ylabel('Occurences')
ax.set_title('Rating comparison')
ax.set_xticks(x + width, grades)
ax.legend(loc='upper left', ncols=1)
# ax.set_ylim(0, 250)

plt.show()