# AUTOMATED SMCII GRADE CALCULATION PERFORMANCE SYSTEM

## Browser dashboard

The optional browser dashboard uses the existing system accounts and grade data. It runs locally and does not replace the Tkinter desktop interface.

1. Open a terminal in the `System` folder.
2. Run `python web_dashboard.py`.
3. Open `http://127.0.0.1:8765` in a browser.
4. Sign in with an existing account and choose its role.

The dashboard is read-only; grade and account changes should continue to be made through the desktop system. Stop the local server with `Ctrl+C`.

## Automatic account ID numbers

When an administrator creates an account, student IDs are generated as `CYY-0001` and teacher IDs as `TYY-0001`, where `YY` is the first year of the current school year. The sequence is tracked separately for each role and school year.
