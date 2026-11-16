import unittest
from text_encoding import ascii_text


class TextEncodingTests(unittest.TestCase):
    def test_polish_text_punctuation_and_unsupported_symbols(self):
        self.assertEqual(ascii_text("Zażółć gęślą jaźń — „Łódź”… 🙂"), 'Zazolc gesla jazn - "Lodz"... ?')

    def test_ascii_and_line_breaks_are_preserved(self):
        self.assertEqual(ascii_text("First\nSecond\t123"), "First\nSecond\t123")
