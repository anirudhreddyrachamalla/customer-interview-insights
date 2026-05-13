"""Canned data fixtures used across the backend test suite.

Contents:

- ``sample_interview.m4a`` — short real interview clip (currently 18.5 MB;
  may be shortened to <1 MB later). Used only by ``@pytest.mark.live`` tests.
- ``sample_transcript.json`` — canned AssemblyAI-shaped transcript.
- ``sample_pain_points.json`` — canned Claude pain-point output. Quotes
  appear verbatim in ``sample_transcript.json`` so the quote-in-transcript
  validator passes.
- ``sample_demographics.json`` — valid demographics blob.
"""
