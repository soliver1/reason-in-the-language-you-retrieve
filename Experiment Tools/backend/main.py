#!/usr/bin/env python
import argparse
import asyncio
import dataclasses
import json
import logging
import os
import pathlib
import sys


if __name__ == '__main__':
    # could also set export PYTHONPATH="/some/path"
    print("Setting path!")
    # sys.path.append(str((pathlib.Path(".") / "shared" / "shared_modules").absolute()))
    sys.path.append(str((pathlib.Path(".") / "shared").absolute()))
    print(sys.path)


from MeisterWissen.world_knowledge import WorldKnowledge
from MeisterWissen.auto_evaluator import DatasetEvaluator, ExperimentType, str_to_experiment_type
from utility import MultiQueue
from shared_modules.logging_utility import prepare_logging, TextEffects
from interface.server import run_server

logger = logging.getLogger("BuchstaffAndFriends")

def serialize(obj):
    try:
        if dataclasses.is_dataclass(obj):
            # not resilient against monkey patches
            properties = {element: getattr(obj, element) for element in dir(obj.__class__) if isinstance(getattr(obj.__class__, element), property)}
            return {key: val for key, val in (vars(obj) | properties).items()
                    if not (hasattr(obj, "ignore_on_serialize") and key in obj.ignore_on_serialize())
                    and not (hasattr(obj, "ignore_on_serialize_transmit") and key in obj.ignore_on_serialize_transmit())}
        return obj.serialize()
    except Exception as e:
        logger.error(e)
        breakpoint()
        raise TypeError(f"Cannot serialize object of type {type(obj)}")


def buchstaff(command: dict):
    match command:
        case {"tool": "MeisterWissen", "function": func, **kwargs}:
            result = call_function(func, kwargs, world_knowledge)
            return json.dumps(result, default=serialize)
        case _:
            raise Exception(f"Unknown command or tool for command: {command}")


def call_function(func, kwargs, tool):
    result = {
        'type': 'return',
        'content': getattr(tool, func)(**kwargs.get("parameters", {}))
    }
    return result


def start_tool(tool, debug=False, *args):
    try:
        ret = tool(*args)
        logger.info(f"Successfully started tool \033[{TextEffects.YELLOW}m\033[{TextEffects.BOLD}m{tool.__name__}")
        return ret
    except Exception as e:
        logger.error(f"Failed to start tool {tool}: {e}")
        if debug:
            raise


if __name__ == '__main__':

    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true", help="Crash on tool startup errors (giving full traceback)")
    parser.add_argument("--meisterwissen", action="store_true", help="Enable Meisterwissen Tool")
    parser.add_argument("--eval-meisterwissen", action="store_true", help="Start Meisterwissen Evaluation")
    parser.add_argument("--meisterwissen-checkpoint", type=pathlib.Path, help="Checkpoint for Meisterwissen Evaluation")
    parser.add_argument("--meisterwissen-experiment", type=str_to_experiment_type, help="Experiment for Meisterwissen Evaluation")
    args = parser.parse_args()

    prepare_logging(verbose=True)

    port = int(os.environ.get("BACKEND_PORT", 8002))
    msg_queue = MultiQueue()
    if args.eval_meisterwissen:
        if not args.meisterwissen_experiment:
            logger.error("Please specify an experiment to perform.")
            sys.exit(1)
        DatasetEvaluator(args.meisterwissen_experiment).start_evaluation(args.meisterwissen_checkpoint)
        sys.exit(0)
    if args.meisterwissen:
        world_knowledge = start_tool(WorldKnowledge, False)


    asyncio.run(run_server(buchstaff, msg_queue, debug=args.debug, port=port))

