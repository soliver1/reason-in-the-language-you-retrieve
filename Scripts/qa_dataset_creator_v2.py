#!/usr/bin/env python3

import argparse
import json
import logging
import random
from collections import defaultdict
from pathlib import Path
import readline

import ruamel.yaml
import ollama
from pydantic import ValidationError
from ollama import Message
from pydantic import BaseModel

from information_container import BookData, ContentBlock

logger = logging.getLogger("QA-Dataset-Creator")
DEFAULT_MODEL = "qwen3:30b-a3b"
DEFAULT_MODEL = "gemma3:27b"


system_prompt_qa_creator = """Du bist ein KI-Assistent, mit der Aufgabe ein QA-Datenset zu erstellen. 
Dazu werden dir Textabschnitte aus einem Hintergrundbuch über Aventurien, der Welt des Fantasy-Rollenspiels DSA, gegeben.
In diesen Abschnitten werden verschiedene Teile der Welt detailliert beleuchtet, je nachdem aus welchem Buch und welchem Abschnitt der Text kommt. 
Deine Aufgabe ist es, Fragen zu generieren die sich mit Hilfe des Textes beantworten lassen. 
Allerdings sollte ein Fachkundiger die Fragen auch so beantworten können - sie dürfen sich also niemals direkt auf den Text beziehen, sondern du musst dir anhand der Informationen im Abschnitt Fragen ausdenken, die mithilfe des Abschnitts, aber auch durch "Allgemeinwissen" über die Welt von Aventurien beantwortet werden könnten.    
Achte dabei auf folgende Punkte: 
- Schreibe deine Fragen und Antworten auf deutsch
- Die Frage muss jeglichen Kontext, der zum Verständnis der Frage nötig ist, bereits beinhalten
- Denke dir niemals neue Fakten aus oder füge etwas hinzu. Alles wonach du fragst muss im Text enthalten sein!
- Beziehe dich niemals direkt auf den Textabschnitt
- Die Frage muss eine eindeutige Antwort haben.
- Für jedes Frage-Antwort Paar das du generierst, musst du auch den relevanten Kontext aus dem Abschnitt mit angeben, der zur Beantwortung der Frage relevant ist.
- Die Frage darf sich niemals direkt auf den Abschnitt beziehen, etwa "Was sagt Abschnitt X dazu, ob Alrik der III. ein guter Bogenschütze war?". Stattdessen müssen die Fragen sich rein auf den Inhalt beziehen und genügens Kontext liefern, etwa "Alrik der III., der letzte Herrscher des Königreichs Y war bekannt für seine Leidenschaft zu jagen. Aber war er ein guter Bogenschütze?". 
- Stelle einfache und direkte Fragen. 
  - Negativbeispiel: "In welchem Teil des südlichen Aventuriens ist der Regenwald nicht der einzige Waldtyp, und welche anderen Waldformen können dort vorkommen?"
  - Positivbeispiel: "Ist der Regenwald der einzige Waldtyp, der in Südaventurien vorkommt?"
  - Weiteres Positivbeispiel: "Welche Waldtypen kommen in Südaventurien vor."
"""

system_prompt_qa_critic = """Du bist Teil eines Systems zur Erstellung und Evaluierung eines QA-Datensatzes über die fiktive Welt Aventurien.
Deine Aufgabe ist es, die Frage-Antwort Paare die ein anderes System mithilfe von Textabschnitten aus einem Buch generiert hat anzuschauen und zu kritisch bewerten.
Der Nutzer bekommt zur Beantwortung der Frage später keine Textabschnitte, sondern soll die Fragen durch sein Allgemeinwissen über Aventurien beantworten.
Dabei musst du auf folgende Kriterien zu den Fragen achten: 
- Die Frage muss jeglichen Kontext, der zum Verständnis der Frage nötig ist, bereits beinhalten
  - Wenn im Text eine Entität benannt wird muss diese eindeutig sein oder durch zusätzliche Informationen klar gemacht werden um welche es sich handelt. "Der Rahja-Tempel" wäre beispielsweise nicht eindeutig, während "Der Rahja-Tempel der Stadt Greifenfurt" eine Entität (bzw. einen Tempel) eindeutig  referenzieren würde.  
- Die Frage muss eine eindeutige Antwort haben.
- Die Frage darf niemals auf den Text verweisen (etwa "die im Textabschnitt genannten...") da sie komplett für sich stehen muss.
    
Antworte stets auf deutsch und im json Format. 
Deine Antwort soll eine Bewertung in Form einer Punktzahl beinhalten die beschreibt wie gut die Frage war (von 1 - "extrem ungeeignete Frage mit großen Kritikpunkten, völlig unbrauchbar" bis 5 - "Sehr gute Frage, nichts auszusetzen.").
Hier eine genaue Aufschlüsselung mit Beispielen was zu welcher Punktzahl führen sollte
1 - Die Frage ist ohne Kontext des zugehörigen Textabschnitts überhaupt nicht zu verstehen oder bezieht sich zumindest direkt auf den Textabschnitt.
2 - Die Frage bezieht sich auf eine Entität, ein Ereignis oder ähnliches die nicht zwingend eindeutig ist oder ist etwas schwammig formuliert.
3 - Die Frage bezieht sich auf eine Entität, ein Ereignis oder ähnliches, es ist allerdings nicht sicher ob die Beschreibung ausreicht um die Entität eindeutig zu beschreiben. 
4 - Die Frage ist eindeutig und ohne weiteren Kontext verständlich. Sie bezieht sich auf eine Entität, ein Ereignis oder ähnliches welche durch die Fragestellung eindeutig beschrieben werden. Möglicherweise ist die Antwort jedoch nicht absolut eindeutig sondern es könnte unter Umständen mehrere ähnliche Antworten geben.  
5 - Die Frage  ist eindeutig und ohne weiteren Kontext verständlich. Sie hat eine eindeutige Antwort.

"""



critic_examples = [
    Message(role="user", content="Welche Kosten fallen für die Teilnahme an den täglichen Opfern im Rabenfelsen an?"),
    Message(role="assistant", content='{"rating": 2, "reason": "Es ist nicht klar ob der Rabenfelsen ein eindeutiger spezifizierter Ort ist oder ob es mehrere geben könnte. Um sicherzugehen sollte die Frage mehr Kontext bieten, etwa \'Welche Kosten fallen für die Teilnahme an den täglichen Opfern am Rabenfelsen in Al\'Anfa an?\'"}'),
    Message(role="user", content="Was ist der Schlund in der Grafenstadt von Al'Anfa und welche besonderen Merkmale hat er?"),
    Message(role="assistant", content='{"rating": 4, "reason": "Der Ort nach dem gefragt wird ist eindeutig festgelegt, allerdings ist die Frage nach besonderen Merkmalen etwas schwammig, hier könnte unklar sein welche Merkmale aufgelistet werden sollen."}'),
    Message(role="user", content=" Wie groß ist der Koloss von Al'Anfa?"),
    Message(role="assistant", content='{"rating": 5, "reason": "Eine einfache Frage die sich auf eine klare Entität bezieht und eine kurze, präzise Antwort zulässt."}'),
    Message(role="user", content=" Wie werden die Straßen in den nobleren Vierteln Al'Anfas gepflegt und was sind die Konsequenzen für die Sklaven?"),
    Message(role="assistant", content='{"rating": 2, "reason": "Die Entität auf die sich die Frage bezieht ist klar (die Straßen in den nobleren Virteln Al\'Anfas). Allerdings ist sie recht offen gestellt. Der hintere Teil \'Was sind die Konsequenzen für die Sklaven\' ergibt allein gar keinen Sinn, weil nicht beschrieben wird für welches Vergehen die Sklaven hier Konsequenzen erleiden sollten."}'),
    Message(role="user", content="Wie viele Meilen können Reisende im Ewigen Wald realistisch an einem Tag zurücklegen, wenn sie sich ihren Weg selbst bahnen müssen?"),
    Message(role="assistant", content='{"rating": 3, "reason": "Es ist nicht ganz klar was der Ewige Wald ist, bzw. ob es sich dabei um einen klar definierten Ort handelt.  "}'),
    Message(role="user", content="Welches Ereignis führte zur Zerstörung der Mirhamer Flotte?"),
    Message(role="assistant", content='{"rating": 3, "reason": "Es wird nach einem spezifischen Ereignis gefragt, jedoch ist nicht klar ob die Mirhamer Flotte in der Geschichte nur ein einziges Mal zerstört wurde oder mehrfach, wodurch die Frage nicht unbedingt eindeutig ist. Weitere Details wie etwa eine Jahreszahl des Ereignisses wären angemessen."}'),
    Message(role="user", content="In welchen Regionen wächst der Cheria-Kaktus, aus dessen getrocknetem Fleisch Cheriacha hergestellt wird?"),
    Message(role="assistant", content='{"rating": 5, "reason": "Die Frage ist klar formuliert und bezieht sich auf eine spezifische Pflanze und deren Herkunft. Der Bezug zur Herstellung von Cheriacha gibt zusätzlichen Kontext."}'),
    Message(role="user", content="Welche Art von Gegenständen sammelt der Prinz von Mirham, Themodates von Shoy’Rina, um sich die Zeit zu vertreiben?"),
    Message(role="assistant", content='{"rating": 5, "reason": "Die Frage ist klar formuliert und bezieht sich auf eine spezifische Person (Themodates von Shoy\'Rina, den Prinzen von Mirham)."}'),
    Message(role="user", content="Immuel Florios ist ein Mitglied des Rates der Zwölf. Welche Position bekleidet er dort?"),
    Message(role="assistant", content='{"rating": 4, "reason": "Die Frage ist klar formuliert und bezieht sich auf eine spezifische Person in einer Organisation. Ich weiß nicht ob es den \'Rat der Zwölf\' nur ein mal gibt, oder mehrmals, demnach ist es womöglich nicht ganz eindeutig. Durch die Verbindung der Person Immuel Florios und der Organisation Rat der Zwölf ist die Frage jedoch relativ eindeutig."}')
]

class QAPairSchema(BaseModel):
    question: str
    answer: str
    context: str

class QASetSchema(BaseModel):
    qa_pairs: list[QAPairSchema]

class QACritiqueSchema(BaseModel):
    rating: int
    reason: str


# ToDo: for some reason seems to break (error/infinite loop?) at question 35 --> why?



class QADatasetCreator:
    def __init__(self, book_data: BookData, source_path: str, model: str = DEFAULT_MODEL):
        self.model = model
        self.book_data = book_data
        self.source_path = source_path
        self.context_size = 8192*2
        self.temperature = 0
        self.question_examples = [
            Message(role="user", content=self.qa_creation_prompt(self.book_data[145])),
            Message(role="assistant", content=str({"Question": "Welche Materialien werden in Al’Anfa hauptsächlich zum Schreiben verwendet, und warum sind andere Optionen weniger verbreitet?",
                                                   "Answer": "Hauptsächlich wird mit Chorhoper Tinte auf schlechtem Pergament geschrieben, welches aus örtlichem Leder gefertigt wird. Mittelländisches Büttenpapier und tulamidischer Papyrus sind gleichermaßen kostspielig wie in der ständigen Schwüle zerfallsgefährdet.",
                                                   "Context": "Geschrieben wird (mit Chorhoper Tinte) fast nur auf schlechtem Pergament, das aus örtlichem Leder gefertigt wird. Mittelländisches Büttenpapier und tulamidischer Papyrus sind gleichermaßen kostspielig wie in der ständigen Schwüle zerfallsgefährdet."})),
            Message(role="user", content=self.qa_creation_prompt(self.book_data[608])),
            Message(role="assistant", content=str({"Question": "Welches auffällige körperliche Merkmal  haben  alle Mitglieder der Al'Anfanischen Grandenfamilie Florios gemeinsam?",
                                                   "Answer": "Aufgrund eines Erbfehlers, fehlt ihnen an der linken Hand der halbe Ringfinger.",
                                                   "Context": "Durch einen familiären Erbfehler fehlt allen Florios an der linken Hand der halbe Ringfinger."})),
            Message(role="user", content=self.qa_creation_prompt(self.book_data[561])),
            Message(role="assistant", content=str({"Question": "Ist das Volk der Tocamuyac besonders kriegerisch?",
                                                   "Answer": "Nein, ganz im Gegenteil. Die Tocamuyac sind ein friedliebendes Volk von schwimmenden Händlern die es vorziehen Konflikten aus dem Weg zu gehen.",
                                                   "Context": "Die Floßleute sind ausgesprochen friedliebend und ziehen es traditionsgemäß vor, jeder Gefahr auszuweichen. Wenn absolut notwendig, wissen sie sich mit Fischspeeren, Harpunen und schweren Dolchen mehr schlecht als recht zu wehren."})),
        ]

    def improve_qa_dataset(self, dataset: dict[str, list[dict[str, str | int | bool]]], output_path: Path = Path("data/QA3 - Improved QA dataset")):
        logger.info("Creating dataset")
        critic = QADatasetCritic()
        for chunk_id, qa_pairs in dataset.items():
            for qa_pair in qa_pairs:
                print(f"------------------------------------------")
                chunk = self.book_data[chunk_id]
                print(f"Chunk: {chunk_id}, len  gth: {chunk.num_words}, ancestor length: {sum(anc.num_words for anc in chunk.ancestors)}")
                # broad_context = chunk.parent.full_text

                critique = qa_pair.get("user_critique") or qa_pair["reason"]

                print("Old:")
                print(f"Question: {qa_pair['question']}")
                print(f"Answer: {qa_pair['answer']}")
                print(f"Rating: {qa_pair['rating']}")
                print(f"Critique: {critique}")

                if qa_pair.get("user_rating", False):
                    logger.info("Skipping because of user rating")
                    continue
                if "user_rating" not in qa_pair and qa_pair["rating"] == 5:
                    logger.info("Skipping because of system rating")
                    continue

                prompt = self.qa_improvement_prompt(chunk, qa_pair, critique)
                while True:
                    try:
                        res = ollama.chat(model=self.model, messages=[{"role": "system",
                                                                       "content": system_prompt_qa_creator}] + self.question_examples + [
                                                                         {"role": "user", "content": prompt}],
                                          format=QAPairSchema.model_json_schema(),
                                          options={"num_ctx": self.context_size, })  # "temperature": self.temperature
                        qa_pair_new = QAPairSchema.model_validate_json(res.message.content)
                        break
                    except ValidationError as e:
                        print(e)
                print("New")
                print(f"Question: {qa_pair_new.question}")
                print(f"Answer: {qa_pair_new.answer}")
                critique = critic.critique_question(qa_pair_new.question)
                print(f"Rating: {critique.rating}")
                print(f"Critique: {critique.reason}")
                qa_pair.pop("user_rating", "")

                # update data
                qa_pair |= {"question": qa_pair_new.question, "answer": qa_pair_new.answer, "context": qa_pair_new.context, "rating": critique.rating,
                            "reason": critique.reason}

        output_path.mkdir(parents=True, exist_ok=True)
        yaml_writer = ruamel.yaml.YAML()
        with open(output_path / f"{self.book_data.title}.yaml", "w") as file:
            # json.dump(dataset, file, indent=4, ensure_ascii=False)
            yaml_writer.dump({"source_path": str(self.source_path), "questions": dataset}, file)


    def create_qa_dataset(self):
        logger.info("Creating dataset")
        # for i in range(24, len(self.book_data)):
        critic = QADatasetCritic()
        # for i in range(random.randint(1, len(self.book_data) - 10), len(self.book_data)):
        dataset = defaultdict(list)
        # for i in range(135, len(self.book_data)):
        for i in range(1, len(self.book_data)):
        # for i in range(1, 3):
            chunk = self.book_data[i]  # .text
            print(f"Chunk: {i}, length: {chunk.num_words}, ancestor length: {sum(anc.num_words for anc in chunk.ancestors)}")
            # if i < 35:
            #     continue
            # if i > 50:
            #     continue
            # breakpoint()
            if chunk.content:
                # broad_context = chunk.parent.full_text
                prompt = self.qa_creation_prompt(chunk)
                # ToDo add few shot example answers
                while True:
                    try:
                        res = ollama.chat(model=self.model, messages=[{"role": "system", "content": system_prompt_qa_creator}] + self.question_examples + [{"role": "user", "content": prompt}],
                                          format=QASetSchema.model_json_schema(),
                                          options={"num_ctx": self.context_size, })  # "temperature": self.temperature
                        questions = QASetSchema.model_validate_json(res.message.content)
                        break
                    except ValidationError as e:
                        print(e)
                        # breakpoint()
                for qa_pair in questions.qa_pairs:
                    print(f"Question: {qa_pair.question}")
                    print(f"Answer: {qa_pair.answer}")
                    print(f"Context: {qa_pair.context}")
                    critique = critic.critique_question(qa_pair.question)
                    data = {"question": qa_pair.question}
                    data |= {"answer": qa_pair.answer, "context": qa_pair.context, "rating": critique.rating, "reason": critique.reason}
                    dataset[chunk.id].append(data)
                    # dataset[chunk.id].append({"question": qa_pair.question, "answer": qa_pair.answer, "context": qa_pair.context, "rating": critique.rating, "reason": critique.reason})
                    print(f"------------------------------------------")
                    # breakpoint()
                    # a = critique
        output_path = Path("data/QA1 - Initial QA dataset")
        output_path.mkdir(parents=True, exist_ok=True)
        yaml_writer = ruamel.yaml.YAML()
        with open(output_path / f"{self.book_data.title}.json", "w") as file:
            # json.dump(dataset, file, indent=4, ensure_ascii=False)
            yaml_writer.dump({"source_path": self.source_path, "questions": dataset}, file)
            breakpoint()


    def qa_improvement_prompt(self, chunk: ContentBlock, qa_pair: dict[str, str], critique: str):
        prompt = f"""
        Hier hast du zunächst einen etwas größeren Überblick der übergeordneten Kapitel/Abschnitte, um den eigentlichen Abschnitt besser einordnen zu können:

        {chunk.ancestor_texts}

        -------------------------------------------------

        Nun kommt der Abschnitt zu dem du eine Frage generieren sollst: 

        {chunk.text}
        
        -------------------------------------------------
        
        Zu dem Abschnitt wurde bereits eine Frage und Antwort generiert, die allerdings nicht den Anforderungen entsprachen. 
        Das Frage-Antwort Paar lautet: 
        question: {qa_pair['question']}
        answer: {qa_pair['answer']}
        
        Diese Frage und Antwort entsprechen nicht den Anforderungen, du sollst sie verbessern. Generiere keine völlig neues Frage-Antwort Paar, sondern eine verbesserte Version derer, die dir gegeben wird. 
        Achte auf die Anforderungen die dir in der ersten Nachricht genannt wurden!
         
        Beachte auch folgendes Feedback zu diesem Frage/Antwort-Paar:
        Kritik: {critique}
        """
        return prompt

    def qa_creation_prompt(self, chunk: ContentBlock, additional_info: str = ""):
        prompt = f"""
Hier hast du zunächst einen etwas größeren Überblick der übergeordneten Kapitel/Abschnitte, um den eigentlichen Abschnitt besser einordnen zu können:

{chunk.ancestor_texts}

-------------------------------------------------

Nun kommt der Abschnitt zu dem du Fragen generieren sollst. Generiere bitte 3 Fragen zum folgenden Abschnitt: 
            
{chunk.text}
"""
        if additional_info:
            prompt = prompt + f"\n\n-------------------------------------------------\n\n{additional_info}"
        return prompt


class QADatasetCritic:

    def __init__(self, model: str = DEFAULT_MODEL):
        self.model = model
        self.book_data = book_data
        self.context_size = 8192*2
        self.temperature = 0


    def critique_question(self, question: str):
        while True:
            try:
                res = ollama.chat(model=self.model, messages=[{"role": "system", "content": system_prompt_qa_critic},
                                                              *critic_examples,
                                                              {"role": "user", "content": question}],
                                  format=QACritiqueSchema.model_json_schema(),
                                  options={"num_ctx": self.context_size, "temperature": self.temperature})

                critique = QACritiqueSchema.model_validate_json(res.message.content)
                break
            except ValidationError as e:
                print(e)
        # print(f"Rating: {critique.rating}")
        # print(f"Reason: {critique.reason}")
        # print(res)
        return critique

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input-file", type=Path, default="data/5 - information_container/G01 - In den Dschungeln Meridianas.yaml", help="Input file")
    parser.add_argument("--improve", type=Path, help="Improve the given dataset instead of creating a new one")
    args = parser.parse_args()
    if args.improve:
        yaml_reader = ruamel.yaml.YAML(typ="safe")
        with open(args.improve, "r") as file:
            old_dataset = yaml_reader.load(file)
        args.input_file = args.input_file or Path(old_dataset["source_path"])

    ratings = [qa_pair["rating"] for chunk in old_dataset["questions"].values() for qa_pair in chunk]
    avg_rating = sum(ratings) / len(ratings)
    logger.info(f"Average rating of old dataset: {avg_rating:.3f}")
    # breakpoint()

    book_data = BookData.load_from_file(args.input_file)
    qa_creator = QADatasetCreator(book_data, args.input_file)
    if not args.improve:
        qa_creator.create_qa_dataset()
    else:
        # ToDo improve output path handling once I have decided how many improvement cycles make sense
        qa_creator.improve_qa_dataset(old_dataset["questions"], output_path=Path("data/QA3 - Improved QA dataset/quadruple"))


