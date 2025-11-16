// Configuration file for Carbon Footprint Tracker
// Make sure this file loads before app.js

// Get base URL from window location or use default
const getBaseUrl = () => {
    if (typeof window !== 'undefined' && window.location) {
        const protocol = window.location.protocol;
        const hostname = window.location.hostname;
        const port = window.location.port ? `:${window.location.port}` : '';
        return `${protocol}//${hostname}${port}`;
    }
    return 'http://localhost:5000';
};

const CONFIG = {
    // API Configuration
    api: {
        baseUrl: getBaseUrl() + '/api',
        timeout: 30000,
    },

    // Stripe Configuration (stubbed)
    stripe: {
        publishableKey: 'pk_test_your_stripe_key_here', // Replace with your Stripe key
        priceId: 'price_premium_monthly',
    },

    // Chatbot Configuration
    chatbot: {
        enabled: true,
        apiBase: getBaseUrl(), // Use same host/port as the page
        mockMode: false, // Set to true if backend is not available
    },

    // Application Settings
    app: {
        name: 'Carbon Footprint Tracker',
        version: '1.0.0',
        demoMode: true, // Toggle between demo and real user data
    },

    // Carbon Emission Factors (kg CO2e per unit)
    emissionFactors: {
        transport: {
            car: 0.41, // kg CO2e per mile
            flightShort: 0.158, // kg CO2e per km (short-haul)
            publicTransport: 0.053, // kg CO2e per mile
        },
        energy: {
            electricity: 0.233, // kg CO2e per kWh (US average)
            gas: 5.3, // kg CO2e per therm
        },
        food: {
            meatMeal: 7.19, // kg CO2e per meal
            dairyServing: 2.5, // kg CO2e per serving
        },
        waste: {
            wasteBag: 2.5, // kg CO2e per bag
            recyclingOffset: -1.2, // negative because recycling reduces emissions
        },
        shopping: {
            general: 0.005, // kg CO2e per dollar
            electronics: 50, // kg CO2e per item
        },
    },

    // Conversion Factors
    conversions: {
        kgToTonnes: 0.001,
        tonnesToKg: 1000,
        treesPerTonne: 20, // Average trees needed to offset 1 tonne CO2
    },

    // UI Configuration
    ui: {
        defaultTheme: 'light',
        chartColors: ['#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'],
        animationDuration: 300,
    },
};

// Initialize theme from localStorage
if (typeof document !== 'undefined') {
    const savedTheme = localStorage.getItem('theme') || CONFIG.ui.defaultTheme;
    document.documentElement.setAttribute('data-theme', savedTheme);
}

// Make CONFIG globally available
if (typeof window !== 'undefined') {
    window.CONFIG = CONFIG;
}

// Export for use in other scripts (Node.js/CommonJS)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = CONFIG;
}

// Verify CONFIG is loaded
console.log('CONFIG loaded:', CONFIG);

