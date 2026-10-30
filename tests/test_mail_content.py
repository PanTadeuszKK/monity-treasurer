import unittest
from mail_content import payment_details, text_to_html, BANK_ACCOUNT, PAYEE

class MailContentTests(unittest.TestCase):
    def test_transfer_details_and_personal_title(self):
        text=payment_details('Jan Kowalski',12)
        self.assertIn(BANK_ACCOUNT,text)
        self.assertIn(PAYEE,text)
        self.assertIn('składka Jan Kowalski A!12',text)
        html=text_to_html(text)
        self.assertIn('color: #B00020;',html)
        self.assertEqual(html.count('WAŻNE:'),1)

    def test_name_or_custom_body_cannot_inject_html(self):
        html=text_to_html(payment_details('<script>Jan</script>',12))
        self.assertNotIn('<script>',html)
        self.assertIn('&lt;script&gt;',html)
