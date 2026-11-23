// Gourmet Delight - Kitchen Admin & Chef Console Logic

const API_BASE = "";
let activeTicketTimers = {};

// DOM Elements
const btnThemeToggle = document.getElementById("btn-theme-toggle");
const themeIcon = document.getElementById("theme-icon");
const themeText = document.getElementById("theme-text");
const queueContainer = document.getElementById("kitchen-tickets-container");
const queueCountBadge = document.getElementById("queue-count");
const inventoryTbody = document.getElementById("inventory-tbody");
const ordersTbody = document.getElementById("orders-tbody");
const ordersFilterBadge = document.getElementById("orders-filter-badge");
const restockCountdown = document.getElementById("restock-countdown");
const btnForceRestock = document.getElementById("btn-force-restock");

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

// ============================================================================
// 1. KITCHEN COOKING QUEUE (HITL with 8-second Timer & Probability)
// ============================================================================

async function fetchPendingReviews() {
    try {
        const res = await fetch(`${API_BASE}/api/pending-reviews`);
        if (!res.ok) return;
        const data = await res.json();
        renderKitchenQueue(data.reviews || []);
    } catch (err) {
        console.error("Error fetching pending reviews:", err);
    }
}

function renderKitchenQueue(reviews) {
    queueCountBadge.textContent = `${reviews.length} pending`;

    if (reviews.length === 0) {
        queueContainer.innerHTML = `
            <div class="empty-state">
                <span class="empty-icon">☕</span>
                <p>No orders currently awaiting kitchen approval.</p>
                <small>When a customer orders, the cooking ticket will appear here with an 8s timer!</small>
            </div>
        `;
        // Clear old timers
        Object.values(activeTicketTimers).forEach(clearInterval);
        activeTicketTimers = {};
        return;
    }

    queueContainer.innerHTML = "";

    reviews.forEach(review => {
        const tid = review.thread_id;
        const card = document.createElement("div");
        card.className = "kitchen-ticket-card";
        card.id = `ticket-${tid}`;

        const itemsSummary = (review.items || [])
            .map(it => `<strong>${it.quantity}x ${it.name}</strong>`)
            .join(", ");

        card.innerHTML = `
            <div class="ticket-header">
                <div>
                    <span class="ticket-badge">Chef Review (Attempt #${review.attempt})</span>
                    <h3 class="ticket-title">Order #${review.order_id || 'ORD'}</h3>
                </div>
                <span class="timer-badge" id="timer-badge-${tid}">⏱️ 8s left</span>
            </div>

            <p class="ticket-items">Dishes to Cook: ${itemsSummary}</p>
            <div class="timer-bar-track">
                <div class="timer-bar-fill" id="timer-fill-${tid}"></div>
            </div>
            <p class="timer-caption">⚡ If not answered within 8s, auto-resolves via probability (85% pass, 15% fail).</p>

            <div class="ticket-actions">
                <button class="btn-approve" id="btn-approve-${tid}">✅ Approve Dish (Cooked)</button>
                <button class="btn-reject" id="btn-reject-${tid}">❌ Reject (Failed / Remake)</button>
            </div>
        `;

        queueContainer.appendChild(card);

        // Bind manual action buttons
        document.getElementById(`btn-approve-${tid}`).addEventListener("click", () => {
            resolveReview(tid, "approved");
        });
        document.getElementById(`btn-reject-${tid}`).addEventListener("click", () => {
            resolveReview(tid, "failed");
        });

        // Set up 8-second countdown timer for this ticket
        if (!activeTicketTimers[tid]) {
            let secondsLeft = review.timeout_seconds || 8;
            activeTicketTimers[tid] = setInterval(() => {
                secondsLeft -= 1;
                const badge = document.getElementById(`timer-badge-${tid}`);
                const fill = document.getElementById(`timer-fill-${tid}`);

                if (badge) badge.textContent = `⏱️ ${secondsLeft}s left`;
                if (fill) fill.style.width = `${(secondsLeft / 8) * 100}%`;

                if (secondsLeft <= 0) {
                    clearInterval(activeTicketTimers[tid]);
                    delete activeTicketTimers[tid];
                    resolveReview(tid, "timeout");
                }
            }, 1000);
        }
    });
}

async function resolveReview(threadId, responseChoice) {
    if (activeTicketTimers[threadId]) {
        clearInterval(activeTicketTimers[threadId]);
        delete activeTicketTimers[threadId];
    }

    try {
        const res = await fetch(`${API_BASE}/api/resume`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                thread_id: threadId,
                response: responseChoice
            })
        });
        await res.json();
        // Refresh queue, inventory & orders immediately
        fetchPendingReviews();
        fetchInventory();
        fetchOrdersHistory();
    } catch (err) {
        alert("Action failed: " + err.message);
    }
}

// ============================================================================
// 2. LIVE INVENTORY TABLE & RESTOCK CONTROLS
// ============================================================================

async function fetchInventory() {
    try {
        const res = await fetch(`${API_BASE}/api/menu`);
        if (!res.ok) return;
        const data = await res.json();
        renderInventoryTable(data.menu || []);

        if (data.last_restocked_at) {
            const lastDate = new Date(data.last_restocked_at);
            const nextDate = new Date(lastDate.getTime() + 24 * 60 * 60 * 1000);
            const hoursLeft = Math.max(0, Math.round((nextDate - new Date()) / (1000 * 60 * 60)));
            restockCountdown.textContent = `24h Restock: in ${hoursLeft}h`;
        }
    } catch (err) {
        console.error("Error fetching inventory:", err);
    }
}

function renderInventoryTable(items) {
    inventoryTbody.innerHTML = "";
    items.forEach(item => {
        const tr = document.createElement("tr");

        let stockBadge = `<span class="stock-pill">${item.stock}</span>`;
        if (item.stock <= 0) stockBadge = `<span class="stock-pill out">0 (OUT)</span>`;
        else if (item.stock <= 5) stockBadge = `<span class="stock-pill low">${item.stock} (LOW)</span>`;

        tr.innerHTML = `
            <td><strong>${item.name}</strong></td>
            <td><span class="badge">${item.category}</span></td>
            <td class="text-green">$${item.price.toFixed(2)}</td>
            <td>${stockBadge} / ${item.default_stock || 15}</td>
            <td>
                <button class="btn-micro-action" onclick="adjustStock('${item.name}', ${item.stock + 5})">+5 Stock</button>
            </td>
        `;
        inventoryTbody.appendChild(tr);
    });
}

async function adjustStock(itemName, newStock) {
    try {
        const res = await fetch(`${API_BASE}/api/menu/update-stock`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: itemName, stock: newStock })
        });
        if (res.ok) {
            fetchInventory();
        }
    } catch (err) {
        alert("Stock update failed: " + err.message);
    }
}

// Force Restock All
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
        fetchInventory();
    } catch (err) {
        alert("Restock failed: " + err.message);
    } finally {
        btnForceRestock.classList.remove("spinning");
    }
});

// ============================================================================
// 3. RECENT ORDERS DATABASE TABLE
// ============================================================================

async function fetchOrdersHistory() {
    try {
        const res = await fetch(`${API_BASE}/api/orders`);
        if (!res.ok) return;
        const data = await res.json();
        renderOrdersTable(data.orders || []);
    } catch (err) {
        console.error("Error fetching orders:", err);
    }
}

function renderOrdersTable(orders) {
    ordersTbody.innerHTML = "";
    if (!orders || orders.length === 0) {
        if (ordersFilterBadge) ordersFilterBadge.textContent = "No Records in Database";
        ordersTbody.innerHTML = `<tr><td colspan="5" class="text-center text-muted">No orders found in MongoDB.</td></tr>`;
        return;
    }

    const now = new Date();
    const todayYear = now.getFullYear();
    const todayMonth = now.getMonth();
    const todayDate = now.getDate();

    // 1. Check for orders placed today (present date)
    const todayOrders = orders.filter(order => {
        if (!order.created_at) return false;
        const d = new Date(order.created_at);
        return d.getFullYear() === todayYear && d.getMonth() === todayMonth && d.getDate() === todayDate;
    });

    let displayOrders = [];
    if (todayOrders.length > 0) {
        displayOrders = todayOrders;
        if (ordersFilterBadge) {
            ordersFilterBadge.textContent = `Today's Orders (${todayOrders.length} present)`;
            ordersFilterBadge.style.color = "var(--gold)";
        }
    } else {
        // If not present today, show recent 15 orders
        displayOrders = orders.slice(0, 15);
        if (ordersFilterBadge) {
            ordersFilterBadge.textContent = `No Orders Today — Showing Recent ${displayOrders.length} Orders`;
            ordersFilterBadge.style.color = "var(--text-secondary)";
        }
    }

    displayOrders.forEach(order => {
        const tr = document.createElement("tr");

        let statusClass = "badge";
        if (order.status === "SERVED") statusClass = "badge status-badge completed";
        else if (order.status === "COOKING" || order.status === "COOKING_RETRY") statusClass = "badge status-badge running";
        else if (order.status === "CANCELLED") statusClass = "badge status-badge failed";

        const itemsText = (order.items || [])
            .map(it => `${it.quantity}x ${it.name}`)
            .join(", ") || "Custom order";

        const timeStr = order.created_at ? new Date(order.created_at).toLocaleString() : "-";

        tr.innerHTML = `
            <td><strong>#${order.order_id || order._id}</strong></td>
            <td>${itemsText}</td>
            <td class="text-green"><strong>$${(order.total_amount || 0).toFixed(2)}</strong></td>
            <td><span class="${statusClass}">${order.status}</span></td>
            <td class="text-muted" style="font-size: 0.8rem;">${timeStr}</td>
        `;
        ordersTbody.appendChild(tr);
    });
}

// Bind manual refresh buttons
document.getElementById("btn-refresh-inventory")?.addEventListener("click", fetchInventory);
document.getElementById("btn-refresh-orders")?.addEventListener("click", fetchOrdersHistory);

// Initial Load & Recurring Polling
fetchPendingReviews();
fetchInventory();
fetchOrdersHistory();

// Poll pending kitchen reviews every 1.5 seconds
setInterval(fetchPendingReviews, 1500);
// Poll orders & inventory every 6 seconds
setInterval(() => {
    fetchInventory();
    fetchOrdersHistory();
}, 6000);
