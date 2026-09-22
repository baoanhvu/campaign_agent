var TAB_PATHS = {
  dashboard: '/chien-dich',
  persona: '/chan-dung-kh',
  actions: '/hanh-dong-clv',
  chat: '/hoi-dap',
};
var PATH_TABS = {};
for (var k in TAB_PATHS) { PATH_TABS[TAB_PATHS[k]] = k; }

function appState() {
  return {
    tab: 'dashboard',
    dark: false,
    draft: '',
    sending: false,
    messages: [],
    dataRange: 'Dữ liệu: 01-31/08/2026',
    etlStatus: 'ETL: 2h trước',
    dashboard: { summary: {}, campaigns: [], funnel: [], trend: [] },
    segments: [],
    actions: [],

    conversations: [],
    currentSessionId: null,
    userId: null,
    currentES: null,

    init() {
      this.userId = localStorage.getItem('mkt_user_id');
      if (!this.userId) {
        this.userId = 'user-' + Date.now() + '-' + Math.random().toString(36).substr(2, 6);
        localStorage.setItem('mkt_user_id', this.userId);
      }
      this.loadConversations();
      this._parseUrl();
      var self = this;
      window.addEventListener('popstate', function() { self._parseUrl(); });
    },

    _parseUrl() {
      var path = window.location.pathname;
      var parts = path.replace(/^\/+|\/+$/g, '').split('/');
      if (parts[0] === 'hoi-dap' && parts[1]) {
        this.tab = 'chat';
        this.loadChat(parts[1]);
      } else if (PATH_TABS['/' + parts[0]]) {
        this.tab = PATH_TABS['/' + parts[0]];
      } else {
        this.tab = 'dashboard';
      }
    },

    switchTab(name) {
      this.tab = name;
      if (name === 'chat' && !this.currentSessionId) {
        this.messages = [];
      }
      var url = TAB_PATHS[name] || '/';
      window.history.pushState({tab: name}, '', url);
    },

    async loadConversations() {
      try {
        var res = await fetch('/api/conversations?user_id=' + encodeURIComponent(this.userId));
        var data = await res.json();
        this.conversations = data.conversations || [];
      } catch (e) { console.error('loadConversations failed', e); }
    },

    newChat() {
      this.currentSessionId = 'session-' + Date.now() + '-' + Math.random().toString(36).substr(2, 6);
      this.messages = [];
      this.tab = 'chat';
      window.history.pushState({tab: 'chat'}, '', '/hoi-dap');
    },

    async loadChat(sessionId) {
      this.currentSessionId = sessionId;
      this.messages = [];
      this.tab = 'chat';
      window.history.pushState({tab: 'chat', sessionId: sessionId}, '', '/hoi-dap/' + sessionId);
      try {
        var res = await fetch('/api/conversations/' + encodeURIComponent(sessionId) + '/messages');
        var data = await res.json();
        var msgs = data.messages || [];
        for (var i = 0; i < msgs.length; i++) {
          var m = msgs[i];
          if (m.role === 'user') {
            this.messages.push({ id: i, role: 'user', text: m.content });
          } else {
            var blocks = [{ seq: 1, html: renderMarkdown(m.content), verified: true, reason: null }];
            var trust = null;
            try {
              var saved = JSON.parse(m.content);
              if (saved.blocks) { blocks = saved.blocks; }
              if (saved.trust) { trust = saved.trust; }
            } catch (e) {}
            this.messages.push({ id: i, role: 'assistant', blocks: blocks, tables: [], stage: null, trust: trust, showEvidence: false, evidenceFacts: [] });
          }
        }
      } catch (e) { console.error('loadChat failed', e); }
    },

    async deleteChat(sessionId) {
      if (!confirm('Xóa cuộc trò chuyện này?')) return;
      try {
        await fetch('/api/conversations/' + encodeURIComponent(sessionId), { method: 'DELETE' });
        if (sessionId === this.currentSessionId) {
          this.messages = [];
          this.currentSessionId = null;
          window.history.pushState({tab: 'chat'}, '', '/hoi-dap');
        }
        this.loadConversations();
      } catch (e) { console.error('deleteChat failed', e); }
    },

    async loadDashboard() {
      try {
        const [s, c, f, t] = await Promise.all([
          fetch('/api/dashboard/summary').then(r => r.json()),
          fetch('/api/dashboard/campaigns').then(r => r.json()),
          fetch('/api/dashboard/funnel').then(r => r.json()),
          fetch('/api/dashboard/trend').then(r => r.json()),
        ]);
        this.dashboard = { summary: s, campaigns: c.rows || [], funnel: f.rows || [], trend: t.rows || [] };
        this.$nextTick(() => { renderCharts(this.dashboard); });
      } catch (e) { console.error('Dashboard load failed', e); }
    },

    async loadSegments() {
      try {
        const r = await fetch('/api/segments').then(r => r.json());
        this.segments = r.rows || [];
        this.$nextTick(() => { renderSegmentCharts(this.segments); });
      } catch (e) { console.error('Segments load failed', e); }
    },

    async loadActions() {
      try {
        const r = await fetch('/api/actions').then(r => r.json());
        this.actions = r.actions || [];
      } catch (e) { console.error('Actions load failed', e); }
    },

    exportActions() {
      var csv = ['action_id,segment,action_type,description,expected_revenue,confidence'];
      this.actions.forEach(function(a) {
        csv.push([a.action_id, a.segment, a.action_type, '"' + a.description + '"', a.expected_revenue, a.confidence].join(','));
      });
      var blob = new Blob([csv.join('\n')], { type: 'text/csv' });
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url; a.download = 'actions.csv'; a.click();
      URL.revokeObjectURL(url);
    },

    send() {
      if (!this.draft.trim()) return;
      if (this.currentES) { this.currentES.close(); this.currentES = null; }
      var question = this.draft.trim();
      this.draft = '';

      if (!this.currentSessionId) {
        this.currentSessionId = 'session-' + Date.now() + '-' + Math.random().toString(36).substr(2, 6);
      }
      var sessionId = this.currentSessionId;
      var isFirstMessage = this.messages.length === 0;

      this.messages.push({ id: Date.now(), role: 'user', text: question });
      this.messages.push({ id: Date.now() + 1, role: 'assistant', blocks: [], tables: [], stage: 'Đang xử lý...', trust: null, showEvidence: false, evidenceFacts: [], rawText: '' });
      var msg = this.messages[this.messages.length - 1];
      this.sending = true;
      console.log('[app] Sending:', question, 'session:', sessionId);

      var self = this;

      (async function() {
        try {
          await fetch('/api/conversations/' + encodeURIComponent(sessionId) + '/messages', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ role: 'user', content: question }),
          });
        } catch (e) { console.error('save user msg failed', e); }

        if (isFirstMessage) {
          try {
            var res = await fetch('/api/conversations', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ session_id: sessionId, user_id: self.userId, first_message: question }),
            });
            var data = await res.json();
            console.log('[app] Conversation created:', data);
            self.loadConversations();
            setTimeout(function() { self.loadConversations(); }, 12000);
          } catch (e) { console.error('create conversation failed', e); }
        }
      })();

      var url = '/api/chat?message=' + encodeURIComponent(question) + '&user_id=' + encodeURIComponent(this.userId) + '&session_id=' + encodeURIComponent(sessionId);
      var es = new EventSource(url);
      self.currentES = es;

      es.addEventListener('token', function(e) {
        var d = JSON.parse(e.data);
        msg.rawText = (msg.rawText || '') + (d.text || '');
        msg.stage = null;
        if (self.sending) { self.sending = false; }
        var displayText = substituteTags(msg.rawText, msg.tagMap || {});
        msg.blocks = [{ seq: 1, html: renderMarkdown(displayText), verified: true, reason: null }];
        scrollToBottom();
      });

      es.addEventListener('stage', function(e) {
        var d = JSON.parse(e.data);
        msg.stage = d.label;
        scrollToBottom();
      });

      es.addEventListener('plan', function(e) {
        var d = JSON.parse(e.data);
        msg.stage = 'Đã chọn ' + (d.metrics || []).length + ' chỉ số';
      });

      es.addEventListener('evidence', function(e) {
        var d = JSON.parse(e.data);
        msg.tagMap = d.tag_map || {};
        msg.stage = null;
      });

      es.addEventListener('table', function(e) {
        var d = JSON.parse(e.data);
        msg.tables.push(d);
        scrollToBottom();
      });

      es.addEventListener('block', function(e) {
        var d = JSON.parse(e.data);
        var htmlContent = '';
        var isVerified = d.verified;
        if (d.md) { htmlContent = renderMarkdown(d.md); isVerified = true; }
        else if (d.md_raw) { htmlContent = renderMarkdown(d.md_raw); isVerified = false; }
        if (htmlContent) {
          msg.blocks.push({ seq: d.seq, html: htmlContent, verified: isVerified, reason: d.reason });
        }
        scrollToBottom();
      });

      es.addEventListener('warning', function(e) {
        var d = JSON.parse(e.data);
        msg.blocks.push({ seq: 0, html: '<p class="text-amber-600">⚠ ' + (d.message || '') + '</p>', verified: true });
      });

      es.addEventListener('verified', function(e) {
        var d = JSON.parse(e.data);
        msg.trust = formatTrust(d);
        msg.stage = null;
      });

      es.addEventListener('judge', function(e) {
        var d = JSON.parse(e.data);
        if (msg.trust) { msg.trust = formatTrust(d); }
      });

      es.addEventListener('done', function(e) {
        var d = JSON.parse(e.data);
        msg.stage = null;
        es.close();
        self.currentES = null;
        self.sending = false;
        self.loadConversations();

        var saveData = JSON.stringify({
          rawText: msg.rawText || '',
          blocks: msg.blocks.map(function(b) { return { seq: b.seq, html: b.html, verified: b.verified, reason: b.reason }; }),
          trust: msg.trust
        });
        if (saveData.length > 2) {
          fetch('/api/conversations/' + encodeURIComponent(sessionId) + '/messages', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ role: 'assistant', content: saveData.substring(0, 10000) }),
          }).catch(function(e) { console.error('save agent msg failed', e); });
        }
      });

      es.addEventListener('error', function(e) {
        console.error('[chat] SSE error:', e);
        if (es.readyState === EventSource.CLOSED) {
          msg.stage = null;
          self.currentES = null;
          self.sending = false;
        }
      });
    },
  };
}

function scrollToBottom() {
  var el = document.getElementById('chat-scroll');
  if (el) {
    var atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50;
    if (atBottom) el.scrollTop = el.scrollHeight;
  }
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

function substituteTags(text, tagMap) {
  if (!tagMap) return text;
  var keys = Object.keys(tagMap);
  return text.replace(/\{\{([^}]+)\}\}/g, function(match, tag) {
    tag = tag.trim();
    if (tagMap[tag]) return tagMap[tag];
    var parts = tag.split('.');
    if (parts.length >= 3) {
      var fid = parts[0], col = parts[parts.length - 1];
      for (var i = 0; i < keys.length; i++) {
        var k = keys[i];
        if (k.startsWith(fid + '.') && k.endsWith('.' + col)) return tagMap[k];
      }
      for (var i = 0; i < keys.length; i++) {
        var k = keys[i];
        var kParts = k.split('.');
        if (kParts.length >= 3 && kParts[0] === fid && kParts[kParts.length - 1].indexOf(col) >= 0) return tagMap[k];
      }
    }
    return '—';
  });
}
