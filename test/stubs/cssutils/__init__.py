"""Minimal offline stub of cssutils.

Supports just what whoogle uses: parseString, getUrls, log.setLevel,
CSSStyleSheet and CSSStyleRule.
"""

import re


class _Log:
    def setLevel(self, level):
        pass


log = _Log()


class CSSStyleRule:
    def __init__(self, selector_text='', style=''):
        self.selectorText = selector_text
        self.style = style


class CSSStyleSheet:
    def __init__(self, css_text=''):
        self._text = css_text or ''
        self._rules = [
            CSSStyleRule(selector_text=m.group(1).strip(),
                         style=m.group(2).strip())
            for m in re.finditer(r'([^{}]+)\{([^{}]*)\}', self._text)
        ]

    def __iter__(self):
        return iter(self._rules)

    def add(self, rule):
        self._rules.append(rule)
        self._text += f'{rule.selectorText} {{ {rule.style} }}'

    @property
    def cssText(self):
        return self._text.encode('utf-8')


def parseString(css_text, *args, **kwargs):
    return CSSStyleSheet(css_text)


def getUrls(sheet):
    text = sheet._text if isinstance(sheet, CSSStyleSheet) else str(sheet)
    return set(re.findall(r'url\(([^)]+)\)', text))
