"""cssutils stub (offline testing only).

Implements just enough of the cssutils API for Whoogle's config/filter
modules: parseString, getUrls, and iterable stylesheets with mutable rules.
"""

import logging
import re

from cssutils.css.cssstylesheet import CSSStyleSheet  # noqa: F401
from cssutils.css.cssstylerule import CSSStyleRule  # noqa: F401

log = logging.getLogger('cssutils')

_RULE_RE = re.compile(r'([^{}]+)\{([^{}]*)\}')
_URL_RE = re.compile(r'url\(([^)]+)\)')


def parseString(css_text, *args, **kwargs):
    sheet = CSSStyleSheet()
    for match in _RULE_RE.finditer(css_text or ''):
        selector = match.group(1).strip()
        body = match.group(2).strip()
        sheet.add(CSSStyleRule(selector, body))
    return sheet


def getUrls(sheet):
    urls = set()
    for match in _URL_RE.finditer(str(sheet.cssText, 'utf-8')):
        urls.add(match.group(1).strip('\'" '))
    return urls
