const CACHE_NAME = 'hydrate-cache-v1';
const ASSETS = [
    '/',
    '/static/manifest.json',
    'https://cdn.jsdelivr.net/npm/canvas-confetti@1.6.0/dist/confetti.browser.min.js',
    'https://cdn.jsdelivr.net/npm/chart.js'
];

// 🌟 BACKGROUND TIMER TRACKING VARIABLES:
let lastLogTime = Date.now();

// Install Event: Cache essential assets
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(ASSETS);
        })
    );
});

// Activate Event: Clean up old caches
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) => {
            return Promise.all(
                keys.map((key) => {
                    if (key !== CACHE_NAME) {
                        return caches.delete(key);
                    }
                })
            );
        })
    );
});

// Fetch Event: Network-first, fallback to cache
self.addEventListener('fetch', (event) => {
    // Only intercept local requests or critical CDNs
    if (event.request.method === 'GET') {
        event.respondWith(
            fetch(event.request)
                .then((response) => {
                    // Cache dynamic responses for offline use
                    if (response.status === 200) {
                        const responseClone = response.clone();
                        caches.open(CACHE_NAME).then((cache) => {
                            cache.put(event.request, responseClone);
                        });
                    }
                    return response;
                })
                .catch(() => {
                    return caches.match(event.request);
                })
        );
    }
});

// 🌟 SW PUSH REMINDER LISTENER (From Server):
self.addEventListener('push', function(event) {
    let data = { title: 'Hydrate Daily', body: 'Time to drink some water!' };

    if (event.data) {
        try {
            data = event.data.json();
        } catch (e) {
            data.body = event.data.text();
        }
    }

    const options = {
        body: data.body,
        icon: '/static/icon-192.png',
        badge: '/static/icon-192.png',
        vibrate: [100, 50, 100],
        data: {
            dateOfArrival: Date.now(),
            primaryKey: '1'
        },
        actions: [
            { action: 'drink', title: 'I had a drink!' },
            { action: 'close', title: 'Dismiss' }
        ]
    };

    event.waitUntil(
        self.registration.showNotification(data.title, options)
    );
});

// 🌟 INTER-THREAD COMMUNICATION (Listens for reset signals from the frontend):
self.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'RESET_REMINDER') {
        lastLogTime = Date.now();
        console.log("Background service worker timer reset successfully!");
    }
});

// 🌟 BACKGROUND TIMER & NUDGE MONITOR ENGINE
let lastLogTime = Date.now();
let lastSeenNudgeIds = new Set(); // Keeps track of already notified nudges to prevent duplicates

// Listen for reset signals from the frontend
self.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'RESET_REMINDER') {
        lastLogTime = Date.now();
        console.log("Background service worker timer reset successfully!");
    }
});

// Run a check cycle every 30 seconds
setInterval(() => {
    const now = Date.now();
    const thirtyMinutes = 30 * 60 * 1000;

    // 1. Check Hydration Inactivity
    if (now - lastLogTime >= thirtyMinutes) {
        self.registration.showNotification('Dehydration Warning! 💧', {
            body: "You haven't logged a drink in over 30 minutes! Take a sip to protect your streak.",
            icon: '/static/icon-192.png',
            badge: '/static/icon-192.png',
            vibrate: [200, 100, 200],
            requireInteraction: true,
            data: { primaryKey: 'dehydration-warning' }
        });
        lastLogTime = now; // Shift baseline forward
    }

    // 2. 🌟 NEW: Poll for New Friend Nudges
    fetch('/api/nudge/check/')
        .then(res => res.json())
        .then(data => {
            if (data.status === 'success' && data.unread_count > 0) {
                data.nudges.forEach(nudge => {
                    // Only notify if we haven't popped up a notification for this specific nudge ID yet
                    if (!lastSeenNudgeIds.has(nudge.id)) {
                        lastSeenNudgeIds.add(nudge.id);

                        self.registration.showNotification('Social Nudge! 💧', {
                            body: `${nudge.sender} is nudging you to stay hydrated!`,
                            icon: '/static/icon-192.png',
                            badge: '/static/icon-192.png',
                            vibrate: [300, 100, 300],
                            requireInteraction: true,
                            data: { primaryKey: `nudge-${nudge.id}` },
                            actions: [
                                { action: 'drink', title: 'Log a Drink!' },
                                { action: 'close', title: 'Dismiss' }
                            ]
                        });
                    }
                });
            }
        })
        .catch(err => console.log("Background nudge sync offline or deferred."));

}, 30000); // Evaluates status cleanly every 30 seconds

// Handle clicking on the notification actions
self.addEventListener('notificationclick', function(event) {
    event.notification.close();

    if (event.action === 'drink') {
        // Automatically open the app to log the drink!
        event.waitUntil(
            clients.openWindow('/')
        );
    }
});