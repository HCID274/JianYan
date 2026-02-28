
## 2025-01-20 - Adding Visual Feedback to Async Operations in Tkinter
**Learning:** Found an async operation (API test connection) tied to a button click in `ui/settings.py` without immediate visual feedback. Users could spam click the "Test Connection" button leading to duplicate async requests.
**Action:** When working with async operations launched from Tkinter buttons via threading, always update the button state (e.g., `state="disabled"`, `text="Testing..."`) synchronously before launching the background thread. Use `root.after(0, ...)` inside the thread to safely schedule the restoration of the button state and text to avoid cross-thread UI manipulation issues. This prevents duplicate submissions and provides clarity to the user.
