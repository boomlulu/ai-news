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

  // ── tasks: initial fetch + incremental upsert ───────────────────────────────
  function loadTasks() {
    fetch("/api/tasks")
      .then(function (r) { return r.json(); })
      .then(function (list) {
        (list || []).forEach(function (t) {
          tasks[t.id] = t;
          upsert(t);
        });
        ensureEmpty();
      })
      .catch(function () {});
  }

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // Returns the inner HTML of a task row (no <li> wrapper).
  function rowInner(t) {
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
      html +=
        '<div class="actions">' +
        '<audio class="player" controls preload="none" src="/api/tasks/' + t.id + '/wav"></audio>' +
        '<a class="dl" href="/api/tasks/' + t.id + '/wav">下载 WAV</a>' +
        "</div>";
    }
    if (t.status === "failed" && t.error) {
      html += '<div class="err-line">' + esc(t.error) + "</div>";
    }
    return html;
  }

  function makeRow(t) {
    var li = document.createElement("li");
    li.className = "task";
    li.setAttribute("data-id", t.id);
    li.setAttribute("data-created", t.created_at);
    li.setAttribute("data-status", t.status);
    li.innerHTML = rowInner(t);
    return li;
  }

  // Insert/update a single row without touching others. Terminal (done) rows
  // are never rebuilt, so a playing <audio> is preserved.
  function upsert(t) {
    var empty = els.list.querySelector("li.empty");
    if (empty) empty.parentNode.removeChild(empty);

    var existing = els.list.querySelector('li[data-id="' + t.id + '"]');
    if (existing) {
      if (existing.dataset.status === "done") return; // terminal — keep audio alive
      existing.dataset.status = t.status;
      existing.innerHTML = rowInner(t);
      return;
    }

    var li = makeRow(t);
    // Insert by created_at DESC (newest first); tie-break by id DESC.
    var rows = els.list.querySelectorAll("li.task");
    for (var i = 0; i < rows.length; i++) {
      var r = rows[i];
      var rc = r.getAttribute("data-created");
      var rid = Number(r.getAttribute("data-id"));
      if (rc < t.created_at || (rc === t.created_at && rid < t.id)) {
        els.list.insertBefore(li, r);
        return;
      }
    }
    els.list.appendChild(li);
  }

  function ensureEmpty() {
    if (els.list.querySelector("li.task")) {
      var empty = els.list.querySelector("li.empty");
      if (empty) empty.parentNode.removeChild(empty);
    } else if (!els.list.querySelector("li.empty")) {
      els.list.innerHTML = '<li class="empty">暂无任务</li>';
    }
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
        upsert(t);
        ensureEmpty();
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
        // The created task arrives via SSE upsert; no full refresh needed.
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
