from __future__ import annotations

import random
import string
from typing import Sequence

from urllib.parse import urlparse as _urlparse

from poly_sbst.common.abstract_executor import AbstractExecutor

from tp3.shared import (
    GrammarSuiteGenerator,
    OnePointSuiteCrossover,
    RatioCoverageProblem,
    SuiteMutation,
)


URL_GRAMMAR: dict[str, list[str]] = {
    "<start>": ["<allow>|<defscheme>|<url>"],
    "<allow>": ["0", "1"],
    "<defscheme>": ["", "http", "https", "ftp", "file", "mailto", "ws", "wss", "ssh", "git", "custom"],
    "<url>": ["<absolute>", "<schemeless>", "<relative>", "<opaque>", "<weird>"],
    "<absolute>": ["<scheme>://<authority><path_opt><query_opt><frag_opt>"],
    "<opaque>": ["<scheme>:<path><query_opt><frag_opt>"],
    "<scheme>": ["http", "https", "ftp", "file", "mailto", "ws", "wss", "ssh", "git", "custom"],
    "<schemeless>": ["//<authority><path_opt><query_opt><frag_opt>"],
    "<relative>": ["<path><query_opt><frag_opt>", "<path>"],
    "<authority>": ["<userinfo_opt><host><port_opt>"],
    "<userinfo_opt>": ["", "user@", "user:pass@", "admin:1234@", ":@", "user:@", ":pass@"],
    "<host>": [
        "example.com",
        "www.example.com",
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "255.255.255.255",
        "192.168.0.1",
        "[::1]",
        "[2001:db8::1]",
        "[2001:db8::dead:beef]",
        "xn--bcher-kva.example",
    ],
    "<port_opt>": ["", ":80", ":443", ":0", ":65535", ":-1", ":99999"],
    "<path_opt>": ["", "<path>"],
    "<path>": ["/<segment><path_tail>", "/", "/..", "/.", "/%2e%2e/", "/%2e/"],
    "<path_tail>": ["", "/<segment><path_tail>"],
    "<segment>": ["<pchar>", "<pchar><segment>"],
    "<pchar>": list(string.ascii_letters + string.digits + "-._~%:@"),
    "<query_opt>": ["", "?<query>"],
    "<query>": ["<qchar>", "<qchar><query>"],
    "<qchar>": list(string.ascii_letters + string.digits + "&=+%._-;/?:@"),
    "<frag_opt>": ["", "#<frag>"],
    "<frag>": ["<fchar>", "<fchar><frag>"],
    "<fchar>": list(string.ascii_letters + string.digits + "._-+/=%"),
    "<weird>": [
        "<scheme>:///../<segment>",
        "<scheme>://<host>\\<segment>",
        " <absolute>",
        "<absolute> ",
        "<scheme>://<host>:<port_digits>/<segment>",
    ],
    "<port_digits>": ["0", "00", "01", "1", "22", "080", "65535", "99999"],
}


URL_SEEDS: Sequence[str] = [
    "1|http|http://example.com",
    "1||www.google.com",
    "0|http|http://example.com#frag",
    "1|file|file:///etc/passwd",
    "1|mailto|mailto:user@example.com",
    "1|ssh|ssh://user@host:22/path",
    "1||//example.com/path",
    "1||/relative/path?query=1",
    "1||http:example.com",
    "1||http://[::1]/",
]


DELIMS = [":", "://", "/", "\\", "?", "#", "&", "=", ";", "@", "[", "]", "|", " "]
UNICODE_SAMPLES = ["é", "✓", "☃", "汉", "Δ", "—"]


def _rand_hex() -> str:
    return random.choice("0123456789ABCDEF")


def delete_random_character(s: str) -> str:
    if not s:
        return s
    i = random.randrange(len(s))
    return s[:i] + s[i + 1 :]


def insert_random_character(s: str, *, alphabet: str) -> str:
    i = random.randrange(len(s) + 1)
    return s[:i] + random.choice(alphabet) + s[i:]


def replace_random_character(s: str, *, alphabet: str) -> str:
    if not s:
        return random.choice(alphabet)
    i = random.randrange(len(s))
    return s[:i] + random.choice(alphabet) + s[i + 1 :]


def flip_random_bit_in_byte(s: str) -> str:
    if not s:
        return s
    b = bytearray(s.encode("utf-8", errors="ignore")[:512])
    if not b:
        return s
    i = random.randrange(len(b))
    bit = 1 << random.randrange(8)
    b[i] ^= bit
    return bytes(b).decode("utf-8", errors="ignore")


def toggle_allow_fragments_flag(s: str) -> str:
    if len(s) >= 2 and s[0] in "01" and s[1] == "|":
        return ("1" if s[0] == "0" else "0") + s[1:]
    return random.choice(["0|", "1|"]) + s


def insert_delimiter(s: str) -> str:
    pos = random.randrange(len(s) + 1)
    return s[:pos] + random.choice(DELIMS) + s[pos:]


def percent_encode_random_byte(s: str) -> str:
    pos = random.randrange(len(s) + 1)
    return s[:pos] + f"%{_rand_hex()}{_rand_hex()}" + s[pos:]


def break_or_fix_scheme_separator(s: str) -> str:
    if "://" in s and random.random() < 0.5:
        return s.replace("://", random.choice([":/", ":", "////", ":///", " ://"]), 1)
    pos = random.randrange(len(s) + 1)
    return s[:pos] + "://" + s[pos:]


def insert_unicode(s: str) -> str:
    pos = random.randrange(len(s) + 1)
    return s[:pos] + random.choice(UNICODE_SAMPLES) + s[pos:]


def urlparse_driver(s: str):
    allow_fragments = True
    scheme = ""
    url = s

    if isinstance(s, str):
        parts = s.split("|", 2)
        if len(parts) == 3 and parts[0] in ("0", "1"):
            allow_fragments = parts[0] == "1"
            scheme = parts[1]
            url = parts[2]

    return _urlparse(url, scheme=scheme, allow_fragments=allow_fragments)


urlparse_driver.__name__ = "urlparse"
urlparse_driver.__module__ = "urllib.parse"


class UrlTestSuiteGenerator(GrammarSuiteGenerator):
    def __init__(self) -> None:
        super().__init__(
            name="UrlTestSuiteGenerator",
            grammar=URL_GRAMMAR,
            seeds=URL_SEEDS,
            min_suite_len=1,
            max_suite_len=40,
            suite_length_exponent=6.0,
            max_input_len=512,
            max_nonterminals=60,
            post_process=None,
            p_seed=0.25,
        )


class UrlTestSuiteProblem(RatioCoverageProblem):
    def __init__(self, executor: AbstractExecutor):
        super().__init__(executor, name="UrlTestSuiteProblem")


class UrlTestSuiteMutation(SuiteMutation):
    def __init__(self, *, generator: UrlTestSuiteGenerator, mut_rate: float = 0.50):
        alphabet = string.ascii_letters + string.digits + string.punctuation + " "
        string_mutators = [
            delete_random_character,
            lambda s: insert_random_character(s, alphabet=alphabet),
            lambda s: replace_random_character(s, alphabet=alphabet),
            flip_random_bit_in_byte,
            toggle_allow_fragments_flag,
            insert_delimiter,
            percent_encode_random_byte,
            break_or_fix_scheme_separator,
            insert_unicode,
        ]
        super().__init__(generator=generator, string_mutators=string_mutators, mut_rate=mut_rate)


class UrlTestSuiteCrossover(OnePointSuiteCrossover):
    def __init__(self, *, generator: UrlTestSuiteGenerator, cross_rate: float = 0.90):
        super().__init__(generator=generator, cross_rate=cross_rate)


def make_executor() -> AbstractExecutor:
    return AbstractExecutor(urlparse_driver)
