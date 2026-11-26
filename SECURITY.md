# Security policy

Please do not report security problems in public issues.

Report them privately through [GitHub's private vulnerability reporting](https://github.com/T3-Venture-Labs-Limited/ohmyugc/security/advisories/new). Include what you found, how to reproduce it, and its impact. We will reply as soon as we can.

oh-my-ugc is designed to run on your own computer. The web app has no login and listens on localhost by default; do not expose it to the internet without authentication in front of it. Your provider API keys, brands, photos, generated media and spend history are stored in `OMU_HOME` (default `~/.oh-my-ugc`). The database file that holds the keys is readable only by you (mode 600). Keys are never sent anywhere except to the provider they belong to, and are never returned by the app's own API or written to logs.
