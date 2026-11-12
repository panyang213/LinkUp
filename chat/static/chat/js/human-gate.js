// One-time "are you human" check shown when the site is first opened.
(() => {
    const gate = document.getElementById("human-gate");
    const msg = document.getElementById("gate-msg");
    const csrf = document.querySelector('meta[name="csrf-token"]').content;
    document.body.classList.add("gate-open");
  
    window.onHumanCheck = async (token) => {
      msg.textContent = "Verifying…";
      try {
        const res = await fetch("/captcha/verify/", {
          method: "POST", credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
          body: JSON.stringify({ token }),
        });
        if (!res.ok) throw new Error("rejected");
        gate.classList.add("done");
        document.body.classList.remove("gate-open");
        setTimeout(() => gate.remove(), 400);
      } catch (e) {
        msg.textContent = "Verification failed. Please try again.";
        if (window.turnstile) turnstile.reset();
      }
    };
    window.onHumanError = () => {
      msg.textContent = "Couldn’t complete the check. Turn off any VPN or blocker, then reload the page.";
    };
  })();