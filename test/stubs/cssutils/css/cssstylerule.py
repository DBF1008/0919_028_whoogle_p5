"""cssutils CSSStyleRule stub (offline testing only)."""


class CSSStyleRule:
    def __init__(self, selector_text='', style=''):
        self.selectorText = selector_text
        self.style = style

    def __repr__(self):
        return f'{self.selectorText} {{{self.style}}}'
