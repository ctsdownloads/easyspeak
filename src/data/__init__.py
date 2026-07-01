"""EasySpeak bundled data files, loaded at runtime via importlib.resources."""

from importlib import resources


def data_text(name, **fields):
    """Read a bundled data file as text, substituting any `{fields}` it uses."""
    text = (resources.files(__name__) / name).read_text()
    return text.format(**fields) if fields else text
