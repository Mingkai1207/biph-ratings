"""
Synthetic review generator. Replaces the base44 imports with reviews that
preserve each teacher's STATISTICAL profile (rating distribution, would-
take-again ratio, has-comment ratio) but compose comment TEXT from a
fresh fragment pool authored here — no base44 sentence is ever surfaced.

Why this design (vs. remixing the base44 corpus): an earlier version
shuffled real base44 sentences, which preserved authenticity but also
made the lineage obvious. Switched to a curated fragment pool so the
output reads like generic-but-natural Chinese student commentary,
calibrated to each teacher's rating profile, with no recognizable
overlap with any base44 review.

Each generated comment composes 0-3 fragments drawn from sentiment-
keyed pools (positive / neutral / negative for each of the four metrics),
plus optional opener and closer connectors. Subject-specific lexical
hints add texture for the most common BIPH subjects.
"""
from __future__ import annotations

import random
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone


# Per-metric, per-sentiment fragment pools. Each fragment is a complete
# stand-alone clause that can be the entire comment OR concatenated with
# others via the connectors below. Bias is toward Chinese (matches the
# audience) with occasional English mix-ins (BIPH is international).
_FRAGS_TEACHING_HIGH = [
    "讲课很清晰", "教得真的好", "知识点讲得明白", "上课能跟得上",
    "节奏把握得不错", "讲解很有条理", "课堂效率高", "重点抓得准",
    "讲得很细致", "概念解释得到位", "上课不会让人犯困", "讲课有逻辑",
    "讲得通透", "听得懂", "上课很有干货", "解题思路讲得清楚",
    "really clear", "explains things well", "good lectures",
]
_FRAGS_TEACHING_MID = [
    "讲课还行", "教得一般", "讲得过得去", "课讲得不算差",
    "节奏一般般", "讲得没那么细", "中规中矩", "听课要靠自己再消化",
    "课堂内容没特别突出", "教学风格偏传统",
]
_FRAGS_TEACHING_LOW = [
    "讲课比较跳", "节奏跟不太上", "讲得有点散", "听课需要专注",
    "重点不太突出", "上课容易走神", "讲解不够细", "得自己课后补",
    "课堂效率不高", "讲课不够清楚", "听不太进去",
]

_FRAGS_TEST_HARD = [
    "考试比较难", "题目挺有挑战", "卷子有难度", "考试要认真准备",
    "题型不简单", "考试容易翻车", "需要刷题", "卷子量也不小",
    "考试拉分", "考前最好多花时间",
]
_FRAGS_TEST_MID = [
    "考试难度适中", "考试还行", "考试不算难也不算简单",
    "卷子中规中矩", "考试照着复习就行",
]
_FRAGS_TEST_EASY = [
    "考试相对简单", "题目不算难", "卷子不刁钻",
    "考前看一遍能过", "考试基础题为主", "考试压力不大",
]

_FRAGS_HW_HEAVY = [
    "作业量挺大", "课后任务不少", "作业占时间", "作业偏多",
    "需要每周花时间", "homework比较密", "作业要赶",
    "课后要花精力", "deadline比较紧",
]
_FRAGS_HW_MID = [
    "作业量适中", "作业不多不少", "课后任务正常",
    "homework还行",
]
_FRAGS_HW_LIGHT = [
    "作业不多", "课后压力不大", "homework比较少",
    "作业量轻", "课外负担小", "不会有太多课后任务",
]

_FRAGS_EASY_HIGH = [
    "人特别好", "脾气好", "好相处", "对学生很友好",
    "课堂氛围轻松", "为人随和", "比较幽默", "和同学关系不错",
    "上课氛围不紧张", "nice", "approachable", "愿意和学生聊天",
    "下课会陪学生聊", "情绪稳定",
]
_FRAGS_EASY_MID = [
    "比较中性", "不太亲近也不太严肃",
    "标准的老师风格", "保持距离感",
]
_FRAGS_EASY_LOW = [
    "比较严格", "要求高", "课堂上比较严肃",
    "对作业要求严", "不太能开玩笑", "氛围有点紧",
    "对纪律比较看重", "strict",
]


# Generic openers / connectors / closings. Sometimes empty so the comment
# starts directly with a fragment (more natural than always prefixing).
_OPENERS = ["", "", "", "", "整体来说", "讲真", "感觉", "我觉得",
            "整体感觉", "上过一年", "上过他/她课", "选了之后"]
_CONNECTORS = ["，", "，", "。", "，但是", "，不过", "，而且",
               "。另外，", "。还有，", " ", "，"]
_CLOSINGS = ["", "", "", "", "", "整体推荐", "想试试可以选", "看自己情况",
             "适合认真学的同学", "适合想轻松点的", "选之前可以打听一下",
             "建议早做功课", "都还可以"]


# Subject-keyed lexical hints — small fragments that make a comment feel
# subject-specific without naming any particular teacher. Used sparingly
# (one per comment, max) to add texture.
_SUBJECT_HINTS = {
    "Math": ["公式讲得清楚", "题型覆盖全", "推导过程讲得细", "概念要靠多刷题"],
    "English": ["essay反馈很认真", "writing 要求细", "vocab 抓得紧", "reading 节奏适合"],
    "Science": ["实验环节有意思", "课堂演示到位", "理论联系实际"],
    "Physics": ["公式推导讲得清楚", "题型变化多", "概念图画得好"],
    "Chemistry": ["反应机理讲得透", "实验讲得细", "记忆量不小"],
    "Biology": ["术语多但讲得清", "图表讲解到位", "需要背的不少"],
    "Chinese": ["课文讲得到位", "古文部分讲得细", "作文反馈认真"],
    "History": ["史料补充丰富", "脉络清晰", "题型偏论述"],
    "Economics": ["案例分析好", "图表讲得清", "概念实用"],
    "Arts": ["创作空间大", "反馈具体", "课堂氛围放松"],
    "PE": ["训练强度合理", "课堂气氛好", "项目多样"],
    "Humanities": ["讨论环节多", "文本分析细", "鼓励独立思考"],
    "Languages": ["对话练习多", "口语进步明显", "词汇量上得快"],
}


def _bucket(avg: float, *, inverse: bool = False) -> str:
    """Map a 1-5 average to high/mid/low. `inverse=True` flips the mapping
    for "harder/heavier-is-not-better" metrics — though we use the raw
    rating direction here (high homework_load = lots of homework, regardless
    of whether students prefer it).
    """
    if avg is None:
        return "mid"
    if avg >= 4.0:
        return "high"
    if avg <= 2.5:
        return "low"
    return "mid"


def _build_per_teacher_corpus(rows: list[dict], teacher_subjects: dict | None = None) -> dict:
    """Group rows by teacher_id and pre-compute the statistical profile we
    need: rating averages, distributions, wta ratio, has-comment ratio,
    and subject (passed in for hints).
    """
    by_t = defaultdict(list)
    for r in rows:
        by_t[r["teacher_id"]].append(r)

    corpus = {}
    for tid, reviews in by_t.items():
        with_comment = 0
        wta_yes = wta_no = wta_null = 0
        ratings = {
            "teaching_quality": [],
            "test_difficulty": [],
            "homework_load": [],
            "easygoingness": [],
        }
        for r in reviews:
            for k in ratings:
                if r.get(k) is not None:
                    ratings[k].append(int(r[k]))
            if r.get("comment") and r["comment"].strip():
                with_comment += 1
            wta = r.get("would_take_again")
            if wta == 1 or wta is True:
                wta_yes += 1
            elif wta == 0 or wta is False:
                wta_no += 1
            else:
                wta_null += 1

        total = len(reviews)
        averages = {
            k: (sum(v) / len(v) if v else None) for k, v in ratings.items()
        }
        corpus[tid] = {
            "n": total,
            "ratings": ratings,
            "averages": averages,
            "wta_yes": wta_yes,
            "wta_no": wta_no,
            "wta_null": wta_null,
            "p_has_comment": with_comment / total if total else 0.0,
            "subject": (teacher_subjects or {}).get(tid),
        }
    return corpus


def _sample_rating(pool: list[int]) -> int:
    if not pool:
        return 3
    return random.choice(pool)


def _sample_wta(c: dict):
    total = c["wta_yes"] + c["wta_no"] + c["wta_null"]
    if total == 0:
        return None
    pick = random.random() * total
    if pick < c["wta_yes"]:
        return 1
    if pick < c["wta_yes"] + c["wta_no"]:
        return 0
    return None


def _pool_for(metric: str, bucket: str) -> list[str]:
    return {
        ("teaching_quality", "high"): _FRAGS_TEACHING_HIGH,
        ("teaching_quality", "mid"): _FRAGS_TEACHING_MID,
        ("teaching_quality", "low"): _FRAGS_TEACHING_LOW,
        ("test_difficulty", "high"): _FRAGS_TEST_HARD,
        ("test_difficulty", "mid"): _FRAGS_TEST_MID,
        ("test_difficulty", "low"): _FRAGS_TEST_EASY,
        ("homework_load", "high"): _FRAGS_HW_HEAVY,
        ("homework_load", "mid"): _FRAGS_HW_MID,
        ("homework_load", "low"): _FRAGS_HW_LIGHT,
        ("easygoingness", "high"): _FRAGS_EASY_HIGH,
        ("easygoingness", "mid"): _FRAGS_EASY_MID,
        ("easygoingness", "low"): _FRAGS_EASY_LOW,
    }[(metric, bucket)]


def _generate_comment(c: dict) -> str | None:
    """Compose a comment from sentiment-keyed fragments matching the
    teacher's rating profile. ~30% of generated reviews skip the comment
    entirely (matching the original ratings-only ratio in base44)."""
    if random.random() > c["p_has_comment"]:
        return None

    avgs = c["averages"]
    # Pick which metrics to mention. Bias toward metrics with extreme
    # buckets — students are more likely to comment on what stood out.
    metric_buckets = [
        ("teaching_quality", _bucket(avgs.get("teaching_quality"))),
        ("test_difficulty", _bucket(avgs.get("test_difficulty"))),
        ("homework_load", _bucket(avgs.get("homework_load"))),
        ("easygoingness", _bucket(avgs.get("easygoingness"))),
    ]
    # Weight: extreme buckets twice as likely to be picked
    weighted = []
    for m, b in metric_buckets:
        weighted.append((m, b))
        if b in ("high", "low"):
            weighted.append((m, b))

    n_frags = random.choices([1, 2, 2, 3], weights=[3, 5, 4, 2])[0]
    chosen_metrics = random.sample(weighted, min(n_frags, len(weighted)))
    # Dedupe — same metric shouldn't appear twice even if it weighted in.
    seen = set()
    pool_picks = []
    for m, b in chosen_metrics:
        if m in seen:
            continue
        seen.add(m)
        pool_picks.append(random.choice(_pool_for(m, b)))

    # Subject hint: small chance to add one piece of subject-specific
    # texture so generic-feeling comments feel grounded in the actual class.
    if c.get("subject") and c["subject"] in _SUBJECT_HINTS and random.random() < 0.25:
        pool_picks.append(random.choice(_SUBJECT_HINTS[c["subject"]]))
        random.shuffle(pool_picks)

    # Build the sentence with random connectors. Opener and closing are
    # also optional so output doesn't have a uniform shape.
    opener = random.choice(_OPENERS)
    closing = random.choice(_CLOSINGS)
    parts: list[str] = []
    for i, frag in enumerate(pool_picks):
        if i == 0:
            if opener:
                parts.append(opener + ("，" if not opener.endswith(("，", "。")) else "") + frag)
            else:
                parts.append(frag)
        else:
            connector = random.choice(_CONNECTORS)
            if connector.strip() in ("", "，", "。"):
                # Glueing connector — append directly
                parts[-1] = parts[-1].rstrip("。") + connector + frag
            else:
                parts[-1] = parts[-1].rstrip("。") + connector + frag

    sentence = "".join(parts)
    if closing:
        sentence = sentence.rstrip("。") + "。" + closing
    # Always end on a sentence terminator.
    if sentence and sentence[-1] not in "。！？.!?":
        sentence += "。"
    return sentence


def _scatter_created_at(now: datetime) -> str:
    """Random datetime in the last 5 days (NEVER earlier than that). Stored
    in SQLite's default text format for compat with the rest of the schema.
    """
    seconds_ago = random.randint(0, 5 * 86400)
    when = now - timedelta(seconds=seconds_ago)
    return when.strftime("%Y-%m-%d %H:%M:%S")


def plan_per_teacher(corpus: dict, target_total: int) -> dict:
    total_orig = sum(c["n"] for c in corpus.values())
    if total_orig == 0:
        return {}
    plan = {}
    for tid, c in corpus.items():
        proportional = c["n"] / total_orig * target_total
        plan[tid] = max(1, round(proportional))
    return plan


def generate_reviews(
    rows: list[dict], target_total: int, *,
    seed: int | None = None,
    teacher_subjects: dict | None = None,
) -> list[dict]:
    """Produce a list of fully-formed review dicts ready for INSERT.
    `teacher_subjects` is a {teacher_id: subject} map used for subject-
    specific lexical hints. Pass `seed` for deterministic output (used
    by tests)."""
    if seed is not None:
        random.seed(seed)
    corpus = _build_per_teacher_corpus(rows, teacher_subjects=teacher_subjects)
    plan = plan_per_teacher(corpus, target_total)
    now = datetime.now(timezone.utc)
    out = []
    for tid, n in plan.items():
        c = corpus[tid]
        for _ in range(n):
            out.append({
                "id": uuid.uuid4().hex,
                "teacher_id": tid,
                "teaching_quality": _sample_rating(c["ratings"]["teaching_quality"]),
                "test_difficulty": _sample_rating(c["ratings"]["test_difficulty"]),
                "homework_load": _sample_rating(c["ratings"]["homework_load"]),
                "easygoingness": _sample_rating(c["ratings"]["easygoingness"]),
                "would_take_again": _sample_wta(c),
                "comment": _generate_comment(c),
                "ip_hash": None,
                "source": "ai_generated",
                "legacy_id": None,
                "is_visible": 1,
                "created_at": _scatter_created_at(now),
            })
    return out
