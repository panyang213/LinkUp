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
   
   --COMMANDS--
    python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
    pip install -r requirements.txt
    python manage.py migrate
    python manage.py runserver

Anonymous chat works immediately. Without logging in to Google.

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

