import random
from pathlib import Path

import ruamel.yaml

def generate_comparison_documents():
    yaml_loader = ruamel.yaml.YAML(typ="safe")

    with open(Path("data/R2 - results/results-NO_RAG-2025-11-03-graded-alternative.yaml")) as file:
        data_no_rag = yaml_loader.load(file)

    with open(Path("data/R2 - results/results-NO_RAG_LOCAL-2025-12-02-graded-alternative.yaml")) as file:
        data_no_rag_local = yaml_loader.load(file)

    with open(Path("data/R2 - results/results-RAG-2025-11-15-simple-chunks-german-graded-alternative.yaml")) as file:
        data_simple_rag_german = yaml_loader.load(file)

    with open(
            Path("data/R2 - results/results-RAG-2025-11-19-simple-chunks-unconstrained-graded-alternative.yaml")) as file:
        data_simple_rag_unconstrained = yaml_loader.load(file)

    with open(
            Path("data/R2 - results/results-RAG-2025-12-12-simple-chunks-english-reasoning-forced-graded-alternative.yaml")) as file:
        data_simple_rag_english = yaml_loader.load(file)

    with open(Path("data/R2 - results/results-2025-10-09-german-reasoning-graded-alternative.yaml")) as file:
        data_semantic_rag_german = yaml_loader.load(file)

    with open(
            Path("data/R2 - results/results-RAG-2025-12-01-english-reasoning-forced-graded-alternative.yaml")) as file:
        data_semantic_rag_english_forced = yaml_loader.load(file)

    with open(Path("data/R2 - results/results-2025-10-15-english-reasoning-graded-alternative.yaml")) as file:
        data_semantic_rag_english = yaml_loader.load(file)

    with open(Path("data/R2 - results/results-RAG-2025-11-25-french-reasoning-graded-alternative.yaml")) as file:
        data_semantic_rag_french = yaml_loader.load(file)

    with open(Path("data/R2 - results/results-RAG-2025-11-22-no-reasoning-graded-alternative.yaml")) as file:
        data_semantic_rag_no_reasoning = yaml_loader.load(file)

    data_tuples = [("data_simple_rag_german", data_simple_rag_german["results"]),
                   ("data_simple_rag_unconstrained", data_simple_rag_unconstrained["results"]),
                   ("data_simple_rag_english", data_simple_rag_english["results"]),
                   ("data_semantic_rag_german", data_semantic_rag_german["results"]),
                   ("data_semantic_rag_english", data_semantic_rag_english["results"]),
                   ("data_semantic_rag_english_forced", data_semantic_rag_english_forced["results"]),
                   ("data_semantic_rag_french", data_semantic_rag_french["results"]),
                   ("data_no_rag", data_no_rag["results"]),
                   ("data_no_rag_local", data_no_rag_local["results"]),
                   ("data_semantic_rag_no_reasoning", data_semantic_rag_no_reasoning["results"])]

    yaml = ruamel.yaml.YAML()
    for name, data in data_tuples:
        with open(f"data/R3 - results comparison human vs LLM/{name}.yaml", "w") as file:
            d = random.choices(data, k=5)
            yaml.dump(d, file)


# generate_comparison_documents()

doc_names = ["data_simple_rag_german", "data_simple_rag_unconstrained", "data_simple_rag_english", "data_semantic_rag_german", "data_semantic_rag_english", "data_semantic_rag_english_forced", "data_semantic_rag_french", "data_no_rag", "data_no_rag_local", "data_semantic_rag_no_reasoning",]

ratings = [[0 for i in range(5)] for j in range(5)]
for doc_name in doc_names:
    with open(f"data/R3 - results comparison human vs LLM/{doc_name}.yaml", "r") as file:
        data = ruamel.yaml.YAML(typ="safe").load(file)
    for qa_pair in data:
        ratings[qa_pair["grade"] - 1][qa_pair["user_grade"] - 1] += 1

breakpoint()


