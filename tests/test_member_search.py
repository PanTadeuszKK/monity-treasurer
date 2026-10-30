import unittest
from member_search import name_matches

class MemberSearchTests(unittest.TestCase):
    def test_name_fragments_order_accents_and_case(self):
        for query in ('łuk','ZOLC','Zolc Lukasz','  łUKASZ  Żółć  ','żół'):
            self.assertTrue(name_matches('Łukasz Żółć',query),query)
        self.assertFalse(name_matches('Łukasz Żółć','12'))
        self.assertFalse(name_matches('Łukasz Żółć','Łukasz Kowalski'))
        self.assertTrue(name_matches('Łukasz Żółć',''))
