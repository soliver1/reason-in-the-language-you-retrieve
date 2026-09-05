import itertools as it
import collections

from jinja2 import Environment, FileSystemLoader, ChoiceLoader, select_autoescape


from jinja2.filters import do_xmlattr
from jinja2.utils import pass_eval_context


def create_environment(template_router, env_callback, templ_path, base_loader=None):
    loader = FileSystemLoader(str(templ_path))
    if base_loader is not None:
        loader = ChoiceLoader([loader, base_loader])


    env = Environment(loader=loader, autoescape=select_autoescape)

    env.globals['route'] = template_router
    env.globals['r'] = template_router
    env.globals['merge_attr'] = merge_attr

    env.filters['selectkeys'] = select_keys
    env.filters['string_max_len'] = string_max_len
    env.filters['chant_tradition_aspects'] = chant_tradition_aspects
    env.filters['group_by_preserve_order'] = group_by_preserve_order
    env.filters['dict_group_by'] = dict_group_by
    env.filters['safename'] = make_name_safe

    env.filters['hxattr'] = format_hx_attributes

    if env_callback:
        env_callback(env)

    return env


def make_name_safe(name):
    return name.lower().translate(str.maketrans({
        '&': None,
        ' ': '_',
        '/': '_',
        'ä': 'ae',
        'ö': 'oe',
        'ü': 'ue',
    })).replace('__', '_')


@pass_eval_context
def format_hx_attributes(ctx_, mapping):

    def format_hx(attr_key: str):
        if attr_key == 'script':
            return '_'
        attr_key = attr_key.replace('_', '-')
        if attr_key.startswith('hx_'):
            
            if attr_key[3:5] == 'on':
                attr_key = attr_key[0:5] + attr_key[5:7].replace('-', ':') + attr_key[7:]
        return attr_key

    formatted_attrs = {format_hx(key): value for key, value in mapping.items()}

    return do_xmlattr(ctx_, formatted_attrs)


def merge_attr(mapping, **kwargs):
    for key, value in kwargs.items():
        if key in mapping:
            mapping[key] += value
        else:
            mapping[key] = value
    return mapping


def select_keys(mapping, keys):
    return {key: mapping[key] for key in keys}


def string_max_len(string, len=3):
    return string[:len]

def chant_tradition_aspects(traditions: list[str]):
    trad_aspects = collections.defaultdict(list)
    # could also use re.match(r"(\w+)(?: \((\w+)\))?", "Boron (Traum)").groups()
    for trad in traditions:
        if "(" in trad:
            trad, aspect = trad.split(" ", maxsplit=1)
            trad_aspects[trad].append(aspect.strip("()"))
        else:
            trad_aspects[trad] = []
    return ", ".join([f"{trad[:3]} {f'({", ".join(aspects)})' if aspects else ''}" for trad, aspects in trad_aspects.items()])


def group_by_preserve_order(mapping, *keys, preserve_order=True):
    def get_attr_rec(x, ks=keys):
        return get_attr_rec(x[ks[0]], ks[1:]) if ks else x
    res = it.groupby(sorted(mapping, key=get_attr_rec) if not preserve_order else mapping, get_attr_rec)
    return res


def dict_group_by(mapping, *keys):
    def get_attr_rec(x, ks=keys):
        return get_attr_rec(x[ks[0]], ks[1:]) if ks else x
    res = it.groupby(sorted(mapping, key=get_attr_rec), get_attr_rec)
    return {cat: list(skills) for cat, skills in res}


