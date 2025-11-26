let pollingInterval = null;
let currentCameraId = null;
let isRunning = false;

function updatePredictionUI(data) {
    const labelEl = document.getElementById("prediction-label");
    const confEl = document.getElementById("prediction-confidence");
    const badgeEl = document.getElementById("prediction-badge");
    if (!labelEl || !confEl || !badgeEl) return;

    const label = data.label || "Unknown";
    const confidence = typeof data.confidence === "number" ? data.confidence : null;

    labelEl.textContent = label;
    if (confidence !== null) {
        confEl.textContent = (confidence * 100).toFixed(1) + "%";
    } else {
        confEl.textContent = "-";
    }

    const lower = label.toLowerCase();
    const isCrime =
        lower !== "normal videos" &&
        lower !== "normal" &&
        lower !== "unknown" &&
        lower.trim() !== "";

    badgeEl.classList.remove("badge-normal", "badge-danger");
    badgeEl.classList.add(isCrime ? "badge-danger" : "badge-normal");
}

function fetchPrediction(cameraId) {
    fetch(`/detection/stats/${cameraId}`)
        .then((res) => res.json())
        .then((data) => {
            updatePredictionUI(data);
        })
        .catch((err) => {
            console.error("Prediction polling error:", err);
        });
}

function startPredictionPolling(cameraId) {
    stopPredictionPolling();
    isRunning = true;
    currentCameraId = cameraId;

    fetchPrediction(cameraId);
    pollingInterval = setInterval(() => fetchPrediction(cameraId), 2000);
}

function stopPredictionPolling() {
    if (pollingInterval !== null) {
        clearInterval(pollingInterval);
        pollingInterval = null;
    }
}

function initLivePage(cameraId) {
    currentCameraId = cameraId;

    const img = document.querySelector(".live-feed img");
    const btn = document.getElementById("toggle-detection");

    // Initial: running
    if (img) {
        img.src = `/detection/stream/${cameraId}`;
    }
    if (btn) {
        btn.textContent = "Stop detection";
    }
    startPredictionPolling(cameraId);

    if (btn && img) {
        btn.addEventListener("click", () => {
            if (isRunning) {
                // STOP: tell backend to kill the camera stream
                if (currentCameraId != null) {
                    fetch(`/detection/stop/${currentCameraId}`, {
                        method: "POST",
                        headers: {
                            "X-Requested-With": "XMLHttpRequest",
                        },
                    }).catch(() => {});
                }

                stopPredictionPolling();
                img.src = "";
                isRunning = false;
                btn.textContent = "Start detection";

                const labelEl = document.getElementById("prediction-label");
                const confEl = document.getElementById("prediction-confidence");
                const badgeEl = document.getElementById("prediction-badge");

                if (labelEl) labelEl.textContent = "Paused";
                if (confEl) confEl.textContent = "-";
                if (badgeEl) {
                    badgeEl.classList.remove("badge-normal", "badge-danger");
                }
            } else {
                // START: just hit the stream again; backend will create/restart stream
                if (currentCameraId == null) return;

                if (img) {
                    img.src = `/detection/stream/${currentCameraId}`;
                }
                startPredictionPolling(currentCameraId);
                isRunning = true;
                btn.textContent = "Stop detection";
            }
        });
    }
}

// expose for inline script in live.html
window.initLivePage = initLivePage;
