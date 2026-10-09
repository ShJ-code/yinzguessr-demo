/*
 * YinzGuessr demo: one page, four screens (start, play, reveal, results).
 *
 * The server owns the game: it picks the Street View panorama, looks up the
 * true location when you guess, and scores it. This file only shows things
 * (Google Street View + Google maps) and sends the player's actions to the
 * JSON API with fetch().
 */
(() => {
  "use strict";

  const config = JSON.parse(document.getElementById("yg-config").textContent);

  const PGH_CENTER = { lat: 40.4406, lng: -79.9959 };
  const PGH_BOUNDS = { north: 40.56, south: 40.30, east: -79.76, west: -80.20 };
  const PANO_TIMEOUT_MS = 20000;

  const $ = (id) => document.getElementById(id);
  const els = {
    startBtn: $("start-btn"),
    roundLabel: $("round-label"),
    scoreLabel: $("score-label"),
    guessBtn: $("guess-btn"),
    loading: $("loading"),
    loadingText: $("loading-text"),
    revealDistance: $("reveal-distance"),
    revealPoints: $("reveal-points"),
    nextBtn: $("next-btn"),
    resultsTotal: $("results-total"),
    resultsMax: $("results-max"),
    resultsRows: $("results-rows"),
    againBtn: $("again-btn"),
    errorBar: $("error-bar"),
    errorText: $("error-text"),
    retryBtn: $("retry-btn"),
  };

  const state = {
    gameId: null,
    round: null,        // {id, number, pano_id}
    totalRounds: config.roundsPerGame,
    totalScore: 0,
    gameOver: false,
    guess: null,        // {lat, lng}
    busy: false,
    retry: null,        // the action the "Try again" button repeats
  };

  // Google classes, filled in by loadGoogle().
  let G = null;
  // Panorama and maps are created the first time they're needed, once their
  // containers are visible.
  let panorama = null;
  let guessMap = null;
  let guessMarker = null;
  let revealMap = null;
  let revealOverlays = [];

  // --- helpers -----------------------------------------------------------------

  function show(screen) {
    document.body.dataset.screen = screen;
  }

  function fmtInt(n) {
    return Number(n).toLocaleString("en-US");
  }

  function fmtDistance(m) {
    if (m < 1000) return `${Math.round(m)} m`;
    if (m < 10000) return `${(m / 1000).toFixed(2)} km`;
    return `${(m / 1000).toFixed(1)} km`;
  }

  function getCookie(name) {
    const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
    return match ? decodeURIComponent(match[1]) : "";
  }

  async function api(method, url, body) {
    const response = await fetch(url, {
      method,
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": getCookie("csrftoken"),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let data = null;
    try {
      data = await response.json();
    } catch (_) {
      /* non-JSON error page */
    }
    if (!response.ok) {
      throw new Error((data && data.error) || `The server answered ${response.status}.`);
    }
    return data;
  }

  function setLoading(text) {
    if (text) {
      els.loadingText.textContent = text;
      els.loading.hidden = false;
    } else {
      els.loading.hidden = true;
    }
  }

  function showError(message, retry) {
    els.errorText.textContent = message;
    state.retry = retry || null;
    els.retryBtn.hidden = !retry;
    els.errorBar.hidden = false;
  }

  function clearError() {
    els.errorBar.hidden = true;
    state.retry = null;
  }

  // Run one server action at a time; double clicks are ignored.
  async function guarded(action) {
    if (state.busy) return;
    state.busy = true;
    clearError();
    try {
      await action();
    } finally {
      state.busy = false;
    }
  }

  // --- loading Google Maps -------------------------------------------------------

  // Google's dynamic library import bootstrap loader, unchanged. Copyright Google
  // LLC, Apache License 2.0. Source:
  // https://developers.google.com/maps/documentation/javascript/load-maps-js-api
  function bootstrapGoogleMaps(options) {
    (g=>{var h,a,k,p="The Google Maps JavaScript API",c="google",l="importLibrary",q="__ib__",m=document,b=window;b=b[c]||(b[c]={});var d=b.maps||(b.maps={}),r=new Set,e=new URLSearchParams,u=()=>h||(h=new Promise(async(f,n)=>{await (a=m.createElement("script"));e.set("libraries",[...r]+"");for(k in g)e.set(k.replace(/[A-Z]/g,t=>"_"+t[0].toLowerCase()),g[k]);e.set("callback",c+".maps."+q);a.src=`https://maps.${c}apis.com/maps/api/js?`+e;d[q]=f;a.onerror=()=>h=n(Error(p+" could not load."));a.nonce=m.querySelector("script[nonce]")?.nonce||"";m.head.append(a)}));d[l]?console.warn(p+" only loads once. Ignoring:",g):d[l]=(f,...n)=>r.add(f)&&u().then(()=>d[l](f,...n))})(options);
  }

  async function loadGoogle() {
    bootstrapGoogleMaps({ key: config.googleMapsApiKey, v: "weekly" });
    const [core, maps, streetView, marker] = await Promise.all([
      google.maps.importLibrary("core"),
      google.maps.importLibrary("maps"),
      google.maps.importLibrary("streetView"),
      google.maps.importLibrary("marker"),
    ]);
    return {
      LatLngBounds: core.LatLngBounds,
      ControlPosition: core.ControlPosition,
      Map: maps.Map,
      Polyline: maps.Polyline,
      StreetViewPanorama: streetView.StreetViewPanorama,
      AdvancedMarkerElement: marker.AdvancedMarkerElement,
    };
  }

  // Google calls this global if it rejects the API key.
  window.gm_authFailure = () => {
    setLoading(null);
    showError("Google rejected the Maps API key. Check GOOGLE_MAPS_API_KEY and the APIs it's allowed to use.");
  };

  // --- street view -----------------------------------------------------------------

  function ensurePanorama() {
    if (panorama) return panorama;
    panorama = new G.StreetViewPanorama($("viewer"), {
      addressControl: false,      // the address would give the answer away
      showRoadLabels: false,      // so would street names on the arrows
      linksControl: true,         // walking arrows
      clickToGo: true,
      fullscreenControl: false,
      enableCloseButton: false,
      motionTracking: false,
      motionTrackingControl: false,
      imageDateControl: false,
      // Keep Google's controls clear of our corner map.
      panControlOptions: { position: G.ControlPosition.LEFT_TOP },
      zoomControlOptions: { position: G.ControlPosition.LEFT_TOP },
    });
    return panorama;
  }

  function loadPanorama(panoId) {
    const pano = ensurePanorama();
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        listener.remove();
        reject(new Error("timeout"));
      }, PANO_TIMEOUT_MS);
      const listener = pano.addListener("status_changed", () => {
        clearTimeout(timer);
        listener.remove();
        const status = pano.getStatus();
        if (status === "OK") resolve();
        else reject(new Error(status));
      });
      pano.setPano(panoId);
      pano.setPov({ heading: Math.random() * 360, pitch: 0 });
      pano.setZoom(0);
      pano.setVisible(true);
    });
  }

  async function showRoundPanorama() {
    setLoading("Loading the street view…");
    try {
      await loadPanorama(state.round.pano_id);
      setLoading(null);
    } catch (err) {
      setLoading(null);
      showError("The street view didn't load from Google.", () => guarded(showRoundPanorama));
    }
  }

  // --- maps ----------------------------------------------------------------------

  function pinElement(kind) {
    const pin = document.createElement("div");
    pin.className = `pin pin-${kind}`;
    return pin;
  }

  function makeMap(element, extra) {
    return new G.Map(element, {
      mapId: config.googleMapsMapId,
      disableDefaultUI: true,   // also removes the Street View pegman (no peeking)
      zoomControl: true,
      clickableIcons: false,
      gestureHandling: "greedy",
      ...extra,
    });
  }

  function ensureGuessMap() {
    if (guessMap) return guessMap;
    guessMap = makeMap($("guess-map"), {
      center: PGH_CENTER,
      zoom: 12,
      draggableCursor: "crosshair",
      restriction: { latLngBounds: PGH_BOUNDS, strictBounds: false },
    });
    guessMap.addListener("click", (event) => placeGuess(event.latLng));
    return guessMap;
  }

  function placeGuess(latLng) {
    state.guess = { lat: latLng.lat(), lng: latLng.lng() };
    if (guessMarker) {
      guessMarker.position = state.guess;
    } else {
      guessMarker = new G.AdvancedMarkerElement({
        map: guessMap,
        position: state.guess,
        content: pinElement("guess"),
        title: "Your guess",
      });
    }
    els.guessBtn.disabled = false;
    els.guessBtn.textContent = "Guess";
  }

  function resetGuessMap() {
    state.guess = null;
    if (guessMarker) {
      guessMarker.map = null;
      guessMarker = null;
    }
    els.guessBtn.disabled = true;
    els.guessBtn.textContent = "Place a pin on the map";
    guessMap.setCenter(PGH_CENTER);
    guessMap.setZoom(12);
  }

  function ensureRevealMap() {
    if (!revealMap) revealMap = makeMap($("reveal-map"), { center: PGH_CENTER, zoom: 12 });
    return revealMap;
  }

  function clearReveal() {
    for (const overlay of revealOverlays) {
      if (typeof overlay.setMap === "function") overlay.setMap(null);
      else overlay.map = null;
    }
    revealOverlays = [];
  }

  // --- game flow -----------------------------------------------------------------

  function updateTopbar() {
    els.roundLabel.textContent = `Round ${state.round.number} of ${state.totalRounds}`;
    els.scoreLabel.textContent = fmtInt(state.totalScore);
  }

  function enterRound(data) {
    state.gameId = data.game_id;
    state.totalRounds = data.total_rounds;
    state.totalScore = data.total_score;
    state.round = data.round;
    state.gameOver = false;
    updateTopbar();
    show("play");
    ensureGuessMap();
    resetGuessMap();
    return showRoundPanorama();
  }

  async function startGame() {
    show("play");
    setLoading("Finding a street in Pittsburgh…");
    try {
      G = G || (await googleReady);
      const data = await api("POST", "/api/games");
      await enterRound(data);
    } catch (err) {
      setLoading(null);
      show("start");
      showError(err.message, () => guarded(startGame));
    }
  }

  async function submitGuess() {
    if (!state.guess) return;
    els.guessBtn.disabled = true;
    try {
      const data = await api("POST", `/api/rounds/${state.round.id}/guess`, state.guess);
      state.totalScore = data.total_score;
      state.gameOver = data.game_over;
      updateTopbar();
      showReveal(data.round);
    } catch (err) {
      els.guessBtn.disabled = false;
      showError(err.message, () => guarded(submitGuess));
    }
  }

  function showReveal(round) {
    show("reveal");
    const map = ensureRevealMap();
    clearReveal();

    const guess = round.guess;
    const answer = round.answer;
    revealOverlays.push(
      new G.Polyline({
        map,
        path: [guess, answer],
        strokeOpacity: 0, // drawn as dashes by the repeating symbol below
        icons: [{
          icon: { path: "M 0,-1 0,1", strokeOpacity: 1, strokeColor: "#262A2F", strokeWeight: 3, scale: 3 },
          offset: "0",
          repeat: "14px",
        }],
      }),
      new G.AdvancedMarkerElement({ map, position: answer, content: pinElement("answer"), title: "Where you were" }),
      new G.AdvancedMarkerElement({ map, position: guess, content: pinElement("guess"), title: "Your guess" }),
    );

    const bounds = new G.LatLngBounds();
    bounds.extend(guess);
    bounds.extend(answer);
    map.fitBounds(bounds, 80);
    google.maps.event.addListenerOnce(map, "idle", () => {
      if (map.getZoom() > 17) map.setZoom(17);
    });

    els.revealDistance.textContent = fmtDistance(round.distance_m);
    els.revealPoints.textContent = `+${fmtInt(round.score)} ${round.score === 1 ? "point" : "points"}`;
    els.nextBtn.textContent = state.gameOver ? "See results" : "Next round";
    els.nextBtn.focus();
  }

  async function nextRound() {
    show("play");
    setLoading("Finding a street in Pittsburgh…");
    try {
      const data = await api("POST", `/api/games/${state.gameId}/rounds`);
      await enterRound(data);
    } catch (err) {
      setLoading(null);
      show("reveal");
      showError(err.message, () => guarded(nextRound));
    }
  }

  async function showResults() {
    try {
      const data = await api("GET", `/api/games/${state.gameId}`);
      els.resultsTotal.textContent = fmtInt(data.total_score);
      els.resultsMax.textContent = fmtInt(data.max_score);
      els.resultsRows.replaceChildren(
        ...data.rounds.map((r) => {
          const tr = document.createElement("tr");
          for (const text of [
            String(r.number),
            r.guessed ? fmtDistance(r.distance_m) : "–",
            r.guessed ? fmtInt(r.score) : "–",
          ]) {
            const td = document.createElement("td");
            td.textContent = text;
            tr.appendChild(td);
          }
          return tr;
        })
      );
      show("results");
      els.againBtn.focus();
    } catch (err) {
      showError(err.message, () => guarded(showResults));
    }
  }

  // --- wire up -------------------------------------------------------------------

  if (!config.googleMapsApiKey) return; // the start page explains the missing key

  const googleReady = loadGoogle();
  googleReady.then(
    (classes) => { G = classes; },
    () => {
      showError("Google Maps didn't load. Check your internet connection and reload the page.");
      if (els.startBtn) els.startBtn.disabled = true;
    }
  );

  if (els.startBtn) els.startBtn.addEventListener("click", () => guarded(startGame));
  els.guessBtn.addEventListener("click", () => guarded(submitGuess));
  els.nextBtn.addEventListener("click", () =>
    guarded(state.gameOver ? showResults : nextRound)
  );
  els.againBtn.addEventListener("click", () => guarded(startGame));
  els.retryBtn.addEventListener("click", () => {
    const retry = state.retry;
    clearError();
    if (retry) retry();
  });
})();
