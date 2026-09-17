const CACHE_VERSION = "v6-light";
const STATIC_CACHE = `gym-static-${CACHE_VERSION}`;
const PAGE_CACHE_PREFIX = `gym-pages-${CACHE_VERSION}-user-`;
const CHART_JS_URL =
  "https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js";

const DB_NAME = "gym-app-db";
const DB_VERSION = 2;
const REQUEST_STORE = "offlineRequests";
const META_STORE = "meta";
const USER_CONTEXT_KEY = "currentUserId";

const STATIC_FILES = [
  "/static/manifest.json",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png"
];

const AUTH_PATHS = [
  "/login",
  "/register",
  "/forgot-password"
];

const QUEUEABLE_PATHS = [
  /^\/zadat\/?$/,
  /^\/edit\/\d+\/?$/,
  /^\/delete\/\d+\/?$/,
  /^\/favorite-exercise\/?$/,
  /^\/custom-exercise\/add\/?$/,
  /^\/custom-exercise\/delete\/\d+\/?$/
];

let syncInProgress = null;
let cachePreparationInProgress = null;

self.addEventListener("install", event => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then(cache =>
      Promise.allSettled(
        STATIC_FILES.map(url => cache.add(url))
      )
    )
  );
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const cacheNames = await caches.keys();
    await Promise.all(
      cacheNames
        .filter(name =>
          (name.startsWith("gym-static-") && name !== STATIC_CACHE) ||
          (name.startsWith("gym-pages-") &&
            !name.startsWith(`gym-pages-${CACHE_VERSION}-`)) ||
          name === "gym-app-v1"
        )
        .map(name => caches.delete(name))
    );
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", event => {
  const request = event.request;
  const url = new URL(request.url);

  if (!["http:", "https:"].includes(url.protocol)) {
    return;
  }

  if (request.method !== "GET") {
    if (
      url.origin === self.location.origin &&
      isQueueablePath(url.pathname)
    ) {
      const responsePromise = handleMutationRequest(request);
      event.respondWith(responsePromise);
    } else if (
      url.origin === self.location.origin &&
      isAuthPath(url.pathname)
    ) {
      event.respondWith(handleAuthMutation(request));
    }
    return;
  }

  if (
    url.origin === self.location.origin &&
    url.pathname === "/logout"
  ) {
    event.respondWith(handleLogout(request));
    return;
  }

  if (
    url.origin === self.location.origin &&
    url.pathname === "/api/offline-manifest"
  ) {
    event.respondWith(fetch(request));
    return;
  }

  if (
    (url.origin === self.location.origin &&
      url.pathname.startsWith("/static/")) ||
    request.url === CHART_JS_URL
  ) {
    event.respondWith(staleWhileRevalidate(request));
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(networkFirstPage(request));
    return;
  }

  event.respondWith(networkFirstResource(request));
});

self.addEventListener("message", event => {
  const message = event.data || {};

  if (message.type === "SET_USER_CONTEXT") {
    event.waitUntil((async () => {
      await setCurrentUserId(message.userId);
      await syncOfflineData();
      if (message.prepareOffline !== false) {
        await prepareOfflineCache(false);
      }
    })());
  }

  if (message.type === "CLEAR_USER_CONTEXT") {
    event.waitUntil(clearCurrentUserContext());
  }

  if (message.type === "SYNC_OFFLINE_DATA") {
    event.waitUntil((async () => {
      await syncOfflineData();
      await prepareOfflineCache(false);
    })());
  }

  if (message.type === "REFRESH_OFFLINE_CACHE") {
    event.waitUntil(prepareOfflineCache(true));
  }
});

self.addEventListener("sync", event => {
  if (event.tag === "sync-gym-offline-data") {
    event.waitUntil(syncOfflineData());
  }
});

function isQueueablePath(pathname) {
  return QUEUEABLE_PATHS.some(pattern => pattern.test(pathname));
}

function isAuthPath(pathname) {
  return AUTH_PATHS.some(
    path => pathname === path ||
      pathname.startsWith("/reset-password/")
  );
}

function pageCacheName(userId) {
  return `${PAGE_CACHE_PREFIX}${String(userId)}`;
}

function pendingPageCacheName(userId) {
  return `${pageCacheName(userId)}-pending`;
}

function offlineVersionKey(userId) {
  return `offlineCacheVersion:${CACHE_VERSION}:${String(userId)}`;
}

function canCache(response) {
  return Boolean(
    response &&
    (
      (
        response.ok &&
        (response.type === "basic" || response.type === "cors")
      ) ||
      response.type === "opaque"
    )
  );
}

function redirectedToLogin(response) {
  if (!response || !response.redirected) {
    return false;
  }
  return new URL(response.url).pathname === "/login";
}

async function handleLogout(request) {
  try {
    const response = await fetch(request);
    if (response.ok || response.redirected) {
      await clearCurrentUserContext();
    }
    return response;
  } catch (error) {
    return offlineResponse(
      request,
      false,
      "Odhlášení vyžaduje připojení k internetu.",
      503
    );
  }
}

async function handleAuthMutation(request) {
  try {
    const response = await fetch(request);
    if (response.ok || response.redirected) {
      await clearCurrentUserContext();
    }
    return response;
  } catch (error) {
    return offlineResponse(
      request,
      false,
      "Přihlášení, registrace a změna hesla vyžadují internet.",
      503
    );
  }
}

async function staleWhileRevalidate(request) {
  const cached = await caches.match(request);
  const networkPromise = fetch(request)
    .then(async response => {
      if (canCache(response)) {
        const cache = await caches.open(STATIC_CACHE);
        await cache.put(request, response.clone());
      }
      return response;
    })
    .catch(() => null);

  return cached || networkPromise ||
    offlineResponse(
      request,
      false,
      "Soubor není dostupný offline.",
      503
    );
}

async function networkFirstPage(request) {
  const requestUrl = new URL(request.url);

  try {
    const response = await fetch(request);
    const userId = await getCurrentUserId();

    if (
      userId &&
      !isAuthPath(requestUrl.pathname) &&
      !redirectedToLogin(response) &&
      canCache(response)
    ) {
      const cache = await caches.open(pageCacheName(userId));
      await cache.put(request, response.clone());
    }

    triggerSync();
    return response;
  } catch (error) {
    const userId = await getCurrentUserId();

    if (userId && !isAuthPath(requestUrl.pathname)) {
      const cache = await caches.open(pageCacheName(userId));
      const cached =
        await cache.match(request) ||
        await cache.match(request, { ignoreSearch: true });

      if (cached) {
        return cached;
      }
    }

    return offlinePage(
      "Tahle stránka se ještě nestihla uložit pro offline použití.",
      503
    );
  }
}

async function networkFirstResource(request) {
  try {
    const response = await fetch(request);
    if (canCache(response)) {
      const cache = await caches.open(STATIC_CACHE);
      await cache.put(request, response.clone());
    }
    triggerSync();
    return response;
  } catch (error) {
    return (await caches.match(request)) ||
      offlineResponse(
        request,
        false,
        "Data nejsou dostupná offline.",
        503
      );
  }
}

async function handleMutationRequest(request) {
  const pathname = new URL(request.url).pathname;

  try {
    const response = await fetch(request.clone());

    if (response.ok || response.redirected) {
      await cacheMutationDestination(response);
    }

    return response;
  } catch (error) {
    const userId = await getCurrentUserId();
    if (!userId) {
      return offlineResponse(
        request,
        false,
        "Nejdřív aplikaci otevři online a přihlas se.",
        503
      );
    }

    await queueRequest(request, userId);
    await requestBackgroundSync();

    const isDelete = /^\/delete\/\d+\/?$/.test(pathname);
    const isEdit = /^\/edit\/\d+\/?$/.test(pathname);
    const action = isDelete ? "delete" : (isEdit ? "edit" : "save");

    await notifyClients({
      type: "OFFLINE_REQUEST_QUEUED",
      action
    });

    const message = isDelete
      ? "Smazání je uložené a provede se po připojení."
      : isEdit
        ? "Úprava je uložená a odešle se po připojení."
        : "Záznam je uložený v telefonu a odešle se po připojení.";

    // For a form submission used as page navigation, keep the user inside
    // the app by returning the cached page they came from. The actual POST
    // remains queued in IndexedDB and is sent automatically when online.
    if (request.mode === "navigate" && userId) {
      const cache = await caches.open(pageCacheName(userId));
      const referrer = request.referrer && request.referrer !== "about:client"
        ? new URL(request.referrer, self.location.origin)
        : null;

      if (referrer && referrer.origin === self.location.origin) {
        const cachedReferrer =
          await cache.match(new Request(referrer.href, { method: "GET" })) ||
          await cache.match(new Request(referrer.pathname + referrer.search, { method: "GET" }));

        if (cachedReferrer) {
          return addOfflineNotice(cachedReferrer, message);
        }
      }

      const historyResponse = await cache.match(
        new Request("/historie", { method: "GET" })
      );
      if (historyResponse) {
        return addOfflineNotice(historyResponse, message);
      }
    }

    return offlineResponse(request, true, message, 202);
  }
}

async function cacheMutationDestination(response) {
  const userId = await getCurrentUserId();
  if (
    !userId ||
    redirectedToLogin(response) ||
    !canCache(response) ||
    response.type !== "basic"
  ) {
    return;
  }

  const responseUrl = new URL(response.url);
  if (isAuthPath(responseUrl.pathname)) {
    return;
  }

  const cache = await caches.open(pageCacheName(userId));
  await cache.put(
    new Request(response.url, { method: "GET" }),
    response.clone()
  );
}

async function addOfflineNotice(response, message) {
  try {
    const html = await response.text();
    const banner = `<div style="position:sticky;top:0;z-index:9999;margin:0;padding:12px 16px;background:#dcfce7;color:#166534;border-bottom:1px solid #86efac;font:600 14px Arial,sans-serif;text-align:center;">${escapeHtml(message)}</div>`;
    const updated = html.replace(/<body([^>]*)>/i, `<body$1>${banner}`);
    return new Response(updated, {
      status: response.status,
      statusText: response.statusText,
      headers: response.headers
    });
  } catch (error) {
    return response;
  }
}

function offlineResponse(request, queued, message, status) {
  const headers = {
    "Content-Type": request.mode === "navigate"
      ? "text/html; charset=utf-8"
      : "application/json; charset=utf-8"
  };

  if (queued) {
    headers["X-Gym-Queued"] = "1";
  }

  if (request.mode === "navigate") {
    return offlinePage(message, status, queued, headers);
  }

  return new Response(
    JSON.stringify({ offline: true, queued, message }),
    { status, headers }
  );
}

function offlinePage(
  message,
  status = 503,
  queued = false,
  extraHeaders = {}
) {
  const title = queued ? "Uloženo offline" : "Jsi offline";
  const safeMessage = escapeHtml(message);

  return new Response(`<!doctype html>
<html lang="cs">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${title}</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f4f4f4; color: #222; }
    main { width: min(88%, 480px); box-sizing: border-box; padding: 28px; text-align: center; background: white; border-radius: 16px; box-shadow: 0 8px 28px rgba(0,0,0,.10); }
    h1 { margin-top: 0; }
    button { border: 0; border-radius: 10px; padding: 14px 20px; background: #4CAF50; color: white; font-size: 1rem; font-weight: 700; cursor: pointer; }
  </style>
</head>
<body>
  <main>
    <h1>${title}</h1>
    <p>${safeMessage}</p>
    <button type="button" onclick="history.back()">Zpět do aplikace</button>
  </main>
</body>
</html>`, {
    status,
    headers: {
      "Content-Type": "text/html; charset=utf-8",
      ...extraHeaders
    }
  });
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function queueRequest(request, userId) {
  const body = await request.clone().arrayBuffer();
  const headers = [];

  for (const [name, value] of request.headers.entries()) {
    const lowerName = name.toLowerCase();
    if (
      [
        "content-type",
        "accept",
        "x-requested-with",
        "x-csrf-token"
      ].includes(lowerName)
    ) {
      headers.push([name, value]);
    }
  }

  const db = await openDB();
  await runTransaction(
    db,
    REQUEST_STORE,
    "readwrite",
    store => {
      store.add({
        url: request.url,
        method: request.method,
        headers,
        body,
        userId: String(userId),
        createdAt: Date.now()
      });
    }
  );
}

async function syncOfflineData() {
  if (syncInProgress) {
    return syncInProgress;
  }

  syncInProgress = performSync().finally(() => {
    syncInProgress = null;
  });
  return syncInProgress;
}

async function performSync() {
  const userId = await getCurrentUserId();
  if (!userId) {
    return;
  }

  const queued = await getQueuedRequests();
  const matchingRequests = queued
    .filter(item => item.userId === String(userId))
    .sort((a, b) => a.id - b.id);

  let syncedCount = 0;

  for (const item of matchingRequests) {
    try {
      const response = await fetch(item.url, {
        method: item.method,
        headers: new Headers(item.headers),
        body: item.body,
        credentials: "same-origin",
        redirect: "follow"
      });

      const path = new URL(item.url).pathname;
      const alreadyDeleted =
        /^\/delete\/\d+\/?$/.test(path) &&
        response.status === 404;

      if (redirectedToLogin(response)) {
        break;
      }

      if (!response.ok && !alreadyDeleted) {
        await notifyClients({
          type: "OFFLINE_SYNC_ERROR",
          status: response.status
        });
        break;
      }

      await deleteQueuedRequest(item.id);
      syncedCount += 1;
    } catch (error) {
      break;
    }
  }

  if (syncedCount > 0) {
    await notifyClients({
      type: "OFFLINE_SYNC_COMPLETE",
      count: syncedCount
    });
    await prepareOfflineCache(true);
  }
}

function triggerSync() {
  syncOfflineData().catch(() => undefined);
}

async function requestBackgroundSync() {
  if (self.registration.sync) {
    try {
      await self.registration.sync.register(
        "sync-gym-offline-data"
      );
    } catch (error) {
      // Safari Background Sync nepodporuje; synchronizace proběhne
      // při dalším otevření aplikace nebo návratu online.
    }
  }
}

async function prepareOfflineCache(force = false) {
  if (cachePreparationInProgress) {
    return cachePreparationInProgress;
  }

  cachePreparationInProgress = performCachePreparation(force)
    .finally(() => {
      cachePreparationInProgress = null;
    });

  return cachePreparationInProgress;
}

async function performCachePreparation(force) {
  const userId = await getCurrentUserId();
  if (!userId) {
    return;
  }

  let manifestResponse;
  try {
    manifestResponse = await fetch("/api/offline-manifest", {
      credentials: "same-origin",
      cache: "no-store"
    });
  } catch (error) {
    return;
  }

  if (
    !manifestResponse.ok ||
    redirectedToLogin(manifestResponse)
  ) {
    return;
  }

  const manifest = await manifestResponse.json();
  const versionKey = offlineVersionKey(userId);
  const savedVersion = await getMeta(versionKey);
  const finalCacheName = pageCacheName(userId);
  const finalCacheExists = await caches.has(finalCacheName);

  if (
    !force &&
    finalCacheExists &&
    savedVersion === manifest.version
  ) {
    await notifyClients({
      type: "OFFLINE_CACHE_READY",
      count: 0,
      unchanged: true
    });
    return;
  }

  await notifyClients({
    type: "OFFLINE_CACHE_START",
    count: manifest.urls.length
  });

  const pendingCacheName = pendingPageCacheName(userId);
  await caches.delete(pendingCacheName);
  const pendingCache = await caches.open(pendingCacheName);

  let cachedCount = 0;
  let failedCount = 0;
  const urls = Array.from(new Set(manifest.urls || []));

  for (let index = 0; index < urls.length; index += 6) {
    const batch = urls.slice(index, index + 6);
    const results = await Promise.all(
      batch.map(async relativeUrl => {
        const absoluteUrl = new URL(
          relativeUrl,
          self.location.origin
        ).href;
        const pageRequest = new Request(absoluteUrl, {
          method: "GET",
          credentials: "same-origin"
        });

        try {
          const response = await fetch(pageRequest);
          if (
            !canCache(response) ||
            redirectedToLogin(response)
          ) {
            return false;
          }
          await pendingCache.put(
            pageRequest,
            response.clone()
          );
          return true;
        } catch (error) {
          return false;
        }
      })
    );

    cachedCount += results.filter(Boolean).length;
    failedCount += results.filter(result => !result).length;
  }

  const preparedRequests = await pendingCache.keys();

  if (failedCount === 0) {
    await caches.delete(finalCacheName);
  }

  const destinationCache = await caches.open(finalCacheName);
  for (const request of preparedRequests) {
    const response = await pendingCache.match(request);
    if (response) {
      await destinationCache.put(request, response);
    }
  }

  await caches.delete(pendingCacheName);

  if (failedCount === 0) {
    await setMeta(versionKey, manifest.version);
  }

  await notifyClients({
    type: failedCount === 0
      ? "OFFLINE_CACHE_READY"
      : "OFFLINE_CACHE_PARTIAL",
    count: cachedCount,
    failed: failedCount
  });
}

async function ensureStaticResource(url) {
  const existing = await caches.match(url);
  if (existing) {
    return true;
  }

  try {
    const response = await fetch(url);
    if (!canCache(response)) {
      return false;
    }
    const cache = await caches.open(STATIC_CACHE);
    await cache.put(url, response.clone());
    return true;
  } catch (error) {
    return false;
  }
}

async function notifyClients(message) {
  const clients = await self.clients.matchAll({
    type: "window",
    includeUncontrolled: true
  });
  clients.forEach(client => client.postMessage(message));
}

function openDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);

    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
    request.onupgradeneeded = event => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains(REQUEST_STORE)) {
        db.createObjectStore(REQUEST_STORE, {
          keyPath: "id",
          autoIncrement: true
        });
      }
      if (!db.objectStoreNames.contains(META_STORE)) {
        db.createObjectStore(META_STORE, {
          keyPath: "key"
        });
      }
    };
  });
}

function runTransaction(db, storeName, mode, action) {
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(storeName, mode);
    const store = transaction.objectStore(storeName);

    action(store);

    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error);
  });
}

async function getQueuedRequests() {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(
      REQUEST_STORE,
      "readonly"
    );
    const request = transaction
      .objectStore(REQUEST_STORE)
      .getAll();
    request.onsuccess = () => resolve(request.result || []);
    request.onerror = () => reject(request.error);
  });
}

async function deleteQueuedRequest(id) {
  const db = await openDB();
  await runTransaction(
    db,
    REQUEST_STORE,
    "readwrite",
    store => store.delete(id)
  );
}

async function setCurrentUserId(userId) {
  if (
    userId === null ||
    userId === undefined ||
    userId === ""
  ) {
    return;
  }

  await setMeta(USER_CONTEXT_KEY, String(userId));
}

async function getCurrentUserId() {
  return getMeta(USER_CONTEXT_KEY);
}

async function getMeta(key) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction(
      META_STORE,
      "readonly"
    );
    const request = transaction
      .objectStore(META_STORE)
      .get(key);
    request.onsuccess = () => resolve(
      request.result ? request.result.value : null
    );
    request.onerror = () => reject(request.error);
  });
}

async function setMeta(key, value) {
  const db = await openDB();
  await runTransaction(
    db,
    META_STORE,
    "readwrite",
    store => store.put({ key, value })
  );
}

async function deleteMeta(key) {
  const db = await openDB();
  await runTransaction(
    db,
    META_STORE,
    "readwrite",
    store => store.delete(key)
  );
}

async function clearCurrentUserContext() {
  const userId = await getCurrentUserId();
  await deleteMeta(USER_CONTEXT_KEY);

  if (userId) {
    await caches.delete(pageCacheName(userId));
    await caches.delete(pendingPageCacheName(userId));
    await deleteMeta(offlineVersionKey(userId));
  }
}
