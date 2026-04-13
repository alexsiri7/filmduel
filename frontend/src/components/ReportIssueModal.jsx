import { useState, useRef } from "react";
import { submitFeedback } from "../api";
import ScreenshotEditor from "./ScreenshotEditor";

export default function ReportIssueModal({ onClose }) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [screenshotFile, setScreenshotFile] = useState(null);
  const [screenshotDataUrl, setScreenshotDataUrl] = useState(null);
  const [editedScreenshotDataUrl, setEditedScreenshotDataUrl] = useState(null);
  const [showEditor, setShowEditor] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(false);
  const fileInputRef = useRef(null);

  const handleFileChange = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setScreenshotFile(file);
    setEditedScreenshotDataUrl(null);
    const reader = new FileReader();
    reader.onload = (ev) => setScreenshotDataUrl(ev.target.result);
    reader.readAsDataURL(file);
  };

  const handleRemoveScreenshot = () => {
    setScreenshotFile(null);
    setScreenshotDataUrl(null);
    setEditedScreenshotDataUrl(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const handleEditorSave = (editedUrl) => {
    setEditedScreenshotDataUrl(editedUrl);
    setShowEditor(false);
  };

  const handleSubmit = async () => {
    if (!title.trim() || !description.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await submitFeedback(title, description, editedScreenshotDataUrl || screenshotDataUrl);
      if (result === null) return; // 401 redirect in progress
      setSuccess(true);
      setTimeout(onClose, 1500);
    } catch (err) {
      setError(err.message);
    } finally {
      setSubmitting(false);
    }
  };

  if (showEditor && screenshotDataUrl) {
    return (
      <ScreenshotEditor
        imageDataUrl={screenshotDataUrl}
        onSave={handleEditorSave}
        onCancel={() => setShowEditor(false)}
      />
    );
  }

  return (
    <div className="fixed inset-0 z-50 bg-[#0F0E0D]/95 backdrop-blur-xl flex items-center justify-center p-6">
      <div className="bg-[#1d1b1a] border-l-4 border-[#E8A020] p-8 w-full max-w-lg">
        <h2 className="font-headline font-black uppercase text-[#F5F0E8] text-xl mb-6">
          Report Issue
        </h2>

        {success ? (
          <div className="text-center py-8">
            <p className="text-[#E8A020] font-headline font-bold text-lg">
              Thank you for your feedback!
            </p>
            <p className="text-[#F5F0E8]/50 text-sm mt-2">This window will close shortly.</p>
          </div>
        ) : (
          <>
            <div className="space-y-4">
              <div>
                <label className="block text-[#F5F0E8]/60 text-xs uppercase tracking-wider font-headline font-bold mb-1">
                  Title
                </label>
                <input
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="Brief title of the issue"
                  className="w-full bg-[#0F0E0D] border border-[#F5F0E8]/10 text-[#F5F0E8] font-body px-4 py-3 placeholder:text-[#6B6760]/50 focus:border-[#E8A020]/50 focus:outline-none transition-colors"
                />
              </div>

              <div>
                <label className="block text-[#F5F0E8]/60 text-xs uppercase tracking-wider font-headline font-bold mb-1">
                  Description
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="Describe the issue or suggestion..."
                  rows={4}
                  className="w-full bg-[#0F0E0D] border border-[#F5F0E8]/10 text-[#F5F0E8] font-body px-4 py-3 placeholder:text-[#6B6760]/50 focus:border-[#E8A020]/50 focus:outline-none transition-colors resize-none"
                />
              </div>

              {/* Screenshot */}
              <div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  onChange={handleFileChange}
                  className="hidden"
                />
                {screenshotDataUrl ? (
                  <div className="space-y-2">
                    <img
                      src={editedScreenshotDataUrl || screenshotDataUrl}
                      alt="Screenshot preview"
                      className="max-h-[120px] border border-[#F5F0E8]/10"
                    />
                    <div className="flex gap-2">
                      <button
                        onClick={() => setShowEditor(true)}
                        className="text-[#E8A020] text-xs font-headline font-bold uppercase tracking-wider hover:text-[#E8A020]/80 transition-colors"
                      >
                        Edit Screenshot
                      </button>
                      <button
                        onClick={handleRemoveScreenshot}
                        className="text-[#F5F0E8]/30 text-xs font-headline font-bold uppercase tracking-wider hover:text-[#F5F0E8]/60 transition-colors"
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                ) : (
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    className="text-[#F5F0E8]/40 text-xs font-headline font-bold uppercase tracking-wider hover:text-[#E8A020]/70 transition-colors"
                  >
                    Attach Screenshot
                  </button>
                )}
              </div>
            </div>

            {error && <p className="text-[#C04A20] text-sm mt-4">{error}</p>}

            <div className="flex gap-3 mt-6">
              <button
                onClick={handleSubmit}
                disabled={!title.trim() || !description.trim() || submitting}
                className="bg-[#E8A020] text-[#0F0E0D] font-headline font-black uppercase px-6 py-3 tracking-widest text-sm hover:scale-[1.02] active:scale-95 transition-all disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:scale-100"
              >
                {submitting ? "Submitting..." : "Submit"}
              </button>
              <button
                onClick={onClose}
                className="text-[#F5F0E8]/30 font-headline font-bold uppercase px-6 py-3 tracking-widest text-sm hover:text-[#F5F0E8]/60 transition-colors"
              >
                Cancel
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
