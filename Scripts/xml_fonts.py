

"""
config for specifying handling of font types in the different books
"""
import enum
from tkinter.messagebox import IGNORE
from xml.etree.ElementTree import Element as XMLElement


class Book(enum.Enum):
    G00 = enum.auto()
    G01 = enum.auto()
    G05 = enum.auto()
    G08 = enum.auto()
    G12 = enum.auto()
    G13 = enum.auto()
    G14 = enum.auto()
    G15 = enum.auto()
    Q01 = enum.auto()
    Q02 = enum.auto()
    Q03 = enum.auto()
    Q05 = enum.auto()
    Q06 = enum.auto()
    Q07 = enum.auto()
    Q08 = enum.auto()
    Q09 = enum.auto()
    Q10 = enum.auto()
    Q12 = enum.auto()


class Font:
    def __init__(self):
        ...

    def before(self) -> str:
        return ""

    def after(self) -> str:
        return ""

    def ignore(self):
        return False

    def __repr__(self):
        return type(self).__name__

    def __eq__(self, other):
        return type(self) == type(other)

class DefaultFont(Font):
    """Just the base font with a different name"""

class Ignore(Font):

    def ignore(self):
        return True

class Italic(Font):
    def before(self):
        return "*"

    def after(self):
        return "*"


class Bold(Font):
    def before(self):
        return "**"

    def after(self):
        return "**"

class Headline(Font):
    def __init__(self, level: int):
        super().__init__()
        self.level = level

    def before(self):
        return self.level * "#" + " "

    def __eq__(self, other):
        return type(self) == type(other) and self.level == other.level

class DebugFont(Font):

    def __init__(self, tag: str):
        super().__init__()
        self.tag = tag

    def before(self) -> str:
        return f"<{self.tag}>"

    def after(self) -> str:
        return f"</{self.tag}>"

    def __eq__(self, other):
        return type(self) == type(other) and self.tag == other.tag

class DebugFontConverter:
    """adds font tags for bold fonts (to find headline fonts easier)"""
    def __init__(self, styles: XMLElement):
        self.styles = styles

    def __getitem__(self, item: str):
        style = self.styles.find(f".//*[@ID='{item}']").get("FONTSTYLE")
        if style == "bold":
            return DebugFont(item)
        return Ignore()

class DummyFontConverter:
    """Just ignores fonts"""
    def __init__(self):
        ...

    def __getitem__(self, item: str):
        return Font()

class FontConverter:

    def __init__(self, book: Book, styles: XMLElement):
        self.styles = styles
        try:
            self.fonts = {
                Book.G00: {
                    # "font4": Headline(4),    # just bold text
                    "font7": Headline(2),
                    "font11": Ignore(),
                    "font12": Headline(1),
                    "font13": Headline(3),
                    "font19": Ignore(),
                    "font20": Headline(1),
                },
                Book.G01: {
                    "font0": Headline(1),
                    "font1": Headline(3),
                    "font7": Headline(2),
                    "font13": Headline(3),
                    "font14": Ignore(),      # headline(1) is doubled, font14 is shadow
                    "font15": Headline(1),      # double
                    "font17": Headline(4),
                },
                Book.G05: {
                    # "font2": Headline(4),
                    "font9": Headline(2),
                    "font10": Ignore(),
                    "font11": Headline(1),
                    "font14": Headline(3),
                },
                Book.G08: {
                    "font6": Headline(3),
                    "font10": Headline(2),
                    "font12": Ignore(),
                    "font13": Headline(1),
                    "font16": Headline(4),
                },
                Book.G12: {
                    "font9": Headline(3),
                    "font13": Headline(2),
                    "font15": Ignore(),
                    "font16": Headline(1),
                    "font19": Headline(4),
                },
                Book.G13: {
                    "font10": Headline(3),
                    "font15": Headline(2),
                    "font18": Headline(1),
                    "font20": Headline(4),
                },
                Book.G14: {
                    "font10": Headline(3),
                    "font16": Headline(2),
                    "font17": Headline(1),
                    "font19": Headline(4),
                },
                Book.G15: {
                    "font5": Headline(3),
                    "font9": Headline(1),
                    "font15": Headline(4),
                    "font17": Headline(2),
                    "font18": Ignore(),
                    "font19": Headline(2),
                    "font20": Headline(2),
                    "font27": Headline(2),
                }
                # ToDo handle other books
            }[book]
        except KeyError as e:
            raise Exception(f"Unknown Book {book}!") from e

    def __getitem__(self, item: str):
        # try:
        #     num = int(item.lstrip("font"))
        # except Exception as e:
        #     raise Exception("Failed to convert font") from e
        if item in self.fonts:
            return self.fonts[item]
        style = self.styles.find(f".//*[@ID='{item}']").get("FONTSTYLE")
        if style == "bold":
            return Bold()
        if style == "italic":
            return Italic()
        return DefaultFont()       # normal font

