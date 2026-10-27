/* SCPro 前端：状态渲染 + scpro:// 命令发送 */

const state = {
  hosts: [],
  projects: [],
  currentHost: "",
  selected: new Set(),
  running: false,
  assets: {},
  hostQuery: "",
  projectQuery: "",
  lang: "zh",
  failed: [],
  deleteRemote: false,
};

let panelHeight = 228;
let dragProjectId = null;

const I18N = {
  zh: {
    "app.title": "SCPro",
    "tab.projects": "项目", "tab.hosts": "Hosts", "tab.log": "输出", "tab.settings": "设置",
    "hosts.header": "HOSTS", "hosts.search": "搜索 Host…", "hosts.settings": "Host 设置",
    "hosts.refresh": "从 ~/.ssh/config 刷新", "hosts.title": "Host 设置",
    "hosts.ignore": "忽略名单（每行一个通配模式，如 *-host）",
    "hosts.ports": "端口（留空或与原值相同表示使用 ssh_config）",
    "host.warning": "没有项目规则匹配该 Host",
    "host.password_ok": "密码已配置", "host.password_missing": "未配置密码",
    "host.no_host": "没有可用 Host",
    "host.status_online": "在线", "host.status_offline": "离线",
    "host.status_unknown": "未测试",
    "row.no_rule": "— 该 Host 无对应规则",
    "act.edit": "编辑…",
    "act.copy": "复制项目", "act.delete": "删除项目",
    "btn.new": "＋ 新建项目", "btn.passwords": "密码",
    "btn.test": "测试连接", "btn.run": "上传选中", "btn.run_n": "上传选中（%d）",
    "btn.test_short": "测试", "menu.more": "更多操作",
    "btn.cancel": "取消", "btn.ok": "确定", "btn.save": "保存",
    "col.project_route": "项目 / 部署路径", "col.actions": "操作",
    "route.local": "本地", "route.remote": "远端",
    "project.search": "搜索项目…", "project.empty": "没有匹配的项目",
    "panel.output": "输出", "panel.search": "筛选日志…",
    "panel.show": "显示输出", "panel.hide": "隐藏输出",
    "filter.all": "全部", "filter.problem": "只看问题",
    "filter.progress": "只看进度", "filter.info": "只看信息",
    "panel.autoscroll": "自动滚动", "panel.logdir": "日志目录",
    "panel.clear": "清空", "panel.stop": "停止",
    "status.ready": "就绪", "status.running": "执行中 %d/%d", "status.done": "完成 %d/%d",
    "status.cancelled": "已取消 %d/%d",
    "editor.edit": "编辑项目", "editor.new": "新建项目",
    "editor.name": "项目名", "editor.src": "本地源码", "editor.remote": "远端目录名",
    "editor.remote_ph": "留空则取源码目录最后一段", "editor.browse": "选择…",
    "editor.rules": "Host 规则（按顺序匹配，第一条命中即用）",
    "editor.add": "＋ 添加", "editor.rule_match": "Host 匹配",
    "editor.rule_base": "远端基路径", "editor.rule_subdir": "子目录",
    "editor.excludes": "排除项",
    "editor.pick_src": "先选择本地源码目录", "editor.loading": "加载中…",
    "editor.empty": "（空目录）",
    "editor.delete_rule": "删除这条规则", "editor.no_template": "（不用模板）",
    "secrets.title": "SSH 密码", "secrets.show": "显示密码",
    "secrets.empty": "（未配置）",
    "settings.title": "设置", "settings.notify": "任务结束时弹托盘通知",
    "settings.autostart": "登录桌面后自动启动 SCPro",
    "settings.language": "语言", "settings.suffix": "默认目录后缀",
    "settings.delete_remote": "上传时删除远端多余文件（谨慎开启）",
    "settings.theme_select": "VS Code 主题",
    "settings.theme_follow": "跟随 VS Code",
    "settings.suffix_ph": "留空 = 当天日期，- = 不加后缀",
    "settings.reload_theme": "重新加载 VS Code 主题",
    "settings.clear_cache": "清理本地打包缓存",
    "confirm.clear_cache": "清理打包缓存",
    "confirm.clear_cache_body": "确定删除 upload_tmp 中的所有本地打包缓存吗？\n源码和远端文件不会受影响。",
    "settings.theme": "当前主题：%s",
    "toast.saved": "已保存", "toast.settings_saved": "设置已保存",
    "toast.secrets_saved": "密码已保存", "toast.hosts_saved": "Host 设置已保存",
    "toast.host_locked": "任务执行中，暂不能切换 Host",
    "toast.save_failed": "保存失败",
    "btn.retry": "重试失败项",
    "summary.text": "成功 %d / 失败 %d / 已取消 %d",
    "confirm.upload": "确认上传", "confirm.start": "开始上传",
    "confirm.delete": "删除项目", "confirm.delete_body": "确定从 projects.yaml 删除项目 %s 吗？\n（原文件会备份为 .bak）",
    "confirm.cannot": "无法开始", "confirm.gotit": "知道了",
    "confirm.hostkey": "主机密钥已变更",
    "confirm.accept_key": "接受新密钥",
    "hostkey.unknown": "（未能识别）",
    "warn.hostkey": "Host %s 的 SSH 主机密钥和 known_hosts 里记录的不一致。\n\n新密钥指纹：\n%s\n\n常见原因：板子重刷、系统重装、IP 被另一台设备占用。\n请先确认这是你的设备。是否删除旧记录并接受新密钥？",
    "preview.none": "没有选中 Host",
    "preview.no_rule": "当前 Host %s 没有匹配规则",
    "preview.path": "当前 Host %s → %s",
    "msg.upload_body": "将 %d 个项目上传到：%s\n\n项目会逐个打包并同步，执行过程中不能切换 Host。",
    "msg.delete_on": "远端清理：已开启，将删除目标目录中本地包不存在的文件。",
    "msg.delete_off": "远端清理：未开启，目标目录中的多余文件会保留。",
    "msg.warning_prefix": "\n\n注意：\n",
  },
  en: {
    "app.title": "SCPro",
    "tab.projects": "Projects", "tab.hosts": "Hosts", "tab.log": "Output", "tab.settings": "Settings",
    "hosts.header": "HOSTS", "hosts.search": "Search hosts…", "hosts.settings": "Host settings",
    "hosts.refresh": "Sync from ~/.ssh/config", "hosts.title": "Host settings",
    "hosts.ignore": "Ignore list (one glob per line, e.g. *-host)",
    "hosts.ports": "Ports (empty or unchanged = use ssh_config)",
    "host.warning": "No project rules match this Host",
    "host.password_ok": "password set", "host.password_missing": "no password",
    "host.no_host": "no Host available",
    "host.status_online": "online", "host.status_offline": "offline",
    "host.status_unknown": "unknown",
    "row.no_rule": "— no rule for this Host",
    "act.edit": "Edit…",
    "act.copy": "Duplicate project", "act.delete": "Delete project",
    "btn.new": "＋ New project", "btn.passwords": "Passwords",
    "btn.test": "Test connection", "btn.run": "Upload selected", "btn.run_n": "Upload selected (%d)",
    "btn.test_short": "Test", "menu.more": "More actions",
    "btn.cancel": "Cancel", "btn.ok": "OK", "btn.save": "Save",
    "col.project_route": "Project / Deployment path", "col.actions": "Actions",
    "route.local": "Local", "route.remote": "Remote",
    "project.search": "Search projects…", "project.empty": "No matching projects",
    "panel.output": "Output", "panel.search": "Filter log…",
    "panel.show": "Show output", "panel.hide": "Hide output",
    "filter.all": "All", "filter.problem": "Problems",
    "filter.progress": "Progress", "filter.info": "Info",
    "panel.autoscroll": "Auto-scroll", "panel.logdir": "Log folder",
    "panel.clear": "Clear", "panel.stop": "Stop",
    "status.ready": "Ready", "status.running": "Running %d/%d", "status.done": "Done %d/%d",
    "status.cancelled": "Cancelled %d/%d",
    "editor.edit": "Edit project", "editor.new": "New project",
    "editor.name": "Name", "editor.src": "Local source", "editor.remote": "Remote dir name",
    "editor.remote_ph": "Empty = last segment of the source path", "editor.browse": "Choose…",
    "editor.rules": "Host rules (first match wins)",
    "editor.add": "＋ Add", "editor.rule_match": "Host pattern",
    "editor.rule_base": "Remote base", "editor.rule_subdir": "Subdir",
    "editor.excludes": "Excludes",
    "editor.pick_src": "Pick a local source directory first", "editor.loading": "Loading…",
    "editor.empty": "(empty)",
    "editor.delete_rule": "Delete this rule", "editor.no_template": "(no template)",
    "secrets.title": "SSH passwords", "secrets.show": "Show passwords",
    "secrets.empty": "(not set)",
    "settings.title": "Settings", "settings.notify": "Notify when a run finishes",
    "settings.autostart": "Start SCPro on login",
    "settings.language": "Language", "settings.suffix": "Default dir suffix",
    "settings.delete_remote": "Delete extra remote files during upload (use with care)",
    "settings.theme_select": "VS Code theme",
    "settings.theme_follow": "Follow VS Code",
    "settings.suffix_ph": "Empty = today's date, - = no suffix",
    "settings.reload_theme": "Reload VS Code theme",
    "settings.clear_cache": "Clear local package cache",
    "confirm.clear_cache": "Clear package cache",
    "confirm.clear_cache_body": "Delete all local packages under upload_tmp?\nSource and remote files will not be affected.",
    "settings.theme": "Theme: %s",
    "toast.saved": "Saved", "toast.settings_saved": "Settings saved",
    "toast.secrets_saved": "Passwords saved", "toast.hosts_saved": "Host settings saved",
    "toast.host_locked": "Cannot switch Host while a task is running",
    "toast.save_failed": "Save failed",
    "btn.retry": "Retry failed",
    "summary.text": "%d ok / %d failed / %d cancelled",
    "confirm.upload": "Confirm upload", "confirm.start": "Start upload",
    "confirm.delete": "Delete project",
    "confirm.delete_body": "Delete project %s from projects.yaml?\n(a .bak backup is kept)",
    "confirm.cannot": "Cannot start", "confirm.gotit": "OK",
    "confirm.hostkey": "Host key changed",
    "confirm.accept_key": "Accept new key",
    "hostkey.unknown": "(unrecognized)",
    "warn.hostkey": "The SSH host key of %s does not match known_hosts.\n\nNew fingerprint:\n%s\n\nCommon causes: reflashed board, reinstalled OS, or the IP moved to another device.\nConfirm this is your device. Remove the old entry and accept the new key?",
    "preview.none": "No host selected",
    "preview.no_rule": "No rule matches Host %s",
    "preview.path": "Host %s → %s",
    "msg.upload_body": "Upload %d project(s) to: %s\n\nProjects are packed and synced one by one; the Host is locked while running.",
    "msg.delete_on": "Remote cleanup is ON: files not present in the local package will be deleted.",
    "msg.delete_off": "Remote cleanup is OFF: extra files in the destination will be preserved.",
    "msg.warning_prefix": "\n\nNote:\n",
  },
};

function t(key, ...args) {
  let text = (I18N[state.lang] || I18N.zh)[key] || (I18N.zh[key] || key);
  args.forEach(value => { text = text.replace(/%[sd]/, value); });
  return text;
}

function applyLanguage(lang) {
  state.lang = I18N[lang] ? lang : "zh";
  document.documentElement.lang = state.lang === "zh" ? "zh-CN" : "en";
  document.querySelectorAll("[data-i18n]").forEach(node => {
    node.textContent = t(node.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(node => {
    node.placeholder = t(node.dataset.i18nPlaceholder);
  });
  document.querySelectorAll("[data-i18n-title]").forEach(node => {
    node.title = t(node.dataset.i18nTitle);
  });
  const panel = document.getElementById("panel");
  if (panel) {
    document.getElementById("btn-toggle").title =
      t(panel.style.display === "none" ? "panel.show" : "panel.hide");
  }
  document.title = t("app.title");
  render();
  updateRunButton();
}

function send(cmd, data) {
  const query = data === undefined
    ? ""
    : "?data=" + encodeURIComponent(JSON.stringify(data));
  window.location.href = "scpro://" + cmd + query;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

window.scproState = function (payload) {
  state.hosts = payload.hosts || [];
  state.projects = payload.projects || [];
  state.currentHost = payload.current_host || "";
  const ids = new Set(state.projects.map(p => p.id));
  state.selected = new Set([...state.selected].filter(id => ids.has(id)));
  render();
};

window.scproTheme = function (payload) {
  const root = document.documentElement;
  root.dataset.theme = payload.dark ? "dark" : "light";
  Object.entries(payload.colors || {}).forEach(([key, value]) => {
    root.style.setProperty("--" + key.replace(/_/g, "-"), value);
  });
};

window.scproAssets = function (assets) {
  state.assets = assets || {};
  render();
};

window.scproUi = function (payload) {
  if (payload && payload.panel_h) {
    panelHeight = Math.max(120, payload.panel_h);
    document.documentElement.style.setProperty("--panel-h", panelHeight + "px");
  }
  if (payload && payload.language) applyLanguage(payload.language);
  if (payload && typeof payload.delete_remote === "boolean") {
    state.deleteRemote = payload.delete_remote;
  }
  if (payload && Array.isArray(payload.selected)) {
    state.selected = new Set(payload.selected);
  }
};

window.scproToast = function (message) {
  const toast = document.getElementById("toast");
  toast.textContent = message;
  toast.className = "toast" + (/失败|错误|ERROR/.test(message) ? " error" : "");
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => { toast.className = "toast hidden"; }, 3500);
};

window.scproHostKey = function (payload) {
  showConfirm(t("confirm.hostkey"),
    t("warn.hostkey", payload.alias, payload.fingerprint || t("hostkey.unknown")),
    () => send("update-host-key", {alias: payload.alias}), t("confirm.accept_key"));
};

function showConfirm(title, body, onOk, okText = t("btn.ok")) {
  const overlay = document.getElementById("overlay");
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-body").textContent = body;
  document.getElementById("modal-ok").textContent = okText;
  overlay.classList.remove("hidden");
  const close = () => overlay.classList.add("hidden");
  document.getElementById("modal-cancel").onclick = close;
  document.getElementById("modal-ok").onclick = () => { close(); onOk(); };
}

const logEntries = [];
const MAX_LOG = 5000;

function classifyLog(line) {
  if (/\[(ERROR|失败)\]/.test(line)) return "error";
  if (/\[WARN\]/.test(line)) return "warn";
  if (/\[(OK|成功|完成)\]/.test(line)) return "ok";
  if (/\[进度\]/.test(line)) return "progress";
  if (/^\[INFO\]/.test(line)) return "info";
  if (/^\$ /.test(line)) return "cmd";
  return "normal";
}

function logClass(level) {
  return {error: "err", warn: "warn", ok: "ok", progress: "prog",
          info: "info", cmd: "cmd", normal: ""}[level] || "";
}

function logMatches(entry) {
  const query = document.getElementById("log-search").value.trim().toLowerCase();
  if (query && !entry.line.toLowerCase().includes(query)) return false;
  const level = document.getElementById("log-level").value;
  if (level === "problem") return entry.level === "error" || entry.level === "warn";
  if (level === "progress") return entry.level === "progress";
  if (level === "info") return entry.level === "info" || entry.level === "ok" || entry.level === "normal";
  return true;
}

function appendLogNode(entry, scroll = true) {
  const log = document.getElementById("log");
  const row = document.createElement("div");
  row.appendChild(el("span", "t", "[" + entry.stamp + "] "));
  const body = el("span", logClass(entry.level));
  body.textContent = entry.line;
  row.appendChild(body);
  log.appendChild(row);
  while (log.childElementCount > MAX_LOG) {
    log.removeChild(log.firstElementChild);
  }
  if (scroll && document.getElementById("log-autoscroll").checked) {
    log.scrollTop = log.scrollHeight;
  }
}

function renderLog() {
  const log = document.getElementById("log");
  log.innerHTML = "";
  logEntries.forEach(entry => {
    if (logMatches(entry)) appendLogNode(entry, false);
  });
  if (document.getElementById("log-autoscroll").checked) {
    log.scrollTop = log.scrollHeight;
  }
}

window.scproLog = function (line) {
  const entry = {
    stamp: new Date().toLocaleTimeString("zh-CN", {hour12: false}),
    line,
    level: classifyLog(line),
  };
  logEntries.push(entry);
  if (logEntries.length > MAX_LOG) logEntries.shift();
  if (logMatches(entry)) appendLogNode(entry);
  const m = line.match(/^\[进度\]\s+(.*?)\s+(\d+)%\s+(\S+)\s+(.*)$/);
  if (m) {
    document.getElementById("status-progress").textContent =
      m[1] + "  " + m[2] + "%  " + m[3];
  }
  if (entry.level === "error") {
    document.getElementById("status-dot").className = "dot fail";
  }
};

window.scproStatus = function (st) {
  const text = document.getElementById("status-text");
  const dot = document.getElementById("status-dot");
  if (st.state === "running") {
    document.getElementById("run-summary").classList.add("hidden");
    dot.className = "dot busy";
    text.textContent = t("status.running", st.done, st.total);
    setRunning(true);
  } else if (st.state === "done") {
    dot.className = "dot";
    text.textContent = t("status.done", st.done, st.total);
    document.getElementById("status-progress").textContent = "";
    setRunning(false);
  } else if (st.state === "cancelled") {
    dot.className = "dot fail";
    text.textContent = t("status.cancelled", st.done, st.total);
    document.getElementById("status-progress").textContent = "";
    setRunning(false);
  } else {
    dot.className = "dot";
    text.textContent = t("status.ready");
  }
};

window.scproSummary = function (payload) {
  const bar = document.getElementById("run-summary");
  if (!payload.fail && !payload.cancelled) {
    state.failed = [];
    bar.classList.add("hidden");
    return;
  }
  state.failed = payload.failed || [];
  document.getElementById("run-summary-text").textContent =
    t("summary.text", payload.ok, payload.fail, payload.cancelled || 0);
  document.getElementById("btn-retry-failed").disabled = state.failed.length === 0;
  bar.classList.remove("hidden");
};

function setRunning(running) {
  state.running = running;
  document.getElementById("btn-run").disabled = running;
  document.getElementById("btn-stop").disabled = !running;
  // 任务状态变化后同步刷新项目操作，避免按钮停留在任务执行期间的禁用状态。
  render();
}

function render() {
  closeContextMenu();
  const host = state.hosts.find(h => h.alias === state.currentHost) || {};
  document.getElementById("host-name").textContent = state.currentHost || "—";
  document.getElementById("host-conn").textContent = host.user
    ? host.user + "@" + host.host + ":" + host.port
    : t("host.no_host");
  const auth = document.getElementById("host-auth");
  auth.classList.toggle("configured", !!host.password);
  auth.classList.toggle("missing", !!host.user && !host.password);
  auth.style.visibility = host.user ? "visible" : "hidden";
  auth.title = host.password ? t("host.password_ok") : t("host.password_missing");
  const hostStatus = host.status || "unknown";
  document.getElementById("host-dot").className =
    "dot" + (host.alias ? " " + hostStatus : "");
  document.getElementById("status-host").textContent = state.currentHost || "";
  const matched = state.projects.filter(p => p.remote).length;
  document.getElementById("host-warning").classList.toggle("hidden", matched > 0);

  const list = document.getElementById("host-list");
  list.innerHTML = "";
  const query = state.hostQuery.trim().toLowerCase();
  state.hosts.filter(h => !query || h.alias.toLowerCase().includes(query)).forEach(h => {
    const row = el("div", "host" + (h.alias === state.currentHost ? " active" : ""));
    const status = h.status || "unknown";
    row.title = t("host.status_" + status) + "  ·  "
      + (h.password ? t("host.password_ok") : t("host.password_missing"));
    row.appendChild(el("span", "dot " + status));
    row.appendChild(el("span", "name", h.alias));
    row.appendChild(el("span", "meta", h.port));
    row.onclick = () => {
      if (state.running) {
        window.scproToast(t("toast.host_locked"));
        return;
      }
      send("set-host", {host: h.alias});
    };
    list.appendChild(row);
  });

  const box = document.getElementById("project-list");
  const projectScrollTop = box.scrollTop;
  box.innerHTML = "";
  const projectQuery = state.projectQuery.trim().toLowerCase();
  const filteredProjects = state.projects.filter(p => {
    if (!projectQuery) return true;
    return [p.id, p.remote, p.local_src, p.error]
      .some(value => String(value || "").toLowerCase().includes(projectQuery));
  });
  box.ondragover = (e) => { if (dragProjectId && !projectQuery) e.preventDefault(); };
  box.ondrop = (e) => {
    if (e.target !== box || !dragProjectId || projectQuery) return;
    e.preventDefault();
    const order = state.projects.map(p => p.id).filter(id => id !== dragProjectId);
    order.push(dragProjectId);
    dragProjectId = null;
    send("reorder-projects", {order});
  };
  filteredProjects.forEach(p => {
    const disabled = !!p.error || !p.remote;
    const row = el("div", "project" + (p.error ? " error" : "") + (disabled ? " disabled" : ""));
    const check = document.createElement("input");
    check.type = "checkbox";
    check.checked = state.selected.has(p.id);
    check.disabled = disabled;
    check.onchange = () => {
      if (check.checked) state.selected.add(p.id); else state.selected.delete(p.id);
      updateRunButton();
      send("save-ui", {panel_h: panelHeight, selected: [...state.selected]});
    };
    row.appendChild(check);
    const nameWrap = el("span", "name");
    if (state.assets.folder) {
      const img = document.createElement("img");
      img.className = "file-icon";
      img.src = state.assets.folder;
      nameWrap.appendChild(img);
    }
    nameWrap.appendChild(el("span", "label", p.id));
    const main = el("span", "project-main");
    main.appendChild(nameWrap);
    const route = el("span", "route");
    const local = el("span", "route-path route-local");
    local.title = p.local_src || "";
    local.appendChild(el("span", "route-label", t("route.local")));
    local.appendChild(el("span", "route-value", p.local_src || "—"));
    const remoteValue = p.error || p.remote || t("row.no_rule");
    const remote = el(
      "span",
      "route-path route-remote" + (disabled ? " invalid" : ""));
    remote.title = remoteValue;
    remote.appendChild(el("span", "route-label", t("route.remote")));
    remote.appendChild(el("span", "route-value", remoteValue));
    route.appendChild(local);
    route.appendChild(el("span", "route-arrow", "→"));
    route.appendChild(remote);
    main.appendChild(route);
    row.appendChild(main);
    const actWrap = el("span", "pact");
    const edit = el("button", "icon", t("act.edit"));
    edit.disabled = state.running;
    edit.onclick = () => send("edit-project", {name: p.id});
    const more = el("button", "icon", "⋯");
    more.title = t("menu.more");
    more.disabled = state.running;
    more.dataset.menuTrigger = "";
    more.onclick = event => {
      event.stopPropagation();
      openContextMenu(more, [
        {label: t("act.copy"), action: () => send("copy-project", {name: p.id})},
        {
          label: t("act.delete"),
          danger: true,
          action: () => showConfirm(
            t("confirm.delete"), t("confirm.delete_body", p.id),
            () => send("delete-project", {name: p.id}), t("confirm.delete")),
        },
      ]);
    };
    actWrap.appendChild(edit);
    actWrap.appendChild(more);
    row.appendChild(actWrap);
    row.draggable = !state.running && !projectQuery;
    row.ondragstart = (e) => {
      dragProjectId = p.id;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", p.id);
      row.classList.add("dragging");
    };
    row.ondragover = (e) => {
      if (dragProjectId && dragProjectId !== p.id && !projectQuery) {
        e.preventDefault();
        row.classList.add("drag-over");
      }
    };
    row.ondragleave = () => row.classList.remove("drag-over");
    row.ondrop = (e) => {
      if (!dragProjectId || dragProjectId === p.id || projectQuery) return;
      e.preventDefault();
      row.classList.remove("drag-over");
      const order = state.projects.map(item => item.id).filter(id => id !== dragProjectId);
      order.splice(order.indexOf(p.id), 0, dragProjectId);
      dragProjectId = null;
      send("reorder-projects", {order});
    };
    row.ondragend = () => {
      dragProjectId = null;
      document.querySelectorAll(".dragging,.drag-over").forEach(node => {
        node.classList.remove("dragging");
        node.classList.remove("drag-over");
      });
    };
    box.appendChild(row);
  });
  if (!filteredProjects.length) {
    box.appendChild(el("div", "project-empty", t("project.empty")));
  }
  box.scrollTop = projectScrollTop;
  updateRunButton();
}

function updateRunButton() {
  const btn = document.getElementById("btn-run");
  btn.textContent = state.selected.size
    ? t("btn.run_n", state.selected.size)
    : t("btn.run");
  btn.disabled = state.running || state.selected.size === 0;
}

function closeContextMenu() {
  const menu = document.getElementById("context-menu");
  if (menu) menu.classList.add("hidden");
}

function openContextMenu(anchor, items) {
  const menu = document.getElementById("context-menu");
  menu.innerHTML = "";
  items.forEach(item => {
    const button = el("button", "menu-item" + (item.danger ? " danger" : ""), item.label);
    button.setAttribute("role", "menuitem");
    button.onclick = () => {
      closeContextMenu();
      item.action();
    };
    menu.appendChild(button);
  });
  menu.classList.remove("hidden");
  const rect = anchor.getBoundingClientRect();
  const menuRect = menu.getBoundingClientRect();
  const left = Math.max(8, Math.min(rect.right - menuRect.width, innerWidth - menuRect.width - 8));
  const top = Math.min(rect.bottom + 4, innerHeight - menuRect.height - 8);
  menu.style.left = left + "px";
  menu.style.top = Math.max(8, top) + "px";
}

function setActivity(view) {
  document.querySelectorAll(".act[data-view]").forEach(item => {
    item.classList.toggle("active", item.dataset.view === view);
  });
}

function setLogPanel(visible) {
  const panel = document.getElementById("panel");
  panel.style.display = visible ? "flex" : "none";
  panel.setAttribute("aria-hidden", visible ? "false" : "true");
  setActivity(visible ? "log" : "projects");
  const toggle = document.getElementById("btn-toggle");
  toggle.textContent = visible ? "▾" : "▸";
  toggle.title = t(visible ? "panel.hide" : "panel.show");
  if (visible) panel.querySelector("#log").scrollTop = panel.querySelector("#log").scrollHeight;
}

function toggleHostSidebar() {
  const sidebar = document.getElementById("sidebar");
  const hostButton = document.querySelector('.act[data-view="hosts"]');
  const collapsed = sidebar.classList.toggle("collapsed");
  sidebar.setAttribute("aria-hidden", collapsed ? "true" : "false");
  hostButton.setAttribute("aria-expanded", collapsed ? "false" : "true");
  setActivity(collapsed ? "projects" : "hosts");
  if (!collapsed) {
    const search = document.getElementById("host-search");
    search.focus();
    search.select();
  }
}

/* ---------------- 项目编辑弹层 ---------------- */
const editor = {
  oldName: "",
  profiles: [],
  profileItems: {},
  template: "",
  patterns: [],
  currentSrc: "",
  tree: {children: {}, expanded: new Set()},
};

function patternToRegex(pattern) {
  let text = pattern.replace(/[.+^${}()|[\]\\]/g, "\\$&");
  text = text.replace(/\*/g, ".*").replace(/\?/g, ".");
  return new RegExp("^" + text + "$");
}

function matchPattern(name) {
  return editor.patterns.find(p => p === name || patternToRegex(p).test(name)) || "";
}

function renderRules(targets) {
  const body = document.querySelector("#ed-rules tbody");
  body.innerHTML = "";
  (targets || []).forEach(rule => {
    const tr = document.createElement("tr");
    ["match", "base", "subdir"].forEach((key, index) => {
      const td = document.createElement("td");
      const input = document.createElement("input");
      input.dataset.key = key;
      input.value = rule[key] || (key === "subdir" ? "." : "");
      td.appendChild(input);
      tr.appendChild(td);
    });
    const td = document.createElement("td");
    const del = el("button", "mini", "✕");
    del.title = t("editor.delete_rule");
    del.onclick = () => tr.remove();
    td.appendChild(del);
    tr.appendChild(td);
    body.appendChild(tr);
  });
  body.querySelectorAll("input").forEach(input => {
    input.oninput = updatePreview;
  });
  updatePreview();
}

function collectRules() {
  return [...document.querySelectorAll("#ed-rules tbody tr")].map(tr => {
    const values = {};
    tr.querySelectorAll("input[data-key]").forEach(input => { values[input.dataset.key] = input.value.trim(); });
    return values;
  }).filter(rule => rule.match);
}

function requestDir(path) {
  if (!path) return;
  if (!(path in editor.tree.children)) editor.tree.children[path] = null;
  send("list-dir", {path});
}

window.scproDirEntries = function (payload) {
  editor.tree.children[payload.path] = payload.entries || [];
  renderTree();
};

window.scproDirChosen = function (payload) {
  if (!payload.path) return;
  const input = document.getElementById("ed-src");
  input.value = payload.path;
  editor.currentSrc = payload.path;
  editor.tree = {children: {}, expanded: new Set()};
  requestDir(editor.currentSrc);
  renderTree();
};

function toggleExclude(name, checked) {
  if (checked) {
    if (!matchPattern(name)) editor.patterns.push(name);
  } else {
    editor.patterns = editor.patterns.filter(p => p !== name && !patternToRegex(p).test(name));
  }
  renderTree();
}

function updatePreview() {
  const host = state.currentHost;
  const rules = collectRules();
  const src = document.getElementById("ed-src").value.trim();
  const remote = document.getElementById("ed-remote").value.trim()
    || src.split("/").filter(Boolean).pop() || "";
  let text = "";
  if (!host) {
    text = t("preview.none");
  } else {
    const rule = rules.find(r => r.match && patternToRegex(r.match).test(host));
    if (!rule) {
      text = t("preview.no_rule", host);
    } else {
      const sub = rule.subdir && rule.subdir !== "." ? rule.subdir.replace(/\/$/, "") + "/" : "";
      text = t("preview.path", host,
        rule.base.replace(/\/$/, "") + "/" + sub + remote + "/");
    }
  }
  document.getElementById("ed-preview").textContent = text;
}

function toggleDir(path) {
  if (editor.tree.expanded.has(path)) {
    editor.tree.expanded.delete(path);
  } else {
    editor.tree.expanded.add(path);
    requestDir(path);
  }
  renderTree();
}

function renderTree() {
  const box = document.getElementById("ed-tree");
  box.innerHTML = "";
  if (!editor.currentSrc) {
    box.appendChild(el("div", "tree-empty", t("editor.pick_src")));
    return;
  }
  if (!(editor.currentSrc in editor.tree.children)) {
    box.appendChild(el("div", "tree-empty", t("editor.loading")));
    return;
  }
  renderLevel(box, editor.currentSrc, 0);
}

function renderLevel(box, base, depth, ancestorExcluded = false) {
  const entries = editor.tree.children[base] || [];
  if (!entries.length && depth === 0) {
    box.appendChild(el("div", "tree-empty", t("editor.empty")));
    return;
  }
  entries.forEach(entry => {
    const path = base + "/" + entry.name;
    const row = el("div", "tree-row");
    row.style.paddingLeft = (4 + depth * 14) + "px";
    const exp = el("span", "exp", entry.dir
      ? (editor.tree.expanded.has(path) ? "▾" : "▸") : "");
    if (entry.dir) exp.onclick = () => toggleDir(path);
    row.appendChild(exp);
    const cb = document.createElement("input");
    cb.type = "checkbox";
    const matched = matchPattern(entry.name);
    const excluded = !!matched || ancestorExcluded;
    cb.checked = excluded;
    cb.disabled = ancestorExcluded;
    if (excluded) row.classList.add("excluded");
    cb.onchange = () => toggleExclude(entry.name, cb.checked);
    row.appendChild(cb);
    row.appendChild(el("span", "", entry.name + (entry.dir ? "/" : "")));
    box.appendChild(row);
    if (entry.dir && editor.tree.expanded.has(path)) {
      if (!(path in editor.tree.children)) {
        box.appendChild(el("div", "tree-empty", t("editor.loading")));
        requestDir(path);
      } else {
        renderLevel(box, path, depth + 1, excluded);
      }
    }
  });
}

window.scproProjectData = function (data) {
  editor.oldName = data.editing ? data.name : "";
  editor.profiles = data.profiles || [];
  editor.profileItems = data.profile_items || {};
  editor.template = data.template || "";
  editor.patterns = (data.patterns || []).slice();
  editor.currentSrc = data.local_src || "";
  editor.tree = {children: {}, expanded: new Set()};

  document.getElementById("ed-title").textContent =
    t(data.editing ? "editor.edit" : "editor.new");
  document.getElementById("ed-name").value = data.name || "";
  document.getElementById("ed-src").value = data.local_src || "";
  document.getElementById("ed-remote").value = data.remote_name || "";
  renderRules(data.targets || []);

  const select = document.getElementById("ed-profile");
  select.innerHTML = "";
  const none = document.createElement("option");
  none.value = "";
  none.textContent = t("editor.no_template");
  select.appendChild(none);
  editor.profiles.forEach(name => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    select.appendChild(option);
  });
  select.value = editor.template;
  select.onchange = () => {
    editor.template = select.value;
    editor.patterns = (editor.profileItems[editor.template] || []).slice();
    renderTree();
  };

  document.getElementById("editor").classList.remove("hidden");
  if (editor.currentSrc) requestDir(editor.currentSrc);
  renderTree();
};

window.scproSaveResult = function (payload) {
  if (payload.ok) {
    document.getElementById("editor").classList.add("hidden");
    window.scproToast(t("toast.saved"));
  } else {
    window.scproToast(payload.error || t("toast.save_failed"));
  }
};

window.scproSecretsData = function (payload) {
  const list = document.getElementById("secret-list");
  list.innerHTML = "";
  (payload.hosts || []).forEach(host => {
    const row = el("div", "secret-row");
    row.appendChild(el("span", "", host.alias));
    row.appendChild(el("span", "meta", host.user + "@" + host.host + ":" + host.port));
    const input = document.createElement("input");
    input.type = "password";
    input.value = host.value || "";
    input.dataset.key = host.key;
    input.placeholder = t("secrets.empty");
    row.appendChild(input);
    list.appendChild(row);
  });
  document.getElementById("show-secrets").checked = false;
  document.getElementById("secrets").classList.remove("hidden");
};

window.scproSecretsSaved = function (payload) {
  if (payload.ok) {
    document.getElementById("secrets").classList.add("hidden");
    window.scproToast(t("toast.secrets_saved"));
  } else {
    window.scproToast(payload.error || t("toast.save_failed"));
  }
};

window.scproSettingsData = function (payload) {
  document.getElementById("set-notify").checked = !!payload.notify;
  document.getElementById("set-autostart").checked = !!payload.autostart;
  document.getElementById("set-delete-remote").checked = !!payload.delete_remote;
  document.getElementById("set-suffix").value = payload.suffix || "";
  document.getElementById("set-language").value = payload.language || state.lang || "zh";
  const themeSelect = document.getElementById("set-theme-select");
  themeSelect.innerHTML = "";
  const followTheme = document.createElement("option");
  followTheme.value = "";
  followTheme.textContent = t("settings.theme_follow");
  themeSelect.appendChild(followTheme);
  (payload.themes || []).forEach(theme => {
    const option = document.createElement("option");
    option.value = theme.id;
    option.textContent = theme.label;
    themeSelect.appendChild(option);
  });
  themeSelect.value = payload.theme_id || "";
  document.getElementById("set-theme").textContent =
    t("settings.theme", payload.theme || "—");
  document.getElementById("set-version").textContent =
    "SCPro v" + (payload.version || "");
  document.getElementById("settings").classList.remove("hidden");
};

window.scproSettingsSaved = function (payload) {
  if (payload.ok) {
    document.getElementById("settings").classList.add("hidden");
    if (payload.language) applyLanguage(payload.language);
    state.deleteRemote = !!payload.delete_remote;
    window.scproToast(t("toast.settings_saved"));
  } else {
    window.scproToast(payload.error || t("toast.save_failed"));
  }
};

window.scproHostsData = function (payload) {
  document.getElementById("host-ignore").value = (payload.ignore || []).join("\n");
  const list = document.getElementById("host-edit-list");
  list.innerHTML = "";
  (payload.hosts || []).forEach(host => {
    const row = el("div", "host-edit-row");
    row.appendChild(el("span", "", host.alias));
    row.appendChild(el("span", "meta", host.user + "@" + host.host));
    const input = document.createElement("input");
    input.type = "number";
    input.min = "1";
    input.max = "65535";
    input.value = host.override || host.ssh_port || host.port;
    input.dataset.alias = host.alias;
    input.dataset.override = host.override || "";
    input.dataset.sshPort = host.ssh_port || host.port;
    row.appendChild(input);
    list.appendChild(row);
  });
  document.getElementById("hosts").classList.remove("hidden");
};

window.scproHostsSaved = function (payload) {
  if (payload.ok) {
    document.getElementById("hosts").classList.add("hidden");
    window.scproToast(t("toast.hosts_saved"));
  } else {
    window.scproToast(payload.error || t("toast.save_failed"));
  }
};

window.scproPreflight = function (result) {
  if (!result.ok) {
    showConfirm(t("confirm.cannot"), (result.errors || []).join("\n"),
                () => {}, t("confirm.gotit"));
    return;
  }
  const warn = (result.warnings || []).length
    ? t("msg.warning_prefix") + result.warnings.join("\n") : "";
  const cleanup = "\n\n" + t(state.deleteRemote ? "msg.delete_on" : "msg.delete_off");
  showConfirm(t("confirm.upload"),
    t("msg.upload_body", result.projects.length, state.currentHost) + cleanup + warn,
    () => {
      send("run", {projects: result.projects});
      setLogPanel(true);
    }, t("confirm.start"));
};

function saveEditor() {
  const base = editor.profileItems[editor.template] || [];
  const add = editor.patterns.filter(p => !base.includes(p));
  const remove = base.filter(p => !editor.patterns.includes(p));
  let excludes;
  if (editor.template) {
    excludes = (add.length || remove.length)
      ? {use: editor.template, add, remove}
      : {use: editor.template};
  } else {
    excludes = editor.patterns.slice();
  }
  send("save-project", {
    old_name: editor.oldName,
    name: document.getElementById("ed-name").value.trim(),
    local_src: document.getElementById("ed-src").value.trim(),
    remote_name: document.getElementById("ed-remote").value.trim(),
    targets: collectRules(),
    excludes,
  });
}

function bind() {
  document.getElementById("btn-refresh").onclick = () => send("refresh");
  document.getElementById("btn-test").onclick = () => send("test");
  document.getElementById("btn-run").onclick = () => {
    if (!state.selected.size) return;
    send("preflight", {projects: [...state.selected]});
  };
  document.getElementById("btn-stop").onclick = () => send("stop");
  document.getElementById("btn-retry-failed").onclick = () => {
    if (state.failed.length) send("preflight", {projects: state.failed});
  };
  document.getElementById("btn-dismiss-summary").onclick = () => {
    document.getElementById("run-summary").classList.add("hidden");
    state.failed = [];
  };
  document.getElementById("btn-clear").onclick = () => {
    logEntries.length = 0;
    document.getElementById("log").innerHTML = "";
  };
  document.getElementById("btn-open-logs").onclick = () => send("open-log-dir");
  document.getElementById("log-search").oninput = renderLog;
  document.getElementById("log-level").onchange = renderLog;
  document.getElementById("btn-toggle").onclick = () => {
    const panel = document.getElementById("panel");
    setLogPanel(panel.style.display === "none");
  };
  document.getElementById("btn-new").onclick = () => send("new-project");
  document.getElementById("btn-more").onclick = event => {
    event.stopPropagation();
    openContextMenu(document.getElementById("btn-more"), [
      {label: t("hosts.refresh"), action: () => send("refresh")},
    ]);
  };
  document.getElementById("btn-settings").onclick = () => send("settings");

  document.getElementById("ed-cancel").onclick = () =>
    document.getElementById("editor").classList.add("hidden");
  document.getElementById("ed-save").onclick = saveEditor;
  document.getElementById("ed-browse").onclick = () =>
    send("choose-dir", {current: document.getElementById("ed-src").value.trim()});
  document.getElementById("ed-add-rule").onclick = () =>
    renderRules([...collectRules(), {match: "", base: "", subdir: "."}]);
  document.getElementById("ed-src").onchange = () => {
    editor.currentSrc = document.getElementById("ed-src").value.trim();
    editor.tree = {children: {}, expanded: new Set()};
    requestDir(editor.currentSrc);
    renderTree();
    updatePreview();
  };
  document.getElementById("ed-remote").oninput = updatePreview;
  document.getElementById("secret-cancel").onclick = () =>
    document.getElementById("secrets").classList.add("hidden");
  document.getElementById("show-secrets").onchange = (e) => {
    document.querySelectorAll("#secret-list input").forEach(input => {
      input.type = e.target.checked ? "text" : "password";
    });
  };
  document.getElementById("secret-save").onclick = () => {
    const values = {};
    document.querySelectorAll("#secret-list input").forEach(input => {
      values[input.dataset.key] = input.value;
    });
    send("save-secrets", {values});
  };
  document.getElementById("set-cancel").onclick = () =>
    document.getElementById("settings").classList.add("hidden");
  document.getElementById("set-save").onclick = () => send("save-settings", {
    notify: document.getElementById("set-notify").checked,
    autostart: document.getElementById("set-autostart").checked,
    delete_remote: document.getElementById("set-delete-remote").checked,
    suffix: document.getElementById("set-suffix").value,
    language: document.getElementById("set-language").value,
    theme_id: document.getElementById("set-theme-select").value,
  });
  document.getElementById("set-reload-theme").onclick = () => send("reload-theme");
  document.getElementById("set-clear-cache").onclick = () => showConfirm(
    t("confirm.clear_cache"), t("confirm.clear_cache_body"),
    () => send("clear-cache"), t("confirm.clear_cache"));
  document.getElementById("btn-host-settings").onclick = () => send("hosts-data");
  document.getElementById("btn-passwords").onclick = () => {
    document.getElementById("hosts").classList.add("hidden");
    send("passwords");
  };
  document.getElementById("host-cancel").onclick = () =>
    document.getElementById("hosts").classList.add("hidden");
  document.getElementById("host-save").onclick = () => {
    const ignore = document.getElementById("host-ignore").value
      .split("\n").map(x => x.trim()).filter(Boolean);
    const ports = {};
    const remove_ports = [];
    document.querySelectorAll("#host-edit-list input").forEach(input => {
      const value = input.value.trim();
      const alias = input.dataset.alias;
      const override = input.dataset.override || "";
      if (!value || value === input.dataset.sshPort) {
        if (override) remove_ports.push(alias);
      } else if (value !== override) {
        ports[alias] = value;
      }
    });
    send("save-hosts", {ignore, ports, remove_ports});
  };
  document.querySelectorAll(".act[data-view]").forEach(btn => {
    btn.onclick = () => {
      const view = btn.dataset.view;
      if (view === "log") {
        const panel = document.getElementById("panel");
        setLogPanel(panel.style.display === "none");
      } else if (view === "hosts") {
        toggleHostSidebar();
      } else if (view === "projects") {
        setActivity("projects");
        document.getElementById("project-list").scrollTop = 0;
        document.getElementById("project-search").focus();
      }
    };
  });
  setLogPanel(true);

  const search = document.getElementById("host-search");
  search.oninput = () => { state.hostQuery = search.value; render(); };
  const projectSearch = document.getElementById("project-search");
  projectSearch.oninput = () => {
    state.projectQuery = projectSearch.value;
    render();
    projectSearch.focus();
  };

  // 日志面板拖动高度
  const resizer = document.getElementById("panel-resizer");
  let resizing = false;
  resizer.onmousedown = (e) => {
    resizing = true;
    e.preventDefault();
  };
  window.addEventListener("mousemove", (e) => {
    if (!resizing) return;
    panelHeight = Math.max(120, Math.min(window.innerHeight - 200,
                                         window.innerHeight - e.clientY - 24));
    document.documentElement.style.setProperty("--panel-h", panelHeight + "px");
  });
  window.addEventListener("mouseup", () => {
    if (resizing) {
      resizing = false;
      send("save-ui", {panel_h: panelHeight});
    }
  });

  // 键盘快捷键
  window.addEventListener("keydown", (e) => {
    if (e.key === "F5") {
      e.preventDefault();
      document.getElementById("btn-run").click();
    } else if (e.key === "Escape") {
      closeContextMenu();
      if (!document.getElementById("overlay").classList.contains("hidden")) {
        document.getElementById("modal-cancel").click();
      }
    }
  });
  document.addEventListener("click", event => {
    if (!event.target.closest("#context-menu") && !event.target.closest("[data-menu-trigger]")) {
      closeContextMenu();
    }
  });
}

bind();
// 初始状态由 Qt 在 loadFinished 后统一推送。加载期间发起自定义协议导航
// 可能取消本次加载，导致首次打开时 Host/项目列表为空。
