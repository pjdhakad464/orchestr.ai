// validator_client.js - Overhauled Dashboard Javascript Engine
document.addEventListener("DOMContentLoaded", () => {
    // Basic elements
    const validatorForm = document.getElementById("validator-form");
    const validationWorkspace = document.getElementById("validation-workspace");
    const sidebarHistory = document.getElementById("sidebarHistory");
    const newValidationBtn = document.getElementById("newValidationBtn");
    
    // SMTP settings
    const settingsBtn = document.getElementById("settingsBtn");
    const settingsModal = document.getElementById("settingsModal");
    const closeModal = document.getElementById("closeModal");
    const cancelSettings = document.getElementById("cancelSettings");
    const settingsForm = document.getElementById("settingsForm");
    const testStatus = document.getElementById("testStatus");

    // Pipeline elements
    const timelineContainer = document.getElementById("timelineContainer");
    const subagentsList = document.getElementById("subagentsList");
    const consoleLogs = document.getElementById("consoleLogs");
    const filesSection = document.getElementById("filesSection");
    const filesList = document.getElementById("filesList");
    const resultsSection = document.getElementById("resultsSection");
    const resultsSummary = document.getElementById("resultsSummary");
    const downloadContainer = document.getElementById("downloadContainer");

    // KPI Metrics dashboard
    const metricsDashboard = document.getElementById("metricsDashboard");
    const metricStatus = document.getElementById("metricStatus");
    const metricIssues = document.getElementById("metricIssues");
    const metricDuration = document.getElementById("metricDuration");
    const metricOwner = document.getElementById("metricOwner");

    // Issues Datagrid elements
    const issuesDatagridContainer = document.getElementById("issuesDatagridContainer");
    const issuesTableBody = document.getElementById("issuesTableBody");
    const issuesSearchInput = document.getElementById("issuesSearchInput");
    const sheetFilterSelect = document.getElementById("sheetFilterSelect");

    // Sidebar search & filter controls
    const historySearchInput = document.getElementById("historySearchInput");
    const sidebarFilterBtns = document.querySelectorAll(".sidebar-filter-btn");

    // Drag-and-drop upload elements
    const workbookDragDrop = document.getElementById("workbookDragDrop");
    const hiddenWorkbookInput = document.getElementById("hiddenWorkbookInput");
    const dragDropFilename = document.getElementById("dragDropFilename");

    // Visual rules builder elements
    const visualRulesList = document.getElementById("visualRulesList");
    const addRuleBtn = document.getElementById("addRuleBtn");
    const rulesJsonTextarea = document.getElementById("rulesJsonTextarea");

    let currentSocket = null;
    let selectedRunId = null;
    let selectedWorkbookFile = null;
    let loadedIssues = []; // Cache list of issues for filtering/searching

    // Schema configuration metadata for Visual Rules Builder
    const COLUMN_OPTIONS = [
        "title", "title_category", "title_sub_category", "genre", "primary_genre",
        "companies", "brand_set", "facebook_page", "twitter_handle", "instagram_user",
        "youtube_channel_username", "tiktok_user", "wikidata_id", "imdb_id",
        "rottentomatoes", "released_on", "release_type", "network"
    ];

    const CHECK_OPTIONS = [
        { value: "required", label: "Required (not empty)" },
        { value: "not_blank_and_not_in", label: "Not Blank & Not In List" },
        { value: "in", label: "In approved set" },
        { value: "equals", label: "Equals" },
        { value: "not_equals", label: "Not Equals" },
        { value: "contains", label: "Contains String" },
        { value: "regex", label: "Matches Regex Pattern" },
        { value: "url_not_contains_if_present", label: "URL doesn't contain tokens" },
        { value: "talent_subcategory_format", label: "Talent Subcategory Format" },
        { value: "rottentomatoes_url_match", label: "Rotten Tomatoes URL Match" },
        { value: "movie_us_release_date_match", label: "TMDB Release Date Match" },
        { value: "movie_release_type_match", label: "TMDB Release Type Match" },
        { value: "movie_genre_match", label: "TMDB Genre Match" },
        { value: "social_reference_format", label: "Social Reference Format" }
    ];

    // Default presets dictionary
    const PRESETS = {
        full: null, // Pull from textarea original loading
        metadata: {
            rules: [
                { sheet: "*", column: "title", check: "not_blank_and_not_in", tokens: ["#NA", "N/A"], message: "Title cannot be blank, #NA, or N/A." },
                { sheet: "*", column: "title_category", check: "in", values: ["Movies", "TV Shows", "Talent", "Media", "Other", "IT, Internet, Computing"], message: "Title category is blank or not in the approved list." },
                { sheet: "*", column: "genre", check: "required", when: [{ column: "title_category", operator: "in", values: ["Movies", "TV Shows"] }], message: "Genre is required for Movies and TV Shows." }
            ]
        },
        dar: {
            rules: [
                { sheet: "*", column: "companies", check: "contains_any", values: ["Pristine Brand", "Pristine Talent", "Pristine Film"], when: [{ column: "title", operator: "endswith", value: " - DAR" }], message: "DAR titles must include Pristine Brand, Pristine Talent, or Pristine Film in companies." },
                { sheet: "*", column: "brand_set", check: "contains", value: "Pristine DAR Brands", when: [{ column: "title", operator: "endswith", value: " - DAR" }], message: "DAR titles must include Pristine DAR Brands in brand_set." },
                { sheet: "*", column: "brand_set", check: "contains", value: "Competitive View", when: [{ column: "title", operator: "not_endswith", value: " - DAR" }], message: "Non-DAR titles must include Competitive View in brand_set." }
            ]
        },
        social: {
            rules: [
                { sheet: "*", column: "facebook_page", check: "url_not_contains_if_present", tokens: ["/p/", "/page/", "/pages/", "/php/", "profile.php"], message: "Facebook URL cannot contain /p/, /page/, /pages/, or profile.php" },
                { sheet: "*", column: "twitter_handle", check: "social_reference_format", platform: "twitter", message: "Twitter handle format is invalid." },
                { sheet: "*", column: "youtube_channel_username", check: "social_reference_format", platform: "youtube", message: "YouTube channel handle format is invalid." }
            ]
        }
    };

    // Store the default preset from textarea initial load
    if (rulesJsonTextarea) {
        PRESETS.full = JSON.parse(rulesJsonTextarea.value.trim());
    }

    // 1. TABS NAVIGATION ENGINE
    const tabBtns = document.querySelectorAll(".tab-btn");
    const tabPanes = document.querySelectorAll(".tab-pane");

    tabBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            const targetTab = btn.dataset.tab;
            
            tabBtns.forEach(b => b.classList.remove("active"));
            tabPanes.forEach(p => p.classList.remove("active"));

            btn.classList.add("active");
            document.getElementById(targetTab).classList.add("active");

            // Sync visual rules representation when visual tab opens
            if (targetTab === "tab-visual-builder") {
                loadJsonToVisualBuilder();
            }
        });
    });

    // 2. DRAG AND DROP FILE UPLOAD
    if (workbookDragDrop) {
        workbookDragDrop.addEventListener("click", () => {
            hiddenWorkbookInput.click();
        });

        // drag over
        workbookDragDrop.addEventListener("dragover", (e) => {
            e.preventDefault();
            workbookDragDrop.classList.add("dragging");
        });

        // drag leave
        workbookDragDrop.addEventListener("dragleave", () => {
            workbookDragDrop.classList.remove("dragging");
        });

        // drop file
        workbookDragDrop.addEventListener("drop", (e) => {
            e.preventDefault();
            workbookDragDrop.classList.remove("dragging");
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                processUploadedFile(files[0]);
            }
        });

        // browser select file
        hiddenWorkbookInput.addEventListener("change", () => {
            if (hiddenWorkbookInput.files.length > 0) {
                processUploadedFile(hiddenWorkbookInput.files[0]);
            }
        });
    }

    function processUploadedFile(file) {
        selectedWorkbookFile = file;
        dragDropFilename.textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
        dragDropFilename.style.display = "block";
    }

    // 3. PRESETS SELECTION
    const presetBtns = document.querySelectorAll(".preset-btn");
    presetBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            presetBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            
            const selectedPreset = btn.dataset.preset;
            const rulesObj = PRESETS[selectedPreset];
            if (rulesObj && rulesJsonTextarea) {
                rulesJsonTextarea.value = JSON.stringify(rulesObj, null, 2);
                // Sync to visual builder if it's currently open
                if (document.getElementById("tab-visual-builder").classList.contains("active")) {
                    loadJsonToVisualBuilder();
                }
            }
        });
    });

    // 4. VISUAL RULES CONFIGURATOR CORE
    if (addRuleBtn) {
        addRuleBtn.addEventListener("click", () => {
            const ruleRow = createRuleRow({ sheet: "*", column: "title", check: "required" });
            visualRulesList.appendChild(ruleRow);
            syncVisualRulesToTextarea();
        });
    }

    function loadJsonToVisualBuilder() {
        if (!visualRulesList || !rulesJsonTextarea) return;
        visualRulesList.innerHTML = "";

        try {
            const parsed = JSON.parse(rulesJsonTextarea.value.trim());
            const rules = parsed.rules || (Array.isArray(parsed) ? parsed : []);
            
            rules.forEach(rule => {
                const row = createRuleRow(rule);
                visualRulesList.appendChild(row);
            });
        } catch (e) {
            visualRulesList.innerHTML = `<div style="padding: 20px; text-align: center; color: #ef4444; font-size: 0.85rem;">Rules JSON is currently invalid. Fix it in the Raw JSON Editor to view visually.</div>`;
        }
    }

    function createRuleRow(rule) {
        const row = document.createElement("div");
        row.className = "visual-rule-row";

        // Select columns options
        let colOptsHtml = COLUMN_OPTIONS.map(col => `
            <option value="${col}" ${rule.column === col ? 'selected' : ''}>${col}</option>
        `).join("");

        // Select checks options
        let checkOptsHtml = CHECK_OPTIONS.map(chk => `
            <option value="${chk.value}" ${rule.check === chk.value ? 'selected' : ''}>${chk.label}</option>
        `).join("");

        // Parse existing input value parameter
        let ruleValueStr = "";
        if (rule.values) {
            ruleValueStr = rule.values.join(", ");
        } else if (rule.tokens) {
            ruleValueStr = rule.tokens.join(", ");
        } else if (rule.pattern) {
            ruleValueStr = rule.pattern;
        } else if (rule.value !== undefined && rule.value !== null) {
            ruleValueStr = rule.value;
        }

        row.innerHTML = `
            <input type="text" class="rule-sheet" placeholder="Sheet (e.g. *)" value="${rule.sheet || '*'}" style="width: 100px;">
            <select class="rule-column" style="width: 150px;">
                ${colOptsHtml}
            </select>
            <select class="rule-check" style="width: 200px;">
                ${checkOptsHtml}
            </select>
            <input type="text" class="rule-val" placeholder="Value/Tokens (comma-separated if list)" value="${ruleValueStr}" style="flex: 1;">
            <button type="button" class="btn-delete-rule" title="Delete Rule">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="3 6 5 6 21 6"></polyline>
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                </svg>
            </button>
        `;

        // Add listeners to sync visual changes back to JSON textarea
        row.querySelectorAll("input, select").forEach(el => {
            el.addEventListener("change", syncVisualRulesToTextarea);
            el.addEventListener("input", syncVisualRulesToTextarea);
        });

        row.querySelector(".btn-delete-rule").addEventListener("click", () => {
            row.remove();
            syncVisualRulesToTextarea();
        });

        return row;
    }

    function syncVisualRulesToTextarea() {
        if (!rulesJsonTextarea) return;
        const rules = [];

        document.querySelectorAll("#visualRulesList .visual-rule-row").forEach(row => {
            const sheet = row.querySelector(".rule-sheet").value.trim() || "*";
            const column = row.querySelector(".rule-column").value;
            const check = row.querySelector(".rule-check").value;
            const val = row.querySelector(".rule-val").value.trim();

            const r = { sheet, column, check };

            // Map inputs based on check selection
            if (["in", "contains_any"].includes(check)) {
                r.values = val ? val.split(",").map(s => s.trim()).filter(Boolean) : [];
            } else if (["not_blank_and_not_in", "url_not_contains_if_present", "talent_subcategory_format"].includes(check)) {
                r.tokens = val ? val.split(",").map(s => s.trim()).filter(Boolean) : [];
            } else if (check === "regex") {
                r.pattern = val || null;
            } else if (["equals", "not_equals", "contains"].includes(check)) {
                r.value = val || null;
            }
            rules.push(r);
        });

        rulesJsonTextarea.value = JSON.stringify({ rules }, null, 2);
    }

    // 5. FORM SUBMISSION (WITH SELECTED FILE DRAG AND DROP CAPTURE)
    if (validatorForm) {
        validatorForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            
            const submitBtn = validatorForm.querySelector("button[type='submit']");
            const runByInput = validatorForm.querySelector("input[name='run_by']");
            
            if (runByInput && !runByInput.value.trim()) {
                alert("Please enter a name in the 'Run by' field.");
                return;
            }

            if (submitBtn) submitBtn.disabled = true;
            
            // Clean timeline logs and panels
            consoleLogs.innerHTML = "";
            filesList.innerHTML = "";
            filesSection.style.display = "none";
            resultsSection.style.display = "none";
            issuesDatagridContainer.style.display = "none";
            downloadContainer.innerHTML = "";
            loadedIssues = [];

            const formData = new FormData(validatorForm);
            
            // Override with drag-and-drop selected file if present
            if (selectedWorkbookFile) {
                formData.set("workbook", selectedWorkbookFile);
            }
            
            try {
                const response = await fetch("/validate-excel", {
                    method: "POST",
                    body: formData
                });

                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.error || "Validation run failed to register.");
                }

                selectedRunId = data.validation_id;
                
                // Show panels
                timelineContainer.style.display = "block";
                validationWorkspace.style.display = "block";
                
                // Connect to WebSocket stream
                connectWebSocket(data.validation_id);

            } catch (err) {
                alert("Validation Error: " + err.message);
                if (submitBtn) submitBtn.disabled = false;
            }
        });
    }

    // 6. WEBSOCKET AND STREAMING UPDATE INTERFACE
    function connectWebSocket(runId) {
        if (currentSocket) {
            currentSocket.close();
        }

        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${protocol}//${window.location.host}/excel-validator/ws/${runId}`;
        currentSocket = new WebSocket(wsUrl);

        currentSocket.onmessage = (event) => {
            const state = JSON.parse(event.data);
            
            // Render subagent list nodes
            renderSubagentsList(state.active_agent, state.status);

            // Re-render console logs
            consoleLogs.innerHTML = "";
            state.logs.forEach(log => appendLog(log));

            if (state.status === "completed" || state.status === "failed") {
                currentSocket.close();
                renderModifiedFiles(state.modified_files);
                renderResultsSummary(state);
                reloadSidebarHistory();

                // If completed, fetch issues datagrid details
                if (state.status === "completed") {
                    fetchRunIssues(runId);
                }
            }
        };

        currentSocket.onclose = () => {
            const submitBtn = validatorForm ? validatorForm.querySelector("button[type='submit']") : null;
            if (submitBtn) submitBtn.disabled = false;
        };
    }

    function appendLog(log) {
        const row = document.createElement("div");
        row.className = "log-row";

        const timestamp = document.createElement("span");
        timestamp.className = "log-timestamp";
        timestamp.textContent = `[${log.timestamp}]`;

        const agent = document.createElement("span");
        agent.className = "log-agent";
        agent.textContent = `${log.agent}:`;

        const msg = document.createElement("span");
        msg.className = "log-message";
        msg.textContent = log.message;

        row.appendChild(timestamp);
        row.appendChild(agent);
        row.appendChild(msg);

        consoleLogs.appendChild(row);
        consoleLogs.scrollTop = consoleLogs.scrollHeight;
    }

    function renderSubagentsList(activeAgent, status) {
        const subagents = [
            { id: "Orchestrator", name: "Orchestrator Agent", desc: "Setting up rule configurations and mapping task scope." },
            { id: "File Analyst", name: "File Analyst", desc: "Parsing workbook sheets metadata and cataloging columns." },
            { id: "Data Ops Validator", name: "Data Ops Validator", desc: "Evaluating cell validations, highlighting cells, and writing workbook notes." },
            { id: "Email Dispatcher", name: "Email Dispatcher", desc: "Sending validation reports and compiling file change lists." }
        ];

        subagentsList.innerHTML = "";

        let activeIdx = subagents.findIndex(s => s.id === activeAgent);
        const isFinished = status === "completed";
        const isFailed = status === "failed";

        subagents.forEach((agent, idx) => {
            const node = document.createElement("div");
            node.className = "subagent-node";

            if (isFinished) {
                node.classList.add("completed");
            } else if (isFailed) {
                if (idx < activeIdx) node.classList.add("completed");
                if (idx === activeIdx) node.style.borderColor = "var(--dark-accent-pink)";
            } else {
                if (idx < activeIdx) {
                    node.classList.add("completed");
                } else if (idx === activeIdx) {
                    node.classList.add("active");
                }
            }

            node.innerHTML = `
                <div class="subagent-status-dot"></div>
                <div class="subagent-info">
                    <div class="subagent-title">${agent.name}</div>
                    <div class="subagent-desc">${agent.desc}</div>
                    <div class="agent-shimmer-bar">
                        <div class="shimmer-progress"></div>
                    </div>
                </div>
            `;
            subagentsList.appendChild(node);
        });
    }

    // 7. LOAD HISTORY RUN SELECTION
    async function selectValidationRun(runId) {
        if (currentSocket) {
            currentSocket.close();
        }
        selectedRunId = runId;

        // Toggle active highlight in history sidebar
        document.querySelectorAll(".history-item").forEach(i => {
            if (i.dataset.runId === runId) {
                i.classList.add("active");
            } else {
                i.classList.remove("active");
            }
        });
        
        timelineContainer.style.display = "block";
        consoleLogs.innerHTML = "";
        filesList.innerHTML = "";
        issuesDatagridContainer.style.display = "none";
        loadedIssues = [];

        try {
            const res = await fetch(`/excel-validator/run/${runId}`);
            const state = await res.json();

            // Render details
            renderSubagentsList(state.active_agent, state.status);
            state.logs.forEach(log => appendLog(log));

            if (state.status === "completed" || state.status === "failed") {
                renderModifiedFiles(state.modified_files);
                renderResultsSummary(state);
                
                // Load cell issues grid details
                if (state.issues) {
                    loadedIssues = state.issues;
                    renderIssuesGrid(state.issues);
                } else {
                    fetchRunIssues(runId);
                }
            } else {
                // Task is still running (connect socket back)
                connectWebSocket(runId);
            }

        } catch (err) {
            console.error("Error loading run details:", err);
        }
    }

    async function fetchRunIssues(runId) {
        try {
            const res = await fetch(`/excel-validator/run/${runId}`);
            const state = await res.json();
            if (state.issues) {
                loadedIssues = state.issues;
                renderIssuesGrid(state.issues);
            }
        } catch (err) {
            console.error("Failed to load workbook issues:", err);
        }
    }

    function renderResultsSummary(state) {
        resultsSection.style.display = "block";
        
        const isSuccess = state.status === "completed";
        resultsSummary.innerHTML = `
            <div style="font-size: 0.95rem; margin-bottom: 12px; line-height: 1.5;">
                ${state.summary ? state.summary.replace(/\n/g, '<br>') : 'Validation completed.'}
            </div>
        `;

        // Update KPI Dashboard
        metricStatus.textContent = state.status.toUpperCase();
        metricStatus.style.color = isSuccess ? '#10b981' : '#ef4444';
        
        metricIssues.textContent = `${state.issue_count} issues`;
        metricIssues.style.color = state.issue_count > 0 ? '#ef4444' : '#10b981';

        metricDuration.textContent = state.duration_seconds > 0 ? `${state.duration_seconds.toFixed(1)}s` : '0.0s';
        metricOwner.textContent = state.run_by || 'system';

        downloadContainer.innerHTML = "";
        if (isSuccess) {
            const dlBtn = document.createElement("a");
            dlBtn.href = `/validate-excel/download/${state.validation_id}`;
            dlBtn.className = "btn-download-validated";
            dlBtn.innerHTML = `
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="margin-right: 8px;">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                    <polyline points="7 10 12 15 17 10"></polyline>
                    <line x1="12" y1="15" x2="12" y2="3"></line>
                </svg>
                Download Validated Workbook
            `;
            downloadContainer.appendChild(dlBtn);
        }
    }

    function renderModifiedFiles(files) {
        filesList.innerHTML = "";
        if (files && files.length > 0) {
            filesSection.style.display = "block";
            files.forEach(f => {
                const li = document.createElement("li");
                li.className = "file-item";

                const pathSpan = document.createElement("span");
                pathSpan.textContent = f.path;

                const meta = document.createElement("div");
                meta.style.display = "flex";
                meta.style.gap = "10px";
                meta.style.alignItems = "center";

                const size = document.createElement("span");
                size.style.fontSize = "0.75rem";
                size.style.color = "var(--dark-text-muted)";
                size.textContent = f.size_bytes > 0 ? `${f.size_bytes} bytes` : "";

                const badge = document.createElement("span");
                badge.className = `file-status-badge file-${f.status.toLowerCase()}`;
                badge.textContent = f.status;

                meta.appendChild(size);
                meta.appendChild(badge);
                li.appendChild(pathSpan);
                li.appendChild(meta);

                filesList.appendChild(li);
            });
        } else {
            filesSection.style.display = "none";
        }
    }

    // Bind sidebar runs clicks
    function bindSidebarHistoryItems() {
        document.querySelectorAll(".history-item").forEach(item => {
            item.addEventListener("click", () => {
                selectValidationRun(item.dataset.runId);
            });
        });
    }
    bindSidebarHistoryItems();

    if (newValidationBtn) {
        newValidationBtn.addEventListener("click", () => {
            if (currentSocket) {
                currentSocket.close();
            }
            selectedRunId = null;
            selectedWorkbookFile = null;
            if (dragDropFilename) {
                dragDropFilename.textContent = "";
                dragDropFilename.style.display = "none";
            }
            timelineContainer.style.display = "none";
            resultsSection.style.display = "none";
            issuesDatagridContainer.style.display = "none";
            validationWorkspace.style.display = "block";
            
            const submitBtn = validatorForm ? validatorForm.querySelector("button[type='submit']") : null;
            if (submitBtn) submitBtn.disabled = false;

            // Remove active sidebar highlight
            document.querySelectorAll(".history-item").forEach(i => i.classList.remove("active"));
        });
    }

    async function reloadSidebarHistory() {
        try {
            const res = await fetch("/excel-validator");
            const parser = new DOMParser();
            const doc = parser.parseFromString(await res.text(), "text/html");
            const newHistory = doc.getElementById("sidebarHistory");
            if (newHistory && sidebarHistory) {
                sidebarHistory.innerHTML = newHistory.innerHTML;
                bindSidebarHistoryItems();
                runSidebarFiltersAndSearch();
            }
        } catch (err) {
            console.error("Failed to reload history list:", err);
        }
    }

    // 8. INTERACTIVE CELL ISSUES DATAGRID
    function renderIssuesGrid(issues) {
        issuesTableBody.innerHTML = "";
        sheetFilterSelect.innerHTML = '<option value="all">All Sheets</option>';

        if (!issues || issues.length === 0) {
            issuesDatagridContainer.style.display = "none";
            return;
        }

        issuesDatagridContainer.style.display = "block";
        const sheetsSet = new Set();

        issues.forEach(issue => {
            sheetsSet.add(issue.sheet);
            const tr = document.createElement("tr");
            tr.dataset.sheet = issue.sheet;
            tr.dataset.rule = issue.rule;
            tr.dataset.cell = issue.cell;
            tr.dataset.message = issue.message;
            tr.dataset.value = issue.value;

            // Set badge class based on error severity
            const badgeClass = issue.message.toLowerCase().includes("should match") || issue.message.toLowerCase().includes("removing") ? "badge-warning" : "badge-error";
            const severityLabel = badgeClass === "badge-warning" ? "Warning" : "Error";

            tr.innerHTML = `
                <td style="padding: 12px 16px; font-weight: 500;">${issue.sheet}</td>
                <td style="padding: 12px 16px; font-family: monospace; font-weight: 600;">${issue.cell}</td>
                <td style="padding: 12px 16px;">
                    <span class="badge-severity ${badgeClass}">${issue.rule}</span>
                </td>
                <td style="padding: 12px 16px; font-family: monospace; max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${issue.value || '-'}</td>
                <td style="padding: 12px 16px; color: var(--dark-text-muted); line-height: 1.4;">${issue.message}</td>
            `;
            issuesTableBody.appendChild(tr);
        });

        // Populate sheet select options
        sheetsSet.forEach(sheet => {
            const opt = document.createElement("option");
            opt.value = sheet;
            opt.textContent = sheet;
            sheetFilterSelect.appendChild(opt);
        });

        // Attach filters
        issuesSearchInput.addEventListener("input", filterIssuesTable);
        sheetFilterSelect.addEventListener("change", filterIssuesTable);
    }

    function filterIssuesTable() {
        const query = issuesSearchInput.value.toLowerCase().trim();
        const selectedSheet = sheetFilterSelect.value;

        document.querySelectorAll("#issuesTableBody tr").forEach(tr => {
            const sheet = tr.dataset.sheet;
            const cell = tr.dataset.cell.toLowerCase();
            const rule = tr.dataset.rule.toLowerCase();
            const message = tr.dataset.message.toLowerCase();
            const value = tr.dataset.value.toLowerCase();

            const matchesSheet = selectedSheet === "all" || sheet === selectedSheet;
            const matchesQuery = !query || 
                                 cell.includes(query) || 
                                 rule.includes(query) || 
                                 message.includes(query) || 
                                 value.includes(query) ||
                                 sheet.toLowerCase().includes(query);

            if (matchesSheet && matchesQuery) {
                tr.style.display = "";
            } else {
                tr.style.display = "none";
            }
        });
    }

    // 9. SIDEBAR HISTORY SEARCH & FILTER SYSTEM
    if (historySearchInput) {
        historySearchInput.addEventListener("input", runSidebarFiltersAndSearch);
    }

    sidebarFilterBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            sidebarFilterBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            runSidebarFiltersAndSearch();
        });
    });

    function runSidebarFiltersAndSearch() {
        const query = historySearchInput ? historySearchInput.value.toLowerCase().trim() : "";
        const activeFilterBtn = document.querySelector(".sidebar-filter-btn.active");
        const filterType = activeFilterBtn ? activeFilterBtn.dataset.filter : "all";

        document.querySelectorAll("#sidebarHistory .history-item").forEach(item => {
            const filename = item.dataset.filename.toLowerCase();
            const runBy = item.dataset.runBy.toLowerCase();
            const issueCount = parseInt(item.dataset.issueCount || "0");

            const matchesQuery = !query || filename.includes(query) || runBy.includes(query);
            
            let matchesFilter = true;
            if (filterType === "issues") {
                matchesFilter = issueCount > 0;
            } else if (filterType === "clean") {
                matchesFilter = issueCount === 0;
            }

            if (matchesQuery && matchesFilter) {
                item.style.display = "";
            } else {
                item.style.display = "none";
            }
        });
    }

    // Modal settings toggles
    if (settingsBtn) {
        settingsBtn.addEventListener("click", () => {
            settingsModal.style.display = "flex";
        });
    }

    const hideModal = () => {
        settingsModal.style.display = "none";
        testStatus.style.display = "none";
        testStatus.textContent = "";
    };

    if (closeModal) closeModal.addEventListener("click", hideModal);
    if (cancelSettings) cancelSettings.addEventListener("click", hideModal);

    if (settingsForm) {
        settingsForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const formData = new FormData(settingsForm);

            testStatus.style.display = "block";
            testStatus.style.backgroundColor = "rgba(255, 255, 255, 0.05)";
            testStatus.style.color = "var(--text-primary)";
            testStatus.textContent = "Testing configurations & saving SMTP setup...";

            try {
                const res = await fetch("/excel-validator/settings", {
                    method: "POST",
                    body: formData
                });

                const data = await res.json();
                if (data.success) {
                    if (data.test_sent) {
                        testStatus.style.backgroundColor = "rgba(52, 168, 83, 0.15)";
                        testStatus.style.color = "#34a853";
                        testStatus.textContent = "SMTP hook saved & verified! Alert email dispatched successfully.";
                    } else {
                        testStatus.style.backgroundColor = "rgba(251, 188, 5, 0.15)";
                        testStatus.style.color = "#fbbc05";
                        testStatus.textContent = data.test_error || "Configuration saved. SMTP offline (wrote to fallback emails/sent_emails.log).";
                    }
                    setTimeout(hideModal, 3000);
                } else {
                    throw new Error("Failed to save settings.");
                }
            } catch (err) {
                testStatus.style.backgroundColor = "rgba(219, 68, 85, 0.15)";
                testStatus.style.color = "#db4437";
                testStatus.textContent = "Error: " + err.message;
            }
        });
    }
});
