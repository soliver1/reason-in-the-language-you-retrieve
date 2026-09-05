from pathlib import Path
import ruamel.yaml

yaml = ruamel.yaml.YAML(typ='safe')
def load_yaml(path):
    with open(path, 'r') as f:
        return yaml.load(f)


results = {doc: load_yaml(doc) for doc in Path("data/RX - results complex dataset").glob("./*.yaml")}
data = [{field: element[field] for field in ["question", "correct_answer"]} for element in next(iter(results.values()))["results"]]

for i, (doc, result) in enumerate(results.items()):
    letter = chr(65 + i)
    print(f"{letter}: {doc}")
    for j, answer in enumerate(result["results"]):
        data[j][f"Answer {letter}"] = answer[f"system_answer"]
        data[j][f"Rating {letter}"] = None
        data[j][f"Comment {letter}"] = ""



dumper = ruamel.yaml.YAML()
with open("data/RX2 - result grading complex dataset/qa-evaluation-data.yaml", "w") as f:
    f.writelines(["# Im Folgenden sind Fragen, korrekte Antworten und System-Antworten in verschiedenen Konfigurationen (A-F) gegeben.\n",
                  "# Deine Aufgabe ist, die verschiedenen Antworten auf einer Skala von 1 (sehr schlecht) bis 5 (sehr gut) zu bewerten.\n",
                  "# Trage deine Bewertung in das dafür vorgesehene 'Rating'-Feld ein.\n",
                  "# Falls du zu einer Bewertung etwas Spezielles anmerken möchtest, kannst du hierzu das 'Comment'-Feld nutzen.\n",
                  "# Achte dabei auf folgende Kriterien:\n",
                  "# ### Inhalt\n",
                  "#   - Ist eine Antwort korrekt und enthält eine Antwort alle nötigen Informationen zur Beantwortung der Frage, sollte sie mit 5 bewertet werden.\n",
                  "#   - Ist eine Antwort falsch, sollte sie mit 1 bewertet werden.\n",
                  "#   - Ist eine Antwort nicht vollständig, enthält jedoch einige korrekte und relevante Aspekte, die noch nicht in der Frage enthalten waren, sollte sie eine Bewertung zwischen 2 und 4 erhalten.\n",
                  "#   - Enthält eine Antwort zusätzliche Informationen die nicht in der vorgegebenen korrekten Antwort enthalten sind, nutze dein eigenes Wissen über Aventurien um einzuordnen, ob die Informationen:\n",
                  "#      - Korrekt sind (kein Abzug in der Bewertung)\n",
                  "#      - Erfunden sind (hierfür solltest du in der Bewertung einen oder mehrere Punkte abziehen)\n",
                  "# ### Formulierung\n",
                  "#   - Enthält eine Antwort grammatikalische oder orthografische Fehler, kannst du dafür Punkte der Bewertung abziehen.\n",
                  "#   - Ist eine Antwort unverständlich oder missverständlich formuliert, kannst du dafür Punkte in der Bewertung abziehen.\n",
                  "#   - Ob eine Antwort auf eine Textpassage verweist oder nicht ist für die Bewertung irrelevant.\n",
                  ])
    dumper.dump(data, f)