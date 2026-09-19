// ============================================================================
// Enry Web Dashboard — app.js
// ============================================================================
// Voice pipeline:
//   Microphone → PCM 16kHz → WebSocket /ws/voice → Server VAD/ASR/LangGraph
//   Server → TTS chunks → Browser Audio Playback
//
// Features:
//   - Continuous PCM streaming (no batch recording)
//   - Server-side VAD + ASR
//   - Real-time partial/final transcripts
//   - Generation-ID-based TTS with barge-in
//   - Microphone stays active during agent speech
//   - Dashboard: customers, inventory, cart, transactions
// ============================================================================

// ---- App State ----
let activeCustomer = null;
let cart = [];
let customers = [];
let inventory = [];
let transactions = [];

// ---- Voice State ----
let voiceSocket = null;
let isAwake = false;
let isListening = false;
let isAgentSpeaking = false;
let isUserSpeaking = false;
let currentGenerationId = -1;
let audioContext = null;
let micStream = null;
let workletNode = null;
let audioSequence = 0;

// ---- TTS Playback ----
let ttsAudioQueue = [];       // queue of {generationId, audioData (Uint8Array)}
let isPlayingTTS = false;
let currentPlaybackSource = null;

// ---- DOM Elements ----
const btnMic = document.getElementById('btnMic');
const micIcon = document.getElementById('micIcon');
const voiceStatus = document.getElementById('voiceStatus');
const liveTranscript = document.getElementById('liveTranscript');

const customerList = document.getElementById('customerList');
const transactionHistory = document.getElementById('transactionHistory');
const activeCustomerName = document.getElementById('activeCustomerName');

const cartItems = document.getElementById('cartItems');
const cartCount = document.getElementById('cartCount');
const cartTotal = document.getElementById('cartTotal');
const btnClearCart = document.getElementById('btnClearCart');
const btnCheckout = document.getElementById('btnCheckout');

const nluOutputCard = document.getElementById('nluOutputCard');
const nluIntent = document.getElementById('nluIntent');
const nluExplanation = document.getElementById('nluExplanation');
const nluEntitiesContainer = document.getElementById('nluEntitiesContainer');

const txtManualCommand = document.getElementById('txtManualCommand');
const btnSendCommand = document.getElementById('btnSendCommand');
const operationsLog = document.getElementById('operationsLog');

// Modal Elements
const btnAddCustomer = document.getElementById('btnAddCustomer');
const modalCustomer = document.getElementById('modalCustomer');
const btnCloseCustomerModal = document.getElementById('btnCloseCustomerModal');
const formAddCustomer = document.getElementById('formAddCustomer');

// ============================================================================
// INITIALIZATION
// ============================================================================
document.addEventListener('DOMContentLoaded', () => {
    fetchData();
    setInterval(fetchData, 3000);
    setupEventListeners();
    addLogItem('System initialized and ready.', 'system');
});

// ============================================================================
// API FETCH (Dashboard Data)
// ============================================================================
async function fetchData() {
    try {
        const [custRes, invRes, txRes] = await Promise.all([
            fetch('/api/customers'),
            fetch('/api/inventory'),
            fetch('/api/transactions')
        ]);
        customers = await custRes.json();
        inventory = await invRes.json();
        transactions = await txRes.json();
        renderCustomers();
        renderTransactions();
    } catch (err) {
        console.error("Error fetching data:", err);
    }
}

// ============================================================================
// DOM RENDERING
// ============================================================================
function renderCustomers() {
    customerList.innerHTML = '';
    if (customers.length === 0) {
        customerList.innerHTML = '<div class="empty-text">No customers in ledger.</div>';
        return;
    }
    customers.forEach(c => {
        const card = document.createElement('div');
        card.className = `customer-card ${activeCustomer && activeCustomer.id === c.id ? 'active' : ''}`;
        const isCredit = c.balance > 0;
        const balClass = isCredit ? 'credit' : 'zero';
        card.innerHTML = `
            <div class="customer-info">
                <h4>${c.name}</h4>
                <p>${c.phone || 'No phone'}</p>
            </div>
            <div class="customer-balance">
                <span class="bal-val ${balClass}">₹${c.balance.toFixed(2)}</span>
                <p>${isCredit ? 'Udhaar Owed' : 'Settled'}</p>
            </div>
        `;
        card.addEventListener('click', () => selectCustomer(c));
        customerList.appendChild(card);
    });
}

function renderTransactions() {
    transactionHistory.innerHTML = '';
    if (transactions.length === 0) {
        transactionHistory.innerHTML = '<div class="empty-text">No recent transactions.</div>';
        return;
    }
    transactions.slice(0, 10).forEach(t => {
        const card = document.createElement('div');
        card.className = `tx-card ${t.type}`;
        const symbol = t.type === 'credit' ? '+' : '-';
        const formattedDate = new Date(t.timestamp).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
        card.innerHTML = `
            <div class="tx-details">
                <h5>${t.customer_name}</h5>
                <p>${t.description || (t.type === 'credit' ? 'Udhaar Taken' : 'Udhaar Paid')} • ${formattedDate}</p>
            </div>
            <span class="tx-amount">${symbol} ₹${t.amount.toFixed(2)}</span>
        `;
        transactionHistory.appendChild(card);
    });
}

function selectCustomer(customer) {
    activeCustomer = customer;
    activeCustomerName.innerText = customer ? customer.name : "Walk-in Customer";
    renderCustomers();
    addLogItem(`Selected customer: ${customer ? customer.name : 'Walk-in'}`, 'system');
}

function renderCart() {
    cartItems.innerHTML = '';
    if (cart.length === 0) {
        cartItems.innerHTML = `<tr class="empty-cart-row"><td colspan="5" class="empty-text">Cart is empty.</td></tr>`;
        cartCount.innerText = '0';
        cartTotal.innerText = '₹0.00';
        return;
    }
    let total = 0, count = 0;
    cart.forEach((item, index) => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td><strong>${item.name}</strong></td>
            <td>${item.quantity} ${item.unit}</td>
            <td>₹${item.price.toFixed(2)}</td>
            <td><strong>₹${item.total.toFixed(2)}</strong></td>
            <td>
                <button class="btn-delete-item" onclick="removeCartItem(${index})">
                    <span class="material-icons-round" style="font-size: 18px;">delete</span>
                </button>
            </td>
        `;
        cartItems.appendChild(row);
        total += item.total;
        count += item.quantity;
    });
    cartCount.innerText = count.toString();
    cartTotal.innerText = `₹${total.toFixed(2)}`;
}

function removeCartItem(index) {
    const item = cart[index];
    cart.splice(index, 1);
    renderCart();
    addLogItem(`Removed ${item.name} from cart.`, 'system');
}

// ============================================================================
// VOICE PIPELINE — WebSocket Audio Streaming
// ============================================================================

function convertFloat32ToInt16(buffer) {
    let l = buffer.length;
    let buf = new Int16Array(l);
    while (l--) {
        buf[l] = Math.min(1, buffer[l]) * 0x7FFF;
    }
    return buf;
}

function downsampleBuffer(buffer, sampleRate, outSampleRate) {
    if (outSampleRate === sampleRate) return buffer;
    const sampleRateRatio = sampleRate / outSampleRate;
    const newLength = Math.round(buffer.length / sampleRateRatio);
    const result = new Float32Array(newLength);
    let offsetResult = 0;
    let offsetBuffer = 0;
    while (offsetResult < result.length) {
        const nextOffsetBuffer = Math.round((offsetResult + 1) * sampleRateRatio);
        let accum = 0, count = 0;
        for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
            accum += buffer[i]; count++;
        }
        result[offsetResult] = accum / count;
        offsetResult++;
        offsetBuffer = nextOffsetBuffer;
    }
    return result;
}

function base64EncodePCM(int16Array) {
    const bytes = new Uint8Array(int16Array.buffer);
    let binary = '';
    for (let i = 0; i < bytes.byteLength; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return window.btoa(binary);
}

async function initMicrophone() {
    try {
        micStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: 16000,
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
            }
        });

        audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        const source = audioContext.createMediaStreamSource(micStream);

        // Use ScriptProcessor for wide browser support (AudioWorklet ideal but complex)
        const scriptProcessor = audioContext.createScriptProcessor(2048, 1, 1);
        source.connect(scriptProcessor);
        scriptProcessor.connect(audioContext.destination);

        scriptProcessor.onaudioprocess = (e) => {
            if (!isAwake || !voiceSocket || voiceSocket.readyState !== WebSocket.OPEN) return;

            const inputData = e.inputBuffer.getChannelData(0);

            // Client-side barge-in detection (energy-based)
            let energy = 0;
            for (let i = 0; i < inputData.length; i++) {
                energy += inputData[i] * inputData[i];
            }
            const rms = Math.sqrt(energy / inputData.length);

            // If agent is speaking and user speaks loud enough, trigger barge-in
            if (isAgentSpeaking && rms > 0.04) {
                console.log("Client barge-in! RMS:", rms.toFixed(4));
                stopTTSPlayback();
                voiceSocket.send(JSON.stringify({ type: "interrupt" }));
            }

            // Always stream audio to server (mic stays active during agent speech)
            const downsampled = downsampleBuffer(inputData, audioContext.sampleRate, 16000);
            const pcm16 = convertFloat32ToInt16(downsampled);

            audioSequence++;
            voiceSocket.send(JSON.stringify({
                type: "audio_chunk",
                sequence: audioSequence,
                sample_rate: 16000,
                encoding: "pcm_s16le",
                data: base64EncodePCM(pcm16),
            }));
        };

        addLogItem("Microphone initialized.", "system");
    } catch (err) {
        console.error("Microphone access failed:", err);
        voiceStatus.innerText = "Microphone access denied.";
        micIcon.innerText = 'mic_off';
    }
}

// ============================================================================
// TTS PLAYBACK (MP3 chunks from Cartesia via WebSocket)
// ============================================================================

function stopTTSPlayback() {
    isAgentSpeaking = false;
    ttsAudioQueue = [];
    currentGenerationId = -1;

    if (currentPlaybackSource) {
        try { currentPlaybackSource.pause(); } catch(e) {}
        currentPlaybackSource.src = '';
        currentPlaybackSource = null;
    }
}

async function playTTSChunk(base64Audio, generationId) {
    // Reject stale generations
    if (generationId !== currentGenerationId) return;

    ttsAudioQueue.push({ generationId, data: base64Audio });
    if (!isPlayingTTS) {
        processPlaybackQueue();
    }
}

async function processPlaybackQueue() {
    if (ttsAudioQueue.length === 0) {
        isPlayingTTS = false;
        return;
    }
    isPlayingTTS = true;

    const item = ttsAudioQueue.shift();

    // Double-check generation is still valid
    if (item.generationId !== currentGenerationId) {
        processPlaybackQueue();
        return;
    }

    try {
        const audioBlob = new Blob(
            [Uint8Array.from(atob(item.data), c => c.charCodeAt(0))],
            { type: 'audio/mpeg' }
        );
        const audioUrl = URL.createObjectURL(audioBlob);
        const audio = new Audio(audioUrl);
        currentPlaybackSource = audio;

        audio.onended = () => {
            URL.revokeObjectURL(audioUrl);
            currentPlaybackSource = null;
            processPlaybackQueue();
        };

        audio.onerror = () => {
            URL.revokeObjectURL(audioUrl);
            currentPlaybackSource = null;
            processPlaybackQueue();
        };

        await audio.play();
    } catch (err) {
        console.error("TTS playback error:", err);
        currentPlaybackSource = null;
        processPlaybackQueue();
    }
}

// ============================================================================
// WEBSOCKET VOICE CONNECTION
// ============================================================================

function initVoiceSocket() {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/voice`;
    console.log(`Connecting to Voice Gateway: ${wsUrl}`);

    voiceSocket = new WebSocket(wsUrl);

    voiceSocket.onopen = () => {
        console.log("Voice WebSocket connected.");
        addLogItem("Connected to voice gateway.", "system");
    };

    voiceSocket.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            handleServerMessage(msg);
        } catch (e) {
            console.error("Failed to parse server message:", e);
        }
    };

    voiceSocket.onclose = (event) => {
        if (!isAwake) return;
        console.warn("Voice WebSocket disconnected. Reconnecting in 3s...", event.reason);
        addLogItem("Voice gateway disconnected. Reconnecting...", "error");
        setTimeout(() => { if (isAwake) initVoiceSocket(); }, 3000);
    };

    voiceSocket.onerror = (error) => {
        console.error("Voice WebSocket error:", error);
    };
}

function handleServerMessage(msg) {
    switch (msg.type) {
        case "vad":
            if (msg.event === "speech_start") {
                isUserSpeaking = true;
                voiceStatus.innerText = "🎤 Listening...";
                liveTranscript.innerText = "Listening...";
            } else if (msg.event === "speech_end") {
                isUserSpeaking = false;
            }
            break;

        case "transcript":
            liveTranscript.innerText = `"${msg.text}"`;
            if (msg.final) {
                addLogItem(`You: "${msg.text}"`, "system");
            }
            break;

        case "agent_state":
            if (msg.state === "processing") {
                voiceStatus.innerText = "⏳ Processing...";
            } else if (msg.state === "speaking") {
                isAgentSpeaking = true;
                voiceStatus.innerText = "🔊 Enry is speaking...";
            } else if (msg.state === "idle") {
                isAgentSpeaking = false;
                voiceStatus.innerText = "Enry is listening...";
            }
            break;

        case "agent_text":
            addLogItem(`Enry: "${msg.text}"`, "success");
            // Show in NLU card
            nluOutputCard.style.display = 'block';
            nluExplanation.innerText = msg.text;
            break;

        case "tts_start":
            currentGenerationId = msg.generation_id;
            isAgentSpeaking = true;
            ttsAudioQueue = []; // Clear any stale chunks
            break;

        case "tts_chunk":
            if (msg.generation_id === currentGenerationId) {
                playTTSChunk(msg.data, msg.generation_id);
            }
            // else: discard stale chunk
            break;

        case "tts_end":
            if (msg.generation_id === currentGenerationId) {
                // Playback will finish naturally from the queue
            }
            break;

        case "action":
            handleActionResult(msg);
            break;

        case "error":
            console.error("Server error:", msg.code, msg.message);
            addLogItem(`Error: ${msg.message}`, "error");
            break;

        default:
            console.warn("Unknown server message type:", msg.type);
    }
}

function handleActionResult(action) {
    if (!action.success) return;

    nluOutputCard.style.display = 'block';
    nluIntent.innerText = action.intent;

    if (action.intent === 'add_to_bill' && action.data) {
        // Parse product details from the tool result
        const msg = action.message;
        // Extract from tool message format
        const nameMatch = msg.match(/of (.+?) to cart/);
        const priceMatch = msg.match(/₹([\d.]+) ×/);
        const qtyMatch = msg.match(/Added ([\d.]+)/);
        const unitMatch = msg.match(/(\w+)\(s\) of/);

        if (nameMatch) {
            const name = nameMatch[1];
            const price = priceMatch ? parseFloat(priceMatch[1]) : 0;
            const qty = qtyMatch ? parseFloat(qtyMatch[1]) : 1;
            const unit = unitMatch ? unitMatch[1] : 'unit';

            const existingIdx = cart.findIndex(item => item.name === name);
            if (existingIdx > -1) {
                cart[existingIdx].quantity += qty;
                cart[existingIdx].total = cart[existingIdx].quantity * cart[existingIdx].price;
            } else {
                cart.push({ name, price, quantity: qty, unit, total: price * qty });
            }
            renderCart();
        }
    }
    else if (action.intent === 'create_bill') {
        const customerName = action.data?.customer;
        if (customerName) {
            const found = customers.find(c => c.name.toLowerCase() === customerName.toLowerCase());
            if (found) selectCustomer(found);
            else {
                activeCustomerName.innerText = customerName;
                activeCustomer = { name: customerName, id: null };
            }
        }
    }
    else if (action.intent === 'record_credit' || action.intent === 'record_payment') {
        const customerName = action.data?.customer;
        if (customerName) {
            const found = customers.find(c => c.name.toLowerCase() === customerName.toLowerCase());
            if (found) selectCustomer(found);
        }
    }
    else if (action.intent === 'checkout_bill') {
        checkoutCart();
    }

    // Refresh data after any action
    fetchData();
}

// ============================================================================
// VOICE SESSION CONTROL
// ============================================================================

async function wakeUpAgent() {
    if (isAwake) return;
    isAwake = true;
    isListening = true;

    addLogItem("Agent connection started.", "success");
    voiceStatus.innerText = "Initializing microphone...";
    micIcon.innerText = 'mic';
    btnMic.classList.add('listening');

    await initMicrophone();
    initVoiceSocket();

    voiceStatus.innerText = "Enry is listening...";
    liveTranscript.innerText = "Ready for voice command...";
}

function sleepAgent() {
    isAwake = false;
    isListening = false;
    stopTTSPlayback();

    if (voiceSocket) {
        voiceSocket.close();
        voiceSocket = null;
    }

    addLogItem("Agent returning to sleep mode.", "system");
    voiceStatus.innerText = "Microphone paused.";
    micIcon.innerText = 'mic_none';
    btnMic.classList.remove('listening');
}

function toggleListening() {
    if (isAwake) {
        sleepAgent();
    } else {
        wakeUpAgent();
    }
}

// ============================================================================
// TEXT COMMAND (Dashboard typed input / chip buttons)
// ============================================================================

function sendTextCommand(text) {
    if (voiceSocket && voiceSocket.readyState === WebSocket.OPEN) {
        addLogItem(`You (Text): "${text}"`, 'system');
        voiceSocket.send(JSON.stringify({
            type: "text_input",
            text: text,
        }));
    } else {
        // Fallback: use the REST API if WebSocket isn't connected
        submitCommandREST(text);
    }
}

async function submitCommandREST(commandText) {
    if (!commandText.trim()) return;
    addLogItem(`Command sent: "${commandText}"`, 'system');
    voiceStatus.innerText = "Processing command...";

    try {
        const response = await fetch('/api/parse-command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: commandText })
        });
        if (!response.ok) throw new Error("Server response error.");
        const result = await response.json();
        handleParsedActionResult(result);
    } catch (err) {
        console.error("Command parsing failed:", err);
        addLogItem("Failed to process command.", "error");
        voiceStatus.innerText = "Processing failed.";
    }
}

function handleParsedActionResult(result) {
    nluOutputCard.style.display = 'block';
    nluIntent.innerText = result.intent;
    nluExplanation.innerText = result.explanation;

    nluEntitiesContainer.innerHTML = '';
    Object.entries(result.entities).forEach(([key, val]) => {
        const badge = document.createElement('span');
        badge.className = `entity-badge ${key}`;
        badge.innerText = `${key}: ${val}`;
        nluEntitiesContainer.appendChild(badge);
    });

    if (result.success) {
        addLogItem(result.action_taken || result.explanation, 'success');

        if (result.intent === 'add_to_bill' && result.product_details) {
            const details = result.product_details;
            const existingIdx = cart.findIndex(item => item.name === details.name);
            if (existingIdx > -1) {
                cart[existingIdx].quantity += details.quantity;
                cart[existingIdx].total = cart[existingIdx].quantity * cart[existingIdx].price;
            } else {
                cart.push({
                    name: details.name, price: details.price,
                    quantity: details.quantity, unit: details.unit, total: details.total
                });
            }
            renderCart();
        }
        else if (result.intent === 'create_bill') {
            const customerName = result.entities.customer;
            if (customerName) {
                const found = customers.find(c => c.name.toLowerCase() === customerName.toLowerCase());
                if (found) selectCustomer(found);
                else {
                    activeCustomerName.innerText = customerName;
                    activeCustomer = { name: customerName, id: null };
                }
            }
        }
        fetchData();
        speak(result.action_taken || result.explanation);
        voiceStatus.innerText = "Action executed successfully.";
    } else {
        addLogItem(result.explanation, 'error');
        speak(result.explanation);
        voiceStatus.innerText = "Command failed to execute.";
    }
}

// Browser TTS fallback (for REST API path only)
function speak(text) {
    if (!text) return;
    isAgentSpeaking = true;
    const audioUrl = `/api/tts?text=${encodeURIComponent(text)}`;
    const audio = new Audio(audioUrl);
    audio.onended = () => {
        isAgentSpeaking = false;
        voiceStatus.innerText = "Enry is listening...";
    };
    audio.play().then(() => {
        voiceStatus.innerText = "🔊 Enry is speaking...";
    }).catch(err => {
        console.warn("TTS fallback:", err);
        browserSpeakFallback(text);
    });
}

function browserSpeakFallback(text) {
    if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 0.95;
        const voices = window.speechSynthesis.getVoices();
        const indianVoice = voices.find(v => v.lang.includes('en-IN') || v.lang.includes('hi-IN'));
        if (indianVoice) utterance.voice = indianVoice;
        utterance.onend = () => { isAgentSpeaking = false; };
        window.speechSynthesis.speak(utterance);
    } else {
        isAgentSpeaking = false;
    }
}

// ============================================================================
// CART / CHECKOUT
// ============================================================================

async function checkoutCart() {
    if (cart.length === 0) { speak("Cart is empty."); return; }
    const customerName = activeCustomer ? activeCustomer.name : "Walk-in Customer";
    try {
        const response = await fetch('/api/checkout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                customer_name: customerName,
                items: cart.map(i => ({ product_name: i.name, quantity: i.quantity }))
            })
        });
        if (!response.ok) throw new Error("Checkout failed.");
        const resData = await response.json();
        addLogItem(`Checkout invoice #${resData.invoice_id} created.`, 'success');
        cart = [];
        selectCustomer(null);
        renderCart();
        fetchData();
    } catch (err) {
        console.error(err);
        addLogItem("Checkout failed.", "error");
    }
}

function clearCart() {
    cart = [];
    renderCart();
    addLogItem("Cart cleared.", "system");
}

// ============================================================================
// LOG
// ============================================================================

function addLogItem(msg, type = 'system') {
    const item = document.createElement('div');
    item.className = `log-item ${type}`;
    const now = new Date();
    const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    item.innerHTML = `<span class="log-time">${timeStr}</span><span class="log-msg">${msg}</span>`;
    operationsLog.appendChild(item);
    operationsLog.scrollTop = operationsLog.scrollHeight;
}

// ============================================================================
// EVENT LISTENERS
// ============================================================================

function setupEventListeners() {
    btnMic.addEventListener('click', toggleListening);

    document.addEventListener('keydown', (e) => {
        if (e.code === 'Space') {
            if (e.repeat) return;
            const activeTag = document.activeElement.tagName;
            const isInput = activeTag === 'INPUT' || activeTag === 'TEXTAREA' || document.activeElement.isContentEditable;
            if (!isInput) {
                e.preventDefault();
                toggleListening();
            }
        }
    });

    btnClearCart.addEventListener('click', clearCart);
    btnCheckout.addEventListener('click', checkoutCart);

    if (btnSendCommand) {
        btnSendCommand.addEventListener('click', () => {
            const text = txtManualCommand.value;
            if (text && text.trim()) { sendTextCommand(text); txtManualCommand.value = ''; }
        });
    }

    if (txtManualCommand) {
        txtManualCommand.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                const text = txtManualCommand.value;
                if (text && text.trim()) { sendTextCommand(text); txtManualCommand.value = ''; }
            }
        });
    }

    if (btnAddCustomer) {
        btnAddCustomer.addEventListener('click', () => { modalCustomer.style.display = 'flex'; });
    }
    if (btnCloseCustomerModal) {
        btnCloseCustomerModal.addEventListener('click', () => { modalCustomer.style.display = 'none'; });
    }

    if (formAddCustomer) {
        formAddCustomer.addEventListener('submit', async (e) => {
            e.preventDefault();
            const name = document.getElementById('custName').value.trim();
            const phone = document.getElementById('custPhone').value.trim();
            const balance = parseFloat(document.getElementById('custBalance').value) || 0.0;
            try {
                const response = await fetch('/api/customers', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ name, phone, balance })
                });
                if (!response.ok) throw new Error("Failed to create customer.");
                addLogItem(`New customer '${name}' added.`, 'success');
                modalCustomer.style.display = 'none';
                formAddCustomer.reset();
                fetchData();
            } catch (err) {
                alert("Error: Customer already exists or invalid input.");
            }
        });
    }
}
