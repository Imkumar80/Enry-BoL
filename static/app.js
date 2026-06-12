// Enry Web Dashboard Client App Logic

// App State
let activeCustomer = null;
let cart = [];
let customers = [];
let inventory = [];
let transactions = [];

// Speech Recognition Variables
let recognition = null;
let isListening = false;

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

// --- VOICE OS OPERATIONS ---

function initSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        voiceStatus.innerText = "Speech recognition not supported in this browser. Use manual input.";
        btnMic.disabled = true;
        return;
    }

    recognition = new SpeechRecognition();
    recognition.continuous = false;
    // Set language to English (Indian) which resolves Hinglish code-switching best,
    // combined with browser intelligence.
    recognition.lang = 'en-IN'; 
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
        isListening = true;
        btnMic.classList.add('listening');
        micIcon.innerText = 'mic_none';
        voiceStatus.innerText = "Listening to Hinglish command...";
        liveTranscript.classList.remove('placeholder-text');
        liveTranscript.innerText = "Listening...";
    };

    recognition.onresult = (event) => {
        const resultText = event.results[0][0].transcript;
        liveTranscript.innerText = `"${resultText}"`;
        submitCommand(resultText);
    };

    recognition.onerror = (event) => {
        console.error("Speech Recognition Error:", event.error);
        voiceStatus.innerText = `Error: ${event.error}`;
        liveTranscript.innerText = "Could not record audio. Try typing manually.";
        liveTranscript.classList.add('placeholder-text');
        stopListening();
    };

    recognition.onend = () => {
        stopListening();
    };
}

function toggleListening() {
    if (!recognition) return;
    if (isListening) {
        recognition.stop();
    } else {
        recognition.start();
    }
}

function stopListening() {
    isListening = false;
    btnMic.classList.remove('listening');
    micIcon.innerText = 'mic';
    voiceStatus.innerText = "Click mic or press Space to speak";
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

// Browser Text-To-Speech (Hinglish Accent fallback)
function speak(text) {
    if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel(); // Cancel active speech
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 0.95;
        
        // Try to find an Indian English voice for Hinglish accent if possible
        const voices = window.speechSynthesis.getVoices();
        const indianVoice = voices.find(voice => voice.lang.includes('en-IN') || voice.lang.includes('hi-IN'));
        if (indianVoice) {
            utterance.voice = indianVoice;
        }
        
        window.speechSynthesis.speak(utterance);
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
        if (e.code === 'Space' && document.activeElement !== txtManualCommand && document.activeElement !== document.getElementById('custName')) {
            e.preventDefault();
            toggleListening();
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
            submitCommand(text);
            txtManualCommand.value = '';
        }
    });

    txtManualCommand.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            const text = txtManualCommand.value;
            if (text.trim()) {
                submitCommand(text);
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
