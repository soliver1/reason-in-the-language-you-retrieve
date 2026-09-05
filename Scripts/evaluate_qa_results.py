import argparse
import logging
import os
import random
import threading
import time
from concurrent.futures.thread import ThreadPoolExecutor
from pathlib import Path

from openai import OpenAI
import ruamel.yaml
from collections import Counter

import logging_utility
from information_container import BookData

logging.getLogger("openai._base_client").setLevel(logging.WARNING)
logger = logging.getLogger("QA-Result-Evaluation")


"""
Grades or compares LLM results using the LLM-as-a-Judge approach
"""

system_note = \
"""You are part of an automatic evaluation for a question answering system.
All questions concern the fictional world of Aventuria.
You will be given quadruplets of *background information*, *questions*, *gold answers* and *system answers*.
The background information is a piece of text from a lore book that includes information that was used to create the question and gold answer.
You shall use the background information in case the system answer includes more information not relevant in the gold answer, to determine if the additional information is correct or hallucinated. 
The gold answer is the correct answer to the question.
The system answer was generated using a RAG based QA system.

Your task is to grade the system answers with a rating from 0 to 4 with a higher rating being better.
The following overview shall help you to determine an appropriate rating:

0 - System answer is wrong or hallucinated and contradicting the ground truth answer.
1 - System answer does not answer the question and may be hallucinated, but does not contradict the ground truth answer either.
2 - System answer is partly correct, but some aspects are inaccurate or hallucinated.
3 - System answer is mostly correct, but missing some minor details.
4 - System answer is correct and includes all required details provided in the ground truth answer.

Your reply shall only consist of the rating number. Do not include any explanation, only reply with the appropriate grade for the system answer.
"""


system_note_alternative = \
"""You are part of an automatic evaluation for a question answering system.
All questions concern the fictional world of Aventuria.
You will be given quadruplets of *background information*, *questions*, *gold answers* and *system answers*.
The background information is a piece of text from a lore book that includes information that was used to create the question and gold answer.
You shall use the background information in case the system answer includes more information not relevant in the gold answer, to determine if the additional information is correct or hallucinated. 
The gold answer is the correct answer to the question.
The system answer was generated using a RAG based QA system.

Your task is to grade the system answers with a rating from 1 to 5 with a higher rating being better.
The following guidelines shall help you with the evaluation:

- A system answer contradicting the gold answer should get the lowest rating (1)
- A system answers that includes all relevant information to answer the question should get the highest rating (5)
- A system answer that does not include all necessary details given in the gold answer but is not completely wrong as well should get a rating between 2 and 4. 
- To evaluate a system answer that includes statements not included in the gold answer, you need to look into the background information.
  - If the statements are true and relevant to the question, this is ok/good.
  - If the statements are not true (hallucinations), this should generally lead to a lower rating.

Your reply shall only consist of the rating number. Do not include any explanation, only reply with the appropriate grade for the system answer.
"""


system_note_comparing = \
"""You are part of an automatic evaluation for a question answering system.
All questions concern the fictional world of Aventuria.
You will be given quintuplets of *background information*, *questions*, *gold answers* and two *system answers*.
The background information is a piece of text from a lore book that includes information that was used to create the question and gold answer.
You shall use the background information in case the system answers includes more information not relevant in the gold answer, to determine if the additional information is correct or hallucinated. 
The gold answer is the correct answer to the question.
The system answers were generated using a RAG based QA system in two different configurations.

Your task is to decide which system answer is better.
The following guidelines shall help you with the evaluation:

- MAIN: If one answer includes all details given in the system answer and the other does not, the first is better.
- MINOR: If one answer includes more (unnecessary) details, this is not important, as long as they are backed by the source data. But if the details are hallucinated, this makes the answer worse.
- MINOR: If one answer contains grammatical errors or wrong spelling, the other one is better.
- MINOR: If an answer mentions chunk ids, you cannot judge this since you do not know which id relates to which chunk. Just ignore them.

- If no answer is better then the other, since they state the same facts and none has any errors, you may also decide that both answers are equally good.

Your reply shall only consist of the number of the system answer that you deem better. If you come to the conclusion that both answers are equal, you may return the number 0. Do not include any explanation, only reply with the id number of the best answer (1 or 2, or 0 for no winner).
"""

system_note_comparing_german = \
"""
Du bist Teil einer automatischen Bewertung für ein Frage-Antwort-System.
Alle Fragen betreffen die fiktive Welt Aventuriens.
Dir werden Quintupel aus Hintergrundinformationen, Fragen, richtigen Antworten und zwei System-Antworten gegeben.
Die Hintergrundinformationen sind ein Textausschnitt aus einem Hintergrundbuch, der Informationen enthält, die zur Erstellung der Frage und der richtigen Antwort verwendet wurden.
Du musst die Hintergrundinformationen nutzen, falls eine System-Antwort zusätzliche Informationen enthält, die nicht in der richtigen Antwort enthalten sind, um zu bestimmen, ob diese zusätzlichen Informationen korrekt oder halluziniert sind.
Die richtige Antwort ist die korrekte Antwort auf die Frage.
Die System-Antworten wurden mit einem RAG-basierten QA-System in zwei verschiedenen Konfigurationen generiert.
Deine Aufgabe ist es, zu entscheiden, welche System-Antwort besser ist.
Die folgenden Richtlinien sollen dir bei der Bewertung helfen:   

- HAUPTKRITERIUM: Wenn eine Antwort alle Details der richtigen Antwort enthält und die andere nicht, ist erstere besser.  
- NEBENKRITERIUM: Wenn eine Antwort mehr (unnötige) Details enthält, ist dies nicht wichtig, solange sie durch die Quelldaten gestützt werden. Falls die Details aber halluziniert sind, ist die Antwort schlechter.  
- NEBENKRITERIUM: Wenn eine Antwort grammatikalische Fehler oder falsche Rechtschreibung enthält, ist die andere besser.  Dazu zählen zum Beispiel auch fehlerhafte Umlaute oder falsche Konjugationen. 
- NEBENKRITERIUM: Wenn eine Antwort Chunk-IDs erwähnt, kannst du dies nicht bewerten, da du nicht weißt, welcher ID welcher Chunk zugeordnet ist. Ignoriere sie einfach. Due Erwähnungen sind weder gut noch schlecht.

Wenn keine Antwort besser ist als die andere, da sie dieselben Fakten nennen und keine Fehler enthalten, kannst du auch entscheiden, dass beide Antworten gleich gut sind.
    
Du solltest vor deiner Antwort nachdenken und überlegen welche Antwort besser passt und warum.
Erläutere dabei warum du die Antwort für besser hälst und was dafür bzw. dagegen spricht sie zu wählen.  
Am Ende deiner Nachricht muss jedoch die Antwort in Form einer Zahl stehen. Füge kein Satzzeichen am Ende der Nachricht an. Deine Antwort muss auf die Zahl enden mit der du antworten möchtest.
Wenn du zu dem Schluss kommst, dass beide Antworten gleichwertig sind, gib die Zahl 0 als Antwort zurück. Ansonsten antworte nur mit der ID der besseren Antwort (1 oder 2, bzw. 0 für keinen Sieger).
"""


# ToDo next
#  try not specifying each grade level and only tell the LLM what are "positive" aspects and what are "negative" aspects.
#  also mention that misspelled words and wrong names are negative (I feel like those happen more often with english reasoning, but am not sure)


def grade_result(question: str, gold_answer: str, system_answer: str, chunk: str) -> tuple[str, int]:
    """Uses an LLM judge to grade a system answer to a question"""
    client = OpenAI(base_url="https://ki-chat.uni-mainz.de/api/", api_key=os.environ["JGU_API_KEY"])
    prompt = f"QUESTION: {question}\n\nGOLD ANSWER: {gold_answer}\n\nSYSTEM ANSWER: {system_answer}\n\nBACKGROUND INFORMATION: {chunk}"
    completion = client.chat.completions.create(
        model="Qwen3 235B Thinking",
        messages=[
            {"role": "system", "content": system_note_alternative},
            {"role": "user", "content": prompt},
        ],
        seed=42,
    )
    return completion.choices[0].message.reasoning_content, int(completion.choices[0].message.content)

# def compare_result_german(question: str, gold_answer: str, system_answer1: str, system_answer2, chunk: str) -> tuple[str, int]:
#     "Uses an LLM judge to compare two system answers to a question. Experiment: see if giving the task in german and not using a thinking model changes anything."
#     client = OpenAI(base_url="https://ki-chat.uni-mainz.de/api/", api_key=os.environ["JGU_API_KEY"])
#     prompt = f"BACKGROUND INFORMATION (chunk: {chunk}\n\nQUESTION: {question}\n\nGOLD ANSWER: {gold_answer}\n\nSYSTEM ANSWER 1: {system_answer1}\n\nSYSTEM ANSWER 2: {system_answer2}"
#     completion = client.chat.completions.create(
#         # model="Qwen3 235B Thinking",
#         model="Qwen3 235B VL",
#         messages=[
#             {"role": "system", "content": system_note_comparing_german},
#             {"role": "user", "content": prompt},
#         ],
#         seed=42,
#     )
#     try:
#         return completion.choices[0].message.content, int(completion.choices[0].message.content.split()[-1])
#     except:
#         breakpoint()

def compare_result(question: str, gold_answer: str, system_answer1: str, system_answer2, chunk: str) -> tuple[str, int]:
    "Uses an LLM judge to compare two system answers to a question"
    client = OpenAI(base_url="https://ki-chat.uni-mainz.de/api/", api_key=os.environ["JGU_API_KEY"])
    prompt = f"BACKGROUND INFORMATION (chunk: {chunk}\n\nQUESTION: {question}\n\nGOLD ANSWER: {gold_answer}\n\nSYSTEM ANSWER 1: {system_answer1}\n\nSYSTEM ANSWER 2: {system_answer2}"
    completion = client.chat.completions.create(
        model="Qwen3 235B Thinking",
        messages=[
            {"role": "system", "content": system_note_comparing},
            {"role": "user", "content": prompt},
        ],
        seed=42,
    )
    return completion.choices[0].message.reasoning_content, int(completion.choices[0].message.content)


def compare_chunk_answers(data_german: dict, data_english: dict, index: int):
    print(f"Thread: {threading.get_ident()} - Index: {index} - Chunk: {data_german['related_chunk']}")
    if index % 2 != 0:
        reasoning, winner = compare_result(data_german["question"], data_german["correct_answer"], data_german["system_answer"], data_english["system_answer"], book_data[data_german["related_chunk"]].text)
    else:
        reasoning, winner = compare_result(data_german["question"], data_german["correct_answer"], data_english["system_answer"], data_german["system_answer"], book_data[data_german["related_chunk"]].text)
    print("index: ", index, "winner: ", winner)
    winner = ((winner + index) % 2) if winner > 0 else winner - 1
    print(f"Evaluated chunk {data_german['related_chunk']} - {data_german["question"]}")
    print("Gold Answer:", data_german["correct_answer"], "\n")
    print("System Answer German:", data_german["system_answer"], "\n")
    print("System Answer English:", data_english["system_answer"], "\n")
    print(f"Reasoning: {reasoning}")
    print(f"\033[33mWinner: {["German", "English", "No Winner"][winner]}\033[0m")
    print("-------------------------------------------------------------------")
    return winner


def evaluate_chunk(chunk_data: dict):
    print(f"Thread: {threading.get_ident()} - Chunk: {chunk_data['related_chunk']}")
    reasoning, grade = grade_result(chunk_data["question"], chunk_data["correct_answer"], chunk_data["system_answer"], book_data[chunk_data["related_chunk"]].text)
    print(f"Evaluated chunk {chunk_data['related_chunk']} - {chunk_data["question"]}")
    print("Gold Answer:", chunk_data["correct_answer"])
    print("System Answer:", chunk_data["system_answer"])
    print(f"Reasoning: {reasoning}")
    print(f"\033[33mGrade: {grade}\033[0m")
    print("-------------------------------------------------------------------")
    chunk_data["grade_reasoning"] = reasoning
    chunk_data["grade"] = grade

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input-results", type=Path, default="data/R1 - results/results-NO_RAG-2025-11-03.yaml", help="Input file")
    parser.add_argument("-i2", "--input-results2", type=Path, help="Input file2")
    args = parser.parse_args()
    logging_utility.prepare_logging()
    yaml_loader = ruamel.yaml.YAML(typ="safe")
    # input_results = Path("data/R1 - results/results-NO_RAG-2025-11-03.yaml")

    book_data = BookData.load_from_file("data/5 - information_container/G01 - In den Dschungeln Meridianas.yaml")

    if args.input_results2:
        logger.info("Two input files given, will do a comparison based evaluation.")
        with open(args.input_results) as file:
            data_german = yaml_loader.load(file)
        with open(args.input_results2) as file:
            data_english = yaml_loader.load(file)
        if not data_german["config"]["force_german_reasoning"]:
            data_german, data_english = data_english, data_german
        assert (data_german["config"]["force_german_reasoning"] and not data_english["config"]["force_german_reasoning"]), "You need to specify one data with german reasoning and one without."
        results = []
        results_full = []

        with ThreadPoolExecutor(max_workers=1) as executor:
            for i in range(len(data_german["results"])):
                results.append(executor.submit(compare_chunk_answers, data_german["results"][i], data_english["results"][i], i))

        results = [res.result() for res in results]
        for i, res in enumerate(results):
            results_full.append({"german": data_german["results"][i], "english": data_english["results"][i], "winner": ["german", "english", "no winner"][res]})
        counter = Counter(results)

        yaml_writer = ruamel.yaml.YAML()
        out_dir = Path("data/R2 - results/")
        out_dir.mkdir(parents=True, exist_ok=True)

        with open(out_dir / f"{args.input_results.stem}-{args.input_results2.stem}-comparison.yaml", "w") as file:
            yaml_writer.dump(results_full, file)
        print(f"{counter = }")
        breakpoint()

    else:
        logger.info("One input file given, will use scoring for evaluation")
        with open(args.input_results) as file:
            data = yaml_loader.load(file)

        results = []
        with ThreadPoolExecutor(max_workers=2) as executor:
            for res in data["results"]:
                results.append(executor.submit(evaluate_chunk, res))
                # print(reasoning_grade.result())

        # check for exceptions
        try:
            for res in results:
                res.result()
        except Exception as e:
            print(e)
            breakpoint()
            print(e)

        yaml_writer = ruamel.yaml.YAML()
        out_dir = Path("data/R2 - results/")
        out_dir.mkdir(parents=True, exist_ok=True)

        with open(out_dir / f"{args.input_results.stem}-graded-alternative.yaml", "w") as file:
            yaml_writer.dump(data, file)
