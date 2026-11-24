// LinkUp voice & video calls (WebRTC).
// Audio and video travel directly between the two browsers; the server only relays small signaling
// messages over the existing chat WebSocket, and only between the two people who are matched.
(() => {
    const chat = window.LinkUpChat;
    const $ = (s) => document.querySelector(s);
    if (!chat || !$("#voice-call-btn")) return;
  
    const cfg = JSON.parse($("#client-config").textContent);
    const RTC_CONFIG = { iceServers: (cfg.ice_servers && cfg.ice_servers.length) ? cfg.ice_servers : [{ urls: "stun:stun.l.google.com:19302" }] };
    const RING_LIMIT_MS = 32000;      // a little longer than the server's own 30 s ring timeout
    const CONNECT_LIMIT_MS = 25000;   // give up if the two devices can't connect in this time
    const RECONNECT_GRACE_MS = 8000;  // a brief network blip is tolerated before the call is dropped
  
    const el = {
      voice: $("#voice-call-btn"), video: $("#video-call-btn"),
      area: $("#call-area"), videoWrap: $("#call-video-wrap"),
      remoteVideo: $("#remote-video"), localVideo: $("#local-video"), remoteAudio: $("#remote-audio"),
      camOff: $("#remote-cam-off"), title: $("#call-title"), status: $("#call-status"),
      mic: $("#call-mic-btn"), cam: $("#call-cam-btn"), end: $("#call-end-btn"),
      incoming: $("#call-incoming"), inTitle: $("#incoming-title"), inSub: $("#incoming-sub"), inIcon: $("#incoming-icon"),
      accept: $("#incoming-accept"), decline: $("#incoming-decline"),
    };
  
    let matched = false, partnerName = "your match";
    let call = null;   // { id, kind, role, phase, stream, pc, remote, pendingIce, remoteSet, mic, cam, peerMic, peerCam, ... }
  
    const label = (kind) => (kind === "video" ? "Video call" : "Voice call");
    const fmt = (ms) => { const s = Math.floor(ms / 1000); return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; };
    const stopStream = (s) => { if (s) s.getTracks().forEach((t) => { try { t.stop(); } catch (e) { /* ignore */ } }); };
  
    // ---------- small ring tone for incoming calls ----------
    let audioCtx = null, ringTimer = null;
    document.addEventListener("pointerdown", () => {
      try { audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)(); audioCtx.resume(); } catch (e) { /* sound is optional */ }
    });
    function ring(on) {
      clearInterval(ringTimer); ringTimer = null;
      if (!on) { if (navigator.vibrate) navigator.vibrate(0); return; }
      const beep = () => {
        if (navigator.vibrate) navigator.vibrate([300, 150, 300]);
        if (!audioCtx) return;
        try {
          const o = audioCtx.createOscillator(), g = audioCtx.createGain();
          o.frequency.value = 480; g.gain.value = 0.06; o.connect(g); g.connect(audioCtx.destination);
          o.start(); o.stop(audioCtx.currentTime + 0.35);
        } catch (e) { /* ignore */ }
      };
      beep(); ringTimer = setInterval(beep, 2000);
    }
  
    // ---------- microphone / camera ----------
    async function getMedia(kind) {
      if (!window.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw Object.assign(new Error("insecure"), { name: "InsecureContext" });
      }
      const audio = { echoCancellation: true, noiseSuppression: true, autoGainControl: true };
      const video = kind === "video" ? { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } } : false;
      return navigator.mediaDevices.getUserMedia({ audio, video });
    }
    function mediaErrorText(err, kind) {
      const what = kind === "video" ? "camera and microphone" : "microphone";
      switch (err && err.name) {
        case "InsecureContext": return "Calls need a secure connection (https). Open the site over https, or use http://localhost on the same computer.";
        case "NotAllowedError": case "SecurityError": return `Access to your ${what} was blocked. Allow it from the lock icon next to the address bar, then try again.`;
        case "NotFoundError": case "OverconstrainedError": return `No ${what} was found on this device.`;
        case "NotReadableError": case "AbortError": return `Your ${what} is being used by another app. Close that app and try again.`;
        default: return `Couldn't start your ${what}. Please try again.`;
      }
    }
  
    // ---------- screen ----------
    function updateButtons() {
      const ok = matched && !call && chat.connected();
      el.voice.disabled = el.video.disabled = !ok;
    }
    function showArea(kind, status) {
      el.area.hidden = false;
      el.videoWrap.hidden = kind !== "video"; el.cam.hidden = kind !== "video"; el.camOff.hidden = true;
      el.title.textContent = `${label(kind)} with ${partnerName}`; el.status.textContent = status;
      setPressed(el.mic, false, "Mute microphone", "Unmute microphone", "bi-mic-fill", "bi-mic-mute-fill");
      setPressed(el.cam, false, "Turn camera off", "Turn camera on", "bi-camera-video-fill", "bi-camera-video-off-fill");
    }
    function setPressed(btn, pressed, offLabel, onLabel, offIcon, onIcon) {
      btn.setAttribute("aria-pressed", String(pressed));
      btn.setAttribute("aria-label", pressed ? onLabel : offLabel);
      btn.title = btn.getAttribute("aria-label");
      const i = btn.querySelector("i"); i.className = `bi ${pressed ? onIcon : offIcon}`;
    }
    function setStatus(text) { if (call) el.status.textContent = text; }
    function showIncoming(kind) {
      el.inTitle.textContent = `${partnerName} is calling`; el.inSub.textContent = label(kind);
      el.inIcon.className = `bi ${kind === "video" ? "bi-camera-video-fill" : "bi-telephone-inbound-fill"}`;
      el.incoming.hidden = false; el.accept.focus({ preventScroll: true });
    }
    const hideIncoming = () => { el.incoming.hidden = true; };
  
    function tickStatus() {
      if (!call || call.phase !== "active") return;
      const extra = [call.peerMic === false ? "muted" : "", call.kind === "video" && call.peerCam === false ? "camera off" : ""].filter(Boolean).join(", ");
      el.status.textContent = `Connected · ${fmt(Date.now() - call.startedAt)}${extra ? ` · ${partnerName} (${extra})` : ""}`;
    }
  
    // ---------- ending / cleaning up ----------
    function resetCall() {
      const c = call; call = null;
      if (c) {
        ["ringTimer", "connectTimer", "failTimer", "tick"].forEach((k) => { clearTimeout(c[k]); clearInterval(c[k]); });
        if (c.pc) { c.pc.ontrack = c.pc.onicecandidate = c.pc.onconnectionstatechange = null; try { c.pc.close(); } catch (e) { /* ignore */ } }
        stopStream(c.stream);
      }
      ring(false); hideIncoming();
      el.remoteVideo.srcObject = el.remoteAudio.srcObject = el.localVideo.srcObject = null;
      el.area.hidden = true; el.camOff.hidden = true;
      updateButtons();
      return c;
    }
    function finish(text) {
      const c = resetCall();
      const lasted = c && c.startedAt ? ` · ${fmt(Date.now() - c.startedAt)}` : "";
      if (text) chat.notice(text + lasted);
    }
    function failCall(reason) {
      if (!call) return;
      const id = call.id;
      if (id) chat.send({ type: "call_end", id, reason: "failed" });
      finish(reason || "The call was disconnected because of a connection problem. On some school, office or mobile networks a relay (TURN) server is needed.");
    }
    function hangUp() {
      if (!call) return;
      const c = call;
      if (c.phase === "incoming") { chat.send({ type: "call_decline", id: c.id, reason: "declined" }); finish(""); return; }
      if (c.role === "caller" && (c.phase === "ringing" || c.phase === "requesting")) {
        if (c.id) chat.send({ type: "call_cancel", id: c.id });
        finish(""); return;
      }
      if (c.id) chat.send({ type: "call_end", id: c.id, reason: "hangup" });
      finish(`${label(c.kind)} ended`);
    }
  
    // ---------- starting a call (caller) ----------
    async function startCall(kind) {
      if (call || !matched || !chat.connected()) return;
      const mine = (call = { kind, role: "caller", phase: "requesting", id: null, stream: null, pc: null, pendingIce: [], remoteSet: false, mic: true, cam: true });
      updateButtons(); showArea(kind, "Allow your microphone" + (kind === "video" ? " and camera" : "") + "…");
      let stream;
      try { stream = await getMedia(kind); }
      catch (err) { if (call === mine) { resetCall(); chat.notice(mediaErrorText(err, kind)); } return; }
      if (call !== mine) { stopStream(stream); return; }      // the chat ended while the permission prompt was open
      mine.stream = stream; el.localVideo.srcObject = stream;
      setStatus("Calling…");
      chat.send({ type: "call_request", kind });
    }
  
    // ---------- answering a call (callee) ----------
    async function acceptCall() {
      const mine = call;
      if (!mine || mine.phase !== "incoming") return;
      ring(false); hideIncoming(); mine.phase = "connecting";
      showArea(mine.kind, "Allow your microphone" + (mine.kind === "video" ? " and camera" : "") + "…");
      let stream;
      try { stream = await getMedia(mine.kind); }
      catch (err) {
        if (call === mine) { chat.send({ type: "call_decline", id: mine.id, reason: "media" }); resetCall(); chat.notice(mediaErrorText(err, mine.kind)); }
        return;
      }
      if (call !== mine) { stopStream(stream); return; }
      mine.stream = stream; el.localVideo.srcObject = stream;
      setStatus("Connecting…");
      mine.connectTimer = setTimeout(() => failCall("The call couldn't connect. On some school, office or mobile networks a relay (TURN) server is needed."), CONNECT_LIMIT_MS);
      chat.send({ type: "call_accept", id: mine.id });
    }
    function declineCall() {
      const c = call;
      if (!c || c.phase !== "incoming") return;
      chat.send({ type: "call_decline", id: c.id, reason: "declined" });
      resetCall();
    }
  
    // ---------- the WebRTC connection ----------
    function newPeer() {
      const c = call, pc = new RTCPeerConnection(RTC_CONFIG);
      c.pc = pc;
      c.stream.getTracks().forEach((t) => pc.addTrack(t, c.stream));
      pc.ontrack = (e) => {
        if (call !== c) return;
        c.remote = c.remote || new MediaStream();
        if (!c.remote.getTracks().includes(e.track)) c.remote.addTrack(e.track);
        el.remoteAudio.srcObject = c.remote;
        if (c.kind === "video") el.remoteVideo.srcObject = c.remote;
        [el.remoteAudio, el.remoteVideo].forEach(playOrAskForTap);
      };
      pc.onicecandidate = (e) => { if (e.candidate && call === c && c.id) chat.send({ type: "call_ice", id: c.id, candidate: e.candidate.toJSON() }); };
      pc.onconnectionstatechange = () => {
        if (call !== c) return;
        const s = pc.connectionState;
        if (s === "connected") {
          clearTimeout(c.failTimer); clearTimeout(c.connectTimer);
          if (c.phase !== "active") {
            c.phase = "active"; c.startedAt = Date.now(); c.tick = setInterval(tickStatus, 1000);
            chat.send({ type: "call_media", id: c.id, mic: c.mic, cam: c.cam });
          }
          tickStatus();
        } else if (s === "disconnected") {
          setStatus("Connection unstable…");
          clearTimeout(c.failTimer); c.failTimer = setTimeout(() => { if (call === c && pc.connectionState !== "connected") failCall(); }, RECONNECT_GRACE_MS);
        } else if (s === "failed") { failCall(); }
      };
      return pc;
    }
    // Browsers (especially iPhones) may block sound until the person taps; ask for a tap if that happens.
    function playOrAskForTap(media) {
      const p = media.play && media.play();
      if (p && p.catch) p.catch(() => {
        setStatus("Tap anywhere on the page to hear the call");
        document.addEventListener("pointerdown", () => media.play().catch(() => {}), { once: true });
      });
    }
    async function flushIce() {
      const c = call; if (!c || !c.pc) return;
      const list = c.pendingIce.splice(0);
      for (const cand of list) { try { await c.pc.addIceCandidate(cand); } catch (e) { /* a stale candidate is harmless */ } }
    }
    async function makeOffer() {
      const c = call, pc = newPeer();
      c.connectTimer = setTimeout(() => failCall("The call couldn't connect. On some school, office or mobile networks a relay (TURN) server is needed."), CONNECT_LIMIT_MS);
      const offer = await pc.createOffer(); await pc.setLocalDescription(offer);
      if (call === c) chat.send({ type: "call_offer", id: c.id, sdp: { type: "offer", sdp: pc.localDescription.sdp } });
    }
    async function answerOffer(sdp) {
      const c = call, pc = c.pc || newPeer();
      await pc.setRemoteDescription({ type: "offer", sdp }); c.remoteSet = true; await flushIce();
      const answer = await pc.createAnswer(); await pc.setLocalDescription(answer);
      if (call === c) chat.send({ type: "call_answer", id: c.id, sdp: { type: "answer", sdp: pc.localDescription.sdp } });
    }
  
    // ---------- messages from the server / the other person ----------
    const declineText = { declined: () => `${partnerName} declined the call.`, busy: () => `${partnerName} is already in a call.`, media: () => `${partnerName} couldn't turn on their microphone or camera.` };
    async function onEvent(m) {
      const t = m.type;
      // --- who we're connected to ---
      if (t === "matched") { matched = true; partnerName = m.partner.nickname; updateButtons(); return; }
      if (t === "searching" || t === "ended" || t === "blocked" || t === "reported") { matched = false; if (call) finish(""); updateButtons(); return; }
      if (t === "partner_left") { const had = !!call; matched = false; if (had) finish(`The call ended because ${partnerName} left.`); updateButtons(); return; }
      if (t === "socket_closed") { matched = false; if (call) finish("The call ended because the connection to the server was lost."); updateButtons(); return; }
      if (!t.startsWith("call_")) return;
  
      // --- call messages ---
      if (t === "call_error") { if (call && call.phase === "requesting") resetCall(); chat.notice(m.message); return; }
      if (t === "call_incoming") {
        if (call) return;
        call = { kind: m.kind, role: "callee", phase: "incoming", id: m.id, stream: null, pc: null, pendingIce: [], remoteSet: false, mic: true, cam: true };
        updateButtons(); showIncoming(m.kind); ring(true);
        call.ringTimer = setTimeout(() => { if (call && call.phase === "incoming") { resetCall(); chat.notice("Missed call"); } }, RING_LIMIT_MS);
        return;
      }
      if (!call || (m.id && call.id && m.id !== call.id && t !== "call_ringing")) return;
      const c = call;
      switch (t) {
        case "call_ringing":
          if (c.role === "caller" && c.phase === "requesting") {
            c.id = m.id; c.phase = "ringing"; setStatus(`Calling ${partnerName}…`);
            c.ringTimer = setTimeout(() => { if (call === c && c.phase === "ringing") hangUp(); }, RING_LIMIT_MS);
          }
          break;
        case "call_accepted":
          if (c.role === "caller") { clearTimeout(c.ringTimer); c.phase = "connecting"; setStatus("Connecting…"); await makeOffer(); }
          break;
        case "call_declined": finish((declineText[m.reason] || declineText.declined)()); break;
        case "call_closed": finish(`${partnerName} didn't answer.`); break;
        case "call_cancelled": finish(m.reason === "no_answer" ? `Missed ${label(c.kind).toLowerCase()} from ${partnerName}` : `${partnerName} cancelled the call.`); break;
        case "call_ended":
          finish(m.reason === "failed" ? "The call was disconnected because of a connection problem." : `${partnerName} ended the call.`); break;
        case "call_offer": if (c.role === "callee") await answerOffer(m.sdp.sdp); break;
        case "call_answer":
          if (c.role === "caller" && c.pc) { await c.pc.setRemoteDescription({ type: "answer", sdp: m.sdp.sdp }); c.remoteSet = true; await flushIce(); }
          break;
        case "call_ice":
          if (c.pc && c.remoteSet) { try { await c.pc.addIceCandidate(m.candidate); } catch (e) { /* ignore */ } } else c.pendingIce.push(m.candidate);
          break;
        case "call_media":
          c.peerMic = m.mic; c.peerCam = m.cam; el.camOff.hidden = !(c.kind === "video" && m.cam === false); tickStatus();
          break;
      }
    }
    document.addEventListener("linkup:event", (e) => { onEvent(e.detail).catch((err) => { console.error("call error", err); failCall("The call hit a problem and was ended."); }); });
  
    // ---------- buttons ----------
    el.voice.addEventListener("click", () => startCall("voice"));
    el.video.addEventListener("click", () => startCall("video"));
    el.accept.addEventListener("click", acceptCall);
    el.decline.addEventListener("click", declineCall);
    el.end.addEventListener("click", hangUp);
    el.mic.addEventListener("click", () => {
      if (!call || !call.stream) return;
      call.mic = !call.mic; call.stream.getAudioTracks().forEach((t) => (t.enabled = call.mic));
      setPressed(el.mic, !call.mic, "Mute microphone", "Unmute microphone", "bi-mic-fill", "bi-mic-mute-fill");
      if (call.id) chat.send({ type: "call_media", id: call.id, mic: call.mic, cam: call.cam });
    });
    el.cam.addEventListener("click", () => {
      if (!call || !call.stream || call.kind !== "video") return;
      call.cam = !call.cam; call.stream.getVideoTracks().forEach((t) => (t.enabled = call.cam));
      setPressed(el.cam, !call.cam, "Turn camera off", "Turn camera on", "bi-camera-video-fill", "bi-camera-video-off-fill");
      if (call.id) chat.send({ type: "call_media", id: call.id, mic: call.mic, cam: call.cam });
    });
    window.addEventListener("pagehide", () => { if (call && call.id) chat.send({ type: "call_end", id: call.id, reason: "hangup" }); });
  })();