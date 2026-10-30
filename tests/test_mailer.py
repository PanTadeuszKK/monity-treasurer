import os
import smtplib
import ssl
import unittest
from unittest.mock import Mock, patch

from mailer import Mailer, valid_address


class MailerTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ, {'MONITY_MAIL_DRY_RUN':'0'})
        self.env.start()
        self.mailer=Mailer('sender@example.invalid','fake-app-password')
        self.smtp_patch=patch('mailer.smtplib.SMTP')
        self.smtp=self.smtp_patch.start()
        self.server=self.smtp.return_value
        self.server.send_message.return_value={}

    def tearDown(self):
        self.smtp_patch.stop()
        self.env.stop()

    def test_connection_verifies_tls_and_logs_in_without_sending(self):
        ok,info=self.mailer.sprawdz_polaczenie()
        self.assertTrue(ok)
        self.smtp.assert_called_once_with('smtp.gmail.com',587,timeout=15)
        self.assertEqual(self.server.ehlo.call_count,2)
        context=self.server.starttls.call_args.kwargs['context']
        self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.server.login.assert_called_once_with('sender@example.invalid','fake-app-password')
        self.server.send_message.assert_not_called()
        self.server.quit.assert_called_once()

    def test_send_one_test_with_no_member_data(self):
        self.assertTrue(self.mailer.wyslij_test('test@example.invalid')[0])
        self.assertEqual(self.mailer.delivery_state,'accepted')
        self.server.send_message.assert_called_once()
        message=self.server.send_message.call_args.args[0]
        self.assertEqual(message['To'],'test@example.invalid')
        self.assertEqual(message['Subject'],'[Monity] Wiadomość testowa')
        self.assertNotIn('fake-app-password',message.as_string())
        self.assertIsNotNone(message['Message-ID'])

    def test_auth_failure_does_not_leak_exception_or_password(self):
        self.server.login.side_effect=smtplib.SMTPAuthenticationError(535,b'SECRET SERVER DETAILS')
        success,info=self.mailer.sprawdz_polaczenie()
        self.assertFalse(success)
        self.assertNotIn('SECRET',info)
        self.assertNotIn('fake-app-password',info)
        self.server.close.assert_called_once()

    def test_disconnect_during_data_is_uncertain_and_not_retried(self):
        self.server.send_message.side_effect=smtplib.SMTPServerDisconnected('test')
        success,info=self.mailer.wyslij_test('test@example.invalid')
        self.assertFalse(success)
        self.assertEqual(self.mailer.delivery_state,'uncertain')
        self.assertIn('Wysłane',info)
        self.server.send_message.assert_called_once()

    def test_quit_failure_does_not_negate_accepted_message(self):
        self.server.quit.side_effect=smtplib.SMTPServerDisconnected('test')
        self.assertTrue(self.mailer.wyslij_test('test@example.invalid')[0])
        self.assertEqual(self.mailer.delivery_state,'accepted')

    def test_rejected_recipient_has_known_not_sent_state(self):
        self.server.send_message.side_effect=smtplib.SMTPRecipientsRefused({'test@example.invalid':(550,b'no')})
        self.assertFalse(self.mailer.wyslij_test('test@example.invalid')[0])
        self.assertEqual(self.mailer.delivery_state,'not_sent')

    def test_dry_run_never_connects(self):
        with patch.dict(os.environ,{'MONITY_MAIL_DRY_RUN':'1'}):
            self.assertTrue(self.mailer.sprawdz_polaczenie()[0])
            self.assertTrue(self.mailer.wyslij_test('test@example.invalid')[0])
        self.smtp.assert_not_called()

    def test_multiple_addresses_and_header_injection_rejected(self):
        for address in ['a@example.invalid,b@example.invalid','a@example.invalid\r\nBcc: x@example.invalid','bad']:
            self.assertFalse(self.mailer.wyslij_test(address)[0])
        self.assertFalse(self.mailer.wyslij_wiadomosc('a@example.invalid','Test\nBcc: bad','body')[0])
        self.smtp.assert_not_called()

    def test_html_contains_alternative_plain_content(self):
        self.assertTrue(self.mailer.wyslij_wiadomosc('test@example.invalid','Test','<b>Test</b>',is_html=True)[0])
        message=self.server.send_message.call_args.args[0]
        self.assertIsNotNone(message.get_body(preferencelist=('plain',)))
        self.assertIsNotNone(message.get_body(preferencelist=('html',)))

    def test_smtp_reply_exposes_codes_and_stage_without_server_private_text(self):
        self.server.starttls.side_effect=smtplib.SMTPResponseException(454,b'4.7.0 private@example.invalid SECRET')
        success,info=self.mailer.sprawdz_polaczenie()
        self.assertFalse(success)
        self.assertIn('TLS',info)
        self.assertIn('454 / 4.7.0',info)
        self.assertNotIn('SECRET',info)
        self.assertNotIn('private@',info)
        self.server.send_message.assert_not_called()

    def test_disconnect_before_send_is_not_reported_as_rejection(self):
        self.server.ehlo.side_effect=smtplib.SMTPServerDisconnected('SECRET')
        success,info=self.mailer.sprawdz_polaczenie()
        self.assertFalse(success)
        self.assertIn('przerwane',info)
        self.assertNotIn('odrzucił',info)
        self.assertNotIn('SECRET',info)

    def test_data_rejection_has_smtp_code(self):
        self.server.send_message.side_effect=smtplib.SMTPDataError(550,b'5.7.1 SECRET')
        success,info=self.mailer.wyslij_test('test@example.invalid')
        self.assertFalse(success)
        self.assertIn('550 / 5.7.1',info)
        self.assertIn('wysyłanie',info)
        self.assertEqual(self.mailer.delivery_state,'not_sent')
        self.assertNotIn('SECRET',info)


if __name__=='__main__':
    unittest.main()
