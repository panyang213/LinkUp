(() => {
  const btn = document.getElementById("google-btn");
  const errEl = document.getElementById("google-error");
  const csrf = document.querySelector('meta[name="csrf-token"]').content;
  firebase.initializeApp(JSON.parse(document.getElementById("firebase-config").textContent));

  const fail = (msg) => { errEl.textContent = msg; errEl.hidden = false; btn.disabled = false; };

  btn.addEventListener("click", async () => {
    errEl.hidden = true; btn.disabled = true;
    try {
      const result = await firebase.auth().signInWithPopup(new firebase.auth.GoogleAuthProvider());
      const idToken = await result.user.getIdToken();
      const res = await fetch("/auth/google/", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
        body: JSON.stringify({ id_token: idToken }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Sign-in failed.");
      location.href = data.redirect;
    } catch (e) {
      if (e.code === "auth/popup-closed-by-user" || e.code === "auth/cancelled-popup-request") { btn.disabled = false; return; }
      fail(e.message || "Sign-in failed. Please try again.");
    }
  });
})();