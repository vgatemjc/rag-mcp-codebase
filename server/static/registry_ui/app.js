(() => {
  const state = {
    meta: null,
    lastPreview: null,
  };

  const statusEl = document.getElementById("status-message");
  const previewOutput = document.getElementById("preview-output");
  const curlOutput = document.getElementById("curl-output");
  const createOutput = document.getElementById("create-output");
  const registryList = document.getElementById("registry-list");
  const configMeta = document.getElementById("config-meta");
  const embeddingList = document.getElementById("embedding-list");
  const collectionList = document.getElementById("collection-list");

  const form = document.getElementById("registry-form");
  const createBtn = document.getElementById("create-btn");

  function setStatus(message) {
    statusEl.textContent = message;
  }

  async function fetchJson(url, options = {}) {
    const headers = options.headers || {};
    const opts = {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...headers,
      },
    };
    const response = await fetch(url, opts);
    const text = await response.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (err) {
        data = { message: text };
      }
    }
    if (!response.ok) {
      const error = new Error(`Request failed with status ${response.status}`);
      error.data = data;
      throw error;
    }
    return data;
  }

  function optionalValue(id) {
    const value = document.getElementById(id).value.trim();
    return value === "" ? undefined : value;
  }

  function buildPayload() {
    const payload = {
      repo_id: document.getElementById("repo_id").value.trim(),
      name: optionalValue("name"),
      url: optionalValue("url"),
      stack_type: optionalValue("stack_type"),
      collection_name: optionalValue("collection_name"),
      embedding_model: optionalValue("embedding_model"),
      last_indexed_commit: optionalValue("last_indexed_commit"),
    };
    return Object.fromEntries(Object.entries(payload).filter(([, value]) => value !== undefined));
  }

  function renderRegistry(entries) {
    registryList.innerHTML = "";
    if (!entries || entries.length === 0) {
      registryList.textContent = "No registry entries yet.";
      return;
    }
    entries.forEach((entry) => {
      const item = document.createElement("div");
      item.className = "registry-card";
      item.innerHTML = `
        <p class="mono">${entry.repo_id}</p>
        <p>${entry.name || "(no name provided)"}</p>
        <p class="dim">Collection: ${entry.collection_name}</p>
        <p class="dim">Model: ${entry.embedding_model}</p>
        <p class="dim">Stack: ${entry.stack_type || "(default)"}</p>
        <p class="dim">${entry.archived ? "Archived" : "Active"}</p>
      `;
      registryList.appendChild(item);
    });
  }

  function renderMeta(config) {
    configMeta.innerHTML = "";
    const entries = {
      "Qdrant URL": config.qdrant_url,
      "Embedding base": config.embedding_base_url,
      "Embedding model": config.embedding_model,
      "Default collection": config.collection,
      "Repos dir": config.repos_dir,
      "Default stack": config.stack_type || "(not set)",
    };
    Object.entries(entries).forEach(([label, value]) => {
      const term = document.createElement("dt");
      term.textContent = label;
      const detail = document.createElement("dd");
      detail.textContent = value || "(not set)";
      configMeta.appendChild(term);
      configMeta.appendChild(detail);
    });
  }

  function renderOptions(listEl, options, emptyText) {
    listEl.innerHTML = "";
    if (!options || options.length === 0) {
      const item = document.createElement("li");
      item.className = "pill muted";
      item.textContent = emptyText;
      listEl.appendChild(item);
      return;
    }
    options.forEach((value) => {
      const item = document.createElement("li");
      item.className = "pill";
      item.textContent = value;
      listEl.appendChild(item);
    });
  }

  function renderEmbeddingDatalist(options) {
    const datalist = document.getElementById("embedding-options");
    datalist.innerHTML = "";
    options.forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      datalist.appendChild(option);
    });
  }

  function renderCurl(preview) {
    if (!preview || !preview.payload) {
      curlOutput.textContent = "Preview payload missing.";
      return;
    }
    const origin = window.location.origin;
    const payload = JSON.stringify(preview.payload, null, 2);
    const lines = [
      `curl -X POST ${origin}${preview.target || "/registry"} \\`,
      '  -H "Content-Type: application/json" \\',
      "  -d @- <<'PAYLOAD'",
      payload,
      "PAYLOAD",
    ];
    curlOutput.textContent = lines.join("\n");
  }

  function renderPreview(preview) {
    const payload = preview && preview.payload ? preview.payload : {};
    const target = preview && preview.target ? preview.target : "/registry";
    const data = { target, payload };
    previewOutput.textContent = JSON.stringify(data, null, 2);
    renderCurl(data);
  }

  async function handlePreview(event) {
    event.preventDefault();
    const payload = buildPayload();
    if (!payload.repo_id) {
      setStatus("Repository ID is required.");
      return;
    }
    setStatus("Generating preview…");
    try {
      const preview = await fetchJson("/registry/preview", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      state.lastPreview = preview;
      renderPreview(preview);
      setStatus("Preview ready.");
    } catch (err) {
      setStatus(err.message || "Preview failed.");
      previewOutput.textContent = JSON.stringify(err.data || {}, null, 2);
    }
  }

  async function handleCreate(event) {
    event.preventDefault();
    const payload = state.lastPreview?.payload || buildPayload();
    if (!payload.repo_id) {
      setStatus("Repository ID is required.");
      return;
    }
    setStatus("Creating registry entry…");
    try {
      const result = await fetchJson("/registry", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      createOutput.textContent = JSON.stringify(result, null, 2);
      setStatus("Registry entry created.");
      state.lastPreview = null;
      await loadMeta(); // refresh lists
    } catch (err) {
      setStatus(err.message || "Create failed.");
      createOutput.textContent = JSON.stringify(err.data || {}, null, 2);
    }
  }

  async function loadMeta() {
    setStatus("Loading configuration…");
    try {
      const meta = await fetchJson("/registry/ui/meta");
      state.meta = meta;
      if (meta.config) {
        renderMeta(meta.config);
        document.getElementById("collection_name").placeholder = meta.config.collection || "";
        document.getElementById("embedding_model").placeholder = meta.config.embedding_model || "";
        document.getElementById("stack_type").placeholder = meta.config.stack_type || "android_app";
      }
      renderRegistry(meta.registry || []);
      renderOptions(embeddingList, meta.embedding_options, "No embedding options found.");
      renderOptions(collectionList, meta.qdrant_collections, "No collections discovered.");
      renderEmbeddingDatalist(meta.embedding_options || []);
      setStatus("Configuration loaded.");
    } catch (err) {
      setStatus("Could not load meta; retry after backend starts.");
      previewOutput.textContent = err.data ? JSON.stringify(err.data, null, 2) : err.message;
    }
  }

  form.addEventListener("submit", handlePreview);
  createBtn.addEventListener("click", handleCreate);
  loadMeta();
})();
