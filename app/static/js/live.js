function startPredictionPolling(cameraId) {
    const labelEl = document.getElementById("prediction-label");
    const confEl = document.getElementById("prediction-confidence");
    const badgeEl = document.getElementById("prediction-badge");

    async function tick() {
        try {
            const res = await fetch(`/detection/stats/${cameraId}`);
            if (!res.ok) {
                throw new Error("HTTP " + res.status);
            }
            const data = await res.json();
            const label = data.label;
            const conf = data.confidence; // 0..1

            labelEl.textContent = label;
            confEl.textContent = (conf * 100).toFixed(1) + "%";

            // Mark as danger only for non-normal labels with decent confidence
            if (label !== "Normal Videos" && conf >= 0.6) {
                badgeEl.className = "badge badge-danger";
            } else {
                badgeEl.className = "badge badge-normal";
            }
        } catch (e) {
            console.error("Prediction polling error:", e);
        } finally {
            setTimeout(tick, 1000); // 1s
        }
    }

    tick();
}
