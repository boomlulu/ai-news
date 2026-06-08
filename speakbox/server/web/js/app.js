// speakbox front-end — vanilla JS, no build step.
(function () {
  "use strict";

  var tasks = {}; // id -> task object

  var els = {
    form: document.getElementById("task-form"),
    text: document.getElementById("text"),
    voice: document.getElementById("voice"),
    tone: document.getElementById("tone"),
    toneDel: document.getElementById("tone-del"),
    customTone: document.getElementById("customTone"),
    submit: document.getElementById("submit"),
    formError: document.getElementById("form-error"),
    count: document.getElementById("count"),
    list: document.getElementById("tasks"),
    conn: document.getElementById("conn"),
  };

  // ── tone presets + custom tones (localStorage) ──────────────────────────────
  var TONE_PRESETS = [
    { label: "默认（原声·不加情绪）", instruct: "" },
    { label: "恋人撒娇（奶声奶气·尾音拖长）", instruct: "像跟恋人撒娇那样，奶声奶气、娇滴滴地说，尾音拖长" },
    { label: "嗲嗲撒娇（慢而软）", instruct: "用嗲嗲的、撒娇黏人的语气，慢一点、软一点说" },
    { label: "温柔甜腻", instruct: "温柔甜腻，黏人撒娇，语速放慢，语气上扬" },
    { label: "开心活泼", instruct: "用开心、活泼、上扬的语气，语速稍快地说" },
    { label: "严肃播音", instruct: "用严肃、正式、沉稳的新闻播报语气说" },
  ];

  var CUSTOM_KEY = "speakbox_custom_tones";
  var TONE_CUSTOM_VALUE = "__custom__"; // value of the "✏️ 自定义…" option

  function loadCustomTones() {
    try {
      var raw = localStorage.getItem(CUSTOM_KEY);
      if (!raw) return [];
      var arr = JSON.parse(raw);
      if (!Array.isArray(arr)) return [];
      return arr.filter(function (s) { return typeof s === "string" && s.trim(); });
    } catch (err) {
      return [];
    }
  }

  function saveCustomTones(arr) {
    try {
      localStorage.setItem(CUSTOM_KEY, JSON.stringify(arr));
    } catch (err) {}
  }

  function truncate(s, n) {
    s = String(s);
    return s.length > n ? s.slice(0, n) + "…" : s;
  }

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

  // ── tone select: presets + saved customs + "custom…" entry ──────────────────
  function buildToneSelect() {
    els.tone.innerHTML = "";

    TONE_PRESETS.forEach(function (p) {
      var opt = document.createElement("option");
      opt.value = "preset:" + p.instruct; // unique enough; instruct read from dataset
      opt.textContent = p.label;
      opt.dataset.instruct = p.instruct;
      els.tone.appendChild(opt);
    });

    var customs = loadCustomTones();
    if (customs.length) {
      var group = document.createElement("optgroup");
      group.label = "我的自定义";
      group.id = "tone-custom-group";
      customs.forEach(function (instruct) {
        group.appendChild(makeCustomOption(instruct));
      });
      els.tone.appendChild(group);
    }

    var customEntry = document.createElement("option");
    customEntry.value = TONE_CUSTOM_VALUE;
    customEntry.textContent = "✏️ 自定义…";
    els.tone.appendChild(customEntry);
  }

  function makeCustomOption(instruct) {
    var opt = document.createElement("option");
    opt.value = "custom:" + instruct;
    opt.textContent = truncate(instruct, 24);
    opt.dataset.instruct = instruct;
    opt.dataset.saved = "1";
    return opt;
  }

  // Append a newly-saved custom into the optgroup (create the group if absent),
  // inserting before the "✏️ 自定义…" entry. Returns the new option.
  function addCustomToSelect(instruct) {
    var group = document.getElementById("tone-custom-group");
    if (!group) {
      group = document.createElement("optgroup");
      group.label = "我的自定义";
      group.id = "tone-custom-group";
      var entry = els.tone.querySelector('option[value="' + TONE_CUSTOM_VALUE + '"]');
      els.tone.insertBefore(group, entry);
    }
    var opt = makeCustomOption(instruct);
    group.appendChild(opt);
    return opt;
  }

  // Reflect UI state for the current tone selection: show/hide the custom input
  // and the delete button.
  function syncToneUI() {
    var sel = els.tone.options[els.tone.selectedIndex];
    var isCustomEntry = els.tone.value === TONE_CUSTOM_VALUE;
    var isSaved = sel && sel.dataset.saved === "1";

    els.customTone.hidden = !isCustomEntry;
    els.toneDel.hidden = !isSaved;
  }

  els.tone.addEventListener("change", syncToneUI);

  els.toneDel.addEventListener("click", function () {
    var sel = els.tone.options[els.tone.selectedIndex];
    if (!sel || sel.dataset.saved !== "1") return;
    var instruct = sel.dataset.instruct || "";

    var customs = loadCustomTones().filter(function (s) { return s !== instruct; });
    saveCustomTones(customs);

    var group = sel.parentNode;
    group.removeChild(sel);
    if (group.id === "tone-custom-group" && !group.querySelector("option")) {
      group.parentNode.removeChild(group);
    }
    els.tone.selectedIndex = 0; // fall back to default
    syncToneUI();
  });

  // Resolve the instruct string for the current selection.
  function currentInstruct() {
    if (els.tone.value === TONE_CUSTOM_VALUE) {
      return els.customTone.value.trim();
    }
    var sel = els.tone.options[els.tone.selectedIndex];
    return (sel && sel.dataset.instruct) || "";
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

    if (t.instruct) {
      html += '<div class="task-tone">语气：' + esc(truncate(t.instruct, 60)) + "</div>";
    }

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

    var instruct = currentInstruct();

    // If the user typed a fresh custom tone, persist + add it to the select.
    if (els.tone.value === TONE_CUSTOM_VALUE && instruct) {
      var customs = loadCustomTones();
      if (customs.indexOf(instruct) === -1) {
        customs.push(instruct);
        saveCustomTones(customs);
        var opt = addCustomToSelect(instruct);
        els.tone.value = opt.value; // select the now-saved tone
        els.customTone.value = "";
        syncToneUI();
      }
    }

    els.submit.disabled = true;
    fetch("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text, voice: voice, instruct: instruct }),
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
  buildToneSelect();
  syncToneUI();
  loadTasks();
  connect();
})();
