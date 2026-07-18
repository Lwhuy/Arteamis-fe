# Bug: imported text files (.md/.txt/…) silently vanish — never uploaded

**File:** `components/CaptureScreen.tsx` (current `main`)
**Severity:** real, user-facing. Reproduced by hand.
**Component:** the "Add source" modal (`SourceDrawer` / `readFile`).

## Symptom

Pick or drop a **text** file (`.md`, `.txt`, `.csv`, `.json`, code files…) in the
Add-source modal → it looks accepted, but it **never appears in the source list**
and never reaches the backend. Bigger/binary files (PDF, DOCX) work fine.

Repro: open the modal → choose a `.md` file → "Add source" → the source list still
shows nothing (or "no sources").

## Root cause

`readFile()` has an asymmetric path. Binary files are staged for upload; **text
files are instead read into a local textarea draft (`inputValue`) that is never
persisted.** So a text file becomes an in-memory draft that quietly dies when the
modal closes — it never hits `/upload`.

Current buggy code (`readFile`, ~line 729):

```tsx
function readFile(file: File) {
  setFileName(file.name);
  setBinaryFile(null);
  const matchingType = sourceTypes.find((t) => t.label === "Upload file");
  if (matchingType) setActiveType(matchingType);

  // Plain-text extensions that can be safely read client-side
  const isTextFile = /\.(txt|md|csv|json|html?|xml|ya?ml|toml|sh|bash|log|py|js|ts|jsx|tsx|rb|go|rs|java|css|sql)$/i.test(file.name);

  if (!isTextFile) {
    setBinaryFile(file);       // binary → staged for /upload  ✅
    setInputValue("");
    return;
  }

  const reader = new FileReader();      // text → read into a draft ❌ never uploaded
  reader.onload = (e) => {
    const text = typeof e.target?.result === "string" ? e.target.result : "";
    const nonPrintable = (text.match(/[\x00-\x08\x0e-\x1f\x7f]/g) ?? []).length;
    if (text && nonPrintable <= text.length * 0.05) {
      setInputValue(text);            // ← the leak: this draft is never persisted
    } else {
      setBinaryFile(file);
      setInputValue("");
    }
  };
  reader.onerror = () => { setBinaryFile(file); setInputValue(""); };
  reader.readAsText(file);
}
```

## The fix

Treat **every picked/dropped file the same** — stage it for `/upload` (the path
binary files already use). Only genuinely *typed* pasted text / URLs keep the draft
path. The `/upload` endpoint already handles `.md`/text correctly, so no backend
change is needed.

**1. `readFile` — replace the whole body with:**

```tsx
function readFile(file: File) {
  setFileName(file.name);
  const matchingType = sourceTypes.find((t) => t.label === "Upload file");
  if (matchingType) setActiveType(matchingType);

  // Any picked/dropped file — text (.md/.txt/…) or binary (PDF/DOCX/…) — is sent as
  // real bytes to /upload, which extracts and persists it server-side so it appears
  // in the source list immediately. We deliberately do NOT read text files into a
  // deferred draft — that path never persisted, so imported text files vanished.
  // Pasted text / URLs (no file) still use the draft path in handleSubmit.
  setPendingFile(file);
  setInputValue("");
}
```

**2. Rename the state so it reads honestly** (it now holds *any* file, not just
binary). At ~line 709:

```tsx
// was: const [binaryFile, setBinaryFile] = useState<File | null>(null);
const [pendingFile, setPendingFile] = useState<File | null>(null);
```

Then update the three other `binaryFile` references:

- `canSubmit` (~line 714): `const canSubmit = pendingFile ? !isUploading : inputValue.trim().length > 0;`
- `handleSubmit` (~line 803): `if (pendingFile) { void onUploadFile(pendingFile); return; }`
- the file-selected display (~line 853), which had a now-dead "characters read"
  branch — simplify to:
  ```tsx
  <div className="mt-0.5 text-xs text-copy-muted">
    {pendingFile ? `${formatBytes(pendingFile.size)} — ready to add` : "Ready to add"}
  </div>
  ```

*(If you'd rather not rename, just keep `binaryFile` everywhere and only change
`readFile` to always `setBinaryFile(file)` + drop the FileReader branch. The rename
is cosmetic; the behavior fix is `readFile`.)*

## Test

Add a regression test (new file `components/__tests__/capture-file-upload.test.tsx`):
mock `uploadSource`, open the modal, select a `.md` `File`, submit, and assert
`uploadSource` was called with that file (and the text-draft `ingestSource` path was
**not**). This is the guard that keeps the asymmetry from coming back.

## Verify

Against a running backend: pick a `.md` in the modal → it uploads (HTTP 202) and
shows in the source list as it parses. Confirmed working with this fix.

---

*Context: this was fixed once on the `feat/beginner-surface-subtraction` branch
(commit `9fa1a4c`), but that branch pre-dates the design-system refactor and doesn't
merge cleanly, so it's cleaner to re-apply the fix directly. The fix above is that
change, re-pointed at current `main`.*
