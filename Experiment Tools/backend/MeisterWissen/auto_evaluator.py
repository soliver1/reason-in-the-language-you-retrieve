import dataclasses
import enum
import logging
import os
import queue
import datetime
import sys
from pathlib import Path

import ruamel.yaml
import torch

from MeisterWissen.agents import Supervisor
from MeisterWissen.rag_model import RAGModel
from MeisterWissen.utility import convert_time_string

logger = logging.getLogger(__name__)

from transformers import set_seed


def set_reproducible_seed(seed: int = 42):
    os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"
    set_seed(seed)  # Hugging Face / transformers
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
    torch.use_deterministic_algorithms(True, warn_only=True)

class ExperimentType(enum.Enum):
    NO_RAG = enum.auto()
    RAG = enum.auto()


def str_to_experiment_type(param: str) -> ExperimentType:
    try:
        return ExperimentType[param]
    except KeyError:
        logger.error(f"Invalid experiment type: {param}. Please choose from: {[val.name for val in ExperimentType]}")
        sys.exit(1)

class DatasetEvaluator:

    def __init__(self, evaluation_type: ExperimentType):
        self.rag_model = None if evaluation_type == ExperimentType.NO_RAG else RAGModel()
        self.supervisor_agent = Supervisor(self.rag_model, queue.Queue(), log_level=logging.DEBUG)  # self.logger.debug("done")
        self.start_time = None
        self.total_time = datetime.timedelta()
        self.max_time = datetime.timedelta()
        self.min_time = datetime.timedelta()
        self.evaluation_type: ExperimentType = evaluation_type

    def evaluate(self, dataset: list[tuple[str, dict]], checkpoint_results: list | None = None, start_index: int = 0):
        set_reproducible_seed(42)
        self.start_time = datetime.datetime.now()
        print("")
        logger.info("===================== Starting Evaluation =====================")
        results = self.evaluate_dataset(dataset, checkpoint_results, start_index)
        self.save_result(results)

    def evaluate_dataset(self, dataset: list[tuple[str, dict]], checkpoint_results: list | None = None, start_index: int = 0):
        results = checkpoint_results or []
        for i, (chunk, qa_pair) in enumerate(dataset, start=1):
            if i < start_index:
                continue
            try:
                results.append(self.evaluate_qa_pair(qa_pair, chunk, i, len(dataset)))
            except KeyboardInterrupt as ki:
                if input("Do you want to save the current progress? [y/N]").lower() == "y":
                    self.save_result(results, i + 1)
                    logger.info(f"Saved results for the first {i-1} questions.")
                sys.exit(42)

            if i % 50 == 0:
                self.save_result(results, i + 1)
        return results

    def evaluate_qa_pair(self, qa_pair: dict, chunk: str, current_index: int, num_questions: int):
        logger.info(f"Question {current_index}/{num_questions}: {qa_pair["question"]}")
        logger.info(f"Correct answer: {qa_pair["answer"]}")
        start = datetime.datetime.now()
        if self.evaluation_type == ExperimentType.NO_RAG:
            inner_monologue, answer = self.supervisor_agent.simple_query(qa_pair["question"])
        else:
            inner_monologue, answer = self.supervisor_agent.ask_query(qa_pair["question"])
        time_needed = (datetime.datetime.now() - start)
        self.max_time = max(time_needed, self.max_time)
        self.min_time = min(time_needed, self.min_time)
        self.total_time += time_needed
        estimate_end_time = (self.total_time / current_index) * (num_questions - current_index)
        estimate_end_time -= datetime.timedelta(microseconds=estimate_end_time.microseconds)  # ignore microseconds
        logger.info(f"Time needed: {time_needed.seconds} seconds. Estimated time remaining: {estimate_end_time} "
                    f"(until {datetime.datetime.now() + estimate_end_time})")
        self.supervisor_agent.current_iteration = 0
        if len(inner_monologue) > 80:
            logger.info(f"System Thoughts: {inner_monologue[:30]} [...] {inner_monologue[-50:]}")
        else:
            logger.info(f"System Thoughts: {inner_monologue}")
        logger.info(f"System Answer: {answer}")
        return {"question": qa_pair["question"], "correct_answer": qa_pair["answer"],
                "inner_monologue": inner_monologue, "system_answer": answer, "related_chunk": chunk}

    def save_result(self, results, current_progress: int | None = None):
        yaml = ruamel.yaml.YAML()
        date = datetime.datetime.today().strftime("%Y-%m-%d")
        logger.info("Saving results to disk.")
        with open(f"backend/MeisterWissen/eval_results/results-{self.evaluation_type.name}-{date}.yaml", "w") as file:
            yaml.dump({"experiment_date": date, "processing_time": f"{self.total_time}", "current_progress": current_progress,
                       "maximum_time_per_question": f"{self.max_time}", "minimum_time_per_question": f"{self.min_time}",
                       "config": dataclasses.asdict(self.supervisor_agent.config), "results": results}, file)

    def start_evaluation(self, checkpoint: Path=None):
        yaml = ruamel.yaml.YAML(typ='safe')
        with open("backend/MeisterWissen/QA2 - Curated QA dataset/G01 - In den Dschungeln Meridianas.yaml") as file:
            qa_data = yaml.load(file)
        # current length: 498 QA-Pairs
        if checkpoint:
            with open(checkpoint) as file:
                checkpoint_data = yaml.load(file)
            checkpoint_results = checkpoint_data["results"]
            start_index = checkpoint_data["current_progress"]
            self.total_time = convert_time_string(checkpoint_data["processing_time"])
            self.max_time = convert_time_string(checkpoint_data["maximum_time_per_question"])
            self.min_time = convert_time_string(checkpoint_data["minimum_time_per_question"])
        else:
            checkpoint_results = None
            start_index = 0
        curated_qa_data = [(chunk, qa_pair) for chunk, qa_pairs in qa_data["questions"].items() for qa_pair in qa_pairs if
                           qa_pair.get("user_rating", False)]
        self.evaluate(curated_qa_data, checkpoint_results, start_index)

    def no_rag_evaluation(self):
        """
        Uses larger LLM but no RAG
        """
        ...

