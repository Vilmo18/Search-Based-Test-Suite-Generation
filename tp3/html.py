from __future__ import annotations

import random
import string
from typing import Sequence

from html.parser import HTMLParser

from poly_sbst.common.abstract_executor import AbstractExecutor

from tp3.shared import (
    GrammarSuiteGenerator,
    OnePointSuiteCrossover,
    RatioCoverageProblem,
    SuiteMutation,
)


TAG_L = "⟪"
TAG_R = "⟫"


def _finalize_html(s: str) -> str:
    return s.replace(TAG_L, "<").replace(TAG_R, ">")


HTML_GRAMMAR: dict[str, list[str]] = {
    "<start>": ["<flag><doc>"],
    "<flag>": ["0|", "1|"],
    "<doc>": ["<nodes>"],
    "<nodes>": ["<node>", "<node><nodes>"],
    "<node>": ["<element>", "<text>", "<comment>", "<doctype>", "<entity>"],
    "<doctype>": [f"{TAG_L}!DOCTYPE html{TAG_R}", f"{TAG_L}!doctype html{TAG_R}", ""],
    "<comment>": [f"{TAG_L}!--<text>--{TAG_R}", f"{TAG_L}!-- --{TAG_R}"],
    "<entity>": ["&amp;", "&lt;", "&gt;", "&quot;", "&#38;", "&#x3c;", "&#x3E;", "&#0;", "&#x0;"],
    "<element>": ["<start_tag><nodes></end_tag>", "<self_closing>"],
    "<start_tag>": [f"{TAG_L}<tagname><attrs>{TAG_R}"],
    "</end_tag>": [f"{TAG_L}/<tagname>{TAG_R}"],
    "<self_closing>": [f"{TAG_L}<tagname><attrs>/{TAG_R}"],
    "<tagname>": ["html", "head", "body", "div", "span", "a", "p", "h1", "h2", "ul", "li", "script", "style"],
    "<attrs>": ["", " <attr>", " <attr><attrs>"],
    "<attr>": [
        "id=\"<word>\"",
        "class='<word>'",
        "href=\"<url>\"",
        "data-x=\"<word>\"",
        "disabled",
        "title=\"<word>\"",
    ],
    "<url>": ["http://example.com", "/path", "#frag", "javascript:alert(1)", "mailto:a@b", ""],
    "<word>": ["<wchar>", "<wchar><word>"],
    "<wchar>": list(string.ascii_letters + string.digits + "-_"),
    "<text>": ["<tchar>", "<tchar><text>"],
    "<tchar>": list(string.ascii_letters + string.digits + " \t\n-_=+.,;:/?&%"),
}


HTML_SEEDS: Sequence[str] = [
    "1|<html><head><title>Test</title></head><body><h1>Parse me!</h1></body></html>",
    "1|<div class='c'>hello</div>",
    "0|<a href=\"http://example.com?x=1#f\">link</a>",
    "1|<!-- comment --><p>text</p>",
    "1|<!DOCTYPE html><html><body></body></html>",
    "0|<script>alert(1)</script>",
    "1|<style>body{color:red}</style>",
    "1|<div><span>nested</div>",
    "1|&lt;not a tag&gt; &amp; &#x3c;",
    "1|<p title=\"unterminated>oops</p>",
]


TAGS = ["div", "span", "a", "p", "h1", "h2", "ul", "li", "script", "style", "table", "tr", "td"]
ENTITIES = ["&amp;", "&lt;", "&gt;", "&quot;", "&#38;", "&#x3c;", "&#x3E;", "&#0;", "&#x0;"]


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
    b = bytearray(s.encode("utf-8", errors="ignore")[:2048])
    if not b:
        return s
    i = random.randrange(len(b))
    bit = 1 << random.randrange(8)
    b[i] ^= bit
    return bytes(b).decode("utf-8", errors="ignore")


def toggle_convert_charrefs_flag(s: str) -> str:
    if len(s) >= 2 and s[0] in "01" and s[1] == "|":
        return ("1" if s[0] == "0" else "0") + s[1:]
    return random.choice(["0|", "1|"]) + s


def insert_html_snippet(s: str) -> str:
    snippet = random.choice(
        [
            "<div>",
            "</div>",
            "<p>",
            "</p>",
            "<a href=\"/\">",
            "</a>",
            "<!--comment-->",
            "<!DOCTYPE html>",
            "<script>alert(1)</script>",
            "<style>body{color:red}</style>",
            "<br/>",
        ]
    )
    pos = random.randrange(len(s) + 1)
    return s[:pos] + snippet + s[pos:]


def insert_random_tag(s: str) -> str:
    tag = random.choice(TAGS)
    pos = random.randrange(len(s) + 1)
    return s[:pos] + f"<{tag}>{random.choice(['', 'X', ' '])}</{tag}>" + s[pos:]


def break_tag_delimiters(s: str) -> str:
    if not s:
        return "<"
    if "<" in s and random.random() < 0.5:
        return s.replace("<", "<<", 1)
    if ">" in s and random.random() < 0.5:
        return s.replace(">", "", 1)
    pos = random.randrange(len(s) + 1)
    return s[:pos] + random.choice(["<", ">", "/"]) + s[pos:]


def insert_entity(s: str) -> str:
    pos = random.randrange(len(s) + 1)
    return s[:pos] + random.choice(ENTITIES) + s[pos:]


def insert_attribute_noise(s: str) -> str:
    noise = random.choice(
        [
            " id=\"x\"",
            " class='c'",
            " href=\"http://example.com\"",
            " data-x=\"1\"",
            " onclick=\"alert(1)\"",
            " =\"\"",
            " '",
        ]
    )
    pos = random.randrange(len(s) + 1)
    return s[:pos] + noise + s[pos:]


def html_feed_driver(s: str):
    convert_charrefs = True
    data = s

    if isinstance(s, str) and "|" in s:
        flag, rest = s.split("|", 1)
        if flag in ("0", "1"):
            convert_charrefs = flag == "1"
            data = rest

    parser = HTMLParser(convert_charrefs=convert_charrefs)
    parser.feed(data)
    return None


html_feed_driver.__name__ = "feed"
html_feed_driver.__module__ = "html.parser"


class HTMLTestSuiteGenerator(GrammarSuiteGenerator):
    def __init__(self) -> None:
        super().__init__(
            name="HTMLTestSuiteGenerator",
            grammar=HTML_GRAMMAR,
            seeds=HTML_SEEDS,
            min_suite_len=1,
            max_suite_len=40,
            suite_length_exponent=6.0,
            max_input_len=2048,
            max_nonterminals=80,
            post_process=_finalize_html,
            p_seed=0.25,
        )


class HTMLTestSuiteProblem(RatioCoverageProblem):
    def __init__(self, executor: AbstractExecutor):
        super().__init__(executor, name="HTMLTestSuiteProblem")


class HTMLTestSuiteMutation(SuiteMutation):
    def __init__(self, *, generator: HTMLTestSuiteGenerator, mut_rate: float = 0.50):
        alphabet = string.ascii_letters + string.digits + string.punctuation + " \t\n"
        string_mutators = [
            delete_random_character,
            lambda s: insert_random_character(s, alphabet=alphabet),
            lambda s: replace_random_character(s, alphabet=alphabet),
            flip_random_bit_in_byte,
            toggle_convert_charrefs_flag,
            insert_html_snippet,
            insert_random_tag,
            break_tag_delimiters,
            insert_entity,
            insert_attribute_noise,
        ]
        super().__init__(generator=generator, string_mutators=string_mutators, mut_rate=mut_rate)


class HTMLTestSuiteCrossover(OnePointSuiteCrossover):
    def __init__(self, *, generator: HTMLTestSuiteGenerator, cross_rate: float = 0.90):
        super().__init__(generator=generator, cross_rate=cross_rate)


def make_executor() -> AbstractExecutor:
    return AbstractExecutor(html_feed_driver)
