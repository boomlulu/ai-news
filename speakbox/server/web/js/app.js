// speakbox front-end — vanilla JS, no build step.
(function () {
  "use strict";

  var tasks = {}; // id -> task object

  var els = {
    form: document.getElementById("task-form"),
    text: document.getElementById("text"),
    voice: document.getElementById("voice"),
    tone: document.getElementById("tone"),
    toneSave: document.getElementById("tone-save"),
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
  var editingOrig = null; // original instruct of the saved custom being edited (null = new)

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

  // Reflect UI state for the current tone selection: show/hide the custom input,
  // the save button (new vs edit) and the delete button. Also tracks editingOrig.
  function syncToneUI() {
    var sel = els.tone.options[els.tone.selectedIndex];
    var isCustomEntry = els.tone.value === TONE_CUSTOM_VALUE;
    var isSaved = sel && sel.dataset.saved === "1";

    if (isCustomEntry) {
      // "✏️ 自定义…": empty editable input, "保存" creates a new tone.
      els.customTone.hidden = false;
      els.customTone.value = "";
      els.toneSave.hidden = false;
      els.toneSave.textContent = "💾 保存";
      els.toneDel.hidden = true;
      editingOrig = null;
    } else if (isSaved) {
      // A saved custom: prefill its instruct, "保存修改" updates it, del removes.
      els.customTone.hidden = false;
      els.customTone.value = sel.dataset.instruct || "";
      els.toneSave.hidden = false;
      els.toneSave.textContent = "💾 保存修改";
      els.toneDel.hidden = false;
      editingOrig = sel.dataset.instruct || "";
    } else {
      // Preset / default: no editing affordances.
      els.customTone.hidden = true;
      els.toneSave.hidden = true;
      els.toneDel.hidden = true;
      editingOrig = null;
    }
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

  // Select the saved-custom option whose instruct matches `text`; if none, fall
  // back to the first option (default).
  function selectToneByInstruct(text) {
    var opts = els.tone.options;
    for (var i = 0; i < opts.length; i++) {
      if (opts[i].dataset.saved === "1" && opts[i].dataset.instruct === text) {
        els.tone.selectedIndex = i;
        return;
      }
    }
    els.tone.selectedIndex = 0;
  }

  // Persist the current input text as a custom tone. When editing an existing
  // saved tone (editingOrig set and changed), replace it; otherwise add it.
  // Rebuilds the select and re-selects the persisted tone.
  function persistCustom() {
    var text = els.customTone.value.trim();
    if (!text) return;
    var customs = loadCustomTones();
    if (editingOrig && editingOrig !== text) {
      customs = customs.filter(function (s) { return s !== editingOrig; });
    }
    if (customs.indexOf(text) === -1) customs.push(text);
    saveCustomTones(customs);
    buildToneSelect();
    selectToneByInstruct(text);
    editingOrig = text;
    syncToneUI();
  }

  els.toneSave.addEventListener("click", persistCustom);

  // Resolve the instruct string for the current selection. For both the
  // "✏️ 自定义…" entry and a saved custom, read the live (possibly edited) input.
  function currentInstruct() {
    var sel = els.tone.options[els.tone.selectedIndex];
    if (els.tone.value === TONE_CUSTOM_VALUE || (sel && sel.dataset.saved === "1")) {
      return els.customTone.value.trim();
    }
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

    // Auto-save the custom tone on submit: a freshly typed one is added, an
    // edited saved one is replaced. persistCustom reads the live input value.
    var sel = els.tone.options[els.tone.selectedIndex];
    var isCustomCtx =
      els.tone.value === TONE_CUSTOM_VALUE || (sel && sel.dataset.saved === "1");
    if (isCustomCtx && instruct) {
      persistCustom();
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
