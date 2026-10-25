# Sensitive-word display filter

The public teacher review list and the author's recent-review notice use
`comment_segments` supplied by the backend. Only matched words are blurred.
The database comment, existing API `comment` field, ratings, votes, visibility,
submission validation, and authenticated moderation view stay unchanged. Keeping
`comment` unchanged also preserves the original-text contract used by
`scripts/sync_prod.py`. This is display moderation, not a restriction on API
access to original text.

Detection runs when reviews are read, so existing reviews, new reviews and Base44
imports receive the same treatment without a database migration or destructive
rewrite. Null/empty comments have an empty segment list. Concatenating segment
text reproduces the original exactly, including emoji, line breaks and case.

## Word list

Edit `backend/sensitive_words.json` and redeploy to update the list:

- `english`: clear profanity, slurs and explicit sexual insults, with explicit
  common inflections. Whole-word boundaries avoid matching ordinary words such
  as *class*, *assistant*, *assessment*, *Scunthorpe* and *Dickens*.
- `english_literal_aliases`: common already-obscured spellings, matched literally.
- `chinese`: explicit multi-character terms, with simplified and traditional
  variants listed separately.

Ordinary criticism (*strict*, *unfair*, *boring*) and mild insults such as
*stupid*, *笨* and *傻* are not in the default list. Identity words, political
terms, medical vocabulary, ambiguous single Chinese characters, pinyin initials
and standalone English words such as *ass*, *cock* and *dick* are intentionally
excluded to limit false positives. Some listed slurs also have uncommon benign
meanings; a dictionary cannot infer the writer's intention or distinguish quotes.

Matching ignores case, folds compatibility/fullwidth characters, and ignores
Unicode format characters such as zero-width spaces. It catches a limited set
of common letter substitutions (`sh1t`, `a$$hole`) and up to two simple separators
between letters (`f.u.c.k`, `傻 逼`). It does not attempt fuzzy matching, arbitrary
Unicode-confusable detection or semantic moderation. No AI or external service
receives comment content. Changes to the list should include both positive and
false-positive regression examples in `tests/test_sensitive_words.py`.

Test: `./venv/bin/python -m pytest`.
