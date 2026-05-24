// Global State
let selectedPosts = new Set();
let scrapedMedias = [];
let isIgLoggedIn = false;
let progressInterval = null;
let hasAttemptedAutoReconnect = false;
let isReconnecting = false;

// DOM Elements
const elIgLoggedOut = document.getElementById('ig-logged-out');
const elIgLoggedIn = document.getElementById('ig-logged-in');
const elIgLoginForm = document.getElementById('ig-login-form');
const elIgUsername = document.getElementById('ig-username');
const elIgPassword = document.getElementById('ig-password');
const elIg2faContainer = document.getElementById('ig-2fa-container');
const elIg2faCode = document.getElementById('ig-2fa-code');
const elBtnIgLogin = document.getElementById('btn-ig-login');
const elIgUserDisplay = document.getElementById('ig-user-display');
const elBtnIgLogout = document.getElementById('btn-ig-logout');

const elTgConfigForm = document.getElementById('tg-config-form');
const elTgToken = document.getElementById('tg-token');
const elTgChatId = document.getElementById('tg-chat-id');
const elTgNotifyToggle = document.getElementById('tg-notify-toggle');
const elTgBotToggle = document.getElementById('tg-bot-toggle');

const elTargetHandle = document.getElementById('target-handle');
const elScrapeLimit = document.getElementById('scrape-limit');
const elBtnFetch = document.getElementById('btn-fetch');

const elGridActionsBar = document.getElementById('grid-actions-bar');
const elBtnSelectAll = document.getElementById('btn-select-all');
const elBtnClearSelection = document.getElementById('btn-clear-selection');
const elBtnRepostSelected = document.getElementById('btn-repost-selected');
const elSelectedCount = document.getElementById('selected-count');

const elGridPlaceholder = document.getElementById('grid-placeholder');
const elGridLoading = document.getElementById('grid-loading');
const elGridError = document.getElementById('grid-error');
const elErrorDescText = document.getElementById('error-desc-text');
const elPostsGrid = document.getElementById('posts-grid');

const elProgressModal = document.getElementById('progress-modal');
const elModalProgressFill = document.getElementById('modal-progress-fill');
const elModalProgressText = document.getElementById('modal-progress-text');
const elModalProgressPercentage = document.getElementById('modal-progress-percentage');
const elModalLogs = document.getElementById('modal-logs');
const elBtnCloseModal = document.getElementById('btn-close-modal');

const elIgStatusText = document.getElementById('ig-status-text');
const elIgDot = document.getElementById('ig-dot');
const elTgStatusText = document.getElementById('tg-status-text');
const elTgDot = document.getElementById('tg-dot');

// INIT
document.addEventListener('DOMContentLoaded', () => {
    // Fill credentials if remembered
    const savedUser = localStorage.getItem('ig_username');
    const savedPass = localStorage.getItem('ig_password');
    if (savedUser) elIgUsername.value = savedUser;
    if (savedPass) elIgPassword.value = savedPass;
    const elRememberMe = document.getElementById('ig-remember-me');
    if (elRememberMe) {
        elRememberMe.checked = !!(savedUser && savedPass);
    }

    checkStatus();
    setupEventListeners();
});

// EVENT LISTENERS
function setupEventListeners() {
    // IG Login Form
    elIgLoginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const username = elIgUsername.value.trim();
        const password = elIgPassword.value;
        const code = elIg2faCode.value.trim() || null;

        showToast('info', 'Connecting to Instagram...');
        setLoadingState(elBtnIgLogin, true, 'Connecting...');

        try {
            const response = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password, verification_code: code })
            });
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'Login failed');
            }

            if (data.status === 'success') {
                showToast('success', `Logged in as @${data.username}`);
                
                // Remember credentials if checked
                const elRememberMe = document.getElementById('ig-remember-me');
                if (elRememberMe && elRememberMe.checked) {
                    localStorage.setItem('ig_username', username);
                    localStorage.setItem('ig_password', password);
                } else {
                    localStorage.removeItem('ig_username');
                    localStorage.removeItem('ig_password');
                }

                elIgLoginForm.reset();
                elIg2faContainer.classList.add('hidden');
                elIg2faCode.removeAttribute('required');
                elBtnIgLogin.innerHTML = '<span>Connect Instagram</span><i data-lucide="log-in"></i>';
                checkStatus();
            } else if (data.status === 'two_factor_required') {
                showToast('warning', '2FA code required to complete login!');
                elIg2faContainer.classList.remove('hidden');
                elIg2faCode.setAttribute('required', 'true');
                elBtnIgLogin.innerHTML = '<span>Verify Code & Connect</span><i data-lucide="shield-check"></i>';
            } else if (data.status === 'challenge_required') {
                showToast('error', data.message);
            }
            lucide.createIcons();
        } catch (err) {
            showToast('error', err.message);
        } finally {
            setLoadingState(elBtnIgLogin, false, 'Connect Instagram');
            lucide.createIcons();
        }
    });

    // IG Logout
    elBtnIgLogout.addEventListener('click', async () => {
        showToast('info', 'Disconnecting session...');
        try {
            const response = await fetch('/api/logout', { method: 'POST' });
            if (response.ok) {
                showToast('success', 'Instagram session removed.');
                
                // Clear remembered credentials on logout
                localStorage.removeItem('ig_username');
                localStorage.removeItem('ig_password');
                const elRememberMe = document.getElementById('ig-remember-me');
                if (elRememberMe) elRememberMe.checked = false;
                elIgUsername.value = '';
                elIgPassword.value = '';
                
                checkStatus();
            } else {
                showToast('error', 'Logout failed.');
            }
        } catch (err) {
            showToast('error', err.message);
        }
    });

    // TG Config Form
    elTgConfigForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const token = elTgToken.value.trim();
        const chatId = elTgChatId.value.trim();
        const notify = elTgNotifyToggle.checked;
        const bot = elTgBotToggle.checked;

        // Skip sending token if it's masked (unchanged)
        const payload = {
            telegram_chat_id: chatId,
            telegram_notifications_enabled: notify,
            telegram_bot_enabled: bot
        };
        if (token && !token.includes('...')) {
            payload.telegram_token = token;
        }

        showToast('info', 'Saving settings...');
        try {
            const response = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (response.ok) {
                showToast('success', 'Telegram configurations synchronized!');
                checkStatus();
            } else {
                showToast('error', 'Failed to save Telegram configurations.');
            }
        } catch (err) {
            showToast('error', err.message);
        }
    });

    // Fetch Target Media
    elBtnFetch.addEventListener('click', async () => {
        const target = elTargetHandle.value.trim();
        if (!target) {
            showToast('warning', 'Please enter a target username or profile link.');
            return;
        }

        if (!isIgLoggedIn) {
            showToast('error', 'You must log in to Instagram first.');
            return;
        }

        // Set loader state
        elGridPlaceholder.classList.add('hidden');
        elGridError.classList.add('hidden');
        elPostsGrid.classList.add('hidden');
        elGridActionsBar.classList.add('hidden');
        elGridLoading.classList.remove('hidden');

        try {
            const response = await fetch('/api/scrape', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    target_username: target,
                    amount: parseInt(elScrapeLimit.value)
                })
            });
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.detail || 'Scraping failed');
            }

            scrapedMedias = data.medias || [];
            selectedPosts.clear();
            updateSelectedCount();

            if (scrapedMedias.length === 0) {
                elGridPlaceholder.classList.remove('hidden');
                elGridLoading.classList.add('hidden');
                showToast('info', 'No recent posts found for this user.');
                return;
            }

            renderMediaGrid(scrapedMedias);
            elGridLoading.classList.add('hidden');
            elPostsGrid.classList.remove('hidden');
            elGridActionsBar.classList.remove('hidden');
            showToast('success', `Found ${scrapedMedias.length} posts successfully.`);
        } catch (err) {
            elGridLoading.classList.add('hidden');
            elErrorDescText.innerText = err.message;
            elGridError.classList.remove('hidden');
            showToast('error', `Fetch error: ${err.message}`);
        }
    });

    // Multi-Selection Controls
    elBtnSelectAll.addEventListener('click', () => {
        scrapedMedias.forEach(p => selectedPosts.add(p.id));
        document.querySelectorAll('.media-card').forEach(card => card.classList.add('selected'));
        updateSelectedCount();
    });

    elBtnClearSelection.addEventListener('click', () => {
        selectedPosts.clear();
        document.querySelectorAll('.media-card').forEach(card => card.classList.remove('selected'));
        updateSelectedCount();
    });

    // Repost Selected Process
    elBtnRepostSelected.addEventListener('click', () => {
        if (selectedPosts.size === 0) {
            showToast('warning', 'Please select at least one post to clone.');
            return;
        }
        triggerRepostFlow();
    });

    // Close Modal
    elBtnCloseModal.addEventListener('click', () => {
        elProgressModal.classList.add('hidden');
    });
}

// CHECK RECENT SYSTEM STATUS
async function checkStatus() {
    try {
        const response = await fetch('/api/status');
        const data = await response.json();

        // Instagram Status
        isIgLoggedIn = data.instagram_logged_in;
        if (isIgLoggedIn) {
            elIgLoggedOut.classList.add('hidden');
            elIgLoggedIn.classList.remove('hidden');
            elIgUserDisplay.innerText = `@${data.instagram_username}`;
            
            elIgStatusText.innerText = `Connected (@${data.instagram_username})`;
            elIgDot.className = 'dot dot-green';
        } else {
            elIgLoggedOut.classList.remove('hidden');
            elIgLoggedIn.classList.add('hidden');
            
            elIgStatusText.innerText = 'Disconnected';
            elIgDot.className = 'dot dot-red';
            
            // Auto-reconnect if saved credentials exist
            if (!hasAttemptedAutoReconnect) {
                const savedUser = localStorage.getItem('ig_username');
                const savedPass = localStorage.getItem('ig_password');
                if (savedUser && savedPass) {
                    hasAttemptedAutoReconnect = true;
                    autoReconnect(savedUser, savedPass);
                }
            }
        }

        // Telegram Status
        if (data.telegram_bot_running) {
            elTgStatusText.innerText = 'Active (Online)';
            elTgDot.className = 'dot dot-green';
        } else {
            elTgStatusText.innerText = 'Inactive (Offline)';
            elTgDot.className = 'dot dot-red';
        }

        // Populate Telegram Inputs
        if (data.telegram_token_configured) {
            elTgToken.value = data.telegram_token_masked;
        } else {
            elTgToken.value = '';
        }
        elTgChatId.value = data.telegram_chat_id;
        elTgNotifyToggle.checked = data.telegram_notifications_enabled;
        elTgBotToggle.checked = data.telegram_bot_enabled;

        lucide.createIcons();
    } catch (err) {
        showToast('error', `Status sync failure: ${err.message}`);
    }
}

// RENDER MEDIA CARDS GRID
function renderMediaGrid(medias) {
    elPostsGrid.innerHTML = '';
    
    medias.forEach(media => {
        const card = document.createElement('div');
        card.className = 'media-card';
        card.setAttribute('data-id', media.id);

        // Thumbnail URL fallback or blank
        const thumbUrl = media.thumbnail_url || 'data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100"><rect width="100" height="100" fill="%231e293b"/><text x="50" y="50" dominant-baseline="middle" text-anchor="middle" font-family="sans-serif" font-size="12" fill="%2364748b">No Preview</text></svg>';
        
        // Icon based on type
        let iconType = 'image';
        if (media.type === 'video') iconType = 'video';
        if (media.type === 'reel') iconType = 'clapperboard';
        if (media.type === 'album') iconType = 'layers';

        card.innerHTML = `
            <div class="media-thumbnail-container">
                <div class="media-selector">
                    <div class="custom-checkbox">
                        <i data-lucide="check"></i>
                    </div>
                </div>
                <div class="media-type-badge">
                    <i data-lucide="${iconType}"></i>
                </div>
                <img src="${thumbUrl}" class="media-thumb" alt="Instagram Post" onerror="this.src='https://placehold.co/400x400/1e293b/64748b?text=Preview+Blocked'">
                <div class="media-stats-overlay">
                    <div class="media-stat">
                        <i data-lucide="heart"></i>
                        <span>${media.like_count.toLocaleString()}</span>
                    </div>
                    <div class="media-stat">
                        <i data-lucide="message-circle"></i>
                        <span>${media.comment_count.toLocaleString()}</span>
                    </div>
                </div>
            </div>
            <div class="media-info-box">
                <p class="caption-preview" id="preview-text-${media.id}">${escapeHtml(media.caption) || '<em>No caption</em>'}</p>
                
                <button class="caption-editor-toggle" onclick="toggleCaptionEditor('${media.id}')">
                    <i data-lucide="edit-3" style="width: 12px; height:12px;"></i>
                    <span>Edit Caption</span>
                </button>
                
                <textarea class="caption-textarea hidden" id="editor-${media.id}" placeholder="Write caption here...">${escapeHtml(media.caption)}</textarea>
            </div>
        `;

        // Click selection on Thumbnail Area specifically (so text selection or clicking button doesn't toggle)
        const thumbArea = card.querySelector('.media-thumbnail-container');
        thumbArea.addEventListener('click', (e) => {
            e.stopPropagation();
            if (selectedPosts.has(media.id)) {
                selectedPosts.delete(media.id);
                card.classList.remove('selected');
            } else {
                selectedPosts.add(media.id);
                card.classList.add('selected');
            }
            updateSelectedCount();
        });

        elPostsGrid.appendChild(card);
    });
    
    lucide.createIcons();
}

// CAPTION EDITOR TOGGLE
window.toggleCaptionEditor = function(mediaId) {
    const editor = document.getElementById(`editor-${mediaId}`);
    const preview = document.getElementById(`preview-text-${mediaId}`);
    
    if (editor.classList.contains('hidden')) {
        editor.classList.remove('hidden');
        preview.classList.add('hidden');
        editor.focus();
    } else {
        editor.classList.add('hidden');
        preview.classList.remove('hidden');
        // Update the preview overlay text
        preview.innerText = editor.value || 'No caption';
    }
};

function updateSelectedCount() {
    elSelectedCount.innerText = selectedPosts.size;
}

// MULTI REPOST SEQUENTIAL CONTROLLER
async function triggerRepostFlow() {
    let items = Array.from(selectedPosts);
    const total = items.length;
    
    // Series Config Read
    const seriesTitle = document.getElementById('series-name-input') ? document.getElementById('series-name-input').value.trim() : "";
    const startPart = document.getElementById('series-part-input') ? (parseInt(document.getElementById('series-part-input').value) || 1) : 1;
    const isOldestFirst = document.getElementById('series-oldest-first') ? document.getElementById('series-oldest-first').checked : false;

    // Optional Chronological Sorting
    if (isOldestFirst) {
        items.sort((aId, bId) => {
            const aMedia = scrapedMedias.find(m => m.id === aId);
            const bMedia = scrapedMedias.find(m => m.id === bId);
            const aTime = aMedia && aMedia.taken_at ? new Date(aMedia.taken_at).getTime() : 0;
            const bTime = bMedia && bMedia.taken_at ? new Date(bMedia.taken_at).getTime() : 0;
            return aTime - bTime; // Ascending order (oldest first)
        });
    }

    // Reset global stop flag on backend
    try {
        await fetch('/api/clear_stop', { method: 'POST' });
    } catch (e) {
        console.warn("Failed to clear backend stop flag", e);
    }

    elProgressModal.classList.remove('hidden');
    elBtnCloseModal.classList.add('hidden');
    elModalLogs.innerHTML = '';
    
    updateModalProgress(0, total, 'Preparing queue...');
    addLogLine('info', `🚀 Initializing clone workflow for ${total} items...`);
    
    let successCount = 0;
    
    for (let i = 0; i < total; i++) {
        const mediaId = items[i];
        const stepNum = i + 1;
        
        // Highlight active card
        document.querySelectorAll('.media-card').forEach(c => c.classList.remove('active-cloning'));
        const activeCard = document.querySelector(`.media-card[data-id="${mediaId}"]`);
        if (activeCard) activeCard.classList.add('active-cloning');

        // Extract custom caption if user updated it
        const editorTextarea = document.getElementById(`editor-${mediaId}`);
        let caption = editorTextarea ? editorTextarea.value : null;

        // Apply Series Formatting
        if (seriesTitle) {
            const currentPart = startPart + i;
            const seriesPrefix = `${seriesTitle} - Part ${currentPart}\n\n`;
            if (caption) {
                caption = seriesPrefix + caption;
            } else {
                const mediaData = scrapedMedias.find(m => m.id === mediaId);
                caption = seriesPrefix + (mediaData && mediaData.caption ? mediaData.caption : '');
            }
        }

        updateModalProgress(i, total, `Reposting media ${stepNum} of ${total}...`);
        addLogLine('info', `⏳ [${stepNum}/${total}] Downloading and publishing post (ID: ${mediaId})...`);

        // Start simulated smooth progress for this item
        startSimulatedProgress(i, total);

        try {
            const response = await fetch('/api/repost', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    media_id: mediaId,
                    custom_caption: caption
                })
            });
            const data = await response.json();

            stopSimulatedProgress();

            if (!response.ok) {
                throw new Error(data.detail || 'Repost API request failed.');
            }

            successCount++;
            addLogLine('success', `✅ [${stepNum}/${total}] Reposted successfully! New Media ID: ${data.new_pk}`);
            
            // Remove success card from selection
            selectedPosts.delete(mediaId);
            if (activeCard) {
                activeCard.classList.remove('selected');
                activeCard.classList.add('reposted-success');
            }
            updateSelectedCount();

        } catch (err) {
            stopSimulatedProgress();
            addLogLine('error', `❌ [${stepNum}/${total}] Repost failed: ${err.message}`);
            if (activeCard) activeCard.classList.add('reposted-failed');
            
            if (err.message.includes('Task stopped via Telegram command')) {
                addLogLine('warn', '🛑 Workflow stopped manually via Telegram /stop command.');
                break;
            }
        }

        // Make sure progress hits the exact completion step visually
        updateModalProgress(i + 1, total, `Completed media ${stepNum} of ${total}`);

        // Dynamic cooldown to prevent throttling
        if (i < total - 1) {
            addLogLine('warn', `💤 Pausing for 4 seconds to comply with Instagram safety bounds...`);
            await sleep(4000);
        }
    }

    stopSimulatedProgress();
    updateModalProgress(total, total, `Finished! Success: ${successCount}/${total}`);
    addLogLine('success', `🎉 Repost workflow complete! Successfully cloned ${successCount} out of ${total} posts.`);
    elBtnCloseModal.classList.remove('hidden');
    
    // Clear selection UI
    if (selectedPosts.size === 0) {
        selectedPosts.clear();
        updateSelectedCount();
    }
}

// LOGGING UTILS
function addLogLine(type, text) {
    const line = document.createElement('div');
    line.className = `log-line log-${type}`;
    const timestamp = new Date().toLocaleTimeString();
    line.innerText = `[${timestamp}] ${text}`;
    elModalLogs.appendChild(line);
    elModalLogs.scrollTop = elModalLogs.scrollHeight;
}

function updateModalProgress(current, total, label) {
    const percentage = total > 0 ? Math.round((current / total) * 100) : 0;
    elModalProgressFill.style.width = `${percentage}%`;
    elModalProgressText.innerText = label;
    elModalProgressPercentage.innerText = `${percentage}%`;
}

function startSimulatedProgress(startIndex, totalItems, durationMs = 12000) {
    if (progressInterval) clearInterval(progressInterval);
    
    let elapsed = 0;
    const intervalTime = 100; // update every 100ms
    
    progressInterval = setInterval(() => {
        elapsed += intervalTime;
        // Asymptotically approach 92% of the current step
        let subProgress = 0.92 * (1 - Math.exp(-elapsed / (durationMs / 2.5)));
        
        const currentProgress = startIndex + subProgress;
        const percentage = totalItems > 0 ? Math.round((currentProgress / totalItems) * 100) : 0;
        
        elModalProgressFill.style.width = `${percentage}%`;
        elModalProgressPercentage.innerText = `${percentage}%`;
    }, intervalTime);
}

function stopSimulatedProgress() {
    if (progressInterval) {
        clearInterval(progressInterval);
        progressInterval = null;
    }
}

// TOAST NOTIFICATIONS
function showToast(type, text) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    
    let iconName = 'info';
    if (type === 'success') iconName = 'check-circle';
    if (type === 'error') iconName = 'alert-octagon';
    if (type === 'warning') iconName = 'alert-triangle';

    toast.innerHTML = `
        <i data-lucide="${iconName}"></i>
        <span>${escapeHtml(text)}</span>
    `;

    container.appendChild(toast);
    lucide.createIcons();

    // Auto-remove after 4s
    setTimeout(() => {
        toast.style.transform = 'translateY(-20px)';
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// HELPER UTILS
function escapeHtml(text) {
    if (!text) return '';
    return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

function setLoadingState(buttonEl, isLoading, text) {
    if (isLoading) {
        buttonEl.disabled = true;
        buttonEl.innerHTML = `<div class="spinner" style="width:16px;height:16px;margin:0;border-width:2px;"></div> <span>${text}</span>`;
    } else {
        buttonEl.disabled = false;
        buttonEl.innerHTML = text;
    }
}

async function autoReconnect(username, password) {
    if (isReconnecting) return;
    isReconnecting = true;
    
    showToast('info', 'Reconnecting Instagram session...');
    setLoadingState(elBtnIgLogin, true, 'Reconnecting...');
    
    try {
        const response = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });
        const data = await response.json();

        if (response.ok && data.status === 'success') {
            showToast('success', `Reconnected successfully as @${data.username}`);
            checkStatus();
        } else if (data.status === 'two_factor_required') {
            showToast('warning', '2FA required for auto-reconnect. Please log in manually.');
            elIg2faContainer.classList.remove('hidden');
            elIg2faCode.setAttribute('required', 'true');
            elBtnIgLogin.innerHTML = '<span>Verify Code & Connect</span><i data-lucide="shield-check"></i>';
            lucide.createIcons();
        } else {
            showToast('warning', 'Auto-reconnect failed. Please enter your credentials manually.');
        }
    } catch (err) {
        console.error('Auto-reconnect error:', err);
    } finally {
        setLoadingState(elBtnIgLogin, false, 'Connect Instagram');
        isReconnecting = false;
    }
}
