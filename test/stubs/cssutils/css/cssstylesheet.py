"""cssutils CSSStyleSheet stub (offline testing only)."""

from cssutils.css.cssstylerule import CSSStyleRule


class CSSStyleSheet:
    def __init__(self):
        self.cssRules = []

    def add(self, rule):
        self.cssRules.append(rule)

    def __iter__(self):
        return iter(self.cssRules)

    @property
    def cssText(self):
        return '\n'.join(
            f'{rule.selectorText} {{{rule.style}}}'
            for rule in self.cssRules
        ).encode('utf-8')
