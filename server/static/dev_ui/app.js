(() => {
  const state = {
    repos: [],
    tools: [],
    selectedRepo: localStorage.getItem("dev-ui:selected-repo") || "",
    indexPoll: null,
  };

  const els = {
    status: document.getElementById("page-status"),
    registryTable: document.getElementById("registry-table"),
    registryRefresh: document.getElementById("refresh-registry"),
    repoPicker: document.getElementById("repo-picker"),
    searchRepo: document.getElementById("search-repo"),
    fullIndex: document.getElementById("full-index"),
    updateIndex: document.getElementById("update-index"),
    fetchStatus: document.getElementById("fetch-status"),
    indexStatus: document.getElementById("index-status"),
    searchForm: document.getElementById("search-form"),
    searchQuery: document.getElementById("search-query"),
    searchK: document.getElementById("search-k"),
    searchOutput: document.getElementById("search-output"),
    toolPicker: document.getElementById("tool-picker"),
    toolArgs: document.getElementById("tool-args"),
    toolOutput: document.getElementById("tool-output"),
    refreshTools: document.getElementById("refresh-tools"),
    invokeTool: document.getElementById("invoke-tool"),
    requestLog: document.getElementById("request-log"),
    responseLog: document.getElementById("response-log"),
    clearLogs: document.getElementById("clear-logs"),
  };

  const fmtDate = (value) => {
    if (!value) return "—";
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return String(value);
    return dt.toLocaleString();
  };

  const pretty = (value) => {
    if (value === null || value === undefined) return "";
    if (typeof value === "string") {
      try {
        return JSON.stringify(JSON.parse(value), null, 2);
      } catch (_) {
        return value;
      }
    }
    try {
      return JSON.stringify(value, null, 2);
    } catch (_) {
      return String(value);
    }
  };

  const badge = (status) => {
    if (!status) return '<span class="badge idle">idle</span>';
    const normalized = status.toLowerCase();
    if (normalized.includes("error")) return `<span class="badge error">${status}</span>`;
    if (normalized.includes("running")) return `<span class="badge success">${status}</span>`;
    if (normalized.includes("completed")) return `<span class="badge success">${status}</span>`;
    if (normalized.includes("noop")) return `<span class="badge idle">${status}</span>`;
    return `<span class="badge idle">${status}</span>`;
  };

  const setStatus = (text) => {
    els.status.textContent = text;
  };

  const setOutput = (el, payload) => {
    if (!el) return;
    el.textContent = pretty(payload);
  };

  const logRequest = (method, url, body) => {
    const data = { method, url };
    if (body !== undefined) data.body = body;
    setOutput(els.requestLog, data);
  };

  const logResponse = (payload) => {
    setOutput(els.responseLog, payload);
  };

  const parseIndexStream = (text) => {
    const lines = text.split("\n").filter((l) => l.trim());
    const parsed = [];
    for (const line of lines) {
      try {
        parsed.push(JSON.parse(line));
      } catch (_) {
        parsed.push({ raw: line });
      }
    }
    return parsed;
  };

  const streamIndexResponse = async (res) => {
    const events = [];
    if (!res.body || !res.body.getReader) {
      const bodyText = await res.text();
      return parseIndexStream(bodyText);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines.filter((l) => l.trim())) {
        try {
          events.push(JSON.parse(line));
        } catch (_) {
          events.push({ raw: line });
        }
        setOutput(els.responseLog, events.slice(-50));
      }
    }
    if (buffer.trim()) {
      try {
        events.push(JSON.parse(buffer));
      } catch (_) {
        events.push({ raw: buffer });
      }
    }
    return events;
  };

  const highlightRepo = () => {
    const rows = els.registryTable.querySelectorAll("tr");
    rows.forEach((row) => {
      if (row.dataset.repoId === state.selectedRepo) {
        row.classList.add("selected-row");
      } else {
        row.classList.remove("selected-row");
      }
    });
    [els.repoPicker, els.searchRepo].forEach((select) => {
      if (!select) return;
      select.value = state.selectedRepo || "";
    });
  };

  const renderRepoSelects = () => {
    const renderOptions = (includeAll) => {
      const opts = includeAll ? ['<option value="">All repos</option>'] : [];
      state.repos.forEach((repo) => {
        opts.push(`<option value="${repo.repo_id}">${repo.repo_id}</option>`);
      });
      return opts.join("");
    };
    els.repoPicker.innerHTML = renderOptions(false);
    els.searchRepo.innerHTML = renderOptions(true);
    highlightRepo();
  };

  const renderRegistry = () => {
    if (!state.repos.length) {
      els.registryTable.innerHTML = `<tr><td colspan="6">No registry entries found.</td></tr>`;
      renderRepoSelects();
      return;
    }
    els.registryTable.innerHTML = state.repos
      .map((repo) => {
        const indexed = repo.last_indexed_at ? fmtDate(repo.last_indexed_at) : "—";
        return `<tr data-repo-id="${repo.repo_id}">
            <td>${repo.repo_id}</td>
            <td>${repo.collection_name}</td>
            <td>${repo.embedding_model}</td>
            <td>${indexed}</td>
            <td>${badge(repo.last_index_status)}</td>
            <td class="actions"><button data-select="${repo.repo_id}">Use</button><button data-delete="${repo.repo_id}">Delete</button></td>
          </tr>`;
      })
      .join("");
    renderRepoSelects();
  };

  const deleteRepo = async (repoId) => {
    const confirmed = confirm(`Delete registry entry '${repoId}'? This does not touch the repo files.`);
    if (!confirmed) return;
    logRequest("DELETE", `/registry/${repoId}`);
    setStatus(`Deleting ${repoId}…`);
    try {
      const res = await fetch(`/registry/${encodeURIComponent(repoId)}`, { method: "DELETE" });
      if (!res.ok) throw new Error(`Delete failed (${res.status})`);
      logResponse({ status: res.status, body: "deleted" });
      if (state.selectedRepo === repoId) {
        state.selectedRepo = "";
        localStorage.removeItem("dev-ui:selected-repo");
        els.indexStatus.innerHTML = "";
      }
      await fetchRegistry();
      setStatus(`Deleted ${repoId}`);
    } catch (err) {
      setStatus(err.message);
      logResponse({ error: err.message });
    }
  };

  const selectRepo = (repoId) => {
    state.selectedRepo = repoId || "";
    localStorage.setItem("dev-ui:selected-repo", state.selectedRepo);
    highlightRepo();
    if (state.selectedRepo) {
      fetchIndexStatus();
    } else {
      els.indexStatus.innerHTML = "";
      stopIndexPolling();
    }
  };

  const fetchRegistry = async () => {
    setStatus("Loading registry…");
    try {
      const res = await fetch("/registry?include_archived=true");
      if (!res.ok) throw new Error(`Registry load failed (${res.status})`);
      state.repos = await res.json();
      renderRegistry();
      if (!state.selectedRepo && state.repos.length) {
        selectRepo(state.repos[0].repo_id);
      } else {
        highlightRepo();
      }
      setStatus(`Loaded ${state.repos.length} repos`);
    } catch (err) {
      setStatus(err.message);
      els.registryTable.innerHTML = `<tr><td colspan="6">${err.message}</td></tr>`;
    }
  };

  const renderIndexStatus = (payload) => {
    if (!payload) {
      els.indexStatus.innerHTML = "";
      return;
    }
    const toNumber = (value) => (typeof value === "number" && Number.isFinite(value) ? value : null);
    const total = toNumber(payload.last_index_total_files);
    const processed = toNumber(payload.last_index_processed_files);
    const percent = total && processed !== null && total > 0 ? Math.floor((processed / total) * 100) : null;
    const progressText =
      total !== null && processed !== null
        ? `${processed}/${total}${percent !== null ? ` (${percent}%)` : ""}`
        : processed !== null
          ? `${processed}`
          : "—";
    const currentFile = payload.last_index_current_file || "—";
    els.indexStatus.innerHTML = `
      <dt>Repo</dt><dd>${payload.repo_id}</dd>
      <dt>Status</dt><dd>${badge(payload.last_index_status)}</dd>
      <dt>Mode</dt><dd>${payload.last_index_mode || "—"}</dd>
      <dt>Last commit</dt><dd>${payload.last_indexed_commit || "—"}</dd>
      <dt>Started</dt><dd>${fmtDate(payload.last_index_started_at)}</dd>
      <dt>Finished</dt><dd>${fmtDate(payload.last_index_finished_at)}</dd>
      <dt>Indexed at</dt><dd>${fmtDate(payload.last_indexed_at)}</dd>
      <dt>Error</dt><dd>${payload.last_index_error || "—"}</dd>
      <dt>Progress</dt><dd>${progressText}</dd>
      <dt>Current file</dt><dd>${currentFile}</dd>
    `;
  };

  const stopIndexPolling = () => {
    if (state.indexPoll) {
      clearInterval(state.indexPoll);
      state.indexPoll = null;
    }
  };

  const startIndexPolling = () => {
    if (state.indexPoll || !state.selectedRepo) return;
    state.indexPoll = setInterval(fetchIndexStatus, 2000);
  };

  const syncIndexPolling = (statusValue) => {
    const normalized = (statusValue || "").toLowerCase();
    if (normalized === "running") {
      startIndexPolling();
    } else {
      stopIndexPolling();
    }
  };

  const fetchIndexStatus = async () => {
    if (!state.selectedRepo) {
      stopIndexPolling();
      return;
    }
    try {
      const res = await fetch(`/repos/${encodeURIComponent(state.selectedRepo)}/index/status`);
      if (!res.ok) throw new Error(`Status load failed (${res.status})`);
      const data = await res.json();
      renderIndexStatus(data);
      syncIndexPolling(data.last_index_status);
    } catch (err) {
      renderIndexStatus({ repo_id: state.selectedRepo, last_index_status: "error", last_index_error: err.message });
      stopIndexPolling();
    }
  };

  const toggleIndexButtons = (disabled) => {
    [els.fullIndex, els.updateIndex, els.fetchStatus].forEach((btn) => {
      btn.disabled = disabled;
    });
  };

  const runIndex = async (mode) => {
    if (!state.selectedRepo) {
      alert("Select a repository first.");
      return;
    }
    toggleIndexButtons(true);
    logRequest("POST", `/repos/${state.selectedRepo}/index/${mode}`);
    startIndexPolling();
    try {
      const res = await fetch(`/repos/${encodeURIComponent(state.selectedRepo)}/index/${mode}`, { method: "POST" });
      const events = await streamIndexResponse(res);
      logResponse({ status: res.status, body: events });
      await fetchRegistry();
      await fetchIndexStatus();
    } catch (err) {
      logResponse({ error: err.message });
      stopIndexPolling();
    } finally {
      toggleIndexButtons(false);
    }
  };

  const runSearch = async (evt) => {
    evt.preventDefault();
    const repoId = els.searchRepo.value || null;
    const payload = {
      query: els.searchQuery.value,
      repo_id: repoId || null,
      k: parseInt(els.searchK.value || "8", 10),
    };
    logRequest("POST", "/search", payload);
    try {
      const res = await fetch("/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      logResponse({ status: res.status, body: data });
      setOutput(els.searchOutput, data);
    } catch (err) {
      setOutput(els.searchOutput, err.message);
      logResponse({ error: err.message });
    }
  };

  const setToolArgs = (tool) => {
    if (!tool) {
      els.toolArgs.value = "{}";
      return;
    }
    const defaults = {};
    const paramNames = new Set();
    (tool.parameters || []).forEach((param) => {
      paramNames.add(param.name);
      if (param.default !== undefined && param.default !== null) {
        defaults[param.name] = param.default;
      } else if (param.required) {
        defaults[param.name] = "";
      }
    });
    if (state.selectedRepo) {
      if (paramNames.has("repo") && defaults.repo === undefined) {
        defaults.repo = state.selectedRepo;
      }
      if (paramNames.has("repo_id") && defaults.repo_id === undefined) {
        defaults.repo_id = state.selectedRepo;
      }
    }
    els.toolArgs.value = JSON.stringify(defaults, null, 2);
  };

  const formatToolOutput = (payload) => {
    if (!payload) return "";
    const parts = [];
    if (payload.tool) parts.push(`tool: ${payload.tool}`);
    if (payload.duration_ms !== undefined) parts.push(`duration_ms: ${payload.duration_ms}`);
    if (payload.content_type) parts.push(`content_type: ${payload.content_type}`);
    if (payload.output_text) parts.push(`output:\n${payload.output_text}`);
    if (payload.parsed_json) parts.push(`parsed_json:\n${pretty(payload.parsed_json)}`);
    if (!payload.parsed_json && payload.raw_result !== undefined) {
      parts.push(`raw_result:\n${pretty(payload.raw_result)}`);
    }
    if (payload.stderr) parts.push(`stderr:\n${payload.stderr}`);
    return parts.join("\n\n");
  };

  const setToolOutput = (payload) => {
    els.toolOutput.textContent = formatToolOutput(payload) || pretty(payload);
  };

  const renderTools = () => {
    if (!state.tools.length) {
      els.toolPicker.innerHTML = `<option value="">No tools available</option>`;
      els.toolArgs.value = "{}";
      return;
    }
    els.toolPicker.innerHTML = state.tools
      .map((tool) => `<option value="${tool.name}">${tool.name} — ${tool.description || ""}</option>`)
      .join("");
    setToolArgs(state.tools[0]);
  };

  const fetchTools = async () => {
    setStatus("Loading MCP tools…");
    try {
      const res = await fetch("/mcp/tools");
      if (!res.ok) throw new Error(`Tool load failed (${res.status})`);
      state.tools = await res.json();
      renderTools();
      setStatus(`Loaded ${state.tools.length} tools`);
    } catch (err) {
      setStatus(err.message);
      state.tools = [];
      renderTools();
      logResponse({ error: err.message });
    }
  };

  const invokeTool = async () => {
    const toolName = els.toolPicker.value;
    if (!toolName) {
      alert("Pick a tool first.");
      return;
    }
    const tool = state.tools.find((t) => t.name === toolName);
    const paramNames = new Set((tool?.parameters || []).map((p) => p.name));
    let args;
    try {
      args = els.toolArgs.value ? JSON.parse(els.toolArgs.value) : {};
    } catch (err) {
      alert("Arguments must be valid JSON.");
      return;
    }
    const normalizedArgs = paramNames.size ? {} : { ...args };
    if (paramNames.size) {
      Object.entries(args || {}).forEach(([key, value]) => {
        if (paramNames.has(key)) {
          normalizedArgs[key] = value;
        }
      });
      if (state.selectedRepo) {
        if (paramNames.has("repo") && normalizedArgs.repo === undefined) {
          normalizedArgs.repo = state.selectedRepo;
        }
        if (paramNames.has("repo_id") && normalizedArgs.repo_id === undefined) {
          normalizedArgs.repo_id = state.selectedRepo;
        }
      }
    }
    logRequest("POST", `/mcp/tools/${toolName}`, { args: normalizedArgs });
    els.invokeTool.disabled = true;
    try {
      const res = await fetch(`/mcp/tools/${encodeURIComponent(toolName)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ args: normalizedArgs }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data?.detail || `Tool failed (${res.status})`);
      }
      logResponse({ status: res.status, body: data });
      setToolOutput(data);
    } catch (err) {
      logResponse({ error: err.message });
      setToolOutput({ error: err.message });
    } finally {
      els.invokeTool.disabled = false;
    }
  };

  const bindEvents = () => {
    els.registryTable.addEventListener("click", (evt) => {
      const target = evt.target;
      if (target instanceof HTMLElement && target.dataset.select) {
        selectRepo(target.dataset.select);
      } else if (target instanceof HTMLElement && target.dataset.delete) {
        deleteRepo(target.dataset.delete);
      }
    });
    els.registryRefresh.addEventListener("click", fetchRegistry);
    els.repoPicker.addEventListener("change", (evt) => selectRepo(evt.target.value));
    els.searchRepo.addEventListener("change", (evt) => {
      const val = evt.target.value;
      if (val) selectRepo(val);
    });
    els.fullIndex.addEventListener("click", () => runIndex("full"));
    els.updateIndex.addEventListener("click", () => runIndex("update"));
    els.fetchStatus.addEventListener("click", fetchIndexStatus);
    els.searchForm.addEventListener("submit", runSearch);
    els.toolPicker.addEventListener("change", (evt) => {
      const tool = state.tools.find((t) => t.name === evt.target.value);
      setToolArgs(tool);
    });
    els.refreshTools.addEventListener("click", fetchTools);
    els.invokeTool.addEventListener("click", invokeTool);
    els.clearLogs.addEventListener("click", () => {
      els.requestLog.textContent = "";
      els.responseLog.textContent = "";
    });
  };

  const init = async () => {
    bindEvents();
    await fetchRegistry();
    await fetchTools();
    if (state.selectedRepo) {
      await fetchIndexStatus();
    }
    setStatus("Ready");
  };

  init();
})();
