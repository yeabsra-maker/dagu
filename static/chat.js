// Get CSRF token
function getCsrfToken() {
    const tokenInput = document.querySelector('input[name="csrf_token"]');
    return tokenInput ? tokenInput.value : '';
}

// Typing variables
let typingTimeout = null;
let typingCheckInterval = null;
const reactions = ['👍', '❤️', '😂', '😮', '😢', '😡', '👎', '🎉', '🔥', '💯'];

let currentUser = null;
let selectedUserId = null;
let refreshInterval = null;
let heartbeatInterval = null;

// ========== EMOJI PICKER ==========
function setupEmojiPicker() {
    const emojiBtn = document.getElementById('emojiBtn');
    if (!emojiBtn) return;
    let picker = null;
    const emojis = ['😀', '😂', '😍', '😎', '😢', '😡', '👍', '❤️', '🎉', '🔥', '💯', '😊', '🤔', '🥳', '😴', '👋'];

    emojiBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        if (picker) {
            picker.remove();
            picker = null;
            return;
        }
        picker = document.createElement('div');
        picker.className = 'emoji-picker';
        emojis.forEach(emoji => {
            const btn = document.createElement('button');
            btn.textContent = emoji;
            btn.onclick = () => {
                const input = document.getElementById('messageInput');
                input.value += emoji;
                input.focus();
                picker.remove();
                picker = null;
            };
            picker.appendChild(btn);
        });
        emojiBtn.parentElement.appendChild(picker);
        setTimeout(() => {
            document.addEventListener('click', function closePicker(e) {
                if (picker && !picker.contains(e.target) && e.target !== emojiBtn) {
                    picker.remove();
                    picker = null;
                    document.removeEventListener('click', closePicker);
                }
            });
        }, 100);
    });
}

// ========== FILE ATTACHMENT ==========
function setupFileAttachment() {
    const attachBtn = document.getElementById('attachBtn');
    if (!attachBtn) return;
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.style.display = 'none';
    document.body.appendChild(fileInput);

    attachBtn.addEventListener('click', () => {
        fileInput.click();
    });

    fileInput.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        if (file.size > 10 * 1024 * 1024) {
            alert('File too large (max 10MB)');
            return;
        }
        const formData = new FormData();
        formData.append('file', file);
        try {
            const res = await fetch('/upload-file', {
                method: 'POST',
                body: formData
            });
            const data = await res.json();
            if (data.success) {
                const message = `📎 File: ${data.filename}\n${window.location.origin}${data.file_url}`;
                const input = document.getElementById('messageInput');
                input.value = message;
                await sendMessage();
                input.value = '';
            } else {
                alert(data.error || 'Upload failed');
            }
        } catch (err) {
            console.error(err);
            alert('Upload failed');
        }
        fileInput.value = '';
    });
}

// ========== REACTIONS ==========
function showReactionPicker(messageId, event) {
    event.stopPropagation();
    const existing = document.getElementById('reactionPicker');
    if (existing) existing.remove();
    const picker = document.createElement('div');
    picker.id = 'reactionPicker';
    picker.className = 'reaction-picker';
    picker.style.position = 'absolute';
    picker.style.left = `${event.clientX - 100}px`;
    picker.style.top = `${event.clientY - 50}px`;
    picker.innerHTML = reactions.map(r => `<button class="reaction-btn" data-reaction="${r}" data-message-id="${messageId}">${r}</button>`).join('');
    document.body.appendChild(picker);
    picker.querySelectorAll('.reaction-btn').forEach(btn => {
        btn.onclick = () => { addReaction(messageId, btn.dataset.reaction); picker.remove(); };
    });
    setTimeout(() => {
        document.addEventListener('click', function closePicker(e) {
            if (!picker.contains(e.target)) { picker.remove(); document.removeEventListener('click', closePicker); }
        });
    }, 100);
}

async function addReaction(messageId, reaction) {
    try {
        const res = await fetch('/add-reaction', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({ message_id: messageId, reaction })
        });
        if (res.ok && selectedUserId) loadMessages(selectedUserId);
    } catch (e) { console.error(e); }
}
async function removeReaction(messageId) {
    try {
        const res = await fetch('/remove-reaction', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({ message_id: messageId })
        });
        if (res.ok && selectedUserId) loadMessages(selectedUserId);
    } catch (e) { console.error(e); }
}
async function toggleReaction(messageId, reaction, isReacted) {
    if (isReacted) await removeReaction(messageId);
    else await addReaction(messageId, reaction);
}

// ========== TYPING INDICATORS ==========
async function sendTypingStatus(isTyping, receiverId) {
    try {
        await fetch('/typing', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({ receiver_id: receiverId, typing: isTyping })
        });
    } catch(e) {}
}
async function checkTypingStatus() {
    if (!selectedUserId) return;
    try {
        const res = await fetch('/typing-status');
        const data = await res.json();
        const indicator = document.getElementById('typingIndicator');
        if (indicator) {
            if (data.typing_users && data.typing_users.includes(selectedUserId)) {
                indicator.style.display = 'block';
                indicator.textContent = '✍️ User is typing...';
            } else indicator.style.display = 'none';
        }
    } catch(e) {}
}

// ========== AUTH & SESSION ==========
async function checkAuth() {
    try {
        const res = await fetch('/check-session');
        const data = await res.json();
        if (!data.authenticated) { window.location.href = '/login'; return null; }
        return data.user;
    } catch(e) { window.location.href = '/login'; return null; }
}
async function updateHeartbeat() {
    try { await fetch('/update-status', { method: 'POST' }); } catch(e) {}
}
async function loadSavedAvatar() {
    try {
        const res = await fetch('/current-avatar');
        const data = await res.json();
        const img = document.getElementById('currentUserAvatar');
        if (img && data.avatar_url) img.src = data.avatar_url + '?t=' + Date.now();
    } catch(e) {}
}

// ========== INIT CHAT ==========
async function initChat() {
    currentUser = await checkAuth();
    if (!currentUser) return;
    loadConversations();
    setupAddUserModal();
    console.log('Add user modal setup complete'); // Debug line
    setupAvatarUpload();
    loadSavedAvatar();
    setupEmojiPicker();
    setupFileAttachment();
    setupChangePassword();
    const navMenu = document.getElementById('navMenu');
    if (navMenu) navMenu.innerHTML = '<span>Welcome, ' + currentUser.username + '</span><button class="theme-toggle" onclick="toggleTheme()">🌙</button><a href="/admin">Admin</a><a href="/chat">Chat</a><a href="#" onclick="logout()">Logout</a>';
    refreshInterval = setInterval(() => {
        if (selectedUserId) loadMessages(selectedUserId);
        loadConversations();
    }, 3000);
    heartbeatInterval = setInterval(updateHeartbeat, 30000);
    typingCheckInterval = setInterval(checkTypingStatus, 2000);

    // Force message form visibility
    setTimeout(() => {
        const msgForm = document.getElementById('messageForm');
        if (msgForm) {
            msgForm.style.display = 'flex';
            msgForm.style.visibility = 'visible';
            msgForm.style.opacity = '1';
        }
    }, 500);
}

// ========== CONVERSATIONS ==========
async function loadConversations() {
    try {
        const res = await fetch('/conversations');
        const data = await res.json();
        const userList = document.getElementById('userList');
        if (!userList) return;
        if (!data.conversations || data.conversations.length === 0) {
            userList.innerHTML = '<div class="loading">No conversations yet.<br>Click "+ Add User" to start!</div>';
        } else {
            const html = data.conversations.map(conv => `
                <div class="user-item ${selectedUserId === conv.user_id ? 'selected' : ''}" data-user-id="${conv.user_id}" onclick="selectUser(${conv.user_id}, '${conv.username}')">
                    <div class="user-avatar"><img src="${conv.avatar_url || '/static/images/default-avatar.png'}" class="avatar"><span class="status-dot ${conv.online ? 'online' : 'offline'}"></span></div>
                    <div class="user-info">
                        <div class="user-name">${escapeHtml(conv.username)}</div>
                        <div class="user-last-message">${conv.last_message ? escapeHtml(conv.last_message) : 'No messages yet'}</div>
                        <div class="user-time">${conv.last_seen || (conv.online ? 'Online' : 'Offline')}</div>
                    </div>
                </div>
            `).join('');
            userList.innerHTML = html;
        }
    } catch(e) { console.error(e); }
}

window.selectUser = function(userId, username) {
    selectedUserId = userId;
    document.getElementById('selectedUser').innerText = `Chatting with ${escapeHtml(username)}`;
    const msgForm = document.getElementById('messageForm');
    if (msgForm) msgForm.style.display = 'flex';
    document.querySelectorAll('.user-item').forEach(el => el.classList.remove('selected'));
    const sel = document.querySelector(`.user-item[data-user-id="${userId}"]`);
    if (sel) sel.classList.add('selected');
    loadMessages(userId);
    fetch(`/get-user-details/${userId}`).then(r=>r.json()).then(data=>updateUserInfoPanel(data)).catch(()=>{});
};

async function loadMessages(userId) {
    try {
        const res = await fetch(`/messages?user_id=${userId}`);
        const data = await res.json();
        displayMessages(data.conversation);
    } catch(e) {}
}
function displayMessages(messages) {
    const container = document.getElementById('messagesContainer');
    if (!container) return;
    if (!messages || messages.length === 0) { container.innerHTML = '<div class="welcome-message">No messages yet. Send a message!</div>'; return; }
    container.innerHTML = messages.map(msg => {
        let statusHtml = '';
        if (msg.is_me) {
            if (msg.seen) statusHtml = '<span class="delivery-status seen">👁️</span>';
            else if (msg.delivered) statusHtml = '<span class="delivery-status delivered">✓✓</span>';
            else statusHtml = '<span class="delivery-status sent">✓</span>';
        }
        let reactionsHtml = '';
        if (msg.reactions && Object.keys(msg.reactions).length) {
            reactionsHtml = '<div class="message-reactions">';
            for (const [reaction, count] of Object.entries(msg.reactions)) {
                const userReacted = msg.user_reacted && msg.user_reacted.includes(reaction);
                reactionsHtml += `<span class="reaction-badge ${userReacted ? 'user-reacted' : ''}" onclick="toggleReaction(${msg.id}, '${reaction}', ${userReacted})">${reaction} ${count}</span>`;
            }
            reactionsHtml += '</div>';
        }
        let messageHtml = escapeHtml(msg.message);
        messageHtml = messageHtml.replace(/(https?:\/\/[^\s]+)/g, '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>');
        return `
            <div class="message ${msg.is_me ? 'sent' : 'received'}">
                <div class="message-content" onclick="showReactionPicker(${msg.id}, event)">${messageHtml}</div>
                <div class="message-time">${new Date(msg.timestamp).toLocaleTimeString()} ${statusHtml} <button class="reaction-trigger" onclick="showReactionPicker(${msg.id}, event)">😊</button></div>
                ${reactionsHtml}
            </div>
        `;
    }).join('');
    container.scrollTop = container.scrollHeight;
    if (selectedUserId) fetch('/mark-seen', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() }, body: JSON.stringify({ user_id: selectedUserId }) });
}

async function sendMessage() {
    const input = document.getElementById('messageInput');
    const message = input.value.trim();
    if (!message || !selectedUserId) return;
    sendTypingStatus(false, selectedUserId);
    try {
        const res = await fetch('/send-message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
            body: JSON.stringify({ receiver_id: selectedUserId, message })
        });
        if (res.ok) { input.value = ''; loadMessages(selectedUserId); loadConversations(); }
    } catch(e) {}
}
async function logout() { await fetch('/logout', { method: 'POST' }); window.location.href = '/login'; }
function escapeHtml(text) { const div = document.createElement('div'); div.textContent = text; return div.innerHTML; }

// ========== ADD USER MODAL ==========
function setupAddUserModal() {
    const modal = document.getElementById('addUserModal');
    const btn = document.getElementById('addUserBtn');
    const closeSpan = modal ? modal.querySelector('.close') : null;
    const searchInput = document.getElementById('searchUserInput');
    const results = document.getElementById('searchResults');
    if (btn) btn.onclick = () => { if(modal) modal.style.display = 'flex'; if(searchInput) searchInput.value = ''; if(results) results.innerHTML = '<div class="loading">Type to search...</div>'; };
    if (closeSpan) closeSpan.onclick = () => { if(modal) modal.style.display = 'none'; };
    if (searchInput) {
        searchInput.addEventListener('input', async function() {
            const q = this.value.trim();
            if (q.length < 2) { if(results) results.innerHTML = '<div class="loading">Type at least 2 characters...</div>'; return; }
            try {
                const res = await fetch(`/search-users?q=${encodeURIComponent(q)}`);
                const data = await res.json();
                if (results) {
                    if (data.users && data.users.length) {
                        results.innerHTML = data.users.map(user => `
                            <div class="user-select-item" data-user-id="${user.id}" data-username="${user.username}">
                                <div style="display:flex; align-items:center; gap:12px; flex:1;">
                                    <img src="${user.avatar_url || '/static/images/default-avatar.png'}" class="avatar-small" style="width:40px; height:40px; border-radius:50%;">
                                    <div><strong>${escapeHtml(user.username)}</strong><div style="font-size:12px; color:#666;">${user.last_seen || (user.online ? 'Online' : 'Offline')}</div></div>
                                </div>
                                <button class="btn-small start-chat-btn" data-user-id="${user.id}" data-username="${user.username}">Chat</button>
                            </div>
                        `).join('');
                        document.querySelectorAll('.start-chat-btn').forEach(btn => {
                            btn.onclick = (e) => { e.stopPropagation(); startChatWith(parseInt(btn.dataset.userId), btn.dataset.username); };
                        });
                        document.querySelectorAll('.user-select-item').forEach(item => {
                            item.onclick = (e) => { if(e.target.classList.contains('start-chat-btn')) return; startChatWith(parseInt(item.dataset.userId), item.dataset.username); };
                        });
                    } else results.innerHTML = '<div class="loading">No users found</div>';
                }
            } catch(e) { if(results) results.innerHTML = '<div class="loading">Error searching</div>'; }
        });
    }
    window.onclick = (event) => { if(event.target === modal && modal) modal.style.display = 'none'; };
}
function startChatWith(userId, username) {
    const modal = document.getElementById('addUserModal');
    if(modal) modal.style.display = 'none';
    const searchInput = document.getElementById('searchUserInput');
    if(searchInput) searchInput.value = '';
    window.selectUser(userId, username);
}

// ========== AVATAR UPLOAD ==========
function setupAvatarUpload() {
    const btn = document.getElementById('uploadAvatarBtn');
    const fileInput = document.getElementById('avatarFileInput');
    const avatarImg = document.getElementById('currentUserAvatar');
    if(!btn || !fileInput) return;
    btn.onclick = () => fileInput.click();
    fileInput.onchange = async (e) => {
        const file = e.target.files[0];
        if(!file) return;
        if(file.size > 5*1024*1024) { alert('Max 5MB'); return; }
        if(!file.type.match('image.*')) { alert('Only images'); return; }
        const fd = new FormData();
        fd.append('avatar', file);
        try {
            const res = await fetch('/upload-avatar', { method: 'POST', body: fd });
            const data = await res.json();
            if(data.success) { avatarImg.src = data.avatar_url + '?t=' + Date.now(); alert('Avatar updated!'); }
            else alert(data.error || 'Upload failed');
        } catch(e) { alert('Upload failed'); }
    };
}

// ========== USER INFO PANEL ==========
function updateUserInfoPanel(user) {
    const panel = document.getElementById('userInfoPanel');
    if(!panel) return;
    if(!user) { document.getElementById('infoUsername').innerText = 'Select a user'; document.getElementById('infoStatus').innerText = '—'; document.getElementById('infoAvatar').src = '/static/images/default-avatar.png'; return; }
    document.getElementById('infoUsername').innerText = user.username;
    document.getElementById('infoStatus').innerHTML = user.online ? '<span class="status-dot online" style="display:inline-block; width:10px; height:10px;"></span> Online' : `Last seen ${user.last_seen}`;
    document.getElementById('infoAvatar').src = user.avatar_url || '/static/images/default-avatar.png';
}
document.getElementById('clearChatBtn')?.addEventListener('click', () => { if(selectedUserId && confirm('Delete all messages?')) { fetch('/clear-conversation', { method: 'POST', headers: { 'X-CSRFToken': getCsrfToken(), 'Content-Type': 'application/json' }, body: JSON.stringify({ user_id: selectedUserId }) }).then(() => loadMessages(selectedUserId)); } });
document.getElementById('messageInput')?.addEventListener('input', function() { this.style.height = 'auto'; this.style.height = Math.min(this.scrollHeight, 100) + 'px'; });

// ========== CHANGE PASSWORD MODAL ==========
function setupChangePassword() {
    const pwModal = document.getElementById('changePasswordModal');
    const pwBtn = document.getElementById('changePasswordBtn');
    const pwClose = pwModal ? pwModal.querySelector('.close') : null;

    if (pwBtn) {
        pwBtn.onclick = () => {
            if (pwModal) pwModal.style.display = 'flex';
            const oldInput = document.getElementById('oldPassword');
            const newInput = document.getElementById('newPassword');
            const confirmInput = document.getElementById('confirmPassword');
            if (oldInput) oldInput.value = '';
            if (newInput) newInput.value = '';
            if (confirmInput) confirmInput.value = '';
            const errorDiv = document.getElementById('pwError');
            const successDiv = document.getElementById('pwSuccess');
            if (errorDiv) errorDiv.style.display = 'none';
            if (successDiv) successDiv.style.display = 'none';
        };
    }
    if (pwClose) {
        pwClose.onclick = () => { if (pwModal) pwModal.style.display = 'none'; };
    }

    const pwForm = document.getElementById('changePasswordForm');
    if (pwForm) {
        pwForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const oldPw = document.getElementById('oldPassword').value;
            const newPw = document.getElementById('newPassword').value;
            const confirmPw = document.getElementById('confirmPassword').value;
            const errorDiv = document.getElementById('pwError');
            const successDiv = document.getElementById('pwSuccess');

            errorDiv.style.display = 'none';
            successDiv.style.display = 'none';

            if (newPw !== confirmPw) {
                errorDiv.textContent = 'New passwords do not match';
                errorDiv.style.display = 'block';
                return;
            }

            try {
                const res = await fetch('/change-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
                    body: JSON.stringify({ old_password: oldPw, new_password: newPw })
                });
                const data = await res.json();
                if (res.ok) {
                    successDiv.textContent = data.message;
                    successDiv.style.display = 'block';
                    setTimeout(() => {
                        if (pwModal) pwModal.style.display = 'none';
                    }, 2000);
                } else {
                    errorDiv.textContent = data.error;
                    errorDiv.style.display = 'block';
                }
            } catch (err) {
                errorDiv.textContent = 'Connection error';
                errorDiv.style.display = 'block';
            }
        });
    }
}

// ========== SEARCH FUNCTIONALITY ==========
// The search button toggles the search input
document.getElementById('searchBtn')?.addEventListener('click', function() {
    const searchInput = document.getElementById('messageSearch');
    if (searchInput) {
        if (searchInput.style.display === 'none') {
            searchInput.style.display = 'block';
            searchInput.focus();
        } else {
            searchInput.style.display = 'none';
            searchInput.value = '';
            // Optionally clear search results
            document.getElementById('searchResultsList').innerHTML = '<div class="loading">Enter a search term...</div>';
            document.getElementById('searchModal').style.display = 'none';
        }
    }
});

// Search on Enter key
document.getElementById('messageSearch')?.addEventListener('keypress', function(e) {
    if (e.key === 'Enter') {
        const query = this.value.trim();
        if (query.length >= 2) {
            performSearch(query);
        }
    }
});

// ========== PERFORM SEARCH ==========
async function performSearch(query) {
    if (!query || query.length < 2) {
        alert('Please enter at least 2 characters');
        return;
    }
    const resultsDiv = document.getElementById('searchResultsList');
    const searchModal = document.getElementById('searchModal');
    if (resultsDiv) resultsDiv.innerHTML = '<div class="loading">Searching...</div>';
    if (searchModal) searchModal.style.display = 'flex';

    try {
        const res = await fetch(`/search-messages?q=${encodeURIComponent(query)}`);
        const data = await res.json();
        if (resultsDiv) {
            if (data.messages && data.messages.length > 0) {
                const highlightRegex = new RegExp(`(${escapeRegex(query)})`, 'gi');
                resultsDiv.innerHTML = data.messages.map(msg => {
                    const highlightedMsg = msg.message.replace(highlightRegex, '<span class="search-result-highlight">$1</span>');
                    return `
                        <div class="search-result-item" onclick="goToConversation(${msg.other_user_id}, '${msg.other_username}')">
                            <div class="search-result-header">
                                <span class="search-result-user">💬 ${escapeHtml(msg.other_username)}</span>
                                <span class="search-result-time">${new Date(msg.timestamp).toLocaleString()}</span>
                            </div>
                            <div class="search-result-message">${highlightedMsg}</div>
                            <div class="search-result-context">${msg.is_me ? 'You said' : `${msg.other_username} said`}</div>
                        </div>
                    `;
                }).join('');
            } else {
                resultsDiv.innerHTML = '<div class="loading">No messages found matching "' + escapeHtml(query) + '"</div>';
            }
        }
    } catch (err) {
        console.error(err);
        if (resultsDiv) resultsDiv.innerHTML = '<div class="loading">Search failed. Please try again.</div>';
    }
}

function escapeRegex(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function goToConversation(userId, username) {
    const searchModal = document.getElementById('searchModal');
    const searchInput = document.getElementById('messageSearch');
    if (searchModal) searchModal.style.display = 'none';
    if (searchInput) searchInput.value = '';
    selectUser(userId, username);
}

// ========== EVENT LISTENERS ==========
document.addEventListener('DOMContentLoaded', initChat);
document.addEventListener('DOMContentLoaded', () => {
    const inp = document.getElementById('messageInput');
    const sendBtn = document.getElementById('sendBtn');
    if(inp) {
        inp.addEventListener('input', () => { if(selectedUserId) { sendTypingStatus(true, selectedUserId); if(typingTimeout) clearTimeout(typingTimeout); typingTimeout = setTimeout(() => sendTypingStatus(false, selectedUserId), 2000); } });
        inp.addEventListener('keydown', (e) => { if(e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); } });
    }
    if(sendBtn) sendBtn.addEventListener('click', () => sendMessage());
});
window.addEventListener('beforeunload', () => { if(refreshInterval) clearInterval(refreshInterval); if(heartbeatInterval) clearInterval(heartbeatInterval); if(typingTimeout) clearTimeout(typingTimeout); if(typingCheckInterval) clearInterval(typingCheckInterval); });
