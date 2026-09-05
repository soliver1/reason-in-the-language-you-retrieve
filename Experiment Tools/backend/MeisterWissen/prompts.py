import warnings
from typing import Callable


def decide_on_tool_need(user_prompt: str, tools: dict[str, Callable]):
    warnings.warn(DeprecationWarning(), "deprecated")
    decision_prompt = ("Du hast eine sehr spezielle Aufgabe: du musst entscheiden, ob für die Beantwortung einer "
                       "Nutzer-Anfrage genügend Informationen zur Verfügung stehen, oder ob noch mehr recherchiert werden "
                       "muss um die Frage korrekt zu beantworten. Die bisher bereits recherchierten Fakten habe ich bereits aufgelistet, "
                       "nach jedem Recherche-Durchgang wirst du erneut gefragt ob nun genügend Informationen zur Verfügung stehen."
                       "Achte jedoch darauf, dass irgendwann auch eine Antwort erreicht werden muss und endloses recherchieren nicht zielführend ist. "
                       "Zur Recherche würden folgende Tools zur Verfügung stehen:\n")
    decision_prompt += "\n".join([f"{name}: {fun.__doc__}" for name, fun in tools.items()])
    decision_prompt += f"\n\nDu musst nun entscheiden, ob folgende Anfrage mit dem gegebenen Kontext und deinem Allgemeinwissen beantwortet werden kann, oder ob dazu mehr Recherche nötig ist: '{user_prompt}'"
    decision_prompt += (
        "\n\nFalls du der Meinung bist, dass genug Wissen zur Verfügung steht um die Frage zu beantworten, antworte mit **0**. "
        "Falls du dagegen der Meinung bist, dass noch mehr recherchiert werden soll, antworte stattdessen mit **1**. "
        "Deine Antwort darf nur aus einem einzigen Zeichen bestehen, füge keine Erklärung oder ähnliches hinzu!"
        # "Bevor du deine finale Antwort gibst, denke zunächst nach. Was spricht dafür noch mehr zu recherchieren, "
        # "was spricht dafür, dass die Informationen ausreichen? "
        # "Erwähne auch wie viele und welche Informationen dir aktuell bereits zur Verfügung stehen und wie viel du zu der gegebenen Frage schon beantworten könntest."
        # "Deine Überlegung müssen mit der Zahl die deiner Antwort entspricht (also 0 oder 1) enden."
        # "Es ist wichtig dass **das letzte Symbol** deiner Nachricht eine 0 oder 1 ist, die deine finale Entscheidung angibt!"
        # "Nach der Zahl, füge bitte noch eine kurze Erklärung an, warum du so entschieden hast."
    )
    return decision_prompt