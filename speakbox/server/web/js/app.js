// speakbox front-end — vanilla JS, no build step.
(function () {
  "use strict";

  var tasks = {}; // id -> task object

  var els = {
    form: document.getElementById("task-form"),
    text: document.getElementById("text"),
    voice: document.getElementById("voice"),
    submit: document.getElementById("submit"),
    formError: document.getElementById("form-error"),
    count: document.getElementById("count"),
    list: document.getElementById("tasks"),
    conn: document.getElementById("conn"),
  };

  var STATUS_LABEL = {
    pending: "排队中",
    generating: "生成中",
    uploading: "上传中",
    done: "已完成",
    failed: "失败",
  };

  // ── voices ────────────────────────────────────────────────────────────────
  function loadVoices() {
    fetch("/api/voices")
      .then(function (r) { return r.json(); })
      .then(function (list) {
        els.voice.innerHTML = "";
        list.forEach(function (v) {
          var opt = document.createElement("option");
          opt.value = v.id;
          opt.textContent = v.label;
          els.voice.appendChild(opt);
        });
      })
      .catch(function () {});
  }

  // ── tasks: initial fetch + render ───────────────────────────────────────────
  function loadTasks() {
    fetch("/api/tasks")
      .then(function (r) { return r.json(); })
      .then(function (list) {
        tasks = {};
        (list || []).forEach(function (t) { tasks[t.id] = t; });
        render();
      })
      .catch(function () {});
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function render() {
    var ids = Object.keys(tasks).map(Number);
    ids.sort(function (a, b) {
      var ta = tasks[a].created_at, tb = tasks[b].created_at;
      if (ta !== tb) return ta < tb ? 1 : -1;
      return b - a;
    });

    if (ids.length === 0) {
      els.list.innerHTML = '<li class="empty">暂无任务</li>';
      return;
    }

    els.list.innerHTML = "";
    ids.forEach(function (id) {
      els.list.appendChild(renderTask(tasks[id]));
    });
  }

  function renderTask(t) {
    var li = document.createElement("li");
    li.className = "task";

    var statusLabel = STATUS_LABEL[t.status] || t.status;
    var html =
      '<div class="task-top">' +
      '<span class="task-text">#' + t.id + " " + esc(t.text) + "</span>" +
      '<span class="badge badge-' + t.status + '">' + statusLabel + "</span>" +
      "</div>" +
      '<div class="task-meta">' + esc(t.voice) + " · " + esc(t.created_at) + "</div>";

    if (t.status === "generating" || t.status === "uploading" || t.status === "pending") {
      html +=
        '<div class="bar"><div class="bar-fill" style="width:' +
        (t.progress || 0) + '%"></div></div>';
    }
    if (t.status === "done") {
      html += '<a class="dl" href="/api/tasks/' + t.id + '/wav">下载 WAV</a>';
    }
    if (t.status === "failed" && t.error) {
      html += '<div class="err-line">' + esc(t.error) + "</div>";
    }

    li.innerHTML = html;
    return li;
  }

  // ── SSE live updates ────────────────────────────────────────────────────────
  function connect() {
    var es = new EventSource("/api/events");

    es.onopen = function () {
      els.conn.textContent = "实时连接";
      els.conn.className = "conn conn-on";
    };
    es.onerror = function () {
      els.conn.textContent = "重连中…";
      els.conn.className = "conn conn-off";
    };
    es.addEventListener("task", function (e) {
      try {
        var t = JSON.parse(e.data);
        tasks[t.id] = t;
        render();
      } catch (err) {}
    });
  }

  // ── submit ──────────────────────────────────────────────────────────────────
  els.text.addEventListener("input", function () {
    els.count.textContent = String(els.text.value.length);
  });

  els.form.addEventListener("submit", function (e) {
    e.preventDefault();
    els.formError.textContent = "";

    var text = els.text.value.trim();
    var voice = els.voice.value;
    if (!text) {
      els.formError.textContent = "请输入文本";
      return;
    }

    els.submit.disabled = true;
    fetch("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text, voice: voice }),
    })
      .then(function (r) {
        return r.json().then(function (body) { return { ok: r.ok, body: body }; });
      })
      .then(function (res) {
        if (!res.ok) {
          els.formError.textContent = res.body.error || "提交失败";
          return;
        }
        els.text.value = "";
        els.count.textContent = "0";
        // The created task arrives via SSE; fall back to a refresh if needed.
        loadTasks();
      })
      .catch(function () {
        els.formError.textContent = "网络错误";
      })
      .finally(function () {
        els.submit.disabled = false;
      });
  });

  // ── boot ────────────────────────────────────────────────────────────────────
  loadVoices();
  loadTasks();
  connect();
})();
