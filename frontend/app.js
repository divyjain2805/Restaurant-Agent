// Gourmet AI Restaurant Automation - Frontend Controller

const API_BASE = "";
let currentThreadId = null;

// DOM Elements
const menuContainer = document.getElementById("menu-container");
const menuCountBadge = document.getElementById("menu-count");
const chatFeed = document.getElementById("chat-feed");
const orderForm = document.getElementById("order-form");
const orderInput = document.getElementById("order-input");
const btnSubmitOrder = document.getElementById("btn-submit-order");
const liveLogs = document.getElementById("live-logs");
const workflowBadge = document.getElementById("workflow-status-badge");
const hitlContainer = document.getElementById("hitl-container");
const hitlBox = document.getElementById("hitl-box");
const receiptContainer = document.getElementById("receipt-container");
const btnForceRestock = document.getElementById("btn-force-restock");
const restockCountdown = document.getElementById("restock-countdown");

// Pipeline steps
const pipelineSteps = {
    api: document.getElementById("step-api"),
    relevance: document.getElementById("step-relevance"),
    db: document.getElementById("step-db"),
    cook: document.getElementById("step-cook"),
    serve: document.getElementById("step-serve")
};

// ============================================================================
// 1. MENU & INVENTORY FUNCTIONS
// ============================================================================

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

        // Click to add to order input
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

// Force 24-hour restock button
btnForceRestock.addEventListener("click", async () => {
    btnForceRestock.classList.add("spinning");
    try {
        const res = await fetch(`${API_BASE}/api/restock`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ force: true })
        });
        const data = await res.json();
        alert(data.message);
        renderMenu(data.menu);
    } catch (err) {
        alert("Restock failed: " + err.message);
    } finally {
        btnForceRestock.classList.remove("spinning");
    }
});

// ============================================================================
// 2. CHAT & PIPELINE VISUALIZATION
// ============================================================================

function addChatBubble(text, sender = "bot", extraClass = "") {
    const bubble = document.createElement("div");
    bubble.className = `chat-bubble ${sender} ${extraClass}`;
    bubble.innerHTML = text.replace(/\n/g, "<br>");
    chatFeed.appendChild(bubble);
    chatFeed.scrollTop = chatFeed.scrollHeight;
}

function updatePipelineSteps(logs) {
    // Reset all
    Object.values(pipelineSteps).forEach(el => el.className = "pipeline-step");

    const allLogsText = logs.join(" ");

    if (allLogsText.includes("[TASK: API Check]")) {
        if (allLogsText.includes("API keys detected")) {
            pipelineSteps.api.className = "pipeline-step completed";
        } else if (allLogsText.includes("No Gemini or Groq")) {
            pipelineSteps.api.className = "pipeline-step active";
        }
    }

    if (allLogsText.includes("[TASK: Input Relevance]")) {
        if (allLogsText.includes("Relevant food order parsed") || allLogsText.includes("Second input is valid")) {
            pipelineSteps.relevance.className = "pipeline-step completed";
        } else {
            pipelineSteps.relevance.className = "pipeline-step active";
        }
    }

    if (allLogsText.includes("[TASK: Database Inventory Check]")) {
        if (allLogsText.includes("verified in DB") || allLogsText.includes("verified and reserved in MongoDB")) {
            pipelineSteps.db.className = "pipeline-step completed";
        } else {
            pipelineSteps.db.className = "pipeline-step active";
        }
    }

    if (allLogsText.includes("[TASK: Kitchen Cook]")) {
        if (allLogsText.includes("Admin approved: Order") || allLogsText.includes("successfully prepared")) {
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

// ============================================================================
// 3. ORDER SUBMISSION & RESUME HANDLER
// ============================================================================

orderForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = orderInput.value.trim();
    if (!query) return;

    // Reset UI
    orderInput.value = "";
    receiptContainer.classList.add("hidden");
    hitlContainer.classList.add("hidden");
    workflowBadge.textContent = "Processing";
    workflowBadge.className = "badge status-badge running";

    addChatBubble(query, "user");

    btnSubmitOrder.disabled = true;
    btnSubmitOrder.innerHTML = `<span>Ordering...</span> ⏳`;

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
        btnSubmitOrder.innerHTML = `<span>Send Order</span> 🚀`;
    }
});

function handleServerResponse(data) {
    currentThreadId = data.thread_id;
    const logs = data.workflow_logs || [];
    updateLiveLogs(logs);
    updatePipelineSteps(logs);
    fetchMenu(); // Refresh stock

    if (data.status === "INTERRUPTED") {
        handleInterrupt(data.interrupt);
    } else if (data.status === "COMPLETED") {
        workflowBadge.textContent = "Completed";
        workflowBadge.className = "badge status-badge completed";
        if (data.final_message) {
            addChatBubble(data.final_message, "bot", "success-bubble");
        }
        if (data.bill) {
            renderReceipt(data.bill);
        }
    } else if (data.status === "FAILED") {
        workflowBadge.textContent = "Failed / Exited";
        workflowBadge.className = "badge status-badge failed";
        if (data.final_message) {
            addChatBubble(data.final_message, "bot", "system-alert");
        }
    }
}

// ============================================================================
// 4. HUMAN-IN-THE-LOOP (HITL) & 8-SECOND TIMER WITH PROBABILITY
// ============================================================================

let adminTimerInterval = null;

function clearAdminCountdown() {
    if (adminTimerInterval) {
        clearInterval(adminTimerInterval);
        adminTimerInterval = null;
    }
}

function handleInterrupt(interruptData) {
    hitlContainer.classList.remove("hidden");
    hitlBox.innerHTML = "";
    clearAdminCountdown();

    const intType = interruptData.type;

    if (intType === "cook_admin_review") {
        let secondsRemaining = 8;

        hitlBox.innerHTML = `
            <div class="hitl-header-row">
                <div class="hitl-title">👨‍🍳 Chef / Admin Role Interrupt (Attempt #${interruptData.attempt})</div>
                <span class="timer-badge" id="admin-timer-badge">⏱️ 8s left</span>
            </div>
            <p class="hitl-desc">${interruptData.prompt} (Order #${interruptData.order_id})</p>
            <div class="timer-bar-track">
                <div class="timer-bar-fill" id="timer-bar-fill"></div>
            </div>
            <p class="timer-caption">⚡ If no response within 8 seconds, system auto-decides using cooking probability (85% pass, 15% fail).</p>
            <div class="hitl-btn-group" style="margin-top: 0.75rem;">
                <button class="btn-approve" id="btn-approve-cook">✅ Approve (Manual)</button>
                <button class="btn-reject" id="btn-reject-cook">❌ Fail (Manual)</button>
            </div>
        `;

        const timerBadge = document.getElementById("admin-timer-badge");
        const timerFill = document.getElementById("timer-bar-fill");

        adminTimerInterval = setInterval(() => {
            secondsRemaining -= 1;
            if (timerBadge) timerBadge.textContent = `⏱️ ${secondsRemaining}s left`;
            if (timerFill) timerFill.style.width = `${(secondsRemaining / 8) * 100}%`;

            if (secondsRemaining <= 0) {
                clearAdminCountdown();
                addChatBubble(`⏱️ <em>8-second admin timer expired. Auto-resolving using probability...</em>`, "bot", "system-alert");
                sendResume("timeout");
            }
        }, 1000);

        document.getElementById("btn-approve-cook").addEventListener("click", () => {
            clearAdminCountdown();
            sendResume("approved");
        });

        document.getElementById("btn-reject-cook").addEventListener("click", () => {
            clearAdminCountdown();
            sendResume("failed");
        });
    
    } else if (intType === "reorder_irrelevant" || intType === "reorder_db_not_found") {
        hitlBox.innerHTML = `
            <div class="hitl-title">⚠️ Customer Attention: 2nd Chance Allowed</div>
            <p class="hitl-desc">${interruptData.message}</p>
            <div class="input-wrapper" style="margin-top: 0.5rem;">
                <input type="text" id="reorder-input" placeholder="Type your replacement order..." style="flex: 1; padding: 0.5rem; border-radius: 6px; background: #0c0f17; color: #fff; border: 1px solid #334155;">
                <button class="btn-primary" id="btn-submit-reorder">Submit 2nd Chance</button>
            </div>
        `;

        document.getElementById("btn-submit-reorder").addEventListener("click", () => {
            const val = document.getElementById("reorder-input").value.trim();
            if (val) sendResume(val);
        });
    }
}

async function sendResume(responseValue) {
    clearAdminCountdown();
    hitlContainer.classList.add("hidden");
    const displayVal = responseValue === "timeout" ? "⏱️ [Timeout - Auto Probability]" : responseValue;
    addChatBubble(`👉 Action: <strong>${displayVal}</strong>`, "user");

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
        addChatBubble(`❌ Resume Error: ${err.message}`, "bot");
    }
}

// ============================================================================
// 5. RECEIPT RENDERER
// ============================================================================

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

// Clear chat
document.getElementById("btn-clear-chat").addEventListener("click", () => {
    chatFeed.innerHTML = `
        <div class="chat-bubble bot welcome-bubble">
            <p>👋 Console cleared! How may I serve you today?</p>
        </div>
    `;
    receiptContainer.classList.add("hidden");
    hitlContainer.classList.add("hidden");
    workflowBadge.textContent = "Idle";
    workflowBadge.className = "badge status-badge";
    Object.values(pipelineSteps).forEach(el => el.className = "pipeline-step");
});

// Initial boot
fetchMenu();
