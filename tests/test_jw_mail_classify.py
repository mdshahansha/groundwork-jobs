"""JW-02 live-probe regressions: shapes of real recruiting mail (names and addresses replaced)
that the first classifier got wrong."""

import unittest

from jw.mailsync import classify

FOOTER = "\n\nYou received this because you applied. To unsubscribe from these emails, click here."


class RealMailShapes(unittest.TestCase):
    def test_footer_unsubscribe_is_not_an_opt_out(self):
        body = "Thank you for applying for the Engineer position at Fixture Co." + FOOTER
        self.assertEqual("acknowledgement", classify("careers@fixture.example", "Your application", body))

    def test_a_person_asking_to_be_removed_is_an_opt_out(self):
        for body in ("Please remove me from your list.", "Please unsubscribe me.", "Do not contact me again."):
            with self.subTest(body=body):
                self.assertEqual("opt_out", classify("someone@fixture.example", "Re: role", body))

    def test_newsletter_mentioning_interviews_is_not_an_invite(self):
        self.assertEqual("other", classify("hello@community.example", "AI has changed the interview game",
                                           "Live with Interview Prep. How to prepare for it."))

    def test_real_invite_phrasings(self):
        for body in ("We'd like to invite you to an interview next week.", "Please share your availability for a call.",
                     "We would like to interview you for the role.", "Let's schedule a call on Monday."):
            with self.subTest(body=body):
                self.assertEqual("interview_invite", classify("talent@fixture.example", "Next steps", body))

    def test_acknowledgement_variants_seen_in_live_mail(self):
        for subject, body in (("Grateful for Your Interest", "Thank you for your interest in joining Fixture Co and for "
                                                             "taking the time to submit your application."),
                              ("Your application was sent to Fixture Co", "Your application was sent to Fixture Co."),
                              ("Thank you for applying", "A recruiter will reach out to schedule a conversation.")):
            with self.subTest(subject=subject):
                self.assertEqual("acknowledgement", classify("no-reply@ats.example", subject, body))


if __name__ == "__main__":
    unittest.main()
