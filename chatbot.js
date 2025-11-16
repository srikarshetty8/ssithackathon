// Chatbot Module - Frontend Implementation

// Helper to get config safely
function getChatbotConfig() {
    const config = typeof CONFIG !== 'undefined' ? CONFIG : (typeof window !== 'undefined' ? window.CONFIG : null);
    return config || {
        chatbot: {
            apiBase: typeof window !== 'undefined' && window.location ? 
                `${window.location.protocol}//${window.location.hostname}:${window.location.port || '5000'}` : 
                'http://localhost:5000',
            mockMode: false
        }
    };
}

class CarbonFootprintChatbot {
    constructor(options = {}) {
        const config = getChatbotConfig();
        this.apiBase = options.apiBase || config.chatbot.apiBase;
        this.userId = options.userId || null;
        this.authToken = options.authToken || null;
        this.isPremium = options.isPremium || false;
        this.mockMode = options.mockMode !== undefined ? options.mockMode : config.chatbot.mockMode;
        this.isOpen = false;
        this.conversationHistory = [];
        this.callbacks = {
            onTipClicked: options.onTipClicked || null,
            onExportRequest: options.onExportRequest || null,
        };

        this.init();
    }

    // Initialize chatbot
    init() {
        this.loadConversationHistory();
        this.createUI();
        this.setupEventListeners();
        this.startOnboarding();
    }

    // Create chatbot UI
    createUI() {
        const container = document.getElementById('chatbotContainer');
        if (!container) {
            console.error('Chatbot container not found');
            return;
        }

        container.innerHTML = `
            <div class="chatbot-widget" id="chatbotWidget" role="region" aria-label="Chatbot">
                <button class="chatbot-toggle" id="chatbotToggle" aria-label="Toggle chatbot">
                    <span class="chatbot-icon">💬</span>
                </button>
                <div class="chatbot-panel" id="chatbotPanel" style="display: none;">
                    <div class="chatbot-header">
                        <div class="chatbot-title">
                            <span class="chatbot-icon">🌱</span>
                            <span>Carbon Footprint Assistant</span>
                        </div>
                        <button class="chatbot-close" id="chatbotClose" aria-label="Close chatbot">×</button>
                    </div>
                    <div class="chatbot-messages" id="chatbotMessages" role="log" aria-live="polite" aria-atomic="false">
                        <!-- Messages will be added here -->
                    </div>
                    <div class="chatbot-input-container">
                        <input 
                            type="text" 
                            id="chatbotInput" 
                            class="chatbot-input" 
                            placeholder="Type your message..."
                            aria-label="Chatbot input"
                            autocomplete="off"
                        />
                        <button class="chatbot-send" id="chatbotSend" aria-label="Send message">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M22 2L11 13" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                                <path d="M22 2L15 22L11 13L2 9L22 2Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                            </svg>
                        </button>
                    </div>
                </div>
            </div>
        `;

        // Add chatbot styles if not already present
        this.injectStyles();
    }

    // Inject chatbot styles
    injectStyles() {
        if (document.getElementById('chatbot-styles')) return;

        const style = document.createElement('style');
        style.id = 'chatbot-styles';
        style.textContent = `
            .chatbot-widget {
                position: fixed;
                bottom: 20px;
                right: 20px;
                z-index: 1000;
                font-family: inherit;
            }

            .chatbot-toggle {
                width: 60px;
                height: 60px;
                border-radius: 50%;
                background: linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-secondary) 100%);
                border: none;
                color: white;
                font-size: 1.5rem;
                cursor: pointer;
                box-shadow: var(--shadow-lg);
                transition: all 0.3s ease;
                display: flex;
                align-items: center;
                justify-content: center;
            }

            .chatbot-toggle:hover {
                transform: scale(1.1);
                box-shadow: var(--shadow-xl);
            }

            .chatbot-panel {
                position: absolute;
                bottom: 80px;
                right: 0;
                width: 400px;
                max-width: calc(100vw - 40px);
                height: 600px;
                max-height: calc(100vh - 120px);
                background: var(--bg-primary);
                border-radius: 20px;
                box-shadow: var(--shadow-xl);
                border: 1px solid var(--border-color);
                display: flex;
                flex-direction: column;
                overflow: hidden;
                animation: slideUp 0.3s ease;
            }

            @keyframes slideUp {
                from {
                    opacity: 0;
                    transform: translateY(20px);
                }
                to {
                    opacity: 1;
                    transform: translateY(0);
                }
            }

            .chatbot-header {
                background: linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-secondary) 100%);
                color: white;
                padding: 1rem;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }

            .chatbot-title {
                display: flex;
                align-items: center;
                gap: 0.5rem;
                font-weight: 600;
            }

            .chatbot-close {
                background: none;
                border: none;
                color: white;
                font-size: 1.5rem;
                cursor: pointer;
                width: 30px;
                height: 30px;
                display: flex;
                align-items: center;
                justify-content: center;
                border-radius: 50%;
                transition: background 0.3s ease;
            }

            .chatbot-close:hover {
                background: rgba(255, 255, 255, 0.2);
            }

            .chatbot-messages {
                flex: 1;
                overflow-y: auto;
                padding: 1rem;
                display: flex;
                flex-direction: column;
                gap: 1rem;
                scroll-behavior: smooth;
            }

            .chatbot-message {
                display: flex;
                gap: 0.5rem;
                animation: fadeIn 0.3s ease;
            }

            .chatbot-message.user {
                flex-direction: row-reverse;
            }

            .message-content {
                max-width: 75%;
                padding: 0.75rem 1rem;
                border-radius: 16px;
                word-wrap: break-word;
            }

            .chatbot-message.bot .message-content {
                background: var(--bg-secondary);
                color: var(--text-primary);
                border-bottom-left-radius: 4px;
            }

            .chatbot-message.user .message-content {
                background: linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-secondary) 100%);
                color: white;
                border-bottom-right-radius: 4px;
            }

            .message-time {
                font-size: 0.7rem;
                opacity: 0.7;
                margin-top: 0.25rem;
            }

            .chatbot-input-container {
                display: flex;
                gap: 0.5rem;
                padding: 1rem;
                border-top: 1px solid var(--border-color);
                background: var(--bg-secondary);
            }

            .chatbot-input {
                flex: 1;
                padding: 0.75rem;
                border: 2px solid var(--border-color);
                border-radius: 12px;
                background: var(--bg-primary);
                color: var(--text-primary);
                font-size: 0.9rem;
                outline: none;
                transition: border-color 0.3s ease;
            }

            .chatbot-input:focus {
                border-color: var(--accent-primary);
            }

            .chatbot-send {
                width: 44px;
                height: 44px;
                border-radius: 12px;
                border: none;
                background: linear-gradient(135deg, var(--accent-primary) 0%, var(--accent-secondary) 100%);
                color: white;
                cursor: pointer;
                display: flex;
                align-items: center;
                justify-content: center;
                transition: transform 0.3s ease;
            }

            .chatbot-send:hover {
                transform: scale(1.1);
            }

            .chatbot-send:disabled {
                opacity: 0.5;
                cursor: not-allowed;
            }

            .quick-reply {
                display: inline-block;
                padding: 0.5rem 1rem;
                margin: 0.25rem;
                background: var(--bg-tertiary);
                border: 1px solid var(--border-color);
                border-radius: 20px;
                cursor: pointer;
                font-size: 0.85rem;
                transition: all 0.3s ease;
                color: var(--text-primary);
            }

            .quick-reply:hover {
                background: var(--accent-primary);
                color: white;
                border-color: var(--accent-primary);
            }

            .tip-link {
                color: var(--accent-primary);
                text-decoration: underline;
                cursor: pointer;
                font-weight: 600;
            }

            @media (max-width: 480px) {
                .chatbot-panel {
                    width: calc(100vw - 20px);
                    height: calc(100vh - 100px);
                    bottom: 70px;
                    right: 10px;
                }
            }
        `;
        document.head.appendChild(style);
    }

    // Setup event listeners
    setupEventListeners() {
        const toggle = document.getElementById('chatbotToggle');
        const close = document.getElementById('chatbotClose');
        const send = document.getElementById('chatbotSend');
        const input = document.getElementById('chatbotInput');

        if (toggle) {
            toggle.addEventListener('click', () => this.toggle());
        }

        if (close) {
            close.addEventListener('click', () => this.close());
        }

        if (send) {
            send.addEventListener('click', () => this.sendMessage());
        }

        if (input) {
            input.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    this.sendMessage();
                }
            });
        }
    }

    // Toggle chatbot
    toggle() {
        this.isOpen = !this.isOpen;
        const panel = document.getElementById('chatbotPanel');
        const toggle = document.getElementById('chatbotToggle');

        if (panel) {
            panel.style.display = this.isOpen ? 'flex' : 'none';
        }

        if (toggle) {
            toggle.style.display = this.isOpen ? 'none' : 'flex';
        }

        if (this.isOpen) {
            const input = document.getElementById('chatbotInput');
            if (input) input.focus();
        }
    }

    // Close chatbot
    close() {
        this.isOpen = false;
        const panel = document.getElementById('chatbotPanel');
        const toggle = document.getElementById('chatbotToggle');

        if (panel) panel.style.display = 'none';
        if (toggle) toggle.style.display = 'flex';
    }

    // Send message
    async sendMessage() {
        const input = document.getElementById('chatbotInput');
        const sendBtn = document.getElementById('chatbotSend');

        if (!input || !sendBtn) return;

        const message = input.value.trim();
        if (!message) return;

        // Add user message to UI
        this.addMessage('user', message);
        input.value = '';
        sendBtn.disabled = true;

        // Process message
        try {
            const response = await this.processMessage(message);
            this.addMessage('bot', response.text, response.quickReplies, response.tips);
        } catch (error) {
            console.error('Chatbot error:', error);
            this.addMessage('bot', "I'm sorry, I encountered an error. Please try again.");
        } finally {
            sendBtn.disabled = false;
            input.focus();
        }
    }

    // Process message
    async processMessage(message) {
        // Save to conversation history
        this.conversationHistory.push({
            role: 'user',
            content: message,
            timestamp: new Date().toISOString(),
        });

        let response;

        if (this.mockMode) {
            // Mock NLU processing
            response = this.processMockNLU(message);
        } else {
            // Call backend API
            try {
                const apiResponse = await fetch(`${this.apiBase}/chatbot/chat`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        ...(this.authToken && { 'Authorization': `Bearer ${this.authToken}` }),
                    },
                    body: JSON.stringify({
                        message,
                        userId: this.userId,
                        conversationHistory: this.conversationHistory.slice(-10), // Last 10 messages
                    }),
                });

                if (!apiResponse.ok) {
                    throw new Error('API request failed');
                }

                response = await apiResponse.json();
            } catch (error) {
                console.error('API error, falling back to mock:', error);
                response = this.processMockNLU(message);
            }
        }

        // Save response to conversation history
        this.conversationHistory.push({
            role: 'assistant',
            content: response.text,
            timestamp: new Date().toISOString(),
        });

        this.saveConversationHistory();

        return response;
    }

    // Mock NLU Processing
    processMockNLU(message) {
        const lowerMessage = message.toLowerCase();

        // Intent detection
        if (lowerMessage.includes('calculate') || lowerMessage.includes('emission') || lowerMessage.includes('footprint')) {
            return {
                text: "To calculate your carbon footprint, use the calculator above! I can help explain what each category means. What would you like to know more about?",
                quickReplies: ['Transport', 'Energy', 'Food', 'Waste'],
                tips: [{
                    title: 'Use the Calculator',
                    description: 'Scroll to the calculator section to input your activities',
                    action: () => scrollToSection('calculator'),
                }],
            };
        }

        if (lowerMessage.includes('reduce') || lowerMessage.includes('lower') || lowerMessage.includes('decrease')) {
            return {
                text: "Great question! Here are some top tips to reduce your carbon footprint:\n\n1. 🚗 Reduce car travel by 20%\n2. ⚡ Switch to renewable energy\n3. 🍽️ Eat less meat\n4. ♻️ Improve recycling\n\nWould you like more specific tips for any category?",
                quickReplies: ['Transport Tips', 'Energy Tips', 'Food Tips'],
                tips: [{
                    title: 'View Insights',
                    description: 'Check out personalized insights in the Insights section',
                    action: () => scrollToSection('insights'),
                }],
            };
        }

        if (lowerMessage.includes('transport') || lowerMessage.includes('car') || lowerMessage.includes('travel')) {
            return {
                text: "Transport is often the biggest contributor to carbon footprints. Here are some tips:\n\n• Use public transport or carpool\n• Walk or cycle for short trips\n• Consider electric vehicles\n• Reduce air travel\n\nWould you like me to help you calculate your transport emissions?",
                quickReplies: ['Calculate Transport', 'More Tips', 'Dashboard'],
            };
        }

        if (lowerMessage.includes('energy') || lowerMessage.includes('electricity') || lowerMessage.includes('power')) {
            return {
                text: "Energy usage can significantly impact your footprint:\n\n• Switch to renewable energy providers\n• Use energy-efficient appliances\n• Reduce heating/cooling usage\n• Install solar panels if possible\n\nCheck your energy consumption in the calculator!",
                quickReplies: ['Calculate Energy', 'Renewable Options'],
            };
        }

        if (lowerMessage.includes('food') || lowerMessage.includes('meat') || lowerMessage.includes('diet')) {
            return {
                text: "Food choices matter! Here's how:\n\n• Reduce meat consumption (especially beef)\n• Eat local and seasonal produce\n• Reduce food waste\n• Choose plant-based options more often\n\nA plant-based meal can have 90% less emissions than a meat meal!",
                quickReplies: ['Food Tips', 'Calculate Food'],
            };
        }

        if (lowerMessage.includes('premium') || lowerMessage.includes('subscribe') || lowerMessage.includes('upgrade')) {
            return {
                text: this.isPremium 
                    ? "You already have premium access! Premium features include advanced analytics, PDF/CSV export, device integrations, and personalized reduction plans. How can I help you with premium features?"
                    : "Premium features unlock advanced analytics, detailed reports, device integrations, and personalized reduction plans. Would you like to learn more about premium?",
                quickReplies: this.isPremium ? ['Generate Plan', 'Export Report'] : ['Learn More', 'Subscribe'],
                tips: this.isPremium ? [] : [{
                    title: 'View Premium',
                    description: 'Check out all premium features',
                    action: () => scrollToSection('premium'),
                }],
            };
        }

        if (lowerMessage.includes('export') || lowerMessage.includes('report') || lowerMessage.includes('pdf') || lowerMessage.includes('csv')) {
            if (!this.isPremium && !CONFIG.app.demoMode) {
                return {
                    text: "Export features are available in premium. You can export your data as CSV or PDF for detailed analysis. Would you like to upgrade?",
                    quickReplies: ['View Premium', 'Subscribe'],
                };
            }

            return {
                text: "I can help you export your carbon footprint data! You can export as CSV for spreadsheets or PDF for reports. Click the export button in the dashboard to get started.",
                quickReplies: ['Go to Dashboard', 'Premium Features'],
                tips: [{
                    title: 'Export Data',
                    description: 'Use the export button in the dashboard',
                    action: () => scrollToSection('dashboard'),
                }],
            };
        }

        if (lowerMessage.includes('plan') || lowerMessage.includes('personalized') || lowerMessage.includes('strategy')) {
            if (!this.isPremium && !CONFIG.app.demoMode) {
                return {
                    text: "Personalized reduction plans are a premium feature. I can analyze your data and create a custom plan to help you reach your goals. Upgrade to premium to access this feature!",
                    quickReplies: ['Learn Premium', 'Subscribe'],
                };
            }

            return {
                text: "I'll create a personalized reduction plan based on your data! Here's a sample plan:\n\n📅 Month 1: Reduce car travel by 10%\n📅 Month 2: Switch 30% to renewable energy\n📅 Month 3: Reduce meat consumption by 2 meals/week\n\nWould you like me to generate a detailed plan?",
                quickReplies: ['Generate Full Plan', 'View Goals'],
            };
        }

        if (lowerMessage.includes('help') || lowerMessage.includes('what can you') || lowerMessage.includes('capabilities')) {
            return {
                text: "I'm here to help you track and reduce your carbon footprint! I can:\n\n• Explain emissions categories\n• Suggest reduction strategies\n• Help with the calculator\n• Provide personalized tips\n• Answer questions about your footprint\n\nWhat would you like to know?",
                quickReplies: ['Calculate Footprint', 'Reduction Tips', 'Dashboard'],
            };
        }

        if (lowerMessage.includes('hello') || lowerMessage.includes('hi') || lowerMessage.includes('hey')) {
            return {
                text: "Hello! I'm your Carbon Footprint Assistant. I can help you understand and reduce your environmental impact. What would you like to know?",
                quickReplies: ['Calculate Footprint', 'Reduction Tips', 'View Dashboard'],
            };
        }

        // Default response
        return {
            text: "I'm here to help with your carbon footprint questions! I can help you:\n\n• Calculate emissions\n• Get reduction tips\n• Understand your dashboard\n• Set goals\n\nWhat would you like to explore?",
            quickReplies: ['Calculate Footprint', 'Reduction Tips', 'Dashboard', 'Help'],
        };
    }

    // Add message to UI
    addMessage(role, text, quickReplies = [], tips = []) {
        const messagesContainer = document.getElementById('chatbotMessages');
        if (!messagesContainer) return;

        const messageDiv = document.createElement('div');
        messageDiv.className = `chatbot-message ${role}`;
        messageDiv.setAttribute('role', role === 'bot' ? 'status' : 'log');

        const time = new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });

        let tipsHTML = '';
        if (tips.length > 0) {
            tipsHTML = '<div style="margin-top: 0.5rem;">';
            tips.forEach(tip => {
                tipsHTML += `<div class="tip-link" onclick="window.chatbot?.handleTipClick('${tip.title}')">💡 ${tip.title}</div>`;
            });
            tipsHTML += '</div>';
        }

        let quickRepliesHTML = '';
        if (quickReplies.length > 0) {
            quickRepliesHTML = '<div style="margin-top: 0.5rem; display: flex; flex-wrap: wrap; gap: 0.5rem;">';
            quickReplies.forEach(reply => {
                quickRepliesHTML += `<button class="quick-reply" onclick="window.chatbot?.sendQuickReply('${reply}')">${reply}</button>`;
            });
            quickRepliesHTML += '</div>';
        }

        messageDiv.innerHTML = `
            <div class="message-content">
                <div>${this.formatMessage(text)}</div>
                ${tipsHTML}
                ${quickRepliesHTML}
                <div class="message-time">${time}</div>
            </div>
        `;

        messagesContainer.appendChild(messageDiv);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    // Format message (simple markdown-like formatting)
    formatMessage(text) {
        return text
            .replace(/\n/g, '<br>')
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>');
    }

    // Send quick reply
    sendQuickReply(reply) {
        const input = document.getElementById('chatbotInput');
        if (input) {
            input.value = reply;
            this.sendMessage();
        }
    }

    // Handle tip click
    handleTipClick(tipTitle) {
        if (this.callbacks.onTipClicked) {
            this.callbacks.onTipClicked(tipTitle);
        }
    }

    // Start onboarding
    startOnboarding() {
        setTimeout(() => {
            if (this.conversationHistory.length === 0) {
                this.addMessage('bot', "Hi! I'm your Carbon Footprint Assistant. I can help you track and reduce your emissions. Would you like to start by calculating your footprint?", 
                    ['Calculate Footprint', 'Learn More', 'View Dashboard']);
            }
        }, 1000);
    }

    // Load conversation history
    loadConversationHistory() {
        try {
            const stored = localStorage.getItem('chatbot_history');
            if (stored) {
                this.conversationHistory = JSON.parse(stored);
            }
        } catch (error) {
            console.error('Error loading conversation history:', error);
        }
    }

    // Save conversation history
    saveConversationHistory() {
        try {
            // Keep only last 50 messages
            const toSave = this.conversationHistory.slice(-50);
            localStorage.setItem('chatbot_history', JSON.stringify(toSave));
        } catch (error) {
            console.error('Error saving conversation history:', error);
        }
    }

    // Initialize chatbot with API configuration
    static initChatbot(options = {}) {
        if (!window.chatbot) {
            window.chatbot = new CarbonFootprintChatbot(options);
        }
        return window.chatbot;
    }
}

// Initialize chatbot when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    const config = getChatbotConfig();
    const user = api?.user || null;
    const chatbotOptions = {
        apiBase: config.chatbot.apiBase,
        userId: user?.id || null,
        authToken: api?.authToken || null,
        isPremium: user?.isPremium || false,
        mockMode: config.chatbot.mockMode,
        onTipClicked: (tipTitle) => {
            console.log('Tip clicked:', tipTitle);
            // Handle tip clicks
        },
        onExportRequest: () => {
            scrollToSection('dashboard');
        },
    };

    CarbonFootprintChatbot.initChatbot(chatbotOptions);
});

// Export for use in other scripts
if (typeof module !== 'undefined' && module.exports) {
    module.exports = CarbonFootprintChatbot;
}

