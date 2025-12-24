let tg = window.Telegram.WebApp;

tg.expand();
tg.MainButton.textColor = '#FFFFFF';
tg.MainButton.color = '#6c5ce7';

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Restore last tab if possible, or default to finance
    switchTab('finance', 'Финансы');
});

// Tab Switching
function switchTab(tabId, title) {
    // Update headers
    document.getElementById('page-title').innerText = title;

    // Update Tab Content
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.getElementById('tab-' + tabId).classList.add('active');

    // Update Bottom Nav
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    // Find nav item by index/class - simple approach:
    const navItems = document.querySelectorAll('.nav-item');
    if (tabId === 'finance') navItems[0].classList.add('active');
    if (tabId === 'tasks') navItems[1].classList.add('active');
    if (tabId === 'habits') navItems[2].classList.add('active');
    if (tabId === 'settings') navItems[3].classList.add('active');
}

// Category Selection
function selectCategory(el, category) {
    document.querySelectorAll('.tag').forEach(t => t.classList.remove('selected'));
    el.classList.add('selected');
    document.getElementById('categoryInput').value = category;

    // Hide custom input if standard selected
    document.getElementById('custom-cat-group').style.display = 'none';
}

function toggleCustomCategory() {
    document.querySelectorAll('.tag').forEach(t => t.classList.remove('selected'));
    document.getElementById('add-cat-btn').classList.add('selected');
    document.getElementById('categoryInput').value = '__custom__';
    document.getElementById('custom-cat-group').style.display = 'flex';
}

// Actions
function sendExpense() {
    const amount = document.getElementById('amountInput').value;
    let category = document.getElementById('categoryInput').value;

    if (category === '__custom__') {
        const customText = document.getElementById('customCategoryInput').value.trim();
        if (!customText) {
            tg.showAlert("Введите название категории!");
            return;
        }
        category = customText;
    }

    if (!amount || !category) {
        tg.showAlert("Введите сумму и выберите категорию!");
        return;
    }

    sendData({
        action: "add_expense",
        amount: parseFloat(amount),
        category: category
    });
}

function sendTask() {
    const text = document.getElementById('taskInput').value.trim();
    if (!text) return;

    sendData({
        action: "add_task",
        text: text
    });
}

function sendHabit() {
    const text = document.getElementById('habitInput').value.trim();
    const time = document.getElementById('habitTimeInput').value;
    if (!text) return;

    sendData({
        action: "add_habit",
        text: text,
        time: time
    });
}

function saveCity() {
    const city = document.getElementById('cityInput').value.trim();
    if (!city) return;

    sendData({
        action: "update_city",
        city: city
    });
}

function sendAction(actionName) {
    if (actionName === 'stop_userbot') {
        tg.showConfirm("Вы точно хотите отключить UserBot?", (confirmed) => {
            if (confirmed) {
                sendData({ action: actionName });
            }
        });
    } else {
        sendData({ action: actionName });
    }
}

// Helper to send data
function sendData(data) {
    tg.sendData(JSON.stringify(data));
    // Telegram automatically parses this and closes the WebApp.
    // If we want to keep it open, we must use CloudStorage or external API,
    // which is not possible with GitHub Pages + Local Bot setup.
    // So we just let it accept the data.
}
