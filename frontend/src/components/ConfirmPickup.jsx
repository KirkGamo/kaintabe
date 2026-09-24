import { useEffect, useRef, useState } from 'react'

/** Photo-then-tap pickup confirmation for a claimed listing. */
export default function ConfirmPickup({ onConfirm }) {
  const inputRef = useRef(null)
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!file) return
    const url = URL.createObjectURL(file)
    setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  const reset = () => {
    setFile(null)
    setPreview(null)
    if (inputRef.current) inputRef.current.value = ''
  }

  async function submit() {
    setBusy(true)
    try {
      await onConfirm(file)
    } catch {
      setBusy(false) // stay open so they can retry; the parent shows the error
      return
    }
    reset()
    setBusy(false)
  }

  return (
    <div className="mt-2" onClick={(e) => e.stopPropagation()}>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="hidden"
        onChange={(e) => e.target.files?.[0] && setFile(e.target.files[0])}
      />

      {!file ? (
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="w-full rounded-lg bg-indigo-600 hover:bg-indigo-700 active:bg-indigo-800 text-white font-semibold py-2.5 min-h-11 transition"
        >
          📸 Confirm pickup
        </button>
      ) : (
        <div className="flex items-center gap-2">
          {preview && <img src={preview} alt="Pickup" className="w-14 h-14 rounded-lg object-cover shrink-0" />}
          <button
            type="button"
            disabled={busy}
            onClick={submit}
            className="flex-1 rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60 text-white font-semibold py-2.5 min-h-11 transition"
          >
            {busy ? 'Uploading…' : '✅ Confirm pickup'}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={reset}
            className="rounded-lg border border-slate-300 hover:bg-slate-50 text-sm px-3 py-2.5 min-h-11"
          >
            Retake
          </button>
        </div>
      )}
    </div>
  )
}
