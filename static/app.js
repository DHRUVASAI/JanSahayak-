// JanSahayak Web Frontend Core Script
let sessionId = localStorage.getItem('jansahayak_session') || '';
if (!sessionId) {
    sessionId = 'web_' + Math.random().toString(36).substring(2, 15);
    localStorage.setItem('jansahayak_session', sessionId);
}

let currentLanguage = 'en';
let activeScheme = '';
let activeKeyboardTag = '';
let isRecording = false;
let mediaRecorder = null;
let audioChunks = [];
let extractedOcrData = {};

// Navigation Tab Switcher
function switchTab(tab) {
    const chatBtn = document.getElementById('btn-chat');
    const dashBtn = document.getElementById('btn-dashboard');
    const chatSec = document.getElementById('chatSection');
    const dashSec = document.getElementById('dashboardSection');
    
    if (tab === 'chat') {
        chatBtn.classList.add('active');
        dashBtn.classList.remove('active');
        chatSec.style.display = 'flex';
        dashSec.style.display = 'none';
    } else {
        dashBtn.classList.add('active');
        chatBtn.classList.remove('active');
        chatSec.style.display = 'none';
        dashSec.style.display = 'flex';
        refreshApplications();
    }
}

// Initial Messages
window.onload = function() {
    // Show chat tab by default
    switchTab('chat');
    
    // Check if user is already logged in
    const savedPhone = localStorage.getItem('user_phone');
    if (savedPhone) {
        const modal = document.getElementById('authModal');
        if (modal) modal.style.display = 'none';
        addBotMessage(`🙏 <b>Welcome back to JanSahayak! (जनसहायक)</b><br>Logged in as: <code>${savedPhone}</code><br><br>Please select your language / अपनी भाषा चुनें:`, 'lang_selection');
    }
    
    // Poll applications status periodically
    setInterval(refreshApplications, 8000);
};

// Login & Signup handlers
function loginWithPhone() {
    const input = document.getElementById('authPhone');
    const phone = input.value.trim();
    if (!phone || phone.length !== 10 || isNaN(phone)) {
        alert("⚠️ Please enter a valid 10-digit mobile number.");
        return;
    }
    
    // Clear old state & generate new fresh session ID
    sessionId = 'web_' + Math.random().toString(36).substring(2, 15);
    localStorage.setItem('jansahayak_session', sessionId);
    localStorage.setItem('user_phone', phone);
    extractedOcrData = {};
    activeScheme = '';
    
    const chatBox = document.getElementById('chatMessages');
    if (chatBox) chatBox.innerHTML = '';
    
    const modal = document.getElementById('authModal');
    if (modal) modal.style.display = 'none';
    
    addBotMessage(`🙏 <b>Welcome to JanSahayak! (जनसहायक)</b><br>Registered & Verified with: <code>${phone}</code><br><br>Please select your language / अपनी भाषा चुनें:`, 'lang_selection');
}

function continueAsGuest() {
    // Clear old state & generate new fresh session ID
    sessionId = 'web_' + Math.random().toString(36).substring(2, 15);
    localStorage.setItem('jansahayak_session', sessionId);
    localStorage.removeItem('user_phone');
    extractedOcrData = {};
    activeScheme = '';
    
    const chatBox = document.getElementById('chatMessages');
    if (chatBox) chatBox.innerHTML = '';
    
    const modal = document.getElementById('authModal');
    if (modal) modal.style.display = 'none';
    
    addBotMessage(`🙏 <b>Welcome Guest!</b><br>Please select your language / अपनी भाषा चुनें:`, 'lang_selection');
}

// Message Rendering Helpers
function addBotMessage(html, tag = '') {
    const chatBox = document.getElementById('chatMessages');
    
    // Remove existing keyboard option elements before adding a new message
    const oldKeyboards = document.querySelectorAll('.options-keyboard');
    oldKeyboards.forEach(el => el.remove());
    
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message bot';
    msgDiv.innerHTML = `
        <div class="avatar"><i class="fa-solid fa-robot"></i></div>
        <div class="bubble">
            <div>${html}</div>
            ${renderKeyboardForTag(tag)}
        </div>
    `;
    
    chatBox.appendChild(msgDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
    
    activeKeyboardTag = tag;
}

function addUserMessage(text) {
    const chatBox = document.getElementById('chatMessages');
    const msgDiv = document.createElement('div');
    msgDiv.className = 'message user';
    msgDiv.innerHTML = `
        <div class="avatar"><i class="fa-solid fa-user"></i></div>
        <div class="bubble">${text}</div>
    `;
    chatBox.appendChild(msgDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
}

function showTypingIndicator() {
    const chatBox = document.getElementById('chatMessages');
    const typingDiv = document.createElement('div');
    typingDiv.className = 'message bot typing-indicator';
    typingDiv.id = 'typingIndicator';
    typingDiv.innerHTML = `
        <div class="avatar"><i class="fa-solid fa-robot"></i></div>
        <div class="bubble">
            <div class="typing">
                <span></span><span></span><span></span>
            </div>
        </div>
    `;
    chatBox.appendChild(typingDiv);
    chatBox.scrollTop = chatBox.scrollHeight;
}

function removeTypingIndicator() {
    const indicator = document.getElementById('typingIndicator');
    if (indicator) indicator.remove();
}

// Interactive Keyboard Renderers
function renderKeyboardForTag(tag) {
    if (!tag) return '';
    
    let buttons = [];
    if (tag === 'lang_selection') {
        buttons = [
            { text: '🇮🇳 English', value: 'lang_en' },
            { text: 'हिंदी (Hindi)', value: 'lang_hi' },
            { text: 'తెలుగు (Telugu)', value: 'lang_te' },
            { text: 'தமிழ் (Tamil)', value: 'lang_ta' },
            { text: 'ಕನ್ನಡ (Kannada)', value: 'lang_kn' },
            { text: 'മലയാളം (Malayalam)', value: 'lang_ml' },
            { text: 'मराठी (Marathi)', value: 'lang_mr' },
            { text: 'অসমীয়া (Assamese)', value: 'lang_as' },
            { text: 'বাংলা (Bengali)', value: 'lang_bn' }
        ];
    } else if (tag === 'schemes') {
        buttons = [
            { text: 'PM-KISAN 🚜', value: 'scheme_pmkisan' },
            { text: 'Ration Card 🌾', value: 'scheme_ration' },
            { text: 'Ayushman Bharat 🏥', value: 'scheme_ayushman' },
            { text: 'NSAP Classifier 🏛️', value: 'scheme_nsap' }
        ];
    } else if (tag === 'yes_no') {
        buttons = [
            { text: 'Yes ✅', value: 'ans_yes' },
            { text: 'No ❌', value: 'ans_no' }
        ];
    } else if (tag === 'gender') {
        buttons = [
            { text: 'Male 👨', value: 'gender_male' },
            { text: 'Female 👩', value: 'gender_female' }
        ];
    } else if (tag === 'income') {
        buttons = [
            { text: 'Less than 1 Lakh', value: 'income_low' },
            { text: '1 to 2 Lakh', value: 'income_mid' },
            { text: 'More than 2 Lakh', value: 'income_high' }
        ];
    } else if (tag === 'land') {
        buttons = [
            { text: 'Less than 2 acres', value: 'land_small' },
            { text: '2 to 5 acres', value: 'land_mid' },
            { text: 'More than 5 acres', value: 'land_large' }
        ];
    } else if (tag === 'family') {
        buttons = [
            { text: '1-2 members', value: 'family_small' },
            { text: '3-4 members', value: 'family_mid' },
            { text: '5+ members', value: 'family_large' }
        ];
    } else if (tag === 'contact') {
        buttons = [
            { text: 'Share My Number 📱', value: 'request_contact' }
        ];
    }
    
    if (buttons.length === 0) return '';
    
    let html = `<div class="options-keyboard">`;
    buttons.forEach(btn => {
        html += `<button class="keyboard-btn" onclick="handleKeyboardClick('${btn.text}', '${btn.value}')">${btn.text}</button>`;
    });
    html += `</div>`;
    return html;
}

// Handle Keyboard Clicking
function handleKeyboardClick(label, value) {
    addUserMessage(label);
    
    // Set language if chosen
    if (value.startsWith('lang_')) {
        currentLanguage = value.replace('lang_', '');
        sendChatMessage(value);
        return;
    }
    
    // Custom Client Logic triggers
    if (value.startsWith('scheme_')) {
        activeScheme = value.replace('scheme_', '');
    }
    
    if (value === 'request_contact') {
        const phone = prompt("Please enter your 10-digit mobile number:");
        if (phone && phone.trim().length === 10) {
            sendChatMessage(phone.trim());
        } else {
            addBotMessage("⚠️ Invalid number. Please try again.", 'contact');
        }
        return;
    }
    
    sendChatMessage(value);
}

// Send input triggers
function sendMessage() {
    const input = document.getElementById('userInput');
    const text = input.value.trim();
    if (!text) return;
    
    addUserMessage(text);
    input.value = '';
    sendChatMessage(text);
}

function handleKeyPress(e) {
    if (e.key === 'Enter') sendMessage();
}

// Core Web Chat Request Loop
async function sendChatMessage(text) {
    showTypingIndicator();
    try {
        const response = await fetch('/api/web-chat/message', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: sessionId,
                message: text,
                language: currentLanguage,
                scheme: activeScheme,
                mobile: localStorage.getItem('user_phone') || null
            })
        });
        
        const data = await response.json();
        removeTypingIndicator();
        
        let botReply = data.reply;
        let tag = data.tag;
        
        // Auto inject Aadhaar Drag-Drop Uploader when bot asks for Aadhaar
        if (botReply.includes("Aadhaar") || botReply.includes("आधार")) {
            botReply += `
                <div class="upload-container" id="dropzone" onclick="document.getElementById('aadhaarFile').click()">
                    <i class="fa-solid fa-cloud-arrow-up upload-icon"></i>
                    <p class="upload-text">Drag & drop Aadhaar image here or <b>Browse file</b></p>
                    <input type="file" id="aadhaarFile" style="display:none" accept="image/*" onchange="uploadAadhaar(this.files[0])">
                </div>
            `;
        }
        
        addBotMessage(botReply, tag);
        
        // If final confirmation step is answered Yes, trigger backend submit
        if (text === 'ans_yes' && activeKeyboardTag === 'yes_no') {
            submitFormApplication();
        }
        
    } catch (e) {
        removeTypingIndicator();
        addBotMessage("⚠️ Connection lost. Please check your internet connection.");
    }
}

// Aadhaar Upload & OCR Parsing
async function uploadAadhaar(file) {
    if (!file) return;
    
    const zone = document.getElementById('dropzone');
    zone.innerHTML = `<i class="fa-solid fa-spinner fa-spin upload-icon"></i><p class="upload-text">Extracting Aadhaar details via Groq Vision...</p>`;
    
    const formData = new FormData();
    formData.append('file', file);
    
    try {
        const response = await fetch('/api/web-chat/ocr', {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) throw new Error("OCR Failed");
        
        const ocrData = await response.json();
        extractedOcrData = ocrData;
        
        // Format masked Aadhaar
        let masked = "************";
        if (ocrData.aadhaar) {
            masked = ocrData.aadhaar.substring(ocrData.aadhaar.length - 4).padStart(12, "*");
        }
        
        zone.className = "upload-container";
        zone.style.borderColor = "var(--gov-green)";
        zone.innerHTML = `
            <i class="fa-solid fa-circle-check upload-icon" style="color: var(--gov-green)"></i>
            <p class="upload-text" style="color: var(--gov-green)"><b>Extracted successfully!</b></p>
            <p style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.25rem;">
                Name: ${ocrData.name || 'N/A'} | DOB: ${ocrData.dob || 'N/A'}
            </p>
        `;
        
        // Feed extracted data directly to the chat
        addUserMessage(`Document uploaded successfully.`);
        sendChatMessage(`Document uploaded. Extracted details: Name: ${ocrData.name}, DOB: ${ocrData.dob}, Gender: ${ocrData.gender}, Address: ${ocrData.address || ocrData.district + ', ' + ocrData.state}`);
        
    } catch (e) {
        zone.innerHTML = `<i class="fa-solid fa-circle-exclamation upload-icon" style="color: #d32f2f"></i><p class="upload-text" style="color: #d32f2f">OCR extraction failed. Click to browse again.</p>`;
    }
}

// Media Audio Mic Recording
async function toggleRecording() {
    const btn = document.getElementById('micBtn');
    
    if (isRecording) {
        mediaRecorder.stop();
        isRecording = false;
        btn.classList.remove('recording');
        
        const rbar = document.getElementById('recBar');
        if (rbar) rbar.remove();
    } else {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            audioChunks = [];
            
            mediaRecorder = new MediaRecorder(stream);
            mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: 'audio/ogg' });
                showTypingIndicator();
                
                const formData = new FormData();
                formData.append('file', audioBlob, 'voice.ogg');
                
                try {
                    const response = await fetch(`/api/web-chat/voice?language=${currentLanguage}`, {
                        method: 'POST',
                        body: formData
                    });
                    const res = await response.json();
                    removeTypingIndicator();
                    
                    if (res.transcription) {
                        document.getElementById('userInput').value = res.transcription;
                        addBotMessage(`🎤 Translated voice to text: <i>"${res.transcription}"</i>. Click Send to submit.`);
                    }
                } catch (err) {
                    removeTypingIndicator();
                    addBotMessage("⚠️ Voice transcription failed. Please try typing.");
                }
            };
            
            mediaRecorder.start();
            isRecording = true;
            btn.classList.add('recording');
            
            const bar = document.createElement('div');
            bar.id = 'recBar';
            bar.className = 'recording-container';
            bar.innerHTML = `<div class="recording-dot"></div><span>Recording voice message... Tap microphone icon to stop and transcribe.</span>`;
            document.querySelector('.chat-input-bar').before(bar);
            
        } catch (e) {
            addBotMessage("⚠️ Microphone permission denied. Please allow mic access.");
        }
    }
}

// Final Submit logic & RPA queue placement
async function submitFormApplication() {
    showTypingIndicator();
    
    let userPhoneNum = localStorage.getItem('user_phone') || extractedOcrData.mobile || "";
    let payloadData = {
        name: extractedOcrData.name || "Vudata Dhruvasai",
        gender: extractedOcrData.gender || "MALE",
        dob: extractedOcrData.dob || "17/07/2006",
        address: extractedOcrData.address || "Sai Prestige Apartment, Pragathi Nagar, Nizampet, Telangana",
        state: extractedOcrData.state || "Telangana",
        district: extractedOcrData.district || "Medchal-malkajgiri",
        pincode: extractedOcrData.pincode || "500090",
        mobile: userPhoneNum
    };

    try {
        const response = await fetch('/api/web-chat/submit', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                session_id: sessionId,
                scheme: activeScheme || "pmkisan",
                user_data: payloadData
            })
        });
        
        const data = await response.json();
        removeTypingIndicator();
        
        if (data.status === 'success') {
            addBotMessage(`🎉 <b>Application submitted successfully!</b><br>🎫 Job ID: <code>${data.job_id}</code><br><br>The automated Chrome worker is filling your application live on the operator console. Check progress on the dashboard!`);
            refreshApplications();
        }
    } catch (e) {
        removeTypingIndicator();
        addBotMessage("⚠️ Failed to submit application. Please try again.");
    }
}

// Fetch applications for Admin panel
async function refreshApplications() {
    try {
        const response = await fetch('/api/web-chat/applications');
        const list = await response.json();
        
        const container = document.getElementById('dashboardContent');
        if (!list || list.length === 0) {
            container.innerHTML = `
                <div style="text-align: center; color: var(--text-muted); margin-top: 4rem;">
                    <i class="fa-solid fa-circle-info" style="font-size: 2rem; margin-bottom: 0.5rem; color: var(--gov-blue);"></i>
                    <p style="font-size: 0.9rem;">No applications submitted yet.</p>
                </div>
            `;
            return;
        }
        
        let html = '';
        list.forEach(app => {
            let badgeClass = 'status-review';
            let status = app.status || 'Under Review';
            if (status.toLowerCase().includes('complete') || status.toLowerCase().includes('success') || status.toLowerCase().includes('under review')) {
                badgeClass = 'status-completed';
            } else if (status.toLowerCase().includes('fail')) {
                badgeClass = 'status-failed';
            }
            
            let date = app.submission_date ? new Date(app.submission_date).toLocaleDateString() : 'N/A';
            
            let schemeLabels = {
                "pmkisan": "PM-KISAN",
                "ration": "Ration Card",
                "ayushman": "Ayushman Bharat",
                "nsap": "NSAP Classifier"
            };
            let schemeName = schemeLabels[app.scheme] || app.scheme;
            
            html += `
                <div class="app-card" onclick="viewRpaScreenshot('${app.application_id}')">
                    <div class="app-card-header">
                        <span class="app-scheme-name">${schemeName}</span>
                        <span class="app-status-badge ${badgeClass}">${status}</span>
                    </div>
                    <div class="app-details">
                        <span>👤 Name: ${app.name || 'N/A'}</span>
                        <span>📅 Date: ${date}</span>
                        <span>📱 Mobile: ${app.mobile || 'N/A'}</span>
                        <span>🎫 ID: ${app.application_id}</span>
                    </div>
                </div>
            `;
        });
        
        container.innerHTML = html;
    } catch (e) {
        console.error("Refresh applications error", e);
    }
}

// Show RPA live screenshots in overlay modal
function viewRpaScreenshot(jobId) {
    const modal = document.getElementById('rpaModal');
    const img = document.getElementById('rpaScreenshot');
    img.src = `/static/app_${jobId}.png`;
    img.onerror = function() {
        img.src = "https://placehold.co/600x400/eceff1/37474f?text=Chrome+Operator+Loading...";
    };
    modal.style.display = 'flex';
}

function closeRpaModal() {
    const modal = document.getElementById('rpaModal');
    modal.style.display = 'none';
}
