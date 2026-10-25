// Run with: node --test tests/comment_renderer.test.cjs
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function renderer(language = 'en') {
  const context = {
    window: {},
    document: { addEventListener() {} },
    localStorage: { getItem: () => language },
  };
  vm.runInNewContext(
    fs.readFileSync(path.join(__dirname, '../frontend/app.js'), 'utf8'),
    context,
  );
  return context.window.RB.renderComment;
}

test('only matched words become blurred placeholders; surrounding writing survives', () => {
  const html = renderer()({
    comment: 'The class was fucking hard.\n这个傻逼很不公平。🙂',
    comment_segments: [
      { text: 'The class was ', sensitive: false },
      { text: 'fucking', sensitive: true },
      { text: ' hard.\n这个', sensitive: false },
      { text: '傻逼', sensitive: true },
      { text: '很不公平。🙂', sensitive: false },
    ],
  });
  assert.equal((html.match(/class="review-word-mask"/g) || []).length, 2);
  assert.ok(html.startsWith('The class was '));
  assert.ok(html.includes(' hard.\n这个'));
  assert.ok(html.endsWith('很不公平。🙂'));
  assert.ok(!html.includes('fucking'));
  assert.ok(!html.includes('傻逼'));
  assert.ok(html.includes('role="img" aria-label="Sensitive word blurred"'));
  assert.ok(html.includes('aria-hidden="true"'));
});

test('review text is never interpreted as HTML, even around a masked word', () => {
  const html = renderer()({
    comment_segments: [
      { text: '<img src=x onerror="alert(1)"> & \'', sensitive: false },
      { text: '"><script>alert(1)</script>', sensitive: true },
    ],
  });
  assert.ok(html.startsWith('&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &amp; &#39;'));
  assert.ok(!html.includes('<img'));
  assert.ok(!html.includes('<script'));
});

test('Chinese accessible text explains the blur without exposing the word', () => {
  const html = renderer('zh')({ comment_segments: [{ text: '混蛋', sensitive: true }] });
  assert.ok(html.includes('aria-label="敏感词已模糊处理"'));
  assert.ok(!html.includes('混蛋'));
});

test('ordinary criticism and empty/rating-only reviews keep their existing display', () => {
  const render = renderer();
  assert.equal(render({ comment_segments: [{ text: 'Strict, unfair & boring. 笨。', sensitive: false }] }), 'Strict, unfair &amp; boring. 笨。');
  assert.equal(render({ comment: null, comment_segments: [] }), '');
  assert.equal(render({ comment: '' }), '');
  assert.equal(render({ comment: '<legacy comment>' }), '&lt;legacy comment&gt;');
});
