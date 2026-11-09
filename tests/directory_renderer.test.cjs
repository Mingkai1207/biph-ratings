const test = require('node:test');
const assert = require('node:assert/strict');
const { teacherRowHTML, groupTeachersByInitial } = require('../frontend/directory-study.js');

test('teacher data is escaped and only used as text or an encoded id', () => {
  const html = teacherRowHTML({id: 'a" onclick="bad()', name: '<img src=x onerror=bad()>', courses: ['<script>bad()</script>'], avg_rating: 4.25, review_count: 2}, 'en', '<svg onload=bad()>');
  assert.ok(!html.includes('<img'));
  assert.ok(!html.includes('<script'));
  assert.ok(!html.includes('<svg'));
  assert.ok(html.includes('&lt;img'));
  assert.ok(html.includes('id=a%22%20onclick%3D%22bad()'));
  assert.ok(html.includes('4.25 out of 5. 2 reviews"'));
  assert.ok(html.includes('aria-label="&lt;img'));
});

test('unrated teacher stays unrated, including in the Chinese accessible label', () => {
  const html = teacherRowHTML({ id: 'new', name: '新老师', avg_rating: null, review_count: 0, courses: [] }, 'zh', '数学');
  assert.ok(html.includes('aria-label="新老师. 数学. 暂无评分. 0 条评价"'));
  assert.ok(html.includes('teacher-row__score">暂无评分</span>'));
  assert.ok(html.includes('teacher-row__reviews">0 条评价</span>'));
  assert.ok(!html.includes('0.00'));
  assert.ok(!html.includes('teacher-row__course'));
});

test('course context stays literal and a singular review reads correctly', () => {
  const html = teacherRowHTML({id: 'one', name: 'A & B', courses: ['AP English', 'Writing'], avg_rating: 3, review_count: 1}, 'en', 'English');
  assert.ok(html.includes('A &amp; B'));
  assert.ok(html.includes('AP English, Writing'));
  assert.ok(html.includes('3.00 out of 5. 1 review"'));
  assert.ok(html.includes('aria-label="A &amp; B. English. AP English, Writing. 3.00 out of 5. 1 review"'));
  assert.ok(html.includes('teacher-row__reviews">1 review</span>'));
});

test('metadata avoids duplicate raw or translated subjects and preserves course context', () => {
  const html = teacherRowHTML({id: 'math', name: 'Teacher', subject: 'Math', courses: ['Math', '数学', 'Algebra', 'algebra', 'Geometry', 'Calculus'], avg_rating: 4.25, review_count: 12}, 'zh', '数学');
  assert.ok(html.includes('teacher-row__course">Algebra, Geometry, Calculus</span>'));
  assert.ok(html.includes('teacher-row__subject">数学</span>'));
  assert.ok(html.includes('teacher-row__score">4.25<small> / 5</small>'));
  assert.ok(html.includes('teacher-row__reviews">12 条评价</span>'));
});

test('initial grouping combines letter case without changing API order or the input', () => {
  const rows = [{name: ' alice'}, {name: 'Adam'}, {name: 'ben'}, {name: 'Amy'}];
  const groups = groupTeachersByInitial(rows);
  assert.deepEqual(groups.map(group => group.letter), ['A', 'B', 'A']);
  assert.deepEqual(groups.map(group => group.teachers.length), [2, 1, 1]);
  assert.deepEqual(groups.flatMap(group => group.teachers), rows);
  assert.equal(groups[0].teachers[0], rows[0]);
  assert.equal(rows[0].name, ' alice');
});

test('initial grouping handles composed accents, non-Latin and supplementary Unicode names', () => {
  const rows = [{name: 'e\u0301milie'}, {name: 'Éric'}, {name: '刘老师'}, {name: '𠀀老师'}, {name: ''}, {}];
  const groups = groupTeachersByInitial(rows);
  assert.deepEqual(groups.map(group => group.letter), ['É', '刘', '𠀀', '#']);
  assert.deepEqual(groups.map(group => group.teachers.length), [2, 1, 1, 2]);
  assert.deepEqual(groupTeachersByInitial([]), []);
});
