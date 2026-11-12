# LinkUp

Django + Channels + Bootstrap 5 + Firebase (Google sign-in, Firestore, Storage).

## Two kinds of users
| | Anonymous | Signed in with Google |
|---|---|---|
| Random stranger chat | yes | yes |
| Chat history / saved conversations | **never** | yes (friends only) |
| Add friends, friend requests | **no** | yes |
| Private messages | **no** | yes |
| Profile, privacy settings | no | yes |

Anonymous chats exist only in server memory while connected. Every friend/message/profile
endpoint returns 401 to anonymous users (covered by tests).

## Quick start (no Firebase yet)
    python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    python manage.py migrate
    python manage.py runserver
Anonymous chat works immediately. Without Firebase keys, the Google button is disabled.

## Turn on Google sign-in + saved data (Firebase)
1. https://console.firebase.google.com -> **Add project**.
2. **Build -> Authentication -> Get started -> Sign-in method -> Google -> Enable.**
   Under *Settings -> Authorized domains*, `localhost` is already allowed; add your real domain when you deploy.
3. **Build -> Firestore Database -> Create database** (production mode). Paste `firestore.rules` into *Rules*.
4. (Optional, for profile pictures) **Build -> Storage -> Get started.** Newer projects may require the
   pay-as-you-go plan. Use `storage.rules`. The server makes uploaded avatars public so they can be shown
   in `<img>` tags; if your bucket uses "uniform bucket-level access", switch it to fine-grained or change
   `avatar_put` in `chat/store.py` to use signed URLs. Without Storage, everything else still works.
5. **Project settings -> Service accounts -> Generate new private key.** Save it as `firebase-key.json`
   in the project folder (it is git-ignored).
6. **Project settings -> General -> Your apps -> Web app (`</>`)** -> copy the config object.
7. `cp .env.example .env` and fill in `FIREBASE_CREDENTIALS`, `FIREBASE_WEB_CONFIG` (one line), and
   `FIREBASE_STORAGE_BUCKET` if using Storage. Restart the server.

Open two different browsers, sign in with two Google accounts, finish the profile modal in each,
then search for the other nickname on **Friends -> Find people**.

## How it works
- The browser signs in with Firebase, sends the ID token to `/auth/google/`; Django verifies it with the
  Admin SDK and starts a session. The email is stored privately and never returned by any API.
- Django is the only thing that reads/writes Firestore, and it always uses the uid from the server-side
  session. Firestore rules deny all direct browser access.
- Private messages go over WebSocket (`/ws/dm/`), are saved to Firestore, and are shown again next login.
  "Delete conversation" hides it for you only.
- Without `FIREBASE_CREDENTIALS`, an in-memory store is used for local development (lost on restart).

## Tests
    python manage.py test chat        # 27 tests

## Not built yet
Cloudflare Turnstile CAPTCHA, the "reconnect after an anonymous chat" flow, profile badges, Redis-backed
random-chat queue and online presence (both are per-process; set `REDIS_URL` for the channel layer
and move those two into Redis before running multiple server processes).
