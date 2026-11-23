// Gourmet Delight - Customer Portal Logic

const API_BASE = "";
let currentThreadId = null;
let pollInterval = null;

// DOM Elements
const btnThemeToggle = document.getElementById("btn-theme-toggle");
const themeIcon = document.getElementById("theme-icon");
const themeText = document.getElementById("theme-text");
const menuContainer = document.getElementById("menu-container");
const menuCountBadge = document.getElementById("menu-count");
const chatFeed = document.getElementById("chat-feed");
const orderForm = document.getElementById("order-form");
const orderInput = document.getElementById("order-input");
const btnSubmitOrder = document.getElementById("btn-submit-order");
const liveLogs = document.getElementById("live-logs");
const workflowBadge = document.getElementById("workflow-status-badge");
const customerReorderContainer = document.getElementById("customer-reorder-container");
const customerReorderBox = document.getElementById("customer-reorder-box");
const kitchenStatusBanner = document.getElementById("kitchen-status-banner");
const receiptContainer = document.getElementById("receipt-container");
const restockCountdown = document.getElementById("restock-countdown");

const pipelineSteps = {
    api: document.getElementById("step-api"),
    relevance: document.getElementById("step-relevance"),
    db: document.getElementById("step-db"),
    cook: document.getElementById("step-cook"),
    serve: document.getElementById("step-serve")
};

// ============================================================================
// 0. AMBIENCE (DAY / NIGHT) THEME CONTROLLER
// ============================================================================

function applyTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("gourmet_theme", theme);
    if (theme === "day") {
        if (themeIcon) themeIcon.textContent = "🌙";
        if (themeText) themeText.textContent = "Night Ambience";
    } else {
        if (themeIcon) themeIcon.textContent = "☀️";
        if (themeText) themeText.textContent = "Day Ambience";
    }
}

const savedTheme = localStorage.getItem("gourmet_theme") || "night";
applyTheme(savedTheme);

btnThemeToggle?.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-theme") || "night";
    applyTheme(current === "night" ? "day" : "night");
});

// 1. Fetch & Render Menu
async function fetchMenu() {
    try {
        const res = await fetch(`${API_BASE}/api/menu`);
        if (!res.ok) throw new Error("Failed to load menu");
        const data = await res.json();
        renderMenu(data.menu);

        if (data.last_restocked_at) {
            const lastDate = new Date(data.last_restocked_at);
            const nextDate = new Date(lastDate.getTime() + 24 * 60 * 60 * 1000);
            const hoursLeft = Math.max(0, Math.round((nextDate - new Date()) / (1000 * 60 * 60)));
            restockCountdown.textContent = `24h Restock: in ${hoursLeft}h`;
        }
    } catch (err) {
        console.error("Error fetching menu:", err);
    }
}

function renderMenu(items) {
    menuContainer.innerHTML = "";
    menuCountBadge.textContent = `${items.length} items`;

    items.forEach(item => {
        const row = document.createElement("div");
        row.className = "menu-item-row";
        
        let stockClass = "";
        if (item.stock <= 0) stockClass = "out";
        else if (item.stock <= 5) stockClass = "low";

        row.innerHTML = `
            <div class="item-info">
                <strong>${item.name}</strong>
                <span class="item-cat">${item.category}</span>
            </div>
            <div class="item-action">
                <span class="item-price">$${item.price.toFixed(2)}</span>
                <span class="stock-pill ${stockClass}">${item.stock} left</span>
            </div>
        `;

        row.addEventListener("click", () => {
            if (item.stock <= 0) {
                alert(`${item.name} is currently out of stock!`);
                return;
            }
            if (!orderInput.value) {
                orderInput.value = `1 ${item.name}`;
            } else {
                orderInput.value += ` and 1 ${item.name}`;
            }
            orderInput.focus();
        });

        menuContainer.appendChild(row);
    });
}

// 2. Chat Feed & Pipeline Visualizer
function addChatBubble(text, sender = "bot", extraClass = "") {
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${sender} ${extraClass}`;
    bubble.innerHTML = text.replace(/\n/g, "<br>");
    chatFeed.appendChild(bubble);
    chatFeed.scrollTop = chatFeed.scrollHeight;
}

function updatePipelineSteps(logs) {
    Object.values(pipelineSteps).forEach(el => el.className = "pipeline-step");
    const allLogsText = logs.join(" ");

    if (allLogsText.includes("[TASK: API Check]")) {
        pipelineSteps.api.className = allLogsText.includes("API keys detected") ? "pipeline-step completed" : "pipeline-step active";
    }

    if (allLogsText.includes("[TASK: Input Relevance]")) {
        pipelineSteps.relevance.className = (allLogsText.includes("Relevant food order parsed") || allLogsText.includes("Second input is valid")) ? "pipeline-step completed" : "pipeline-step active";
    }

    if (allLogsText.includes("[TASK: Database Inventory Check]")) {
        pipelineSteps.db.className = (allLogsText.includes("verified in DB") || allLogsText.includes("verified and reserved in MongoDB")) ? "pipeline-step completed" : "pipeline-step active";
    }

    if (allLogsText.includes("[TASK: Kitchen Cook]")) {
        if (allLogsText.includes("successfully prepared") || allLogsText.includes("Passing to Server")) {
            pipelineSteps.cook.className = "pipeline-step completed";
        } else {
            pipelineSteps.cook.className = "pipeline-step active";
        }
    }

    if (allLogsText.includes("[TASK: Serve & Billing]")) {
        pipelineSteps.serve.className = "pipeline-step completed";
    }
}

function updateLiveLogs(logs) {
    if (!logs || logs.length === 0) return;
    liveLogs.innerHTML = "";
    logs.forEach(line => {
        const div = document.createElement("div");
        div.className = "log-line";
        div.textContent = line;
        liveLogs.appendChild(div);
    });
    liveLogs.scrollTop = liveLogs.scrollHeight;
}

// 3. Order Submission
orderForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = orderInput.value.trim();
    if (!query) return;

    stopPolling();
    orderInput.value = "";
    receiptContainer.classList.add("hidden");
    customerReorderContainer.classList.add("hidden");
    kitchenStatusBanner.classList.add("hidden");
    workflowBadge.textContent = "Processing";
    workflowBadge.className = "badge status-badge running";

    addChatBubble(query, "user");

    btnSubmitOrder.disabled = true;
    btnSubmitOrder.innerHTML = `<span>Placing...</span> ⏳`;

    try {
        const res = await fetch(`${API_BASE}/api/order`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_input: query })
        });
        const data = await res.json();
        handleServerResponse(data);
    } catch (err) {
        addChatBubble(`❌ Error: ${err.message}`, "bot");
        workflowBadge.textContent = "Error";
        workflowBadge.className = "badge status-badge failed";
    } finally {
        btnSubmitOrder.disabled = false;
        btnSubmitOrder.innerHTML = `<span>Place Order</span> 🚀`;
    }
});

function handleServerResponse(data) {
    currentThreadId = data.thread_id;
    const logs = data.workflow_logs || [];
    updateLiveLogs(logs);
    updatePipelineSteps(logs);
    fetchMenu();

    if (data.status === "INTERRUPTED") {
        const intType = data.interrupt?.type;

        if (intType === "cook_admin_review") {
            // Kitchen is cooking! Show cooking banner and poll for chef's action
            kitchenStatusBanner.classList.remove("hidden");
            customerReorderContainer.classList.add("hidden");
            workflowBadge.textContent = "Cooking (Chef Review)";
            workflowBadge.className = "badge status-badge running";
            startPollingStatus();
        } 
        else if (intType === "reorder_irrelevant" || intType === "reorder_db_not_found") {
            // Customer input needed! Show 2nd chance reorder box
            kitchenStatusBanner.classList.add("hidden");
            customerReorderContainer.classList.remove("hidden");
            customerReorderBox.innerHTML = `
                <div class="hitl-title">⚠️ Notice: 2nd Chance to Reorder</div>
                <p class="hitl-desc">${data.interrupt.message}</p>
                <div class="input-wrapper" style="margin-top: 0.5rem;">
                    <input type="text" id="reorder-input" placeholder="Type your corrected order..." style="flex: 1; padding: 0.6rem; border-radius: 6px; background: #0c0f17; color: #fff; border: 1px solid #334155;">
                    <button class="btn-primary" id="btn-submit-reorder">Submit</button>
                </div>
            `;
            document.getElementById("btn-submit-reorder").addEventListener("click", () => {
                const val = document.getElementById("reorder-input").value.trim();
                if (val) submitCustomerResume(val);
            });
        }
    } else if (data.status === "COMPLETED") {
        stopPolling();
        kitchenStatusBanner.classList.add("hidden");
        customerReorderContainer.classList.add("hidden");
        workflowBadge.textContent = "Completed & Served";
        workflowBadge.className = "badge status-badge completed";
        if (data.final_message) {
            addChatBubble(data.final_message, "bot", "success-bubble");
        }
        if (data.bill) {
            renderReceipt(data.bill);
        }
    } else if (data.status === "FAILED") {
        stopPolling();
        kitchenStatusBanner.classList.add("hidden");
        customerReorderContainer.classList.add("hidden");
        workflowBadge.textContent = "Order Exited";
        workflowBadge.className = "badge status-badge failed";
        if (data.final_message) {
            addChatBubble(data.final_message, "bot", "system-alert");
        }
    }
}

// 4. Polling while Kitchen is Cooking
function startPollingStatus() {
    if (pollInterval) clearInterval(pollInterval);
    pollInterval = setInterval(async () => {
        if (!currentThreadId) return;
        try {
            const res = await fetch(`${API_BASE}/api/order-status/${currentThreadId}`);
            if (res.ok) {
                const data = await res.json();
                if (data.status !== "INTERRUPTED" || data.interrupt?.type !== "cook_admin_review") {
                    handleServerResponse(data);
                }
            }
        } catch (err) {
            console.error("Status polling error:", err);
        }
    }, 1200);
}

function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

async function submitCustomerResume(responseValue) {
    customerReorderContainer.classList.add("hidden");
    addChatBubble(`👉 Corrected order: <strong>${responseValue}</strong>`, "user");

    try {
        const res = await fetch(`${API_BASE}/api/resume`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                thread_id: currentThreadId,
                response: responseValue
            })
        });
        const data = await res.json();
        handleServerResponse(data);
    } catch (err) {
        addChatBubble(`❌ Error: ${err.message}`, "bot");
    }
}

// 5. Receipt Renderer
function renderReceipt(bill) {
    receiptContainer.classList.remove("hidden");
    document.getElementById("receipt-order-id").textContent = `#${bill.order_id || 'ORD-0001'}`;
    document.getElementById("receipt-subtotal").textContent = `$${bill.subtotal.toFixed(2)}`;
    document.getElementById("receipt-tax").textContent = `$${bill.tax_amount.toFixed(2)}`;
    document.getElementById("receipt-grand-total").textContent = `$${bill.grand_total.toFixed(2)}`;

    const itemsContainer = document.getElementById("receipt-items");
    itemsContainer.innerHTML = "";
    (bill.items || []).forEach(it => {
        const row = document.createElement("div");
        row.className = "receipt-row";
        row.innerHTML = `<span>${it.quantity}x ${it.name}</span><strong>$${it.item_total.toFixed(2)}</strong>`;
        itemsContainer.appendChild(row);
    });
}

// Quick chip buttons
document.querySelectorAll(".chip").forEach(chip => {
    chip.addEventListener("click", () => {
        orderInput.value = chip.dataset.query;
        orderForm.dispatchEvent(new Event("submit"));
    });
});

document.getElementById("btn-clear-chat").addEventListener("click", () => {
    stopPolling();
    chatFeed.innerHTML = `
        <div class="chat-bubble bot welcome-bubble">
            <p>👋 Ready for your new order! What can I get for you?</p>
        </div>
    `;
    receiptContainer.classList.add("hidden");
    customerReorderContainer.classList.add("hidden");
    kitchenStatusBanner.classList.add("hidden");
    workflowBadge.textContent = "Idle";
    workflowBadge.className = "badge status-badge";
    Object.values(pipelineSteps).forEach(el => el.className = "pipeline-step");
});

// Boot
fetchMenu();
