// Local directory study. Uses the same public API and language preference.
(function () {
  const COPY = {
    en: {
      photoCredit: 'Campus photographs:', campus: 'BIPH campus', campusAlt: 'Aerial view of the BIPH campus, with green-roofed buildings and blue sports courts', skip: 'Skip to teacher search', title: 'The teacher directory.',
      intro: 'Anonymous reviews from BIPH students.',
      subjects: 'Subjects', missing: 'Missing a teacher?',
      order: 'Alphabetical', reset: 'Clear filters', teacher: 'Teacher / course',
      subject: 'Subject', rating: 'Rating', reviews: 'Reviews',
      note: 'Every review is anonymous. Read a few to get the full picture.',
      all: 'All teachers', allSubjects: 'All subjects', results: 'Search results',
      count: n => `${n} listed`,
      review: n => n === 1 ? 'review' : 'reviews', noReviews: 'Not yet rated',
      ratingLabel: 'out of 5', retry: 'Try again',
    },
    zh: {
      photoCredit: '校园照片：', campus: 'BIPH 校园', campusAlt: 'BIPH 校园航拍图，展示绿顶教学楼与蓝色运动场', skip: '跳转到教师搜索', title: '教师名录。',
      intro: '来自 BIPH 学生的匿名评价。',
      subjects: '学科', missing: '没找到某位老师？',
      order: '按姓名排序', reset: '清除筛选', teacher: '教师 / 课程',
      subject: '学科', rating: '评分', reviews: '评价',
      note: '每条评价均为匿名。多读几条，了解更全面。',
      all: '所有教师', allSubjects: '所有学科', results: '搜索结果',
      count: n => `共 ${n} 位`, review: () => '条评价', noReviews: '暂无评分',
      ratingLabel: '满分 5 分', retry: '重试',
    },
  };
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

  function teacherRowHTML(t, lang, subject) {
    const copy = COPY[lang] || COPY.en;
    const rating = Number.isFinite(t.avg_rating) ? t.avg_rating.toFixed(2) : null;
    const normalize = value => String(value ?? '').trim().normalize('NFC').toLowerCase();
    const seen = new Set([normalize(subject), normalize(t.subject)]);
    const courses = Array.isArray(t.courses) ? t.courses.filter(value => {
      const key = normalize(value);
      if (!key || seen.has(key)) return false;
      seen.add(key);
      return true;
    }) : [];
    const course = courses.join(', ');
    const count = Number.isFinite(t.review_count) ? t.review_count : 0;
    const accessibleLabel = [t.name, subject, course, rating ? `${rating} ${copy.ratingLabel}` : copy.noReviews, `${count} ${copy.review(count)}`].filter(Boolean).join('. ');
    const metadata = [
      subject ? `<span class="teacher-row__subject">${escape(subject)}</span>` : '',
      course ? `<span class="teacher-row__course">${escape(course)}</span>` : '',
    ].filter(Boolean).join('<span aria-hidden="true"> · </span>');
    return `<a class="teacher-row" href="teacher.html?id=${encodeURIComponent(t.id)}" aria-label="${escape(accessibleLabel)}">
      <span class="teacher-row__identity"><span class="teacher-row__text"><span class="teacher-row__name">${escape(t.name)}</span>${metadata ? `<span class="teacher-row__meta">${metadata}</span>` : ''}</span></span>
      <span class="teacher-row__summary"><span class="teacher-row__score">${rating || copy.noReviews}${rating ? '<small> / 5</small>' : ''}</span><span class="teacher-row__reviews">${count} ${copy.review(count)}</span></span>
    </a>`;
  }

  function groupTeachersByInitial(rows) {
    const groups = [];
    rows.forEach(teacher => {
      const name = String(teacher.name ?? '').trim().normalize('NFC');
      const letter = (Array.from(name)[0] || '#').toUpperCase();
      let group = groups[groups.length - 1];
      // Keep consecutive groups so grouping never changes the API's ordering.
      if (!group || group.letter !== letter) {
        group = { letter, teachers: [] };
        groups.push(group);
      }
      group.teachers.push(teacher);
    });
    return groups;
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = { teacherRowHTML, groupTeachersByInitial };
    return;
  }

  const qInput = document.getElementById('q');
  const form = document.getElementById('searchForm');
  const chipsHost = document.getElementById('chips');
  const select = document.getElementById('subjectSelect');
  const grid = document.getElementById('grid');
  const empty = document.getElementById('empty');
  const loading = document.getElementById('loading');
  const counter = document.getElementById('resultCount');
  const heading = document.getElementById('resultsHeading');
  const reset = document.getElementById('resetFilters');
  const initial = new URLSearchParams(location.search);
  const state = { q: initial.get('q') || '', subject: initial.get('subject') || 'All', subjects: ['All'] };
  let lastRows = null;
  let counts = null;
  let requestId = 0;
  let debounce;
  let loadError = null;
  qInput.value = state.q;
  const copy = () => COPY[RB.getLang()] || COPY.en;

  function updateLabels() {
    document.querySelectorAll('[data-study]').forEach(el => { el.textContent = copy()[el.dataset.study]; });
    document.querySelectorAll('[data-study-alt]').forEach(el => { el.alt = copy()[el.dataset.studyAlt]; });
    heading.textContent = state.q ? copy().results : state.subject === 'All' ? copy().all : RB.localizeSubject(state.subject);
    reset.hidden = !state.q && state.subject === 'All';
    if (lastRows) counter.textContent = copy().count(lastRows.length);
  }

  function renderSubjects() {
    const focused = document.activeElement?.dataset.subject;
    chipsHost.replaceChildren();
    select.replaceChildren();
    state.subjects.forEach(subject => {
      const label = subject === 'All' ? copy().allSubjects : RB.localizeSubject(subject);
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'directory-subject';
      button.dataset.subject = subject;
      button.setAttribute('aria-pressed', String(subject === state.subject));
      const text = document.createElement('span');
      text.textContent = label;
      button.appendChild(text);
      if (counts && counts[subject] != null) {
        const count = document.createElement('span');
        count.className = 'directory-subject__count';
        count.textContent = counts[subject];
        count.setAttribute('aria-hidden', 'true');
        button.appendChild(count);
      }
      button.addEventListener('click', () => changeSubject(subject));
      chipsHost.appendChild(button);
      const option = document.createElement('option');
      option.value = subject;
      option.textContent = label;
      option.selected = subject === state.subject;
      select.appendChild(option);
      if (focused === subject) button.focus();
    });
  }

  function changeSubject(subject) {
    state.subject = subject;
    renderSubjects();
    clearTimeout(debounce);
    loadTeachers();
  }

  function renderRows(rows) {
    grid.replaceChildren();
    const appendEntries = (teachers, host) => {
      const list = document.createElement('div');
      list.className = 'directory-letter-entries';
      list.setAttribute('role', 'list');
      teachers.forEach(t => {
        const item = document.createElement('div');
        item.setAttribute('role', 'listitem');
        item.innerHTML = teacherRowHTML(t, RB.getLang(), RB.localizeSubject(t.subject));
        list.appendChild(item);
      });
      host.appendChild(list);
    };
    if (!state.q && state.subject === 'All') {
      groupTeachersByInitial(rows).forEach((group, index) => {
        const section = document.createElement('section');
        section.className = 'directory-letter-group';
        const letter = document.createElement('h3');
        letter.className = 'directory-letter';
        letter.id = `directory-letter-${index}`;
        letter.textContent = group.letter;
        section.setAttribute('aria-labelledby', letter.id);
        section.appendChild(letter);
        appendEntries(group.teachers, section);
        grid.appendChild(section);
      });
    } else {
      appendEntries(rows, grid);
    }
    empty.hidden = rows.length !== 0;
    if (!rows.length) empty.innerHTML = RB.t('home.empty.html');
    updateLabels();
  }

  function renderError() {
    empty.hidden = false;
    empty.textContent = RB.t('home.errLoading', { msg: loadError });
    const retry = document.createElement('button');
    retry.type = 'button'; retry.className = 'btn btn--ghost';
    retry.textContent = copy().retry;
    retry.addEventListener('click', loadTeachers);
    empty.appendChild(document.createElement('br'));
    empty.appendChild(retry);
  }

  async function loadTeachers() {
    const request = ++requestId;
    loadError = null;
    loading.hidden = false;
    grid.setAttribute('aria-busy', 'true');
    grid.replaceChildren();
    lastRows = null;
    counter.textContent = '';
    empty.hidden = true;
    updateLabels();
    const params = new URLSearchParams();
    if (state.q) params.set('q', state.q);
    if (state.subject !== 'All') params.set('subject', state.subject);
    history.replaceState(null, '', `${location.pathname}${params.size ? '?' + params : ''}`);
    try {
      const rows = await RB.api('/api/teachers' + (params.size ? '?' + params : ''));
      if (request !== requestId) return;
      lastRows = rows;
      if (!state.q && state.subject === 'All') {
        counts = { All: rows.length };
        rows.forEach(t => { if (t.subject) counts[t.subject] = (counts[t.subject] || 0) + 1; });
        renderSubjects();
      }
      renderRows(rows);
    } catch (e) {
      if (request !== requestId) return;
      loadError = e.message;
      renderError();
    } finally {
      if (request === requestId) {
        loading.hidden = true;
        grid.setAttribute('aria-busy', 'false');
      }
    }
  }

  async function loadSubjects() {
    try {
      const subjects = await RB.api('/api/subjects');
      state.subjects = ['All', ...subjects];
      if (!state.subjects.includes(state.subject)) {
        state.subject = 'All';
        loadTeachers();
      }
      renderSubjects();
    } catch (_) {
      // Ordinary search remains usable when the subject list is unavailable.
      renderSubjects();
    }
  }

  select.addEventListener('change', () => changeSubject(select.value));
  qInput.addEventListener('input', () => {
    state.q = qInput.value.trim();
    requestId += 1;
    clearTimeout(debounce);
    debounce = setTimeout(loadTeachers, 200);
  });
  form.addEventListener('submit', e => {
    e.preventDefault(); clearTimeout(debounce);
    state.q = qInput.value.trim(); loadTeachers();
  });
  reset.addEventListener('click', () => {
    state.q = ''; state.subject = 'All'; qInput.value = '';
    clearTimeout(debounce); renderSubjects(); loadTeachers(); qInput.focus();
  });
  document.addEventListener('rb:lang', () => {
    updateLabels(); renderSubjects();
    if (lastRows) renderRows(lastRows);
    if (loadError) renderError();
  });
  updateLabels(); renderSubjects(); loadSubjects(); loadTeachers();
})();
