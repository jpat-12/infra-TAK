# Samsung S21 – Capture logs on the phone (no computer)

Use this to capture a **bug report** (includes dumpstate + logcat) on the phone, then email or share the file. No cable or computer needed.

---

## 1. Turn on Developer options (one-time)

1. Open **Settings**.
2. Tap **About phone**.
3. Find **Software information** and tap it.
4. Tap **Build number** 7 times. You’ll see “Developer mode has been enabled”.

---

## 2. Start a bug report (do this *before* the error)

1. Open **Settings**.
2. Tap **Developer options** (near the bottom).
3. Find **Bug report** (or **Send bug report** / **Error report**).
4. Tap **Bug report**.
5. Choose **Interactive report** (so you can use the phone and then finish the report when the error has happened).
6. Confirm. The phone is now recording logs.

---

## 3. Make the error happen

- Use the phone normally until the problem occurs (freeze, crash, wrong behavior).
- When it’s happened, pull down the notification shade.
- Tap the **Bug report** notification and choose **Share** or **Done** so the report is saved.

---

## 4. Find and send the file

- The report is saved as a **.zip** file, usually in **My Files → Internal storage** or **Downloads**, with a name like `bugreport-... .zip`.
- Open the file (or long-press → **Share**).
- Choose **Email** (or Gmail, etc.) and send it to you or to himself. If the file is too big for email, use **Google Drive** or **OneDrive**: upload the zip, then share the link.

---

## Quick recap

| Step | What to do |
|------|------------|
| 1 | Enable Developer options (Build number × 7). |
| 2 | **Settings → Developer options → Bug report → Interactive report** and start it. |
| 3 | Use the phone until the error happens, then finish the report from the notification. |
| 4 | Open the saved .zip in My Files, then **Share → Email** (or Drive link). |

The .zip contains dumpstate and logcat so you can debug. If he can’t find **Bug report**, tell him to search in **Settings** for “bug report” or “error report”.
