"""Search-term cards: every card matches its own wording and common variants, and nothing unrelated."""

import unittest

from jw.search_terms import CARDS, ROLE_PATTERN, search_queries, terms


class SearchTermTests(unittest.TestCase):
    def test_fifty_cards_each_matches_itself(self):
        self.assertEqual(50, len(terms()))
        for term in terms():
            self.assertTrue(ROLE_PATTERN.search(f"We are hiring a {term} in Pune"), term)

    def test_variants_and_non_matches(self):
        for text in ("Hiring: full-stack developer", "Fullstack Engineer needed", "NodeJS Developer", "nextjs developer",
                     "SDE-2 backend", "Member of technical staff"):
            self.assertTrue(ROLE_PATTERN.search(text), text)
        for text in ("Hiring an AC motor winder", "Finance analyst wanted", "Electrical design engineer"):
            self.assertFalse(ROLE_PATTERN.search(text), text)

    def test_queries_one_per_card(self):
        self.assertEqual(len(terms()), len(search_queries()))
        self.assertEqual(sorted(CARDS), ["backend", "frontend", "full_stack", "general", "java", "mobile", "skill_combos"])


if __name__ == "__main__":
    unittest.main()
