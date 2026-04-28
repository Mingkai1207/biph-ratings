// Rate BIPH — shared frontend helpers. Vanilla JS, no framework.
(function () {
  const API = window.API_BASE || '';

  // ——— Fetch wrapper
  async function api(path, opts = {}) {
    const res = await fetch(API + path, {
      ...opts,
      headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    });
    const text = await res.text();
    const data = text ? JSON.parse(text) : null;
    if (!res.ok) {
      const err = new Error((data && (data.message || data.detail)) || res.statusText);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  // ——— i18n
  // Two-language toggle (EN ↔ 中文). User-entered content (teacher names,
  // subjects, courses, comments, suggestion bodies) is NEVER translated —
  // only chrome / labels / placeholders / system toasts.
  //
  // Static markup uses `data-i18n="key"` (textContent), `data-i18n-html="key"`
  // (innerHTML, for strings that contain markup like <em>), `data-i18n-placeholder`,
  // `data-i18n-title`, `data-i18n-aria-label`. Inline JS uses `RB.t('key', { param })`.
  // Per-page scripts that render dynamic content (review lists, cards) listen for
  // the `rb:lang` event on `document` and re-render.
  const I18N = {
    en: {
      // Nav
      'nav.browse':      'Browse',
      'nav.rankings':    'Rankings',
      'nav.compare':     'Compare',
      'nav.submit':      'Add a teacher',
      'nav.suggestions': 'Suggestions',
      'nav.admin':       'Admin',
      'nav.menu':        'Menu',
      // Footer
      'footer.body':     'Rate BIPH is student-run and independent of Beijing International Private High. Reviews are anonymous and moderated.<br/>Be kind. Be honest. Be specific.',
      // Relative time
      'time.today':      'today',
      'time.yesterday':  'yesterday',
      'time.justNow':    'just now',
      'time.mAgo':       '{n}m ago',
      'time.hAgo':       '{n}h ago',
      'time.dAgo':       '{n}d ago',
      'time.wAgo':       '{n}w ago',
      'time.moAgo':      '{n}mo ago',
      'time.yAgo':       '{n}y ago',
      'time.daysAgo':    '{n} days ago',
      'time.tomorrow':   'tomorrow',
      'time.inDays':     'in {n} days',
      // Common
      'common.cancel':   'Cancel',
      'common.save':     'Save',
      'common.saving':   'Saving…',
      'common.somethingWentWrong': 'Something went wrong.',

      // Home
      'home.pageTitle':           'Rate BIPH — anonymous teacher reviews',
      'home.hero.titleHtml':      'How is the teacher, <em>honestly</em>?',
      'home.hero.subtitle':       'Real reviews from BIPH students. Anonymous, unfiltered, kind when deserved.',
      'home.search.placeholder':  'Teacher name…',
      'home.search.go':           'Go',
      'home.search.smartAria':    'Ask in plain English',
      'home.search.smartHint':    'Click the sparkle to ask in plain English: "best math teacher", "easiest tests", "who gives the most homework"',
      'home.search.smartHintHtml': '<em>Or just ask:</em> <span class="hero__smart-hint__eg">"best math teacher"</span> · <span class="hero__smart-hint__eg">"easiest tests"</span> · <span class="hero__smart-hint__eg">"who gives the most homework"</span>',
      'home.smart.loading':       'Searching…',
      'home.smart.empty':         'Smart search returned no teachers. Try a different question.',
      'home.smart.error':         "Smart search couldn't run. Try a regular search instead.",
      'home.smart.clear':         'Clear smart search',
      'home.smart.fallback':      'Smart search is offline right now — showing keyword matches.',
      'home.chips.all':           'All',
      'home.empty.html':          'No teachers match that search. <a href="submit.html">Add one →</a>',
      'home.loading':             'Loading teachers…',
      'home.card.overall':        'overall rating',
      'home.card.noReviews':      'no reviews yet',
      'home.card.review':         'review',
      'home.card.reviews':        'reviews',
      'home.cursorHint':          'drag your cursor',
      'home.errLoading':          'Could not load teachers: {msg}',
      'home.card.wta':            '{n}% would take again',

      // Teacher detail
      'teacher.pageTitle':        'Rate BIPH — teacher profile',
      'teacher.back':             '← Back to roster',
      'teacher.notFound':         'Teacher not found.',
      'teacher.review.heading':   'What students said',
      'teacher.review.sortLabel': 'most liked first',
      'teacher.review.empty':     'No reviews yet. Be the first.',
      'teacher.review.noComment': 'No comment — rating only.',
      'teacher.basedOn':          'based on {n} anonymous reviews',
      'teacher.basedOnSingular':  'based on {n} anonymous review',
      'teacher.distribution':     'Teaching quality distribution',
      'teacher.metrics.teaching_quality': 'Teaching quality',
      'teacher.metrics.test_difficulty':  'Test difficulty',
      'teacher.metrics.homework_load':    'Homework load',
      'teacher.metrics.easygoingness':    'Easygoingness',
      'teacher.metrics.short.teaching_quality': 'Teaching',
      'teacher.metrics.short.test_difficulty':  'Test',
      'teacher.metrics.short.homework_load':    'Homework',
      'teacher.metrics.short.easygoingness':    'Easygoing',
      'teacher.courses.add':         '+ Add courses',
      'teacher.courses.placeholder': 'e.g. AP Calculus BC, Precalculus',
      'teacher.courses.note':        'Comma-separated. This locks once saved.',
      'teacher.courses.errEmpty':    'Enter at least one course.',
      'teacher.courses.errSave':     'Could not save.',
      'teacher.courses.saved':       'Courses saved.',
      'teacher.form.heading':        'Write a review',
      'teacher.form.commentPlaceholder': "What's the class actually like? Grading, pace, personality, anything specific that'd help the next student…",
      'teacher.form.submit':         'Post anonymously',
      'teacher.form.submitting':     'Posting…',
      'teacher.form.posted':         'Posted. Thanks for reviewing.',
      'teacher.form.missing':        'Pick a rating for "{label}".',
      'teacher.already.heading':     'You already reviewed this teacher',
      'teacher.already.ledeHtml':    'You posted {when} with a rating of <strong>{rating}/5</strong>. You can post another review {again}.',
      'teacher.voteFail':            'Could not save your vote.',
      'teacher.wta.question':        'Would you take this teacher again?',
      'teacher.wta.yes':             'Yes',
      'teacher.wta.no':              'No',
      'teacher.wta.skip':            'Skip',
      'teacher.wta.statsLabel':      'Would take again',
      'teacher.wta.statsCount':      '{n} said',
      'teacher.wta.statsCountOne':   '{n} said',
      'teacher.wta.statsNone':       'Not enough responses yet',
      'teacher.wta.badgeYes':        'Would take again',
      'teacher.wta.badgeNo':         "Wouldn't take again",
      'teacher.share.card':          'Share card',
      'teacher.share.qr':            'Print QR',
      'teacher.share.text':          'Honest reviews of {name} on Rate BIPH.',

      // Printable QR sheet
      'qrs.pageTitle':    'Rate BIPH — printable QR sheet',
      'qrs.back':         '← Back to roster',
      'qrs.eyebrow':      'PRINT-READY QR SHEET',
      'qrs.headingHtml':  'Printable <em>QR codes</em>.',
      'qrs.lede':         "One QR per teacher. Print this page, cut into cards, tape outside classrooms during course-selection week. Each QR takes students straight to that teacher's page.",
      'qrs.filter':       'Filter by name or subject…',
      'qrs.print':        'Print',
      'qrs.count':        '{n} teachers',
      'qrs.loading':      'Loading teachers…',
      'qrs.empty':        'No teachers match that filter.',
      'qrs.error':        "Couldn't load teachers. Try refreshing.",

      // Rankings
      'rank.pageTitle':           'Rate BIPH — rankings',
      'rank.eyebrow':             'LEADERBOARD',
      'rank.headingHtml':         'Teacher <em>rankings</em>.',
      'rank.lede':                "Sorted by student ratings. Only teachers with at least 3 reviews appear here — a single review isn't enough to rank on.",
      'rank.empty.heading':       'Not enough reviews yet',
      'rank.empty.body':          "Once a few teachers pick up 3+ reviews, they'll show up here.",
      'rank.review':              'review',
      'rank.reviews':             'reviews',
      'rank.metric.overall.label':  'Overall',
      'rank.metric.overall.note':   "Average across all 4 metrics. The default \"who's best overall\" view.",
      'rank.metric.teaching.label': 'Teaching quality',
      'rank.metric.teaching.note':  'Who students felt actually taught them the material well.',
      'rank.metric.easy.label':     'Easygoing',
      'rank.metric.easy.note':      'Relaxed vibe, not strict. Ranked high = chill class.',
      'rank.metric.tests.label':    'Hardest tests',
      'rank.metric.tests.note':     "Higher rating = harder tests. Useful if you're choosing how much you want to suffer.",
      'rank.metric.homework.label': 'Most homework',
      'rank.metric.homework.note':  "Higher rating = heavier workload. Useful if you're already drowning.",

      // Compare
      'compare.pageTitle':   'Rate BIPH — compare teachers',
      'compare.eyebrow':     'SIDE BY SIDE',
      'compare.headingHtml': 'Compare two <em>teachers</em>.',
      'compare.lede':        "Picking between two teachers for the same course? Stack their stats next to each other and decide.",
      'compare.pickA':       'Teacher A',
      'compare.pickB':       'Teacher B',
      'compare.placeholder': 'Pick a teacher…',
      'compare.viewProfile': 'View full profile →',
      'compare.empty':       'Pick two teachers above to see them side by side.',
      'compare.same':        'Pick two different teachers.',
      'compare.row.overall': 'Overall',
      'compare.row.reviews': 'Reviews',
      'compare.row.wta':     'Would take again',
      'compare.notEnough':   '—',

      // Submit
      'sub.pageTitle':       'Rate BIPH — add a teacher',
      'sub.eyebrow':         "CAN'T FIND SOMEONE?",
      'sub.headingHtml':     'Add a teacher to the <em>roster</em>.',
      'sub.lede':            'Submissions are reviewed by a student moderator and usually show up within a day. No photos, no personal contact info — just the basics.',
      'sub.name.label':      'Teacher name',
      'sub.name.hint':       'Full name as used at school',
      'sub.name.placeholder':'e.g. Daniel Huang',
      'sub.subject.label':   'Subject',
      'sub.subject.placeholder': 'Or type a subject…',
      'sub.courses.label':   'Courses',
      'sub.courses.hint':    'Optional. Comma-separated.',
      'sub.courses.placeholder': 'e.g. AP Calculus BC, Precalculus',
      'sub.submit':          'Submit for review',
      'sub.sending':         'Sending…',
      'sub.errShort':        'Teacher name looks too short.',
      'sub.success.title':   'Sent for review ✓',
      'sub.success.body':    'Thanks — a student moderator will take a look. Once approved, ',
      'sub.success.bodyTail':' will appear in the roster.',
      'sub.success.again':   'Submit another',
      'sub.success.back':    'Back to roster',

      // Suggestions
      'sug.pageTitle':       'Rate BIPH — suggestions',
      'sug.eyebrow':         'IDEAS FOR THE SITE',
      'sug.headingHtml':     'Suggestions <em>welcome</em>.',
      'sug.lede':            'Bug reports, missing teachers, features you want, things that feel off. Read by a student moderator. Your suggestion is private — only the admin account can see it.',
      'sug.body.label':      'Your suggestion',
      'sug.body.hint':       'Anonymous. At least 10 characters.',
      'sug.body.placeholder':"Be specific so we can actually act on it — what should change, what's broken, what you wish existed…",
      'sug.send':            'Send suggestion',
      'sug.sending':         'Sending…',
      'sug.errShort':        'Write at least 10 characters so we can act on it.',
      'sug.success.title':   'Sent ✓',
      'sug.success.body':    'Thanks for writing in. The moderator will read this. Suggestions are only visible to the admin account, not to other students.',
      'sug.success.again':   'Send another',
      'sug.success.back':    'Back to roster',

      // Admin
      'admin.pageTitle':     'Rate BIPH — admin',
      'admin.eyebrow':       'MODERATION',
      'admin.heading':       'Admin',
      'admin.lede':          'Token-gated tools for the student moderator. Approve teacher submissions or hide individual reviews.',
      'admin.token.label':   'Admin token',
      'admin.token.placeholder': 'Paste admin token',
      'admin.unlock':        'Unlock',
      'admin.invalid':       'Invalid token.',
      'admin.subs.title':    'Pending submissions',
      'admin.subs.refresh':  'Refresh',
      'admin.subs.empty':    'No pending submissions.',
      'admin.subs.approve':  'Approve',
      'admin.subs.reject':   'Reject',
      'admin.subs.approved': 'Approved',
      'admin.subs.rejected': 'Rejected',
      'admin.sugs.title':    'Suggestions inbox',
      'admin.sugs.showResolved': 'Show resolved',
      'admin.sugs.empty':    'No suggestions.',
      'admin.sugs.open':     'open',
      'admin.sugs.resolved': 'resolved {when}',
      'admin.sugs.markResolved': 'Mark resolved',
      'admin.sugs.reopen':   'Reopen',
      'admin.sugs.markedResolved': 'Marked resolved',
      'admin.sugs.reopened': 'Reopened',
      'admin.hide.title':    'Hide a review',
      'admin.hide.label':    'Review ID (UUID)',
      'admin.hide.placeholder': 'paste review id',
      'admin.hide.button':   'Hide review',
      'admin.hide.empty':    'Paste a review ID.',
      'admin.hide.toast':    'Review hidden',
      // Admin · Teachers section (rename / change subject)
      'admin.tabs.teachers':    'Teachers',
      'admin.tabs.subs':        'Submissions',
      'admin.tabs.sugs':        'Suggestions',
      'admin.tabs.tools':       'Tools',
      'admin.teachers.title':   'Edit teachers',
      'admin.teachers.lede':    'Click any name or subject to edit. Changes save when you click outside the field or press Enter.',
      'admin.teachers.search':  'Search teachers…',
      'admin.teachers.empty':   'No teachers match.',
      'admin.teachers.saved':   'Saved {name}',
      'admin.teachers.error':   'Could not save: {msg}',
      'admin.teachers.subjectMissing': 'no subject',
    },
    zh: {
      // Nav
      'nav.browse':      '浏览',
      'nav.rankings':    '排行榜',
      'nav.compare':     '对比',
      'nav.submit':      '添加老师',
      'nav.suggestions': '建议',
      'nav.admin':       '管理',
      'nav.menu':        '菜单',
      // Footer
      'footer.body':     'Rate BIPH 由学生独立运营，与北京君诚国际学校无任何关联。所有评价匿名提交并经过审核。<br/>请友善、诚实、具体。',
      // Relative time
      'time.today':      '今天',
      'time.yesterday':  '昨天',
      'time.justNow':    '刚刚',
      'time.mAgo':       '{n}分钟前',
      'time.hAgo':       '{n}小时前',
      'time.dAgo':       '{n}天前',
      'time.wAgo':       '{n}周前',
      'time.moAgo':      '{n}个月前',
      'time.yAgo':       '{n}年前',
      'time.daysAgo':    '{n}天前',
      'time.tomorrow':   '明天',
      'time.inDays':     '{n}天后',
      // Common
      'common.cancel':   '取消',
      'common.save':     '保存',
      'common.saving':   '保存中…',
      'common.somethingWentWrong': '出错了。',

      // Home
      'home.pageTitle':           'Rate BIPH — 匿名老师评价',
      'home.hero.titleHtml':      '这位老师怎么样，<em>说真的</em>？',
      'home.hero.subtitle':       'BIPH 学生写的真实评价。匿名、不过滤、该夸的时候就夸。',
      'home.search.placeholder':  '老师姓名…',
      'home.search.go':           '搜索',
      'home.search.smartAria':    '用自然语言提问',
      'home.search.smartHint':    '点击星星用自然语言提问："最好的数学老师"、"考试最简单"、"作业最多的老师"',
      'home.search.smartHintHtml': '<em>或者直接问：</em> <span class="hero__smart-hint__eg">"最好的数学老师"</span> · <span class="hero__smart-hint__eg">"考试最简单"</span> · <span class="hero__smart-hint__eg">"作业最多"</span>',
      'home.smart.loading':       '正在搜索…',
      'home.smart.empty':         '智能搜索没有找到老师。换一种问法试试？',
      'home.smart.error':         '智能搜索暂时无法运行，请用普通搜索。',
      'home.smart.clear':         '清除智能搜索',
      'home.smart.fallback':      '智能搜索暂不可用 — 已切换为关键词匹配。',
      'home.chips.all':           '全部',
      'home.empty.html':          '没找到匹配的老师。<a href="submit.html">添加一位 →</a>',
      'home.loading':             '加载中…',
      'home.card.overall':        '综合评分',
      'home.card.noReviews':      '暂无评价',
      'home.card.review':         '条评价',
      'home.card.reviews':        '条评价',
      'home.cursorHint':          '拖动你的鼠标',
      'home.errLoading':          '加载失败：{msg}',
      'home.card.wta':            '{n}% 愿意再选',

      // Teacher detail
      'teacher.pageTitle':        'Rate BIPH — 老师主页',
      'teacher.back':             '← 返回名单',
      'teacher.notFound':         '没找到这位老师。',
      'teacher.review.heading':   '学生怎么说',
      'teacher.review.sortLabel': '按点赞数排序',
      'teacher.review.empty':     '还没有评价。来当第一个。',
      'teacher.review.noComment': '没有评论 — 仅评分。',
      'teacher.basedOn':          '基于 {n} 条匿名评价',
      'teacher.basedOnSingular':  '基于 {n} 条匿名评价',
      'teacher.distribution':     '教学质量评分分布',
      'teacher.metrics.teaching_quality': '教学质量',
      'teacher.metrics.test_difficulty':  '考试难度',
      'teacher.metrics.homework_load':    '作业量',
      'teacher.metrics.easygoingness':    '好相处程度',
      'teacher.metrics.short.teaching_quality': '教学',
      'teacher.metrics.short.test_difficulty':  '考试',
      'teacher.metrics.short.homework_load':    '作业',
      'teacher.metrics.short.easygoingness':    '相处',
      'teacher.courses.add':         '+ 添加课程',
      'teacher.courses.placeholder': '例如：AP 微积分 BC、初等微积分',
      'teacher.courses.note':        '用逗号分隔。保存后无法修改。',
      'teacher.courses.errEmpty':    '至少填一门课程。',
      'teacher.courses.errSave':     '保存失败。',
      'teacher.courses.saved':       '课程已保存。',
      'teacher.form.heading':        '写一条评价',
      'teacher.form.commentPlaceholder': '这门课实际上怎么样？打分、节奏、老师风格，任何能帮到下一届学生的具体细节…',
      'teacher.form.submit':         '匿名发布',
      'teacher.form.submitting':     '发布中…',
      'teacher.form.posted':         '已发布。感谢你的评价。',
      'teacher.form.missing':        '请给「{label}」打分。',
      'teacher.already.heading':     '你已经评价过这位老师',
      'teacher.already.ledeHtml':    '你在 {when} 给出了 <strong>{rating}/5</strong> 的评分。{again}可以再发一条评价。',
      'teacher.voteFail':            '点赞/点踩保存失败。',
      'teacher.wta.question':        '你愿意再选这位老师的课吗？',
      'teacher.wta.yes':             '愿意',
      'teacher.wta.no':              '不愿意',
      'teacher.wta.skip':            '跳过',
      'teacher.wta.statsLabel':      '愿意再选',
      'teacher.wta.statsCount':      '{n} 人回答',
      'teacher.wta.statsCountOne':   '{n} 人回答',
      'teacher.wta.statsNone':       '回答还不够',
      'teacher.wta.badgeYes':        '愿意再选',
      'teacher.wta.badgeNo':         '不会再选',
      'teacher.share.card':          '分享卡片',
      'teacher.share.qr':            '打印二维码',
      'teacher.share.text':          '{name} 在 Rate BIPH 的真实评价。',

      // 可打印的二维码总表
      'qrs.pageTitle':    'Rate BIPH — 可打印二维码',
      'qrs.back':         '← 返回老师列表',
      'qrs.eyebrow':      '可打印二维码',
      'qrs.headingHtml':  '可打印的 <em>二维码</em>。',
      'qrs.lede':         '每位老师一个二维码。打印这页，剪成卡片，选课周贴在教室门口 — 扫码直达老师主页。',
      'qrs.filter':       '按姓名或科目筛选…',
      'qrs.print':        '打印',
      'qrs.count':        '共 {n} 位老师',
      'qrs.loading':      '加载中…',
      'qrs.empty':        '没有匹配的老师。',
      'qrs.error':        '加载失败，请刷新重试。',

      // Rankings
      'rank.pageTitle':           'Rate BIPH — 排行榜',
      'rank.eyebrow':             '排行榜',
      'rank.headingHtml':         '老师 <em>排行榜</em>。',
      'rank.lede':                '按学生评分排序。只显示至少 3 条评价的老师 — 单条评价不足以参与排名。',
      'rank.empty.heading':       '评价数还不够',
      'rank.empty.body':          '等到几位老师攒够 3 条以上评价，就会出现在这里。',
      'rank.review':              '条评价',
      'rank.reviews':             '条评价',
      'rank.metric.overall.label':  '综合',
      'rank.metric.overall.note':   '四项指标的平均值。默认的「整体最好」视图。',
      'rank.metric.teaching.label': '教学质量',
      'rank.metric.teaching.note':  '学生觉得真的把课讲明白了的老师。',
      'rank.metric.easy.label':     '好相处',
      'rank.metric.easy.note':      '氛围放松、不严苛。排名高 = 课堂轻松。',
      'rank.metric.tests.label':    '考试最难',
      'rank.metric.tests.note':     '评分越高 = 考试越难。如果你想选个虐自己的程度，可以参考。',
      'rank.metric.homework.label': '作业最多',
      'rank.metric.homework.note':  '评分越高 = 作业越重。如果你已经被作业淹没，可以参考。',

      // Compare
      'compare.pageTitle':   'Rate BIPH — 对比老师',
      'compare.eyebrow':     '左右对比',
      'compare.headingHtml': '对比两位<em>老师</em>。',
      'compare.lede':        '在同一门课的两位老师之间纠结？把他们的数据放在一起，自己判断。',
      'compare.pickA':       '老师 A',
      'compare.pickB':       '老师 B',
      'compare.placeholder': '选择一位老师…',
      'compare.viewProfile': '查看完整资料 →',
      'compare.empty':       '请在上方选择两位老师，即可对比查看。',
      'compare.same':        '请选择两位不同的老师。',
      'compare.row.overall': '总评',
      'compare.row.reviews': '评价数',
      'compare.row.wta':     '愿意再选',
      'compare.notEnough':   '—',

      // Submit
      'sub.pageTitle':       'Rate BIPH — 添加老师',
      'sub.eyebrow':         '没找到这位老师？',
      'sub.headingHtml':     '添加一位老师到 <em>名单</em>。',
      'sub.lede':            '提交后由学生管理员审核，通常一天内会出现在网站上。不收照片，不收个人联系方式 — 只要基本信息。',
      'sub.name.label':      '老师姓名',
      'sub.name.hint':       '学校里使用的全名',
      'sub.name.placeholder':'例如：Daniel Huang',
      'sub.subject.label':   '学科',
      'sub.subject.placeholder': '或者自己输入一个学科…',
      'sub.courses.label':   '课程',
      'sub.courses.hint':    '可选。用逗号分隔。',
      'sub.courses.placeholder': '例如：AP 微积分 BC、初等微积分',
      'sub.submit':          '提交审核',
      'sub.sending':         '提交中…',
      'sub.errShort':        '老师姓名太短了。',
      'sub.success.title':   '已提交审核 ✓',
      'sub.success.body':    '谢谢 — 学生管理员会看一下。审核通过后，',
      'sub.success.bodyTail':' 会出现在名单里。',
      'sub.success.again':   '再提交一位',
      'sub.success.back':    '返回名单',

      // Suggestions
      'sug.pageTitle':       'Rate BIPH — 建议',
      'sug.eyebrow':         '给网站提点想法',
      'sug.headingHtml':     '欢迎 <em>提建议</em>。',
      'sug.lede':            'Bug 反馈、缺失的老师、想要的功能、感觉不对劲的地方都行。学生管理员会看。你的建议是私密的 — 只有管理员账号能看到。',
      'sug.body.label':      '你的建议',
      'sug.body.hint':       '匿名。至少 10 个字符。',
      'sug.body.placeholder':'写得具体些我们才能真的去改 — 该改什么、哪里坏了、希望多一个什么功能…',
      'sug.send':            '发送建议',
      'sug.sending':         '发送中…',
      'sug.errShort':        '至少写 10 个字符，这样才好处理。',
      'sug.success.title':   '已发送 ✓',
      'sug.success.body':    '谢谢你写来。管理员会读到。建议只对管理员账号可见，其他学生看不到。',
      'sug.success.again':   '再发一条',
      'sug.success.back':    '返回名单',

      // Admin
      'admin.pageTitle':     'Rate BIPH — 管理',
      'admin.eyebrow':       '审核',
      'admin.heading':       '管理',
      'admin.lede':          '学生管理员的工具，需要 token。用于审核老师提交、隐藏单条评价。',
      'admin.token.label':   '管理员 token',
      'admin.token.placeholder': '粘贴管理员 token',
      'admin.unlock':        '解锁',
      'admin.invalid':       'Token 无效。',
      'admin.subs.title':    '待审核提交',
      'admin.subs.refresh':  '刷新',
      'admin.subs.empty':    '没有待审核的提交。',
      'admin.subs.approve':  '通过',
      'admin.subs.reject':   '拒绝',
      'admin.subs.approved': '已通过',
      'admin.subs.rejected': '已拒绝',
      'admin.sugs.title':    '建议收件箱',
      'admin.sugs.showResolved': '显示已处理',
      'admin.sugs.empty':    '没有建议。',
      'admin.sugs.open':     '未处理',
      'admin.sugs.resolved': '已处理 {when}',
      'admin.sugs.markResolved': '标为已处理',
      'admin.sugs.reopen':   '重新打开',
      'admin.sugs.markedResolved': '已标为已处理',
      'admin.sugs.reopened': '已重新打开',
      'admin.hide.title':    '隐藏一条评价',
      'admin.hide.label':    '评价 ID（UUID）',
      'admin.hide.placeholder': '粘贴评价 id',
      'admin.hide.button':   '隐藏评价',
      'admin.hide.empty':    '请粘贴评价 ID。',
      'admin.hide.toast':    '评价已隐藏',
      // Admin · Teachers section
      'admin.tabs.teachers':    '老师',
      'admin.tabs.subs':        '待审核',
      'admin.tabs.sugs':        '建议',
      'admin.tabs.tools':       '工具',
      'admin.teachers.title':   '编辑老师',
      'admin.teachers.lede':    '点击姓名或科目即可编辑。点击其他地方或按回车保存。',
      'admin.teachers.search':  '搜索老师…',
      'admin.teachers.empty':   '没有匹配的老师。',
      'admin.teachers.saved':   '已保存 {name}',
      'admin.teachers.error':   '保存失败：{msg}',
      'admin.teachers.subjectMissing': '未填科目',
    },
  };

  // Subject labels are stored in the DB in English (e.g. "Math", "Chemistry").
  // We translate only for display, never on the wire — filter params, teacher
  // submissions, and admin views all keep the English value so the DB stays
  // canonical. Subjects NOT in this map (user-typed or new additions) fall
  // through untranslated, which is the correct behavior.
  const SUBJECT_I18N = {
    zh: {
      'Arts':                  '艺术',
      'Arts/Art History':      '艺术 / 艺术史',
      'Band':                  '乐队',
      'Biology':               '生物',
      'Chemistry':             '化学',
      'Chinese':               '中文',
      'Choir':                 '合唱',
      'Computer Science':      '计算机科学',
      'Dean':                  '教务',
      'Drama':                 '戏剧',
      'Economics':             '经济',
      'English':               '英语',
      'Environmental Science': '环境科学',
      'History':               '历史',
      'Math':                  '数学',
      'Other':                 '其他',
      'Physics':               '物理',
      'STEM':                  'STEM',
      'Sports':                '体育',
      'Statistics':            '统计',
    },
  };
  function localizeSubject(s) {
    if (!s) return s;
    const lang = getLang();
    if (lang === 'en') return s;
    const map = SUBJECT_I18N[lang];
    return (map && map[s]) || s;
  }

  function getLang() {
    const v = (typeof localStorage !== 'undefined' && localStorage.getItem('rb.lang')) || '';
    return v === 'zh' ? 'zh' : 'en';
  }
  function t(key, params) {
    const dict = I18N[getLang()] || I18N.en;
    let s = dict[key];
    if (s == null) s = I18N.en[key];
    if (s == null) return key;
    if (params) {
      Object.keys(params).forEach(k => {
        s = s.replace(new RegExp('\\{' + k + '\\}', 'g'), String(params[k]));
      });
    }
    return s;
  }
  function setLang(lang) {
    if (lang !== 'en' && lang !== 'zh') return;
    try { localStorage.setItem('rb.lang', lang); } catch (_) {}
    document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
    applyI18n();
    document.dispatchEvent(new CustomEvent('rb:lang', { detail: { lang } }));
  }
  function applyI18n() {
    document.querySelectorAll('[data-i18n]').forEach(el => {
      el.textContent = t(el.getAttribute('data-i18n'));
    });
    document.querySelectorAll('[data-i18n-html]').forEach(el => {
      el.innerHTML = t(el.getAttribute('data-i18n-html'));
    });
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
      el.placeholder = t(el.getAttribute('data-i18n-placeholder'));
    });
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
      el.title = t(el.getAttribute('data-i18n-title'));
    });
    document.querySelectorAll('[data-i18n-aria-label]').forEach(el => {
      el.setAttribute('aria-label', t(el.getAttribute('data-i18n-aria-label')));
    });
    // Page <title>
    const pt = document.documentElement.getAttribute('data-i18n-page-title');
    if (pt) document.title = t(pt);
    // Update language toggle button label — show CURRENT language (click flips it)
    const langBtns = document.querySelectorAll('[data-lang-toggle]');
    langBtns.forEach(b => {
      const cur = getLang();
      b.textContent = cur === 'zh' ? '中文' : 'EN';
      b.setAttribute('aria-label', cur === 'zh' ? '切换到英文' : 'Switch to Chinese');
    });
  }

  // ——— Avatar helpers (hash name -> color from warm palette)
  const AVATAR_COLORS = [
    'oklch(0.85 0.08 70)',
    'oklch(0.86 0.07 110)',
    'oklch(0.84 0.09 40)',
    'oklch(0.86 0.06 170)',
    'oklch(0.84 0.08 20)',
    'oklch(0.87 0.06 150)',
    'oklch(0.85 0.09 85)',
    'oklch(0.83 0.08 55)',
  ];
  function hashString(s) {
    let h = 0;
    for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
    return Math.abs(h);
  }
  function avatarColor(name) {
    return AVATAR_COLORS[hashString(name) % AVATAR_COLORS.length];
  }
  function initials(name) {
    const parts = (name || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '?';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }
  function avatarEl(name, size = 44) {
    const el = document.createElement('div');
    el.className = 'avatar';
    el.style.width = size + 'px';
    el.style.height = size + 'px';
    el.style.borderRadius = size * 0.3 + 'px';
    el.style.fontSize = size * 0.42 + 'px';
    el.style.background = avatarColor(name);
    el.textContent = initials(name);
    return el;
  }

  // ——— Stars
  const STAR_PATH = 'M12 2.5l2.95 5.98 6.6.96-4.78 4.66 1.13 6.57L12 17.58l-5.9 3.1 1.13-6.58L2.45 9.44l6.6-.96L12 2.5z';
  function starSvg(kind, id, size) {
    const star = 'var(--star)';
    const empty = 'var(--line-strong)';
    let fill, stroke;
    if (kind === 'full') { fill = star; stroke = star; }
    else if (kind === 'half') { fill = `url(#h-${id})`; stroke = star; }
    else { fill = empty; stroke = empty; }
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" data-kind="${kind}">
      <defs><linearGradient id="h-${id}"><stop offset="50%" stop-color="${star}"/><stop offset="50%" stop-color="${empty}"/></linearGradient></defs>
      <path d="${STAR_PATH}" fill="${fill}" stroke="${stroke}" stroke-width="0.8" stroke-linejoin="round"/>
    </svg>`;
  }
  function renderStars(container, value, { size = 18, interactive = false, onChange } = {}) {
    // Build span wrappers ONCE and keep them stable. Only swap the inner SVG on hover/commit.
    // Rebuilding the DOM on every hover breaks touch taps: the emulated mouseenter destroys
    // the span mid-gesture, so the subsequent click event never fires. Keeping the spans
    // stable lets both desktop clicks and mobile taps register reliably.
    container.innerHTML = '';
    container.classList.add('stars');
    if (interactive) container.classList.add('stars--interactive');
    const id = 's' + Math.random().toString(36).slice(2, 7);
    let committed = value || 0;
    let hover = 0;

    const wraps = [];
    for (let i = 1; i <= 5; i++) {
      const wrap = document.createElement('span');
      wrap.style.display = 'inline-flex';
      wrap.style.cursor = interactive ? 'pointer' : 'default';
      wrap.dataset.idx = String(i);
      if (interactive) {
        const idx = i;
        // Use pointerenter (fires for both mouse and touch) plus mouseenter fallback.
        wrap.addEventListener('mouseenter', () => { hover = idx; paint(); });
        wrap.addEventListener('pointerenter', () => { hover = idx; paint(); });
        // pointerdown registers the commit on touch even before click fires.
        wrap.addEventListener('pointerdown', (e) => {
          if (e.pointerType === 'touch' || e.pointerType === 'pen') {
            if (onChange) onChange(idx);
          }
        });
        wrap.addEventListener('click', () => { if (onChange) onChange(idx); });
      }
      container.appendChild(wrap);
      wraps.push(wrap);
    }

    const paint = () => {
      const v = hover || committed;
      for (let i = 1; i <= 5; i++) {
        let kind = 'empty';
        if (i <= Math.floor(v)) kind = 'full';
        else if (i - 0.5 <= v) kind = 'half';
        wraps[i - 1].innerHTML = starSvg(kind, id + '-' + i, size);
      }
    };
    paint();

    if (interactive) {
      container.addEventListener('mouseleave', () => { hover = 0; paint(); });
      container.addEventListener('pointerleave', () => { hover = 0; paint(); });
      container.setValue = (v) => { committed = v; hover = 0; paint(); };
    }
  }

  // ——— Toast
  function toast(msg) {
    let el = document.querySelector('.toast');
    if (!el) {
      el = document.createElement('div');
      el.className = 'toast';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.add('toast--show');
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.remove('toast--show'), 3200);
  }

  // ——— Relative date
  function relDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d)) return '';
    // Clamp to 0 so a client with a clock behind the server's timestamp
    // doesn't render "-3m ago".
    const ms = Math.max(0, Date.now() - d.getTime());
    const mins = Math.floor(ms / 60000);
    const hours = Math.floor(ms / 3600000);
    const days = Math.floor(ms / 86400000);
    if (mins < 1)   return t('time.justNow');
    if (mins < 60)  return t('time.mAgo', { n: mins });
    if (hours < 24) return t('time.hAgo', { n: hours });
    if (days < 7)   return t('time.dAgo', { n: days });
    if (days < 30)  return t('time.wAgo', { n: Math.floor(days / 7) });
    if (days < 365) return t('time.moAgo', { n: Math.floor(days / 30) });
    return t('time.yAgo', { n: Math.floor(days / 365) });
  }

  // ——— Turnstile loader (resilient: if sitekey missing, Cloudflare blocked,
  // or api.js never fully initializes, we give up gracefully and let the user
  // submit anyway — backend still has rate limiting + IP hashing.)
  let turnstileLoaded = false;
  function loadTurnstile() {
    if (turnstileLoaded) return;
    turnstileLoaded = true;
    // Wipe any stub that extensions / earlier failed loads left behind.
    if (window.turnstile && typeof window.turnstile.render !== 'function') {
      try { delete window.turnstile; } catch (_) { window.turnstile = undefined; }
    }
    const s = document.createElement('script');
    s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
    s.async = true; s.defer = true;
    s.onerror = () => { console.warn('[turnstile] api.js failed to load'); };
    document.head.appendChild(s);
  }
  function mountTurnstile(slot, onToken) {
    if (!slot || !window.TURNSTILE_SITEKEY) {
      if (slot) slot.style.display = 'none';
      return;
    }
    loadTurnstile();
    const started = Date.now();
    const MAX_WAIT = 6000;
    const tryRender = () => {
      const ready = window.turnstile && typeof window.turnstile.render === 'function';
      if (ready) {
        try {
          window.turnstile.render(slot, {
            sitekey: window.TURNSTILE_SITEKEY,
            callback: (t) => onToken(t),
            'error-callback': () => { slot.style.display = 'none'; console.warn('[turnstile] widget error'); },
          });
          return;
        } catch (e) {
          console.warn('[turnstile] render threw', e);
          slot.style.display = 'none';
          return;
        }
      }
      if (Date.now() - started > MAX_WAIT) {
        // Gave up — hide the empty slot so the form doesn't look broken.
        slot.style.display = 'none';
        console.warn('[turnstile] never became ready after ' + MAX_WAIT + 'ms — submit will proceed without captcha');
        return;
      }
      setTimeout(tryRender, 200);
    };
    tryRender();
  }

  // ——— Topnav helper (logo + links + language toggle)
  // Desktop: inline link row. Mobile (≤640px): hamburger button + collapsible
  // panel. The hamburger / panel elements are always in the DOM; CSS shows
  // them only below 640px. JS just toggles aria-expanded.
  function renderTopnav(active) {
    const host = document.querySelector('[data-topnav]');
    if (!host) return;
    const link = (href, id, key) =>
      `<a href="${href}" class="topnav__link"${active===id?' aria-current="page"':''} data-i18n="${key}">${t(key)}</a>`;
    const links = [
      link('index.html',       'home',        'nav.browse'),
      link('rankings.html',    'rankings',    'nav.rankings'),
      link('compare.html',     'compare',     'nav.compare'),
      link('submit.html',      'submit',      'nav.submit'),
      link('suggestions.html', 'suggestions', 'nav.suggestions'),
      // Admin link is always visible in the nav. Clicking lands on the
      // token-gated admin page — non-admins just see the login screen.
      link('admin.html',       'admin',       'nav.admin'),
    ].join('');
    // Language toggle — shown in THREE positions so it's always reachable:
    // 1. Inline in the desktop link row (hidden on mobile via .topnav__links display:none)
    // 2. Standalone in the top bar on mobile, next to the hamburger (desktop hides it)
    // 3. Inside the mobile hamburger panel (for users who've already opened it)
    // All three share `data-lang-toggle` and get wired to the same setLang flip.
    const cur = getLang();
    // Button shows the CURRENT language, not the target. Click flips it.
    const langLabel = cur === 'zh' ? '中文' : 'EN';
    const langAria  = cur === 'zh' ? '切换到英文' : 'Switch to Chinese';
    const langBtnInline = `<button type="button" class="topnav__lang" data-lang-toggle aria-label="${langAria}">${langLabel}</button>`;
    const langBtnMobile = `<button type="button" class="topnav__lang topnav__lang--mobile" data-lang-toggle aria-label="${langAria}">${langLabel}</button>`;
    host.innerHTML = `
      <div class="topnav">
        <div class="topnav__inner">
          <a href="index.html" class="logo">
            <span class="logo__mark">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <rect x="6" y="13.5" width="10" height="1.4" rx="0.7" fill="oklch(0.98 0.01 75)"/>
                <rect x="6" y="16.5" width="7" height="1.4" rx="0.7" fill="oklch(0.98 0.01 75)"/>
                <path d="M13.5 9.8l3.6-3.6a1 1 0 0 1 1.4 0l1 1a1 1 0 0 1 0 1.4l-3.6 3.6-2.6.6.2-3z" fill="oklch(0.98 0.01 75)"/>
              </svg>
            </span>
            <span class="logo__word">Rate <em>BIPH</em></span>
          </a>
          <div class="topnav__links">${links}${langBtnInline}</div>
          ${langBtnMobile}
          <button class="topnav__toggle" type="button" data-i18n-aria-label="nav.menu" aria-label="${t('nav.menu')}" aria-expanded="false" data-topnav-toggle>
            <span></span><span></span><span></span>
          </button>
        </div>
        <div class="topnav__panel" data-topnav-panel hidden>${links}${langBtnInline}</div>
      </div>`;
    const toggle = host.querySelector('[data-topnav-toggle]');
    const panel = host.querySelector('[data-topnav-panel]');
    if (toggle && panel) {
      toggle.addEventListener('click', () => {
        const open = toggle.getAttribute('aria-expanded') === 'true';
        toggle.setAttribute('aria-expanded', open ? 'false' : 'true');
        panel.hidden = open;
      });
      // Tapping a link closes the panel
      panel.querySelectorAll('.topnav__link').forEach(a => {
        a.addEventListener('click', () => {
          toggle.setAttribute('aria-expanded', 'false');
          panel.hidden = true;
        });
      });
    }
    // Wire every language toggle (top bar + mobile panel).
    host.querySelectorAll('[data-lang-toggle]').forEach(btn => {
      btn.addEventListener('click', () => {
        setLang(getLang() === 'zh' ? 'en' : 'zh');
      });
    });
  }

  function renderFooter() {
    const host = document.querySelector('[data-footer]');
    if (!host) return;
    host.innerHTML = `<footer class="footer">
      <div data-i18n-html="footer.body">${t('footer.body')}</div>
    </footer>`;
  }

  window.RB = {
    api, renderStars, avatarEl, initials, avatarColor, toast, relDate,
    mountTurnstile, renderTopnav, renderFooter,
    t, getLang, setLang, applyI18n, localizeSubject,
  };
  document.addEventListener('DOMContentLoaded', () => {
    document.documentElement.lang = getLang() === 'zh' ? 'zh-CN' : 'en';
    renderTopnav(document.body.dataset.page);
    renderFooter();
    applyI18n();
  });
})();
