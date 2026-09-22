function renderMarkdown(md) {
  if (!md) return '';
  try {
    if (typeof marked !== 'undefined') {
      marked.setOptions({ breaks: true, gfm: true });
      var html = marked.parse(md);
      if (typeof DOMPurify !== 'undefined') {
        html = DOMPurify.sanitize(html);
      }
      return html;
    }
  } catch (e) {
    console.error('renderMarkdown error:', e);
  }
  return md.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
}

async function askSSE(state, question, msg) {
  const userId = 'user-' + Math.random().toString(36).substr(2, 8);
  const sessionId = 'session-' + Date.now();
  console.log('[chat] Starting SSE for:', question);
  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
        'X-GreenNode-AgentBase-User-Id': userId,
        'X-GreenNode-AgentBase-Session-Id': sessionId,
      },
      body: JSON.stringify({ message: question, history: [] }),
    });
    console.log('[chat] Response status:', res.status, 'Content-Type:', res.headers.get('content-type'));

    if (!res.body) {
      console.error('[chat] No response body stream');
      msg.blocks.push({ seq: 0, html: '<p>Không nhận được dữ liệu từ server.</p>', verified: false, reason: 'no_stream' });
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let eventType = 'message';
    let eventCount = 0;

    while (true) {
      const { done, value } = await reader.read();
      if (done) { console.log('[chat] Stream done. Total events:', eventCount); break; }
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split('\n');
      buf = lines.pop() || '';
      for (const line of lines) {
        if (line === '') { continue; }
        if (line.startsWith('event:')) {
          eventType = line.slice(6).trim();
        } else if (line.startsWith('data:')) {
          const dataStr = line.slice(5).trim();
          if (!dataStr) continue;
          try {
            const data = JSON.parse(dataStr);
            eventCount++;
            handleSSEEvent(state, msg, eventType, data);
          } catch (e) {
            console.error('[chat] JSON parse error for event:', eventType, e, dataStr.substring(0, 200));
          }
        } else if (line.startsWith(':')) {
          // SSE comment/keep-alive — ignore
        }
      }
    }
    scrollToBottom(state);
  } catch (e) {
    console.error('[chat] SSE fetch error:', e);
    msg.blocks.push({ seq: 0, html: '<p class="text-red-600">Lỗi kết nối: ' + e.message + '</p>', verified: false, reason: 'fetch_error' });
  }
}

function handleSSEEvent(state, msg, event, data) {
  switch (event) {
    case 'stage':
      msg.stage = data.label;
      break;
    case 'plan':
      msg.stage = 'Đã chọn ' + (data.metrics || []).length + ' chỉ số';
      break;
    case 'evidence':
      msg.stage = null;
      break;
    case 'table':
      msg.tables.push(data);
      break;
    case 'block':
      var htmlContent = '';
      var isVerified = data.verified;
      if (data.md) {
        htmlContent = renderMarkdown(data.md);
        isVerified = true;
      } else if (data.md_raw) {
        htmlContent = renderMarkdown(data.md_raw);
        isVerified = false;
      }
      if (htmlContent) {
        msg.blocks.push({ seq: data.seq, html: htmlContent, verified: isVerified, reason: data.reason });
        console.log('[chat] Block', data.seq, 'verified:', isVerified, 'len:', htmlContent.length);
      }
      break;
    case 'warning':
      msg.blocks.push({ seq: 0, html: '<p class="text-amber-600">⚠ ' + (data.message || '') + '</p>', verified: true });
      break;
    case 'verified':
      msg.trust = formatTrust(data);
      msg.stage = null;
      console.log('[chat] Verified:', data.band, 'trust:', data.trust);
      break;
    case 'judge':
      if (msg.trust) { msg.trust = formatTrust(data); }
      break;
    case 'done':
      msg.stage = null;
      console.log('[chat] Done:', data);
      break;
    case 'error':
      msg.blocks.push({ seq: 0, html: '<p class="text-red-600">Lỗi: ' + (data.message || '') + '</p>', verified: false });
      console.error('[chat] Server error:', data);
      break;
  }
  scrollToBottom(state);
}

function formatTrust(data) {
  var band = data.band || 'ABSTAIN';
  var emojis = { PASS: '🟢', HEDGE: '🟡', ABSTAIN: '⚪', BLOCKED: '🔴' };
  var labels = { PASS: 'Đã kiểm chứng', HEDGE: 'Hạn chế tin cậy', ABSTAIN: 'Từ chối', BLOCKED: 'Bị chặn' };
  var checks = data.checks || {};
  var okCount = 0, totalCount = 0;
  for (var k in checks) { totalCount++; if (checks[k].passed) okCount++; }
  return { emoji: emojis[band] || '⚪', label: labels[band] || '', detail: okCount + '/' + totalCount + ' kiểm tra đạt' };
}

function scrollToBottom(state) {
  var el = document.getElementById('chat-scroll');
  if (el) {
    var atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50;
    if (atBottom) el.scrollTop = el.scrollHeight;
  }
}
