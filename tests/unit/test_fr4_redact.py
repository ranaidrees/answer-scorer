"""FR-4 step 3: deterministic redaction of emails, phone numbers and URLs.

All contact details here are synthetic: reserved example domains and the phone number
ranges that regulators set aside for fiction.
"""

from __future__ import annotations

import pytest

from scorer.redact import EMAIL_PLACEHOLDER, PHONE_PLACEHOLDER, URL_PLACEHOLDER, redact
from tests.unit.samples import ORDINARY_ANSWERS


@pytest.mark.parametrize(
    "email",
    ["sam.taylor@example.com", "s_taylor+work@mail.example.org", "SAM@EXAMPLE.CO.UK"],
)
def test_fr4_redaction_replaces_email_addresses(email):
    result = redact(f"I wrote to the team from {email}, and they replied.")
    assert result.text == f"I wrote to the team from {EMAIL_PLACEHOLDER}, and they replied."
    assert result.emails == 1


@pytest.mark.parametrize(
    "phone",
    [
        "07700 900123",
        "07700900123",
        "+44 7700 900123",
        "+44 (0)20 7946 0958",
        "020 7946 0958",
        "(555) 010-0199",
        "555-010-0199",
        "+1 555 010 0199",
        "0044 7700 900123",
    ],
)
def test_fr4_redaction_replaces_phone_numbers(phone):
    result = redact(f"The customer rang me on {phone} and I called back.")
    assert result.text == f"The customer rang me on {PHONE_PLACEHOLDER} and I called back."
    assert result.phones == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://www.example.com/profile/sam-taylor",
        "http://example.org",
        "www.example.com/team?id=7",
        "example.com/portfolio",
        "intranet.example.co.uk",
    ],
)
def test_fr4_redaction_replaces_urls(url):
    result = redact(f"The plan is at {url}. Everyone could see it.")
    assert result.text == f"The plan is at {URL_PLACEHOLDER}. Everyone could see it."
    assert result.urls == 1


def test_fr4_redaction_handles_several_contact_details_in_one_answer():
    result = redact(
        "Reach me at sam@example.com or 07700 900123 (see https://example.com/me). "
        "I shared the plan with everyone."
    )
    assert result.text == (
        f"Reach me at {EMAIL_PLACEHOLDER} or {PHONE_PLACEHOLDER} (see {URL_PLACEHOLDER}). "
        "I shared the plan with everyone."
    )
    assert (result.emails, result.phones, result.urls) == (1, 1, 1)
    assert result.redactions == 3


@pytest.mark.parametrize("answer", ORDINARY_ANSWERS)
def test_fr4_redaction_leaves_an_ordinary_answer_unchanged(answer):
    result = redact(answer)
    assert result.text == answer
    assert result.redactions == 0
    assert result.remaining_chars == len(answer)


@pytest.mark.parametrize(
    "text",
    [
        "We cut the backlog from 1200 to 800 tickets between 2019 and 2021.",
        "The budget was 12,000 and we saved 3.5 hours a week by 2024-10-12.",
        "Version 2.10.3 fixed it. Then 15 of 20 people adopted it in 6 weeks.",
        "I finished the report.Then I shared it, e.g. with the whole team.",
        "It ran from 09:00 to 17:30 on 12/10/2024 for 250 users.",
    ],
)
def test_fr4_redaction_does_not_touch_ordinary_numbers_and_punctuation(text):
    result = redact(text)
    assert result.text == text
    assert result.redactions == 0


def test_fr4_redaction_is_deterministic():
    text = "Reach me at sam@example.com or 07700 900123."
    assert redact(text) == redact(text)
    assert redact(redact(text).text).redactions == 0


def test_fr4_placeholders_do_not_count_as_answer_text():
    only_contacts = "sam@example.com, pat@example.org, 07700 900123, https://example.com/a/b/c"
    result = redact(only_contacts)

    assert len(result.text) >= 30, "the placeholders alone are 30 characters or more"
    assert result.remaining_chars < 30
    assert result.remaining_chars == len(", , ,")


def test_fr4_remaining_characters_ignore_spare_whitespace():
    result = redact("I  asked\n\nthe   team   sam@example.com   ")
    assert result.remaining_chars == len("I asked the team")
