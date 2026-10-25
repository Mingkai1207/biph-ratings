"""Display-only sensitive-word detection, including false-positive boundaries."""
import pytest

from backend.sensitive_words import comment_segments


@pytest.mark.parametrize("text, expected", [
    ("Good lessons, fucking hard tests.", ["fucking"]),
    ("SHIT! Helpful feedback, though.", ["SHIT"]),
    ("That is bullshit, but the notes help.", ["bullshit"]),
    ("Avoid shithole, shitholes, shitstorm, shitstorms, fuckup and fuckups.",
     ["shithole", "shitholes", "shitstorm", "shitstorms", "fuckup", "fuckups"]),
    ("A motherfucker and a fuckwit.", ["motherfucker", "fuckwit"]),
    ("Please do not use the slur faggot.", ["faggot"]),
    ("The phrase son of a bitch is an insult.", ["son of a bitch"]),
    ("老师是傻逼，但讲题很清楚。", ["傻逼"]),
    ("別說他媽的，課程很充實。", ["他媽的"]),
    ("不要说臭婊子或去你妈的。", ["臭婊子", "去你妈的"]),
    ("不要骂傻逼傻逼。", ["傻逼", "傻逼"]),
    ("这个fuck词不合适。", ["fuck"]),
    ("😀 ＦＵＣＫ！作业仍然有用。", ["ＦＵＣＫ"]),
    ("Bad: f\u200bu\u200cc\u200dk. Good: helpful.", ["f\u200bu\u200cc\u200dk"]),
    ("This is sh1t and b!tch is an insult.", ["sh1t", "b!tch"]),
    ("Do not write a$$hole or f.u.c.k.", ["a$$hole", "f.u.c.k"]),
    ("f u c k is spaced out; 傻 逼 too.", ["f u c k", "傻 逼"]),
    ("Please avoid f*ck, f**k and f***ing.", ["f*ck", "f**k", "f***ing"]),
    ("请勿说傻．逼。", ["傻．逼"]),
])
def test_only_matched_words_are_marked(text, expected):
    segments = comment_segments(text)
    assert [part["text"] for part in segments if part["sensitive"]] == expected
    assert "".join(part["text"] for part in segments) == text


@pytest.mark.parametrize("text", [
    "The class is strict, unfair and boring. This rule is stupid.",
    "老师很笨，有时很傻，但是讲义不错。",
    "class classic classification assistant assessment Scunthorpe Dickens",
    "The cock is a bird. Dick is a name. An ass is an animal.",
    "Biology covers sex education, penis, vagina and sexual health.",
    "Students can be gay, straight, Chinese, Jewish, Black or white.",
    "我妈妈的课讲过草、操作、干燥和脑科学。",
    "批评政策不等于攻击个人。",
    "Team SB studied an NM problem; cao is a surname.",
    "shittingly is not an explicitly listed inflection",
    "xshithole shitstorming fuckupdate are not whole-word matches",
    "dickens and scunthorpe appear next to shell and skill",
    "A single f, then an unrelated sentence, then u c k.",
    "\u200b\u200c\u200d",
    " \n\t ",
])
def test_benign_words_and_ordinary_criticism_remain_readable(text):
    assert comment_segments(text) == [{"text": text, "sensitive": False}]


@pytest.mark.parametrize("text", [None, ""])
def test_rating_only_comments_have_no_segments(text):
    assert comment_segments(text) == []


def test_unicode_positions_and_surrounding_punctuation_are_exact():
    text = "👩‍🏫 ﬀ notes\n  ＳＨＩＴ，but useful!\n傻逼？Not fair."
    assert comment_segments(text) == [
        {"text": "👩‍🏫 ﬀ notes\n  ", "sensitive": False},
        {"text": "ＳＨＩＴ", "sensitive": True},
        {"text": "，but useful!\n", "sensitive": False},
        {"text": "傻逼", "sensitive": True},
        {"text": "？Not fair.", "sensitive": False},
    ]


def test_cached_results_cannot_be_changed_by_a_caller():
    original = "fuck, but useful"
    first = comment_segments(original)
    first[0]["text"] = "changed"
    first.append({"text": "extra", "sensitive": False})
    assert "".join(part["text"] for part in comment_segments(original)) == original
