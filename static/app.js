// Enry Web Dashboard Client App Logic

// App State
let activeCustomer = null;
let cart = [];
let customers = [];
let inventory = [];
let transactions = [];

// Speech Recognition Variables (Web Audio API + Backend STT)
let isListening = false;
let isAgentSpeaking = false;
let micStream = null;
let audioContext = null;
let scriptProcessor = null;
let audioChunks = [];

// Voice Agent WebSocket
let voiceSocket = null;

// DOM Elements
const btnMic = document.getElementById('btnMic');
const micIcon = document.getElementById('micIcon');
const micRipple = document.getElementById('micRipple');
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

// Initial Setup
document.addEventListener('DOMContentLoaded', () => {
    fetchData();
    setInterval(fetchData, 3000); // Live polling to automatically refresh the ledger!
    initSpeechRecognition();
    setupEventListeners();
    addLogItem('System initialized and ready.', 'system');
});

// --- API FETCH OPERATIONS ---

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
        console.error("Error fetching database stats:", err);
        addLogItem("Error loading database stats from server.", "error");
    }
}

// --- DOM RENDERING ---

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
        
        card.addEventListener('click', () => {
            selectCustomer(c);
        });
        
        customerList.appendChild(card);
    });
}

function renderTransactions() {
    transactionHistory.innerHTML = '';
    if (transactions.length === 0) {
        transactionHistory.innerHTML = '<div class="empty-text">No recent transactions.</div>';
        return;
    }

    // Show top 10 recent transactions
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
    renderCustomers(); // Updates active class highlighting
    addLogItem(`Selected customer: ${customer ? customer.name : 'Walk-in'}`, 'system');
}

function renderCart() {
    cartItems.innerHTML = '';
    if (cart.length === 0) {
        cartItems.innerHTML = `
            <tr class="empty-cart-row">
                <td colspan="5" class="empty-text">Cart is empty. Speak "Ek packet Britannia biscuit add karo" or select a product.</td>
            </tr>
        `;
        cartCount.innerText = '0';
        cartTotal.innerText = '₹0.00';
        return;
    }

    let total = 0;
    let count = 0;

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

// --- VOICE OS OPERATIONS (Raw Audio Streaming + VAD) ---
let isAwake = false;
let currentTurnId = "0";
let activeAudio = null;
let audioSequence = 0;

function _base64EncodePCM(buffer) {
    let binary = '';
    let bytes = new Uint8Array(buffer.buffer);
    let len = bytes.byteLength;
    for (let i = 0; i < len; i++) {
        binary += String.fromCharCode(bytes[i]);
    }
    return window.btoa(binary);
}

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
            accum += buffer[i];
            count++;
        }
        result[offsetResult] = accum / count;
        offsetResult++;
        offsetBuffer = nextOffsetBuffer;
    }
    return result;
}

function initSpeechRecognition() {
    navigator.mediaDevices.getUserMedia({ audio: true }).then((stream) => {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const source = audioContext.createMediaStreamSource(stream);
        
        scriptProcessor = audioContext.createScriptProcessor(4096, 1, 1);
        source.connect(scriptProcessor);
        
        // Output must be connected for onaudioprocess to fire
        scriptProcessor.connect(audioContext.destination);
        
        scriptProcessor.onaudioprocess = (e) => {
            if (!isAwake || !voiceSocket || voiceSocket.readyState !== WebSocket.OPEN) return;
            
            const inputData = e.inputBuffer.getChannelData(0);
            
            // Client-side VAD (energy-based) for immediate Barge-in
            let energy = 0;
            for (let i = 0; i < inputData.length; i++) {
                energy += inputData[i] * inputData[i];
            }
            const rms = Math.sqrt(energy / inputData.length);
            
            // Immediate Client-Side Barge-in
            if (isAgentSpeaking && rms > 0.05) {
                console.log("Client-side barge-in triggered! RMS Energy:", rms);
                stopAgentAudio();
                
                voiceSocket.send(JSON.stringify({
                    type: "interrupt",
                    turn_id: currentTurnId
                }));
            }
            
            // Send PCM audio frames if listening
            if (isListening) {
                const downsampled = downsampleBuffer(inputData, audioContext.sampleRate, 16000);
                const pcm16 = convertFloat32ToInt16(downsampled);
                
                audioSequence++;
                voiceSocket.send(JSON.stringify({
                    type: "audio",
                    sequence: audioSequence,
                    data: _base64EncodePCM(pcm16)
                }));
            }
        };
    }).catch((err) => {
        console.error("Microphone access failed", err);
        voiceStatus.innerText = "Microphone access denied.";
        btnMic.classList.remove('listening');
        micIcon.innerText = 'mic_off';
    });
}

function stopAgentAudio() {
    isAgentSpeaking = false;
    
    // Wipe the playback queue on barge-in
    playQueue = [];
    activeGenerationId = null;
    
    if (activeAudio) {
        activeAudio.pause();
        activeAudio.currentTime = 0;
        activeAudio = null;
    }
}

function wakeUpAgent() {
    if (isAwake) return;
    isAwake = true;
    isListening = true;
    addLogItem("Agent connection started.", "success");
    voiceStatus.innerText = "Agent awake. Stream is active.";
    liveTranscript.innerText = "Ready for voice command...";
    micIcon.innerText = 'mic';
    btnMic.classList.add('listening');
    
    if (!voiceSocket || voiceSocket.readyState !== WebSocket.OPEN) {
        initVoiceAgentSocket();
    }
}

function sleepAgent() {
    isAwake = false;
    isListening = false;
    stopAgentAudio();
    addLogItem("Agent returning to sleep mode.", "system");
    voiceStatus.innerText = "Microphone paused.";
    micIcon.innerText = 'mic_none';
    
    if (voiceSocket) {
        voiceSocket.close();
        voiceSocket = null;
    }
}

function toggleListening() {
    if (isAwake) {
        sleepAgent();
        btnMic.classList.remove('listening');
        micIcon.innerText = 'mic_off';
    } else {
        wakeUpAgent();
    }
}

function stopListening() {
    sleepAgent();
    btnMic.classList.remove('listening');
    micIcon.innerText = 'mic_off';
    voiceStatus.innerText = "Microphone paused.";
}

// Submit spoken or typed command to FastAPI
async function submitCommand(commandText) {
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
        addLogItem("Failed to process command. Please verify connection.", "error");
        speak("Server connection failure. Command not processed.");
        voiceStatus.innerText = "Processing failed.";
    }
}

function handleParsedActionResult(result) {
    // Show AI intent block
    nluOutputCard.style.display = 'block';
    nluIntent.innerText = result.intent;
    nluExplanation.innerText = result.explanation;
    
    // Render entity badges
    nluEntitiesContainer.innerHTML = '';
    Object.entries(result.entities).forEach(([key, val]) => {
        const badge = document.createElement('span');
        badge.className = `entity-badge ${key}`;
        badge.innerText = `${key}: ${val}`;
        nluEntitiesContainer.appendChild(badge);
    });

    if (result.success) {
        addLogItem(result.action_taken || result.explanation, 'success');
        
        // Execute UI modifications depending on intent
        if (result.intent === 'add_to_bill' && result.product_details) {
            const details = result.product_details;
            // Add to client-side cart
            const existingItemIndex = cart.findIndex(item => item.name === details.name);
            if (existingItemIndex > -1) {
                cart[existingItemIndex].quantity += details.quantity;
                cart[existingItemIndex].total = cart[existingItemIndex].quantity * cart[existingItemIndex].price;
            } else {
                cart.push({
                    name: details.name,
                    price: details.price,
                    quantity: details.quantity,
                    unit: details.unit,
                    total: details.total
                });
            }
            renderCart();
        } 
        else if (result.intent === 'create_bill') {
            // Find customer
            const customerName = result.entities.customer;
            if (customerName) {
                const found = customers.find(c => c.name.toLowerCase() === customerName.toLowerCase());
                if (found) {
                    selectCustomer(found);
                } else {
                    activeCustomerName.innerText = customerName;
                    activeCustomer = { name: customerName, id: null };
                }
            } else {
                selectCustomer(null);
            }
        }
        
        // Refresh DB data
        fetchData();
        
        // Voice Response confirmation
        speak(result.action_taken || result.explanation);
        voiceStatus.innerText = "Action executed successfully.";
    } else {
        addLogItem(result.explanation, 'error');
        speak(result.explanation);
        voiceStatus.innerText = "Command failed to execute.";
    }
}

// Browser Text-To-Speech (Fallback logic - Phase 8 replaces this with server TTS streaming)
function speak(text) {
    if (!text) return;

    // Do NOT stop listening. True barge-in means we keep listening.
    isAgentSpeaking = true;
    
    const audioUrl = `/api/tts?text=${encodeURIComponent(text)}`;
    activeAudio = new Audio(audioUrl);

    activeAudio.onended = () => {
        isAgentSpeaking = false;
        activeAudio = null;
        voiceStatus.innerText = "Enry is listening...";
    };

    activeAudio.play()
        .then(() => {
            console.log("Playing speech via Cartesia TTS...");
            voiceStatus.innerText = "🔊 Enry is speaking...";
        })
        .catch(err => {
            console.warn("Cartesia TTS API unavailable, falling back...", err);
            browserSpeakFallback(text);
        });
}

function browserSpeakFallback(text) {
    if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 0.95;
        
        const voices = window.speechSynthesis.getVoices();
        const indianVoice = voices.find(voice => voice.lang.includes('en-IN') || voice.lang.includes('hi-IN'));
        if (indianVoice) utterance.voice = indianVoice;
        
        utterance.onend = () => {
            isAgentSpeaking = false;
            voiceStatus.innerText = "Enry is listening...";
        };
        
        window.speechSynthesis.speak(utterance);
    } else {
        isAgentSpeaking = false;
    }
}


// Checkout active bill
async function checkoutCart() {
    if (cart.length === 0) {
        speak("Cart is empty. Cannot checkout.");
        return;
    }

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
        addLogItem(`Checkout invoice #${resData.invoice_id} successfully created.`, 'success');
        speak(`Bill settled for ${customerName}. Invoice generated.`);
        
        // Clear active cart & customer
        cart = [];
        selectCustomer(null);
        renderCart();
        fetchData(); // Refresh inventory
    } catch (err) {
        console.error(err);
        addLogItem("Checkout failed. Check stock availability.", "error");
        speak("Checkout failed. Some items might be out of stock.");
    }
}

// Clear cart
function clearCart() {
    cart = [];
    renderCart();
    addLogItem("Active cart cleared.", "system");
}

// --- LOG OPERATIONS ---

function addLogItem(msg, type = 'system') {
    const item = document.createElement('div');
    item.className = `log-item ${type}`;
    
    const now = new Date();
    const timeStr = now.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit'});
    
    item.innerHTML = `
        <span class="log-time">${timeStr}</span>
        <span class="log-msg">${msg}</span>
    `;
    
    operationsLog.appendChild(item);
    operationsLog.scrollTop = operationsLog.scrollHeight;
}

// --- EVENT LISTENERS & HOTKEYS ---

function setupEventListeners() {
    // Microphone Button Click
    btnMic.addEventListener('click', toggleListening);

    // Global spacebar hotkey (Toggles listening if no inputs are active)
    document.addEventListener('keydown', (e) => {
        if (e.code === 'Space') {
            if (e.repeat) return; // Prevent rapid toggling if key is held down
            
            const activeTag = document.activeElement.tagName;
            const isInput = activeTag === 'INPUT' || activeTag === 'TEXTAREA' || document.activeElement.isContentEditable;
            
            if (!isInput) {
                e.preventDefault();
                toggleListening();
            }
        }
    });

    // Clear Cart button
    btnClearCart.addEventListener('click', clearCart);

    // Checkout button
    btnCheckout.addEventListener('click', checkoutCart);

    // Manual text command submit
    btnSendCommand.addEventListener('click', () => {
        const text = txtManualCommand.value;
        if (text.trim()) {
            sendTextCommand(text);
            txtManualCommand.value = '';
        }
    });

    txtManualCommand.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            const text = txtManualCommand.value;
            if (text.trim()) {
                sendTextCommand(text);
                txtManualCommand.value = '';
            }
        }
    });

    // Customer modal toggles
    btnAddCustomer.addEventListener('click', () => {
        modalCustomer.style.display = 'flex';
    });

    btnCloseCustomerModal.addEventListener('click', () => {
        modalCustomer.style.display = 'none';
    });

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

            addLogItem(`New customer '${name}' added to Khata.`, 'success');
            modalCustomer.style.display = 'none';
            formAddCustomer.reset();
            fetchData();
        } catch (err) {
            alert("Error: Customer already exists or invalid input details.");
        }
    });
}

// --- VOICE AGENT WEBSOCKET HANDLERS ---

let activeGenerationId = null;
let playQueue = [];
let isPlaying = false;

function playNextAudioChunk() {
    if (playQueue.length === 0) {
        isPlaying = false;
        return;
    }
    isPlaying = true;
    const chunk = playQueue.shift();
    
    const source = audioContext.createBufferSource();
    source.buffer = chunk;
    source.connect(audioContext.destination);
    source.onended = playNextAudioChunk;
    source.start();
}

function handleServerTtsMessage(data) {
    if (activeGenerationId && data.generation_id !== activeGenerationId) {
        // Discard old generation chunks after barge-in
        return;
    }
    activeGenerationId = data.generation_id;
    
    const binaryStr = window.atob(data.data);
    const len = binaryStr.length;
    const bytes = new Uint8Array(len);
    for (let i = 0; i < len; i++) {
        bytes[i] = binaryStr.charCodeAt(i);
    }
    
    const int16 = new Int16Array(bytes.buffer);
    const float32 = new Float32Array(int16.length);
    for(let i=0; i<int16.length; i++) float32[i] = int16[i] / 0x7FFF;
    
    const audioBuffer = audioContext.createBuffer(1, float32.length, 16000);
    audioBuffer.getChannelData(0).set(float32);
    
    playQueue.push(audioBuffer);
    if (!isPlaying) playNextAudioChunk();
}

function initVoiceAgentSocket() {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/voice`;
    console.log(`Connecting to Voice Agent WebSocket: ${wsUrl}`);
    
    voiceSocket = new WebSocket(wsUrl);
    
    voiceSocket.onopen = () => {
        console.log("Connected to Voice Agent WebSocket.");
        addLogItem("Connected to voice gateway.", "system");
    };
    
    voiceSocket.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            
            if (data.type === "transcript") {
                liveTranscript.innerText = `"${data.text}"`;
                addLogItem(`You: ${data.text}`, "system");
            } 
            else if (data.type === "tts") {
                isAgentSpeaking = true;
                handleServerTtsMessage(data);
                voiceStatus.innerText = "🔊 Enry is speaking...";
            }
            else if (data.type === "tts_end") {
                activeGenerationId = null; // Clear so new turns can start
                isAgentSpeaking = false;
                voiceStatus.innerText = "Enry is listening...";
            }
            else if (data.type === "error") {
                console.error("Voice Agent error:", data.content);
                addLogItem(`Agent Error: ${data.content}`, "error");
            }
        } catch (e) {
            console.error("Error parsing WebSocket message:", e);
        }
    };
    
    voiceSocket.onclose = (event) => {
        if (!isAwake) return; 
        console.warn("Voice Agent WebSocket disconnected. Reconnecting in 3 seconds...", event.reason);
        addLogItem("Voice agent server disconnected. Retrying...", "error");
        setTimeout(() => { if (isAwake) initVoiceAgentSocket(); }, 3000);
    };
    
    voiceSocket.onerror = (error) => {
        console.error("Voice Agent WebSocket error:", error);
    };
}

function handleLedgerToolResult(resultString) {
    try {
        const result = JSON.parse(resultString);
        console.log("Parsed ledger tool result:", result);
        
        if (result.success) {
            addLogItem(result.message, "success");
        } else {
            addLogItem(result.message, "error");
        }
        
        if (result.success) {
            if (result.intent === "add_to_bill" && result.product_details) {
                const details = result.product_details;
                // Add to client-side cart
                const existingItemIndex = cart.findIndex(item => item.name === details.name);
                if (existingItemIndex > -1) {
                    cart[existingItemIndex].quantity += details.quantity;
                    cart[existingItemIndex].total = cart[existingItemIndex].quantity * cart[existingItemIndex].price;
                } else {
                    cart.push({
                        name: details.name,
                        price: details.price,
                        quantity: details.quantity,
                        unit: details.unit,
                        total: details.total
                    });
                }
                renderCart();
            } 
            else if (result.intent === "create_bill") {
                const customerName = result.customer;
                if (customerName) {
                    const found = customers.find(c => c.name.toLowerCase() === customerName.toLowerCase());
                    if (found) {
                        selectCustomer(found);
                    } else {
                        activeCustomerName.innerText = customerName;
                        activeCustomer = { name: customerName, id: null };
                    }
                } else {
                    selectCustomer(null);
                }
            }
            else if (result.intent === "record_credit" || result.intent === "record_payment") {
                const customerName = result.customer;
                if (customerName) {
                    const found = customers.find(c => c.name.toLowerCase() === customerName.toLowerCase());
                    if (found) {
                        selectCustomer(found);
                    }
                }
            }
            else if (result.intent === "checkout_bill") {
                checkoutCart();
            }
            
            // Refresh dashboard DB statistics
            fetchData();
        }
    } catch (e) {
        console.warn("Ledger result is not JSON:", resultString);
        addLogItem(resultString, "system");
        speak(resultString);
    }
}

function sendTextCommand(text) {
    if (voiceSocket && voiceSocket.readyState === WebSocket.OPEN) {
        addLogItem(`You (Text): "${text}"`, 'system');
        
        voiceSocket.send(JSON.stringify({
            type: "user_state",
            value: "speaking"
        }));
        voiceSocket.send(JSON.stringify({
            type: "message",
            content: text
        }));
        voiceSocket.send(JSON.stringify({
            type: "user_state",
            value: "idle"
        }));
    } else {
        submitCommand(text);
    }
}
